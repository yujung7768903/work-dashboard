"""병합으로 작업이 끝났을 때의 리소스 해제.

세 가지가 남는다 — 연결된 할일, 그 워크트리를 쓰던 서버 프로세스, 워크트리 디렉토리.
앞의 둘은 여기서 처리하고, 워크트리 제거는 에이전트의 ExitWorktree 가 맡는다
(에이전트의 cwd 가 그 안이라 밖에서 지우면 셸이 깨진다).
"""
import os
import re
import signal
import subprocess

from app.constants import STATUS_DONE
from app.repositories import sessions as session_repo
from app.repositories import todos as todo_repo
from app.services import transcript

# 종료 대상은 워크트리 안에서만 찾는다. 메인 체크아웃까지 뒤지면
# 사용자가 보고 있는 대시보드 서버를 죽인다
WORKTREE_MARK = "/.claude/worktrees/"
# cwd 가 워크트리라도 서버 형태가 아니면 건드리지 않는다 (셸·에디터 등)
SERVER_NAMES = ("server.py", "manage.py", "npm", "yarn", "pnpm", "vite", "next", "node")
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
    root = next((path for path in looked if _is_worktree(path)), "")
    return {
        "todos": _finish_todos(con, claude_session_id),
        "killed": kill_serving(root),
        "worktree": root,
        "looked": looked,
    }


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
    """이미 done 인 것은 건드리지 않는다. 하위할일이 남았으면 Validation 이 그대로 올라온다"""
    finished = []
    for todo_id in session_repo.linked_todo_ids(con, claude_session_id):
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


def serving_processes(root):
    """cwd 가 root 인 서버 프로세스 [(pid, 명령)]. 워크트리가 아니면 빈 목록"""
    if not _is_worktree(root):
        return []
    mine = {os.getpid(), os.getppid()}
    return [
        (pid, command)
        for pid, command in _processes_with_cwd(root)
        if pid not in mine and _is_server(command)
    ]


def _is_worktree(path):
    """메인 체크아웃의 대시보드 서버를 죽이지 않기 위한 안전장치 — 경로 모양으로 판단"""
    return bool(path) and WORKTREE_MARK in path and os.path.isdir(path)


def _is_server(command):
    """어떻게 띄웠는지(상대·절대 경로, `-u` 같은 플래그, `env VAR=값` 래퍼)에 판정이
    흔들리면 안 된다. 실행 위치는 이미 cwd 로 걸렀으므로 여기서는 명령 모양만 본다
    """
    tokens = [
        token
        for token in command.split()
        if not token.startswith("-")
        and "=" not in token
        and os.path.basename(token) not in COMMAND_WRAPPERS
    ]
    return any(
        os.path.basename(token) in SERVER_NAMES for token in tokens[:COMMAND_TOKENS]
    )


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
