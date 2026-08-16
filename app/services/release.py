"""병합으로 작업이 끝났을 때의 리소스 해제.

세 가지가 남는다 — 연결된 할일, 그 워크트리를 쓰던 서버 프로세스, 워크트리 디렉토리.
앞의 둘은 여기서 처리하고, 워크트리 제거는 에이전트의 ExitWorktree 가 맡는다
(에이전트의 cwd 가 그 안이라 밖에서 지우면 셸이 깨진다).
"""
import os
import re
import signal
import subprocess
import time

from app.constants import STATUS_DONE
from app.repositories import sessions as session_repo
from app.repositories import todos as todo_repo
from app.services import transcript

# 종료 대상은 워크트리 안에서만 찾는다. 메인 체크아웃까지 뒤지면
# 사용자가 보고 있는 대시보드 서버를 죽인다
WORKTREE_MARK = "/.claude/worktrees/"
# cwd 가 워크트리라도 서버 형태가 아니면 건드리지 않는다 (셸·에디터 등)
SERVER_NAMES = ("server.py", "manage.py", "npm", "yarn", "pnpm", "vite", "next", "node")
# 워크트리를 잡고 있는 Claude 세션. 서버와 따로 두는 이유 — finish 는 세션이 자기 자신에
# 대해 부르므로 거기 섞으면 자기를 죽인다. 병합이 끝난 적용(apply)에서만 종료한다
CLAUDE_NAME = "claude"
# 죽기를 기다리는 상한. 안 죽어도 정리는 그대로 진행한다 — 잠금만 풀리면 제거는 된다
EXIT_WAIT_SEC = 5
EXIT_POLL_SEC = 0.1
# 플래그를 걷어낸 앞 두 토큰만 본다 — `zsh -c '... server.py ...'` 같은 셸이 서버로 잡히면
# 자기 자신을 죽인다
COMMAND_TOKENS = 2
# 앞에 붙는 실행 래퍼는 명령 이름이 아니다 — `nohup env WORK_DASHBOARD_DB=... python3 server.py`
# 처럼 띄우면 래퍼가 앞 두 토큰을 다 차지해 서버를 놓친다
COMMAND_WRAPPERS = ("nohup", "env")
LSOF_TIMEOUT_SEC = 5
# transcript 는 줄마다 그때의 cwd 를 남긴다. 이스케이프된 도구 결과(\"cwd\")는 걸리지 않는다
CWD_PATTERN = re.compile(r'"cwd"\s*:\s*"([^"]+)"')


def finish(con, claude_session_id, worktree=None):
    """할일을 done 으로 내리고 그 워크트리의 서버를 종료.

    무엇을 했는지와 어디를 봤는지(looked) 를 돌려준다 — 못 찾았을 때 조용히 끝나면
    서버가 남은 것을 아무도 모른다
    """
    session = session_repo.get(con, claude_session_id)
    looked = _candidates(worktree, claude_session_id, session["cwd"])
    root = _first_worktree(looked)
    return {
        "todos": _finish_todos(con, claude_session_id),
        "killed": kill_serving(root),
        "worktree": root,
        "looked": looked,
    }


def worktree_of(claude_session_id, session_cwd, worktree=None):
    """세션이 작업 중인 워크트리 루트. 못 찾으면 빈 문자열"""
    return _first_worktree(_candidates(worktree, claude_session_id, session_cwd))


def _first_worktree(paths):
    return next((path for path in paths if _is_worktree(path)), "")


def _candidates(worktree, claude_session_id, session_cwd):
    """서버를 찾아볼 위치를 순서대로. 손으로 준 값 > transcript 의 마지막 워크트리 > 세션 cwd.

    세션 cwd 를 앞에 두지 않는 이유 — 그 값은 SessionStart 훅이 세션이 열릴 때 적은 것이라
    EnterWorktree 로 옮겨간 뒤에는 메인 체크아웃을 가리킨다. 워크트리로 옮겨 작업하는 것이
    기본 흐름이므로 transcript 에 남은 실제 작업 위치를 먼저 본다
    """
    found = []
    for path in (worktree, last_worktree_cwd(claude_session_id), session_cwd):
        full = os.path.abspath(path) if path else ""
        if full and full not in found:
            found.append(full)
    return found


def last_worktree_cwd(claude_session_id, root=None):
    """세션 transcript 꼬리에 기록된 마지막 워크트리 cwd. 없으면 빈 문자열"""
    path = transcript.find_path(claude_session_id, root)
    if not path:
        return ""
    text = "\n".join(transcript.tail(path))
    worktrees = [cwd for cwd in CWD_PATTERN.findall(text) if WORKTREE_MARK in cwd]
    return worktrees[-1] if worktrees else ""


def _finish_todos(con, claude_session_id):
    return finish_todo_ids(con, session_repo.linked_todo_ids(con, claude_session_id))


def finish_todo_ids(con, todo_ids):
    """이미 done 인 것은 건드리지 않는다.

    세션 단위(_finish_todos)와 워크트리 적용(worktrees.apply) 양쪽이 같은 done 처리를
    쓴다 — 후자는 세션이 아니라 작업 위치로 할일을 찾으므로 id 목록을 직접 받는다
    """
    finished = []
    for todo_id in todo_ids:
        todo = todo_repo.get(con, todo_id)
        if todo["status"] == STATUS_DONE:
            continue
        todo_repo.update(con, todo_id, status=STATUS_DONE)
        finished.append(todo_id)
    return finished


def kill_serving(root):
    """워크트리를 cwd 로 쓰는 서버에 SIGTERM. 죽인 [(pid, 명령)] 을 돌려준다"""
    killed = []
    for pid, command in serving_processes(root):
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:  # 이미 죽었거나 권한 밖
            continue
        killed.append((pid, command))
    return killed


def kill_claude(root):
    """워크트리를 cwd 로 쓰는 Claude 세션에 SIGTERM 하고 죽을 때까지 기다린다.

    워크트리를 지우기 전에 기다리는 이유 — 세션이 종료 중에 파일을 더 쓰면 그 쓰기가
    갓 지운 디렉토리를 되살린다. 죽인 [(pid, 명령)] 을 돌려준다
    """
    killed = []
    for pid, command in claude_processes(root):
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:  # 이미 죽었거나 권한 밖
            continue
        killed.append((pid, command))
    _wait_gone([pid for pid, _ in killed])
    return killed


def claude_processes(root):
    """cwd 가 root 인 Claude 세션 [(pid, 명령)]. 워크트리가 아니면 빈 목록"""
    if not _is_worktree(root):
        return []
    mine = {os.getpid(), os.getppid()}
    return [
        (pid, command)
        for pid, command in _processes_with_cwd(root)
        if pid not in mine and _is_claude(command)
    ]


def _is_claude(command):
    """`claude bg-spare --bg-spare ...`. 그 세션이 띄운 자식(mcp 서버 등)은 부모가
    죽으면 같이 정리되므로 따로 찾지 않는다
    """
    return _named(command, (CLAUDE_NAME,))


def _wait_gone(pids):
    """다 죽었으면 True. 남의 자식이라 waitpid 를 못 쓰므로 신호 0 으로 확인한다"""
    deadline = time.monotonic() + EXIT_WAIT_SEC
    while pids and time.monotonic() < deadline:
        pids = [pid for pid in pids if _alive(pid)]
        if pids:
            time.sleep(EXIT_POLL_SEC)
    return not pids


def _alive(pid):
    """좀비는 죽은 것으로 본다 — 이미 끝났고 부모가 거둬가기만 기다리는 상태인데,
    신호 0 은 그것도 살아 있다고 답한다
    """
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return not _is_zombie(pid)


def _is_zombie(pid):
    """/proc 이 없는 곳(macOS)에서는 판정하지 않는다 — 대기 상한이 대신 받아낸다"""
    try:
        with open(f"/proc/{pid}/stat", "rb") as handle:
            # 명령 이름에 공백·괄호가 들어갈 수 있어 마지막 ')' 뒤부터 읽는다
            fields = handle.read().rsplit(b")", 1)[-1].split()
    except OSError:
        return False
    return bool(fields) and fields[0] == b"Z"


def serving_port(root):
    """그 디렉토리를 cwd 로 쓰는 프로세스가 듣고 있는 포트. 없으면 0.

    죽이는 쪽과 달리 읽기만 하므로 워크트리로 제한하지 않는다 — 메인 체크아웃에서
    작업하는 세션도 자기 서버 포트를 봐야 한다.

    상태줄이 렌더링마다 부르므로 kill_serving 쪽 경로(`lsof -d cwd -t <경로>`, 전체
    프로세스 스캔 300ms)는 쓸 수 없다. 듣고 있는 소켓 목록을 먼저 받아(40ms) 그 pid
    들만 cwd 로 확인한다(40ms). lsof 가 없는 환경에서는 0 — 포트만 안 보이면 된다
    """
    if not root or not os.path.isdir(root):
        return 0
    listeners = _listening_ports()
    if not listeners:
        return 0
    cwds = _cwd_by_pid(listeners)
    target = os.path.realpath(root)
    ports = [
        port
        for pid, port in listeners.items()
        if pid in cwds and os.path.realpath(cwds[pid]) == target
    ]
    return min(ports) if ports else 0


def _listening_ports():
    """{pid: 듣고 있는 포트}. 한 프로세스가 여럿 들으면 가장 작은 것 (보통 그게 웹 포트)"""
    found = {}
    for pid, name in _lsof_fields(["lsof", "-nP", "-iTCP", "-sTCP:LISTEN", "-Fpn"]):
        port = _port_of(name)
        if port and port < found.get(pid, port + 1):
            found[pid] = port
    return found


def _cwd_by_pid(pids):
    joined = ",".join(str(pid) for pid in sorted(pids))
    return dict(_lsof_fields(["lsof", "-a", "-d", "cwd", "-p", joined, "-Fpn"]))


def _lsof_fields(argv):
    """lsof -F 출력을 [(pid, n 필드)] 로. p<pid> 뒤의 n 줄들이 그 프로세스의 것이다"""
    pairs = []
    pid = 0
    for line in _run(argv).splitlines():
        tag, value = line[:1], line[1:]
        if tag == "p":
            pid = int(value) if value.isdigit() else 0
        elif tag == "n" and pid:
            pairs.append((pid, value))
    return pairs


def _port_of(name):
    """`127.0.0.1:9081`, `*:7000`, `[::1]:6379` 에서 포트만. 못 읽으면 0"""
    tail = name.rsplit(":", 1)[-1]
    return int(tail) if tail.isdigit() else 0


def serving_processes(root):
    """cwd 가 root 이고 포트를 듣고 있는 서버 프로세스 [(pid, 명령)].
    워크트리가 아니면 빈 목록"""
    if not _is_worktree(root):
        return []
    mine = {os.getpid(), os.getppid()}
    listening = _listening_ports()
    return [
        (pid, command)
        for pid, command in _processes_with_cwd(root)
        if pid not in mine and _is_server(command) and _listens(pid, listening)
    ]


def _listens(pid, listening):
    """듣고 있는 포트가 있는지. 목록 자체를 못 얻었으면 이름 판정만으로 본다"""
    return not listening or pid in listening


def _is_worktree(path):
    """메인 체크아웃의 대시보드 서버를 죽이지 않기 위한 안전장치 — 경로 모양으로 판단"""
    return bool(path) and WORKTREE_MARK in path and os.path.isdir(path)


def _is_server(command):
    return _named(command, SERVER_NAMES)


def _named(command, names):
    """어떻게 띄웠는지(상대·절대 경로, `-u` 같은 플래그, `env VAR=값` 래퍼, `/bin/sh` 같은
    인터프리터)에 판정이 흔들리면 안 된다. 실행 위치는 이미 cwd 로 걸렀으므로 여기서는
    명령 모양만 본다
    """
    tokens = [
        token
        for token in command.split()
        if not token.startswith("-")
        and "=" not in token
        and os.path.basename(token) not in COMMAND_WRAPPERS
    ]
    return any(os.path.basename(token) in names for token in tokens[:COMMAND_TOKENS])


def _processes_with_cwd(root):
    """(pid, 명령). /proc 이 있으면 그걸로, 없으면(macOS) lsof"""
    if os.path.isdir("/proc"):
        return _by_proc(root)
    return _by_lsof(root)


def _by_proc(root):
    found = []
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            if os.path.realpath(os.readlink(f"/proc/{entry}/cwd")) != os.path.realpath(root):
                continue
            with open(f"/proc/{entry}/cmdline", "rb") as handle:
                raw = handle.read()
        except OSError:  # 이미 죽었거나 권한 밖
            continue
        found.append((int(entry), raw.decode("utf-8", "replace").replace("\0", " ").strip()))
    return found


def _by_lsof(root):
    pids = _run(["lsof", "-a", "-d", "cwd", "-t", root])
    found = []
    for line in pids.splitlines():
        if not line.strip().isdigit():
            continue
        pid = int(line.strip())
        command = _run(["ps", "-p", str(pid), "-o", "command="]).strip()
        if command:
            found.append((pid, command))
    return found


def _run(argv):
    """도구가 없거나 느리면 빈 결과 — 정리 실패가 병합을 막지 않는다"""
    try:
        result = subprocess.run(
            argv, capture_output=True, text=True, timeout=LSOF_TIMEOUT_SEC
        )
    except Exception:
        return ""
    return result.stdout
