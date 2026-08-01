"""병합으로 작업이 끝났을 때의 리소스 해제.

세 가지가 남는다 — 연결된 할일, 그 워크트리를 쓰던 서버 프로세스, 워크트리 디렉토리.
앞의 둘은 여기서 처리하고, 워크트리 제거는 에이전트의 ExitWorktree 가 맡는다
(에이전트의 cwd 가 그 안이라 밖에서 지우면 셸이 깨진다).
"""
import os
import signal
import subprocess

from app.constants import STATUS_DONE
from app.repositories import sessions as session_repo
from app.repositories import todos as todo_repo

# 종료 대상은 워크트리 안에서만 찾는다. 메인 체크아웃까지 뒤지면
# 사용자가 보고 있는 대시보드 서버를 죽인다
WORKTREE_MARK = "/.claude/worktrees/"
# cwd 가 워크트리라도 서버 형태가 아니면 건드리지 않는다 (셸·에디터 등)
SERVER_NAMES = ("server.py", "manage.py", "npm", "yarn", "pnpm", "vite", "next", "node")
# 명령줄 앞 두 토큰만 본다 — `zsh -c '... server.py ...'` 같은 셸이 서버로 잡히면
# 자기 자신을 죽인다
COMMAND_TOKENS = 2
LSOF_TIMEOUT_SEC = 5


def finish(con, claude_session_id, worktree=None):
    """할일을 done 으로 내리고 그 워크트리의 서버를 종료. 무엇을 했는지 돌려준다"""
    session = session_repo.get(con, claude_session_id)
    root = os.path.abspath(worktree or session["cwd"] or "") if (worktree or session["cwd"]) else ""
    return {
        "todos": _finish_todos(con, claude_session_id),
        "killed": kill_serving(root),
        "worktree": root,
    }


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
    if not root or WORKTREE_MARK not in root or not os.path.isdir(root):
        return []
    mine = {os.getpid(), os.getppid()}
    return [
        (pid, command)
        for pid, command in _processes_with_cwd(root)
        if pid not in mine and _is_server(command)
    ]


def _is_server(command):
    tokens = command.split()[:COMMAND_TOKENS]
    return any(os.path.basename(token) in SERVER_NAMES for token in tokens)


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
