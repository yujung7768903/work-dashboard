"""보드 워크트리 탭 데이터. 워크스페이스마다 저장소 하나, 그 아래 브랜치·워크트리 행.

저장소 경로는 워크스페이스에 저장돼 있지 않다 — 그 워크스페이스에서 돌았던 세션의
cwd 로 유추한다. 조회(overview)는 git·lsof 를 읽기 전용으로만 부르고 실패하면 그
칸만 비운다 — 한 저장소가 깨져도 나머지는 그려져야 한다.

상태를 바꾸는 것은 케밥 메뉴에서 부르는 셋뿐이다 — apply() 는 병합·서버 종료·워크트리
및 브랜치 제거·할일 done 을 순서대로, discard() 는 병합 없이 버리기, control() 은
서버만 실행·재실행·중지(app/services/serve.py).
"""
import os
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from app.constants import STATUS_DONE, WORKSPACE_ACTIVE
from app.db import now
from app.errors import Conflict, NotFound, Validation
from app.repositories import categories as category_repo
from app.repositories import sessions as session_repo
from app.repositories import worktrees as worktree_repo
from app.repositories import workspaces as workspace_repo
from app.services import release, serve

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
# 할일 팝업의 워크트리 상태 4종. 살아 있는 워크트리는 지금 git 으로, 끝난 것은 남은 자국으로 정한다
STATE_CREATE = "create"
STATE_WORKING = "working"
STATE_MERGED = "merged"
STATE_DELETED = "deleted"
# 세션 cwd 가 워크트리인지 가르고 저장소 루트를 잘라내는 표식
WORKTREE_MARK = release.WORKTREE_MARK
# 워크트리 탭 뷰 모드 — 워크스페이스별(기존)과 프로젝트(저장소)별
GROUP_BY_WORKSPACE = "workspace"
GROUP_BY_PROJECT = "project"
GROUP_BY_CHOICES = (GROUP_BY_WORKSPACE, GROUP_BY_PROJECT)
# 기준 브랜치 reflog 의 병합 항목 — `merge <브랜치>: Merge made by ...` / `...: Fast-forward`
MERGE_ENTRY = re.compile(r"^merge (\S+):")


def overview(con, group_by=GROUP_BY_WORKSPACE):
    """워크스페이스별은 저장소를 찾은 활성 워크스페이스만(기존과 같음).

    프로젝트별은 워크스페이스·할일 연결과 무관하게, 세션이 한 번이라도 다녀간 저장소를
    전부 보여준다 — 워크스페이스가 done·아카이브됐거나 세션이 아직 분류되지 않았어도
    그 저장소의 워크트리는 남아 있을 수 있어서다
    """
    if group_by not in GROUP_BY_CHOICES:
        raise Validation(f"group_by 는 {GROUP_BY_CHOICES} 중 하나여야 함")
    summaries = {_real(cwd): title
                 for cwd, title in session_repo.todo_titles_by_cwd(con).items()}
    # 줄 클릭으로 열 할일. 적용 로직이 쓰는 todo_ids_by_cwd(위치별 전체)와 달리
    # 요약 제목과 같은 세션에서 뽑은 하나여야 해서 단수 조회를 쓴다
    todo_id_by_path = {_real(cwd): todo_id
                       for cwd, todo_id in session_repo.todo_id_by_cwd(con).items()}
    ports = _ports_by_pid()
    builder = _project_groups if group_by == GROUP_BY_PROJECT else _workspace_groups
    return {"group_by": group_by, "groups": builder(con, summaries, todo_id_by_path, ports)}


def _workspace_groups(con, summaries, todo_id_by_path, ports):
    categories = {row["id"]: row for row in category_repo.list_all(con)}
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
                **_repo_state(root, summaries, todo_id_by_path, ports),
            }
        )
    return groups


def _project_groups(con, summaries, todo_id_by_path, ports):
    """저장소 하나 = 그룹 하나. 최근 커밋 시각 내림차순"""
    groups = []
    for root in _known_repo_roots(session_repo.all_cwds(con)):
        groups.append(
            {
                "id": None,
                "name": os.path.basename(root),
                "category_id": None,
                "category_name": None,
                "category_color": None,
                "repo": root,
                **_repo_state(root, summaries, todo_id_by_path, ports),
            }
        )
    return sorted(groups, key=_latest_activity, reverse=True)


def _latest_activity(group):
    """그 저장소 안 브랜치들의 가장 최근 커밋 시각(ISO8601). 없으면 빈 문자열"""
    stamps = [row["commits"][0]["at"] for row in group["rows"] if row["commits"]]
    return max(stamps) if stamps else ""


def _known_repo_roots(cwds):
    """cwd 들이 걸친 서로 다른 저장소 루트 전부. 워크스페이스 뷰의 _repo_root 는 하나 찾으면
    멈추지만(워크스페이스 하나 = 저장소 하나 가정), 여기는 저장소 목록 자체가 필요하다"""
    roots = []
    seen = set()
    for cwd in cwds:
        root = repo_root_of(cwd)
        if root and root not in seen:
            seen.add(root)
            roots.append(root)
    return roots


def history(con, todo_ids):
    """할일 팝업의 워크트리 탭. 그 할일을 잡은 세션이 돌았던 워크트리를 최근 생성 순으로.

    병합·삭제로 사라진 워크트리도 남아야 한다 — git 은 그것을 기억하지 않으므로 이름·생성
    시각은 worktrees 테이블에서, 병합 사실은 기준 브랜치 reflog 에서 되짚는다.
    이력에 아직 없던 워크트리는 이 조회가 지나가면서 적힌다
    """
    rows = []
    for repo, entries in _by_repo(_worktree_cwds(con, todo_ids)).items():
        rows.extend(_history_rows(con, repo, entries))
    return sorted(rows, key=lambda row: row["created_at"], reverse=True)


def _worktree_cwds(con, todo_ids):
    """워크트리 경로 → (브랜치 후보, 거기서 가장 먼저 돈 세션의 시작 시각).
    시작 시각은 이력에 없던 워크트리의 생성 시각 대타로 쓴다 (디렉터리가 이미 없으면
    stat 할 것이 없다 — 실제 생성보다 늦지만 그 워크트리가 있었던 시점은 된다)"""
    found = {}
    for todo_id in todo_ids:
        for session in session_repo.list_by_todo(con, todo_id):
            started = session["started_at"]
            for path, branch in _session_worktrees(session):
                current = found.get(path)
                found[path] = (
                    branch or (current[0] if current else ""),
                    min(started, current[1]) if current else started,
                )
    return found


def _session_worktrees(session):
    """그 세션이 돌았던 워크트리 [(경로, 브랜치 후보)]. 두 군데를 본다 — 세션 cwd(워크트리
    안에서 시작한 세션)와 transcript 꼬리(EnterWorktree 로 옮겨간 세션).

    후자가 기본 흐름이다. cwd 는 SessionStart 훅이 세션이 열릴 때 적은 것이라 대개
    메인 체크아웃을 가리키고, 그것만 보면 대부분의 할일에 워크트리가 하나도 안 붙는다
    """
    found = []
    for path in (session["cwd"], release.last_worktree_cwd(session["claude_session_id"])):
        real = _real(path or "")
        if real and WORKTREE_MARK in real:
            found.append((real, session["git_branch"] or ""))
    return found


def _by_repo(seen):
    """저장소 루트 → [(경로, 브랜치, 첫 세션 시각)]. 워크트리 경로가 곧 저장소 위치를 담고 있다"""
    grouped = {}
    for path, (branch, started) in seen.items():
        grouped.setdefault(path.split(WORKTREE_MARK)[0], []).append((path, branch, started))
    return grouped


def _history_rows(con, repo, entries):
    """저장소마다 기준 브랜치·병합 이력·살아 있는 워크트리를 한 번만 읽고 줄을 만든다"""
    base = _base_branch(repo, _branches(repo))
    events = merge_events(repo, base)
    live = {path: branch for branch, path in _worktrees(repo).items()}
    return [_history_row(con, repo, base, events, live, *entry) for entry in entries]


def _history_row(con, repo, base, events, live, path, hint, started):
    branch = _resolve_branch(path, live, events, base, hint)
    row = worktree_repo.remember(con, path, repo, branch, _created_at(path) or started)
    row = _stamped(con, row, path, events.get(branch), path in live)
    ahead, behind, commits = _history_commits(repo, base, branch, path in live, row)
    return {
        "path": path,
        "name": os.path.basename(path),
        "branch": row["branch"],
        "repo": repo,
        "base": base,
        "state": _state(row, path in live, ahead),
        "created_at": row["created_at"],
        "merged_at": row["merged_at"],
        "deleted_at": row["deleted_at"],
        "ahead": ahead,
        "behind": behind,
        "commits": commits,
    }


def _resolve_branch(path, live, events, base, hint):
    """이 워크트리의 브랜치. 살아 있으면 git 이 알려준다.

    사라졌으면 이름에서 되짚는다 — EnterWorktree 는 디렉터리 `foo` 를 브랜치
    `worktree-foo` 로 만들지만 손으로 만든 워크트리는 이름이 그대로일 수 있어 둘 다 본다.
    세션이 준 브랜치는 대개 메인 체크아웃의 것(기준 브랜치)이라 그건 후보에서 뺀다
    """
    if path in live:
        return live[path]
    name = os.path.basename(path)
    candidates = [hint if hint != base else "", f"worktree-{name}", name]
    return next((item for item in candidates if item in events), candidates[0] or name)


def _stamped(con, row, path, event, alive):
    """끝난 워크트리에 병합·삭제 자국을 남긴다. 한 번 적힌 자국은 다시 쓰지 않는다"""
    # 이 워크트리가 생기기 전의 병합은 같은 이름을 쓴 앞 워크트리의 것이다
    if event and event["at"] >= row["created_at"] and not row["merged_at"]:
        return worktree_repo.mark_merged(con, path, event["at"], event["hash"], event["from"])
    if not alive and not row["merged_at"] and not row["deleted_at"]:
        # 지우는 순간을 관측할 방법이 없다 — 사라진 것을 처음 확인한 시각을 삭제 시각으로 쓴다
        return worktree_repo.mark_deleted(con, path, now())
    return row


def _state(row, alive, ahead):
    """병합 뒤에 커밋이 더 쌓였으면 다시 working 이다 — 그 커밋은 아직 기준 브랜치에 없다"""
    if alive and (ahead or _dirty(row["path"])):
        return STATE_WORKING
    if row["merged_at"]:
        return STATE_MERGED
    if not alive:
        return STATE_DELETED
    return STATE_CREATE


def _history_commits(repo, base, branch, alive, row):
    """(앞섬, 뒤처짐, 커밋).

    아직 기준 브랜치에 없는 커밋이 있으면 그것이 이 워크트리의 지금 작업이다. 병합으로
    끝났으면 기준 브랜치에서 본 격차는 0 이므로 병합 커밋 범위를 되짚어야 커밋이 남는다
    """
    behind, ahead = _divergence(repo, base, branch) if alive else (0, 0)
    if alive and ahead:
        return ahead, behind, _commits(repo, base, branch)
    if row["merge_hash"] and row["merge_from"]:
        revs = f"{row['merge_from']}..{row['merge_hash']}"
        # 기준 브랜치를 워크트리로 들인 병합 커밋은 작업이 아니라 잡음이라 뺀다.
        # 개수도 같은 조건으로 세야 ↑숫자와 펼친 목록 길이가 어긋나지 않는다
        return _count(repo, revs, "--no-merges"), behind, _log(repo, revs, "--no-merges")
    # 병합 없이 버린 워크트리의 커밋은 브랜치와 함께 사라졌다 — 되짚을 자국이 없다
    return ahead, behind, _commits(repo, base, branch) if alive else []


def _created_at(path):
    """워크트리 디렉터리가 생긴 시각. `.git` 파일은 워크트리를 만들 때 한 번 쓰인다.
    이미 사라진 워크트리면 빈 문자열"""
    marker = os.path.join(path, ".git")
    if not os.path.exists(marker):
        return ""
    return _stamp(os.path.getmtime(marker))


def _dirty(path):
    return bool(_git(path, "status", "--porcelain").strip())


def merge_events(root, base):
    """브랜치 → 마지막 병합 {at, hash, from}. 기준 브랜치 reflog 의 `merge <브랜치>:` 항목.

    지워진 브랜치가 병합된 것인지 알 수 있는 유일한 자국이다. 병합 결과 커밋(hash)과 바로
    앞 상태(from)를 함께 잡아 두면 `from..hash` 로 그 브랜치의 커밋까지 되짚을 수 있다 —
    reflog 자체는 지워지므로(기본 90일) 처음 본 때 저장한다
    """
    if not base:
        return {}
    lines = _git(root, "reflog", "show", base, "--date=iso-strict",
                 f"--format=%H{UNIT}%gd{UNIT}%gs").splitlines()
    found = {}
    for index, line in enumerate(lines):
        parts = line.split(UNIT)
        if len(parts) != 3:
            continue
        commit, when, message = parts
        matched = MERGE_ENTRY.match(message)
        # 최신 항목이 먼저 온다 — 같은 브랜치를 두 번 병합했으면 마지막 것만 남는다
        if not matched or matched.group(1) in found:
            continue
        stamp = _utc(when)
        if not stamp:
            continue
        found[matched.group(1)] = {
            "at": stamp,
            "hash": commit,
            # 한 칸 아래(더 오래된) 항목이 그 병합 직전의 기준 브랜치 상태다
            "from": _entry_hash(lines, index + 1) or f"{commit}^",
        }
    return found


def _entry_hash(lines, index):
    return lines[index].split(UNIT)[0] if 0 <= index < len(lines) else ""


def _utc(reflog_date):
    """`master@{2026-08-05T19:35:26+09:00}` → DB 와 같은 UTC ISO8601. 못 읽으면 빈 문자열"""
    inside = reflog_date.partition("{")[2].rstrip("}")
    try:
        parsed = datetime.fromisoformat(inside)
    except ValueError:
        return ""
    return parsed.astimezone(timezone.utc).isoformat(timespec="seconds")


def _stamp(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat(timespec="seconds")


def apply(con, repo, branch):
    """워크트리 브랜치를 기준 브랜치에 병합하고 뒷정리까지 마친다.

    순서 — 되돌릴 수 없는 것부터 먼저 확인하고, 실행은 병합(실패하면 여기서 멈추고
    아무것도 건드리지 않음) → 서버 종료 → 워크트리·브랜치 제거 → 할일 done
    """
    root, base, path = _resolve_target(repo, branch, "적용")

    todo_ids = _todo_ids_for_cwd(con, path)
    _ensure_no_local_changes(root, "메인 체크아웃")
    _ensure_checked_out(root, base)
    _ensure_no_local_changes(path, "워크트리")

    if not _merge(root, branch):
        raise Conflict("충돌로 병합하지 못했습니다. 직접 정리가 필요합니다")

    # Claude Code 는 세션이 쓰는 동안 워크트리를 잠근다. 병합이 끝난 시점이면 그 세션은
    # 할 일이 없으므로 종료하고 잠금을 푼다 — 남겨 두면 세션이 끝날 때까지 정리가 밀린다.
    # 잠금 파일은 세션이 죽어도 남으므로(git 은 pid 생존을 보지 않는다) unlock 이 필요하다
    lock = _lock_reason(root, path)
    ended = release.kill_claude(path) if lock else []
    if lock:
        _git_write(root, "worktree", "unlock", path)
    killed = release.kill_serving(path)
    _git_write(root, "worktree", "remove", path)
    _git_write(root, "branch", "-d", branch)
    finished = release.finish_todo_ids(con, todo_ids)
    return {
        "branch": branch,
        "base": base,
        "killed": killed + ended,
        "removed": path,
        "finished": finished,
        # 세션을 끊은 것은 조용히 넘길 일이 아니다 — 프런트가 그대로 알림으로 띄운다
        "message": _ended_message(ended) if ended else None,
    }


def _ended_message(ended):
    pids = ", ".join(str(pid) for pid, _ in ended)
    return (
        f"워크트리를 쓰던 Claude 세션을 종료했습니다 (pid {pids})."
        " 대화 기록은 남아 있어 claude --resume 으로 이어갈 수 있습니다"
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


# 케밥 메뉴의 서버 조작. 동작 → (사용자에게 보이는 이름, 실행할 것)
CONTROLS = {
    "start": ("실행", serve.start),
    "restart": ("재실행", serve.restart),
    "stop": ("중지", serve.stop),
}


def control(repo, branch, action):
    """워크트리 서버를 실행·재실행·중지한다. 대상 판정은 적용·삭제와 같은 것을 쓴다.

    con 을 받지 않는다 — 할일·세션을 건드리지 않고 프로세스만 다룬다
    """
    if action not in CONTROLS:
        raise Validation(f"알 수 없는 동작: {action}")
    label, run = CONTROLS[action]
    _, _, path = _resolve_target(repo, branch, label)
    return {"branch": branch, "action": action, **run(path)}


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


def _repo_state(root, summaries, todo_id_by_path, ports):
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
                lambda name: _row(
                    root, base, name, worktrees.get(name), summaries, todo_id_by_path, processes
                ),
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


def _row(root, base, branch, path, summaries, todo_id_by_path, processes):
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
        "todo_id": todo_id_by_path.get(path),
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
    return _log(root, f"{base}..{branch}")


def _count(root, revs, *extra):
    out = _git(root, "rev-list", "--count", *extra, revs).strip()
    return int(out) if out.isdigit() else 0


def _log(root, revs, *extra):
    """커밋 목록. 범위 표기는 부르는 쪽이 만든다 (`base..branch`, `병합전..병합커밋`)"""
    out = _git(root, "log", f"--format=%h{UNIT}%s{UNIT}%cI", f"-n{COMMIT_LIMIT}", *extra, revs)
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
