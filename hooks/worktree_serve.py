#!/usr/bin/env python3
"""Stop 훅: 워크트리에서 웹 프로젝트를 고쳤는데 그 워크트리를 서비스하는 프로세스가 없으면
종료를 막고, 서버를 띄워 `url:` 로 주소를 알리라고 지시.

이미 떠 있으면 관여하지 않음 — 다른 세션이 그 화면을 보고 있을 수 있어 재기동하지 않는다.
훅 오류는 fail-open(exit 0) — 종료를 막는 사고가 더 큼.
"""
import json
import os
import re
import socket
import subprocess
import sys

EXIT_OK = 0
EXIT_BLOCK = 2
RUN_TIMEOUT_SEC = 2
WORKTREE_MARK = "/.claude/worktrees/"
# 이 중 하나라도 워크트리 루트에 있으면 띄울 수 있는 웹 프로젝트로 본다
SERVER_ENTRIES = ("server.py", "manage.py", "package.json")
# 프로세스 cwd 가 워크트리라도 서버 형태가 아니면(셸 등) 떠 있다고 보지 않음
SERVER_HINTS = ("server.py", "manage.py", "npm", "yarn", "pnpm", "vite", "next", "node")
PORT_RANGE = range(9080, 9140)
PATH_PATTERN = re.compile(r'"(?:file_path|notebook_path)"\s*:\s*"([^"]+)"')

MESSAGE = """워크트리를 고쳤는데 그 코드를 서비스하는 프로세스가 없음: {root}

- 실행 방법은 그 워크트리의 README·CLAUDE.md 에서 확인 (예: python3 server.py --port {port})
- 워크트리 루트를 cwd 로, `nohup ... &` 로 띄워 세션이 끝나도 살아 있게 함
  (macOS 에는 setsid 가 없으므로 쓰지 않는다)
- 비어 있는 포트: {port}
- 띄운 뒤 응답 마지막을 아래 리스트로 끝냄:

- 워크트리: {root}
- url: http://127.0.0.1:{port}/
- 작업 요약: <이 워크트리에서 바꾼 것>"""


def main(stdin=None):
    try:
        payload = json.loads((stdin or sys.stdin).read() or "{}")
        # 이미 이 훅이 한 번 막았으면 다시 막지 않음 (무한 루프 방지)
        if payload.get("stop_hook_active"):
            return EXIT_OK
        pending = unserved_worktrees(payload.get("transcript_path") or "")
        if not pending:
            return EXIT_OK
        port = free_port()
        if port is None:
            return EXIT_OK
    except Exception:  # 훅 실패로 세션 종료를 막지 않음
        return EXIT_OK
    print(MESSAGE.format(root=pending[0], port=port), file=sys.stderr)
    return EXIT_BLOCK


def unserved_worktrees(transcript_path):
    """이번 세션에 편집된 워크트리 중 웹 프로젝트인데 서버가 없는 것"""
    return [
        root
        for root in _edited_worktrees(transcript_path)
        if _is_web_project(root) and not _is_served(root)
    ]


def _edited_worktrees(transcript_path):
    if not transcript_path or not os.path.isfile(transcript_path):
        return []
    with open(transcript_path, encoding="utf-8", errors="replace") as handle:
        text = handle.read()
    roots = []
    for path in PATH_PATTERN.findall(text):
        root = _worktree_root(path)
        if root and root not in roots:
            roots.append(root)
    return roots


def _worktree_root(path):
    """.../.claude/worktrees/<이름> 까지가 워크트리 루트"""
    index = path.find(WORKTREE_MARK)
    if index < 0:
        return None
    name = path[index + len(WORKTREE_MARK) :].split("/")[0]
    if not name:
        return None
    return path[:index] + WORKTREE_MARK + name


def _is_web_project(root):
    return any(os.path.exists(os.path.join(root, name)) for name in SERVER_ENTRIES)


def _is_served(root):
    """cwd 가 그 워크트리이고 커맨드가 서버 형태인 프로세스가 있는지.

    cwd 는 symlink 가 풀린 실경로로 나오므로(macOS 의 /var → /private/var) 양쪽을 맞춘다.
    """
    return os.path.realpath(root) in _cwds(_server_pids())


def _server_pids():
    """커맨드가 서버 형태인 프로세스의 pid. ps 는 리눅스·macOS 공통"""
    pids = []
    for line in _run(["ps", "-eo", "pid=,args="]).splitlines():
        pid, _, args = line.strip().partition(" ")
        if pid.isdigit() and any(hint in args for hint in SERVER_HINTS):
            pids.append(pid)
    return pids


def _cwds(pids):
    """프로세스들의 cwd 집합. 리눅스는 /proc, macOS 등은 lsof 한 번으로 모아 읽는다"""
    if not pids:
        return set()
    if os.path.isdir("/proc"):
        return {cwd for cwd in (_proc_cwd(pid) for pid in pids) if cwd}
    # lsof -Fn 은 경로 줄만 'n' 으로 시작 — pid 짝은 필요 없고 경로 집합이면 충분
    output = _run(["lsof", "-a", "-d", "cwd", "-Fn", "-p", ",".join(pids)])
    return {line[1:] for line in output.splitlines() if line.startswith("n")}


def _proc_cwd(pid):
    try:
        return os.readlink(f"/proc/{pid}/cwd")
    except OSError:  # 이미 죽었거나 권한 밖
        return None


def _run(command):
    """실패·미설치·지연은 빈 출력으로 — 판단을 못 하면 '서버 없음'으로 보고 알린다"""
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=RUN_TIMEOUT_SEC
        )
    except Exception:
        return ""
    return result.stdout


def free_port():
    for port in PORT_RANGE:
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                continue
        return port
    return None


if __name__ == "__main__":
    sys.exit(main())
