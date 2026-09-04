"""세션 탭에서 친 문장을 돌고 있는 Claude 세션에 넣는다.

Claude Code 는 세션마다 /run/user/<uid>/cc-socks/<pid>.sock 을 열고 줄 단위 JSON 을 받는다.
{"type":"user","message":{"content":...}} 가 들어오면 프롬프트 큐에 사용자 메시지로 들어간다 —
SendMessage 가 다른 세션에 보낼 때 쓰는 것과 같은 길이다. 세션 쪽은 이걸 다른 세션이
보낸 메시지로 취급해서 되돌리기 힘든 작업은 한 번 되묻는다.

pid 는 저장하지 않는다. 데몬 spare 프로세스는 처음 등록될 때와 다른 세션을 맡을 수 있어
훅에서 적어 두면 어긋난다. `claude agents --json` 이 유일하게 믿을 수 있는 매핑이다
"""
import json
import os
import socket
import subprocess

from app.constants import AUTORUN_CLAUDE_BIN
from app.errors import Validation
from app.repositories import sessions as session_repo
from app.services import autorun, transcript

SOCKET_DIR = "cc-socks"
SENDER = "work-dashboard"
# now 는 진행 중인 턴을 끊고 다음 입력이 된다 — 열린 선택창을 닫는 용도로만 쓴다.
# next 는 지금 하는 일이 끝난 뒤 큐에서 처리된다
PRIORITY_NOW = "now"
PRIORITY_NEXT = "next"
DELIVERED_SOCKET = "socket"
DELIVERED_RESUMED = "resumed"
AGENTS_TIMEOUT_SEC = 15
SOCKET_TIMEOUT_SEC = 2


def send(con, session_row_id, text, *, agents=None, deliver=None, resume=None):
    """문장을 세션에 넣는다. 살아 있으면 소켓, 끝나 있으면 --resume 으로 다시 띄운다.

    agents·deliver·resume 은 테스트 주입점. 결과 {"delivered": socket|resumed, "priority", "job_id"?}
    """
    text = (text or "").strip()
    if not text:
        raise Validation("보낼 내용이 비어 있습니다")
    session = session_repo.get_by_row_id(con, session_row_id)
    claude_session_id = session["claude_session_id"]
    priority = PRIORITY_NOW if transcript.pending_question(claude_session_id) else PRIORITY_NEXT
    pid = (agents or live_pid)(claude_session_id)
    if pid:
        (deliver or _deliver)(socket_path(pid), _line(claude_session_id, text, priority))
        return {"delivered": DELIVERED_SOCKET, "priority": priority}
    cwd = session.get("cwd") or ""
    if not os.path.isdir(cwd):
        raise Validation(f"세션 작업 위치가 없어 재개할 수 없습니다: {cwd}")
    launched = (resume or autorun.resume_session)(claude_session_id, text, cwd)
    if not launched.get("job_id"):
        raise Validation(f"세션이 살아 있지 않고 재개도 실패했습니다: {launched.get('error')}")
    return {"delivered": DELIVERED_RESUMED, "priority": priority, "job_id": launched["job_id"]}


def live_pid(claude_session_id, claude_bin=AUTORUN_CLAUDE_BIN):
    """`claude agents --json` 에서 이 세션의 pid. 돌고 있지 않으면 None (1~2초)"""
    try:
        result = subprocess.run(
            [claude_bin, "agents", "--json"], capture_output=True, text=True,
            timeout=AGENTS_TIMEOUT_SEC, env=autorun.child_env(),
        )
        rows = json.loads(result.stdout or "[]")
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None
    for row in rows:
        if isinstance(row, dict) and row.get("sessionId") == claude_session_id and row.get("pid"):
            return int(row["pid"])
    return None


def socket_path(pid):
    """XDG_RUNTIME_DIR(없으면 /run/user/<uid>) 아래. 그 경로가 너무 길면 Claude 가 /tmp 로 옮긴다"""
    runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    primary = os.path.join(runtime, SOCKET_DIR, f"{pid}.sock")
    if os.path.exists(primary):
        return primary
    return os.path.join("/tmp", f"{SOCKET_DIR}-{os.getuid()}", f"{pid}.sock")


def _line(claude_session_id, text, priority):
    # session_id 를 같이 보낸다 — pid 가 재사용돼 다른 세션이 받으면 그쪽이 버린다
    message = {
        "type": "user",
        "message": {"content": text},
        "session_id": claude_session_id,
        "priority": priority,
        "from": SENDER,
    }
    return json.dumps(message, ensure_ascii=False) + "\n"


def _deliver(path, line):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(SOCKET_TIMEOUT_SEC)
        try:
            sock.connect(path)
            sock.sendall(line.encode("utf-8"))
        except OSError as error:
            raise Validation(f"세션 소켓에 연결하지 못했습니다: {error}") from error
