"""보드 워크트리 탭 데이터. 워크스페이스마다 저장소 하나, 그 아래 브랜치·워크트리 행.

저장소 경로는 워크스페이스에 저장돼 있지 않다 — 그 워크스페이스에서 돌았던 세션의
cwd 로 유추한다. 조회(overview)는 git·lsof 를 읽기 전용으로만 부르고 실패하면 그
칸만 비운다 — 한 저장소가 깨져도 나머지는 그려져야 한다.

apply() 만 예외적으로 상태를 바꾼다 — 케밥 메뉴의 "적용" 한 번으로 병합·서버
종료·워크트리 및 브랜치 제거·할일 done 을 순서대로 실행한다.
"""
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor

from app.constants import STATUS_DONE, SUBTASKS_REMAINING_MSG, WORKSPACE_ACTIVE
from app.errors import Conflict, NotFound, Validation
from app.repositories import categories as category_repo
from app.repositories import sessions as session_repo
from app.repositories import subtasks as subtask_repo
from app.repositories import workspaces as workspace_repo
from app.services import release

GIT_TIMEOUT_SEC = 5
# merge·worktree remove·branch delete 는 조회용 git 호출보다 오래 걸릴 수 있다
APPLY_TIMEOUT_SEC = 30
# 브랜치마다 git 을 두 번(격차·커밋) 부르므로 오래된 브랜치까지 다 보면 느려진다.
# 최근 커밋 순 상위 30 개만 보고, 잘라낸 개수는 응답에 실어 화면에 알린다
BRANCH_LIMIT = 30
COMMIT_LIMIT = 20
# 브랜치별 git 을 겹쳐 부르는 폭. 저장소 하나가 CPU 를 다 먹지 않을 만큼만
GIT_WORKERS = 8
# 명령줄 앞 두 토큰만 이름으로 줄여 보여준다 (`python3 server.py`)
COMMAND_TOKENS = 2
# git log 필드 구분자. 커밋 제목에 들어갈 일이 없어 split 이 안전하다
UNIT = "\x1f"
BASE_FALLBACKS = ("master", "main")
ORIGIN_HEAD = "refs/remotes/origin/HEAD"
BRANCH_REF = "refs/heads/"


def overview(con):
    """저장소를 찾은 활성 워크스페이스만. 못 찾은 워크스페이스는 그리지 않는다"""
    summaries = {_real(cwd): title
                 for cwd, title in session_repo.todo_titles_by_cwd(con).items()}
    categories = {row["id"]: row for row in category_repo.list_all(con)}
    ports = _ports_by_pid()
    groups = []
    for workspace in workspace_repo.list_all(con, status=WORKSPACE_ACTIVE):
        root = _repo_root(session_repo.cwds_by_workspace(con, workspace["id"]))
        if not root:
            continue
        category = categories.get(workspace["category_id"]) or {}
        groups.append(
            {
                "id": workspace["id"],
                "name": workspace["name"],
                "category_id": workspace["category_id"],
                "category_name": category.get("name"),
                "category_color": category.get("color"),
                "repo": root,
                **_repo_state(root, summaries, ports),
            }
        )
    return {"groups": groups}


def apply(con, repo, branch):
    """워크트리 브랜치를 기준 브랜치에 병합하고 뒷정리까지 마친다.

    순서 — 되돌릴 수 없는 것부터 먼저 확인하고, 실행은 병합(실패하면 여기서 멈추고
    아무것도 건드리지 않음) → 서버 종료 → 워크트리·브랜치 제거 → 할일 done.
    할일을 마지막에 두는 게 아니라 먼저 "완료 가능한지"만 확인해 두는 이유는, 하위할일이
    남아 done 처리가 막히는 경우를 워크트리를 지운 뒤에 알면 되돌릴 방법이 없어서다
    """
    root, base, path = _resolve_target(repo, branch, "적용")

    todo_ids = _todo_ids_for_cwd(con, path)
    _ensure_todos_completable(con, todo_ids)
    _ensure_no_local_changes(root, "메인 체크아웃")
    _ensure_checked_out(root, base)
    _ensure_no_local_changes(path, "워크트리")

    if not _merge(root, branch):
        raise Conflict("충돌로 병합하지 못했습니다. 직접 정리가 필요합니다")

    # 잠긴 워크트리는 지울 수 없다 — Claude Code 는 세션이 쓰는 동안 잠가 둔다.
    # 강제로 지우면 그 세션의 작업 디렉터리가 사라지므로 병합·할일까지만 하고 남긴다
    lock = _lock_reason(root, path)
    killed = [] if lock else release.kill_serving(path)
    if not lock:
        _git_write(root, "worktree", "remove", path)
        _git_write(root, "branch", "-d", branch)
    finished = release.finish_todo_ids(con, todo_ids)
    return {
        "branch": branch,
        "base": base,
        "killed": killed,
        "removed": None if lock else path,
        "finished": finished,
        "kept": _kept_message(base, path, lock) if lock else None,
    }


def _kept_message(base, path, lock):
    return (
        f"{base} 병합은 끝냈습니다. 다만 {path} 는 잠겨 있어 남겼습니다 ({lock})."
        " 그 세션을 끝낸 뒤 적용을 다시 누르면 정리됩니다"
    )


def _lock_reason(root, path):
    """이 워크트리의 잠금 사유. 잠겨 있지 않으면 빈 문자열"""
    target = _real(path)
    current = None
    for line in _git(root, "worktree", "list", "--porcelain").splitlines():
        head, _, rest = line.partition(" ")
        if head == "worktree":
            current = _real(rest.strip())
        elif head == "locked" and current == target:
            return rest.strip() or "사유 없음"
    return ""


def discard(con, repo, branch):
    """병합 없이 워크트리를 버린다 — 서버 종료 → 워크트리·브랜치 강제 제거.

    적용과 달리 클린 여부·병합 가능 여부를 확인하지 않는다 — 버리는 게 목적이라
    커밋되지 않았거나 아직 병합되지 않은 커밋도 그대로 사라진다. 되돌릴 수 없다는
    경고는 프런트의 확인창이 맡는다
    """
    root, base, path = _resolve_target(repo, branch, "삭제")
    killed = release.kill_serving(path)
    _git_write(root, "worktree", "remove", "--force", path)
    _git_write(root, "branch", "-D", branch)
    return {"branch": branch, "base": base, "killed": killed, "removed": path}


def _resolve_target(repo, branch, action):
    """적용·삭제 공통 — 대상 워크트리를 찾고 없으면 그 자리에서 실패시킨다"""
    if not repo or not branch:
        raise Validation("repo·branch 는 필수")
    root = os.path.abspath(repo)
    branches = _branches(root)
    if branch not in branches:
        raise NotFound(f"{branch} 브랜치를 찾을 수 없습니다")
    base = _base_branch(root, branches)
    if branch == base:
        raise Validation(f"기준 브랜치는 {action} 대상이 아님")
    path = _worktrees(root).get(branch)
    if not path:
        raise NotFound(f"{branch} 브랜치의 워크트리를 찾을 수 없습니다")
    return root, base, path


def _todo_ids_for_cwd(con, path):
    """이 워크트리에서 돈 세션들이 연결한 할일 id. 경로 비교는 realpath 로 맞춘다"""
    target = os.path.realpath(path)
    ids = set()
    for cwd, todo_ids in session_repo.todo_ids_by_cwd(con).items():
        if os.path.realpath(cwd) == target:
            ids |= todo_ids
    return sorted(ids)


def _ensure_todos_completable(con, todo_ids):
    """todo_repo.update 가 하는 검사와 같은 규칙을 먼저 확인만 해 둔다 — 병합·삭제가
    다 끝난 뒤에야 이 검사에 걸리면 워크트리는 이미 없는데 할일만 done 이 안 된다"""
    for todo_id in todo_ids:
        if any(
            row["status"] != STATUS_DONE
            for row in subtask_repo.list_by_todo(con, todo_id)
        ):
            raise Validation(SUBTASKS_REMAINING_MSG)


def _ensure_checked_out(root, base):
    current = _git(root, "rev-parse", "--abbrev-ref", "HEAD").strip()
    if current != base:
        raise Validation(
            f"메인 체크아웃이 {current} 입니다. 먼저 {base} 로 체크아웃해 주세요"
        )


def _ensure_no_local_changes(path, label):
    if _git(path, "status", "--porcelain").strip():
        raise Validation(f"{label} 에 커밋되지 않은 변경사항이 있습니다")


def _merge(root, branch):
    result = _run_write(["git", "-C", root, "merge", "--no-edit", branch])
    if result.returncode == 0:
        return True
    _run_write(["git", "-C", root, "merge", "--abort"])
    return False


def _git_write(root, *args):
    result = _run_write(["git", "-C", root, *args])
    if result.returncode:
        raise Conflict(f"git {' '.join(args)} 실패: {result.stderr.strip()}")


def _run_write(argv):
    """조회용 _run 과 달리 실패를 예외로 올린다 — 정리 실패를 조용히 넘기면
    워크트리가 반쯤 지워진 채로 화면에는 성공만 보인다"""
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=APPLY_TIMEOUT_SEC)
    except Exception as error:
        raise Conflict(f"{' '.join(argv)} 실행 실패: {error}")


def _repo_state(root, summaries, ports):
    branches = _branches(root)
    base = _base_branch(root, branches)
    shown = _base_first(branches, base)[:BRANCH_LIMIT]
    worktrees = _worktrees(root)
    processes = _process_map(sorted(set(worktrees.values())), ports)
    # 브랜치마다 git 을 두 번 부른다. 순서대로 돌면 브랜치 수만큼 곱해져 눈에 띄게
    # 느려지므로 한꺼번에 띄운다 — subprocess 대기라 스레드로 충분히 겹친다
    with ThreadPoolExecutor(max_workers=GIT_WORKERS) as pool:
        rows = list(
            pool.map(
                lambda name: _row(root, base, name, worktrees.get(name), summaries, processes),
                shown,
            )
        )
    return {
        "base": base,
        "hidden_branches": max(0, len(branches) - len(shown)),
        "rows": rows,
    }


def _base_first(branches, base):
    """기준 브랜치를 맨 위로. 나머지는 최근 커밋 순 그대로"""
    rest = [name for name in branches if name != base]
    return ([base] if base in branches else []) + rest


def _row(root, base, branch, path, summaries, processes):
    is_base = branch == base
    commits = [] if is_base else _commits(root, base, branch)
    behind, ahead = (0, 0) if is_base else _divergence(root, base, branch)
    return {
        "branch": branch,
        "path": path,
        "is_base": is_base,
        "ahead": ahead,
        "behind": behind,
        "summary": _summary(path, summaries, commits),
        "processes": processes.get(path, []),
        "commits": commits,
    }


def _summary(path, summaries, commits):
    """그 위치에서 잡았던 할일 제목이 먼저. 없으면 분기 이후 최신 커밋 제목"""
    return summaries.get(path) or (commits[0]["subject"] if commits else "")


def _branches(root):
    out = _git(root, "for-each-ref", "--format=%(refname:short)",
               "--sort=-committerdate", BRANCH_REF)
    return [line.strip() for line in out.splitlines() if line.strip()]


def _base_branch(root, branches):
    """origin/HEAD 가 가리키는 브랜치. 없으면 master → main 순으로 있는 것"""
    head = _git(root, "symbolic-ref", "--short", ORIGIN_HEAD).strip()
    candidates = ([head.split("/", 1)[-1]] if head else []) + list(BASE_FALLBACKS)
    for name in candidates:
        if name in branches:
            return name
    return branches[0] if branches else ""


def _worktrees(root):
    """브랜치 → 워크트리 경로. 체크아웃돼 있지 않은 브랜치는 빠진다"""
    found = {}
    path = None
    for line in _git(root, "worktree", "list", "--porcelain").splitlines():
        head, _, rest = line.partition(" ")
        if head == "worktree":
            path = rest.strip()
        elif head == "branch" and path:
            found[rest.strip().replace(BRANCH_REF, "", 1)] = _real(path)
    return found


def _divergence(root, base, branch):
    """(뒤처진 커밋 수, 앞선 커밋 수). lazygit 의 ↓↑ 와 같은 기준"""
    parts = _git(root, "rev-list", "--left-right", "--count", f"{base}...{branch}").split()
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        return (0, 0)
    return (int(parts[0]), int(parts[1]))


def _commits(root, base, branch):
    """기준 브랜치에서 갈라진 뒤의 커밋. 최신 순, COMMIT_LIMIT 개까지"""
    out = _git(root, "log", f"--format=%h{UNIT}%s{UNIT}%cI",
               f"-n{COMMIT_LIMIT}", f"{base}..{branch}")
    commits = []
    for line in out.splitlines():
        parts = line.split(UNIT)
        if len(parts) == 3:
            commits.append({"hash": parts[0], "subject": parts[1], "at": parts[2]})
    return commits


def processes_by_path(paths):
    """경로 → 거기서 포트를 듣고 있는 프로세스. 자율 수행 패널도 같은 조회를 쓴다.

    lsof 두 번이라 부르는 쪽에서 경로를 몰아서 넘긴다 — 비면 아예 부르지 않는다
    """
    live = [_real(path) for path in paths if path]
    if not live:
        return {}
    return _process_map(live, _ports_by_pid())


def _process_map(paths, ports):
    """워크트리 경로 → 거기서 포트를 듣고 있는 프로세스.
    셸·에디터까지 다 보이면 잡음이라 듣는 포트가 있는 것만 남긴다.
    lsof 는 한 번에 0.2 초라 경로마다 부르면 탭이 눈에 띄게 느려진다 — 경로를 몰아
    한 번만 묻는다"""
    live = [path for path in paths if os.path.isdir(path)]
    if not live:
        return {}
    owned = [(pid, path) for pid, path in _cwd_pids(live) if pid in ports]
    commands = _commands([pid for pid, _ in owned])
    found = {}
    for pid, path in owned:
        entry = {"pid": pid, "command": commands.get(pid, ""), "ports": ports[pid]}
        found.setdefault(path, []).append(entry)
    return found


def _cwd_pids(paths):
    """[(pid, cwd)] — 그 경로들을 작업 위치로 쓰는 프로세스. lsof 한 번"""
    found = []
    pid = None
    for line in _run(["lsof", "-a", "-d", "cwd", "-F", "pn", *paths]).splitlines():
        if line.startswith("p") and line[1:].strip().isdigit():
            pid = int(line[1:])
        elif line.startswith("n") and pid is not None:
            found.append((pid, line[1:].strip()))
    return found


def _ports_by_pid():
    """pid → 듣고 있는 포트. 저장소와 무관하므로 전체에서 한 번만 부른다"""
    ports = {}
    pid = None
    for line in _run(["lsof", "-nP", "-iTCP", "-sTCP:LISTEN", "-F", "pn"]).splitlines():
        if line.startswith("p") and line[1:].strip().isdigit():
            pid = int(line[1:])
            continue
        # 이름 줄은 'n*:8765' / 'n127.0.0.1:8765' / 'n[::1]:8765' 형태
        if line.startswith("n") and pid is not None and ":" in line:
            tail = line.rsplit(":", 1)[1].strip()
            if tail.isdigit():
                ports.setdefault(pid, set()).add(int(tail))
    return {pid: sorted(values) for pid, values in ports.items()}


def _commands(pids):
    """pid → 짧게 줄인 명령. ps 한 번"""
    if not pids:
        return {}
    out = _run(["ps", "-p", ",".join(str(pid) for pid in sorted(set(pids))),
                "-o", "pid=,command="])
    found = {}
    for line in out.splitlines():
        pid, _, command = line.strip().partition(" ")
        if pid.isdigit():
            found[int(pid)] = _short(command)
    return found


def _short(command):
    """`/usr/bin/python3 server.py --port 8765` → `python3 server.py`"""
    tokens = command.split()[:COMMAND_TOKENS]
    return " ".join(os.path.basename(token) for token in tokens)


def _real(path):
    """심볼릭 링크를 푼 경로. git·lsof·세션 cwd 가 같은 곳을 다른 문자열로 부르면
    (macOS 의 /var ↔ /private/var) 프로세스도 작업 요약도 붙지 않는다"""
    return os.path.realpath(path) if path else path


def repo_root_of(cwd):
    """그 위치가 속한 저장소의 루트. 워크트리 안이면 본 저장소로 올라간다. 못 읽으면 빈 문자열"""
    if not os.path.isdir(cwd):
        return ""
    # 본 저장소는 '.git', 워크트리는 본 저장소의 절대경로를 돌려준다
    common = _git(cwd, "rev-parse", "--git-common-dir").strip()
    return os.path.dirname(os.path.abspath(os.path.join(cwd, common))) if common else ""


def _repo_root(cwds):
    """세션이 남긴 위치들 중 처음으로 저장소가 잡히는 곳의 루트"""
    return next((root for root in map(repo_root_of, cwds) if root), "")


def _git(root, *args):
    """실패하면 빈 결과. 없는 브랜치·저장소를 물어도 화면이 죽지 않는다"""
    return _run(["git", "-C", root, *args], strict=True)


def _run(argv, strict=False):
    """도구가 없거나 느리면 빈 결과.
    lsof 는 찾은 게 없으면 0 이 아닌 코드로 끝나므로 strict 를 걸지 않는다"""
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=GIT_TIMEOUT_SEC)
    except Exception:
        return ""
    return "" if strict and result.returncode else result.stdout
