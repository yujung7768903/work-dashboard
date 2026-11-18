"""권한 요청에 화면에서 답하기 — 할일 상세 창 제목 아래 '권한 요청' 상자.

무엇을 기다리는지(도구·명령 전문·대상·기다린 시간)는 세션 transcript 의 미응답 도구 호출에서 읽는다. 매니저가
남기는 요청 파일(state/perm/<id>.json)의 미리보기는 비밀값을 가리고 200자에서 자른 것이라 사람이 보고 고를
전문이 아니다. 요청 파일은 '지금 화면에서 답할 수 있는가'와 요청 id 를 아는 데만 쓴다.

화면에서 답할 수 있는 길은 하나다 — 매니저 permission_gate 훅이 결정 파일을 기다리는 동안(최대 9분)
manager.py perm-answer <id> yes|no 로 결정 파일을 쓴다. 훅이 터미널 프롬프트로 넘긴 뒤(사용자가 자리에 있었거나
시간 초과)에는 그 프롬프트가 세션 프로세스 안에 있어 화면에서 닿지 않는다 — 그 세션에 붙어(claude attach)
답하라고 보이기만 한다. 세션이 꺼졌으면 권한 창도 같이 없어졌다고 보인다. 자동 허용은 없다.

허용은 사람이 본 그 호출에만 간다. 요청 id 는 4자리라 끝난 요청의 id 를 새 요청이 다시 쓸 수 있다 — 화면이
보낸 세션·요청 생성 시각·도구 호출 id 가 지금 파일·transcript 와 같을 때만 넘긴다. 미리보기와 transcript 의
호출이 맞는지 확인하지 못했으면 거부만 받는다 — 보지 못한 명령을 허용하게 두지 않는다.
매니저 쪽은 CLI(perm-answer)로만 쓰고, 요청 파일은 읽기만 한다(매니저 탭이 attendance.json 을 읽는 것과 같다).
"""
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone

from app.constants import MANAGER_GATE_HOOK_TIMEOUT_SEC, MANAGER_GATE_WAIT_SEC, MANAGER_TASK_TIMEOUT_SEC
from app.errors import Conflict, NotFound, Validation
from app.repositories import sessions as session_repo
from app.services import session_message, transcript

MODE_GATE = "gate"  # 매니저 훅이 결정 파일을 기다린다 — 화면에서 답한다
MODE_TERMINAL = "terminal"  # 훅이 세션 터미널 프롬프트로 넘겼다 — 그 세션에 붙어서만 답한다
MODE_ENDED = "ended"  # 세션이 꺼져 권한 창도 없어졌다
WAITING_PERMISSION = "permission"
# claude agents --json 행의 waitingFor. 살아 있는 세션이 지금 권한 창을 띄우고 있다는 유일한 신호다 —
# 대시보드 DB 의 waiting 은 훅이 켜고 다음 이벤트가 끄므로 세션이 죽으면 켜진 채 남는다
PROMPT_WAITING = "permission prompt"
REQUEST_ID = re.compile(r"\d{4}")
ANSWERS = {"yes": "allow", "no": "deny"}
# 매니저 redaction.REDACTED 와 같은 표지. 미리보기에서 가린 자리
REDACTED = "[REDACTED]"
# 명령이 아닌 도구에서 '대상'으로 보일 입력 칸
TARGET_FIELDS = ("file_path", "notebook_path", "path", "url")
COMMAND_FIELD = "command"
SCRIPT = "manager.py"
STDERR_TAIL_LINES = 1
STALE_MESSAGE = "이 권한 요청은 이미 끝났거나 바뀌었습니다 — 다시 불러와 확인해 주세요"


def manager_home():
    from app.services import manager_panel

    return manager_panel.manager_home()


def for_todo(con, todo_id, home=None, live=None, root=None, now=None):
    """그 할일을 지금 잡은 세션이 기다리는 권한 → {"items": [...]}.

    세션 고르기는 결정 칸과 같다 — 세션이 가장 최근에 연결한 할일이 이 할일인 것. 꺼진 세션의 남은 요청은
    이 할일의 가장 최근 세션일 때만 보인다(예전 세션의 흔적이 지금 일을 가리지 않게)"""
    sessions = session_repo.list_by_todo(con, todo_id)
    if not sessions:
        return {"items": []}
    cards = session_repo.current_cards(con, [row["claude_session_id"] for row in sessions])
    mine = [row for row in sessions if (cards.get(row["claude_session_id"]) or {}).get("todo_id") == todo_id]
    if not mine:
        return {"items": []}
    now = now or _now()
    requests = pending_requests(home, now)
    # 권한 창이 뜨면 매니저 훅이 DB 에 waiting=permission 을 먼저 찍는다. 그 표시도 요청 파일도 없으면
    # 기다리는 권한이 없다 — 팝업을 열 때마다 claude agents(1~2초)를 부르지 않는다
    mine = [row for row in mine if row.get("waiting") == WAITING_PERMISSION or row["claude_session_id"] in requests]
    if not mine:
        return {"items": []}
    alive = (live or session_message.live_sessions)()
    latest = sessions[0]["claude_session_id"]  # list_by_todo 는 최근 순
    items = []
    for row in mine:
        sid = row["claude_session_id"]
        item = _item(row, requests.get(sid), alive.get(sid), sid == latest, root, now)
        if item:
            items.append(item)
    return {"items": items}


def pending_requests(home=None, now=None):
    """매니저 permission_gate 가 지금 결정을 기다리는 요청. 세션 id → 가장 최근 요청 한 건.
    훅 timeout 보다 오래 남은 파일은 기다리던 훅이 이미 없어 뺀다 — 답해도 받을 쪽이 없다"""
    folder = os.path.join(home or manager_home(), "state", "perm")
    try:
        names = os.listdir(folder)
    except OSError:
        return {}
    now = now or _now()
    found = {}
    for name in names:
        stem, ext = os.path.splitext(name)
        if ext != ".json" or not REQUEST_ID.fullmatch(stem):
            continue
        try:
            with open(os.path.join(folder, name), encoding="utf-8") as handle:
                request = json.load(handle)
        except (OSError, ValueError):
            continue
        if not isinstance(request, dict) or request.get("id") != stem:
            continue
        created = _local_time(request.get("created_at"))
        if not created or (now - created).total_seconds() > MANAGER_GATE_HOOK_TIMEOUT_SEC:
            continue
        sid = request.get("session_id") or ""
        if sid and (sid not in found or found[sid]["created_at"] < request["created_at"]):
            found[sid] = request
    return found


def answer(request_id, reply, session_id, created_at, tool_use_id=None, home=None, root=None, now=None,
           run=subprocess.run):
    """사람이 누른 답을 매니저에 넘긴다(perm-answer). reply 는 yes|no.
    화면이 본 요청(세션·생성 시각)과 지금 기다리는 요청이 같을 때만, 허용은 본 호출(tool_use_id)까지 같을 때만"""
    request_id = str(request_id or "")
    if not REQUEST_ID.fullmatch(request_id):
        raise Validation(f"권한 요청 id 는 숫자 4자리입니다: {request_id}")
    if reply not in ANSWERS:
        raise Validation(f"권한 요청 답은 yes 또는 no 입니다: {reply}")
    home = home or manager_home()
    script = os.path.join(home, SCRIPT)
    if not os.path.isfile(script):
        raise NotFound(f"매니저가 없습니다: {script}")
    request = pending_requests(home, now).get(session_id or "")
    if not request or request["id"] != request_id or request.get("created_at") != created_at:
        raise Conflict(STALE_MESSAGE)
    if reply == "yes":
        matched = match_call(request, transcript.pending_tool_uses(session_id, root))
        if not matched or matched["tool_use_id"] != tool_use_id:
            raise Validation(
                "화면에 보인 명령이 기다리는 요청과 같은지 확인하지 못해 허용할 수 없습니다 — 거부하거나 세션 터미널에서 답해 주세요"
            )
    done = run(
        [sys.executable, script, "perm-answer", request_id, reply],
        cwd=home,
        capture_output=True,
        text=True,
        timeout=MANAGER_TASK_TIMEOUT_SEC,
    )
    if done.returncode == 1:
        raise Conflict(STALE_MESSAGE)  # 그 사이 훅이 시간 초과로 닫았다
    if done.returncode != 0:
        tail = (done.stderr or done.stdout or "").strip().splitlines()[-STDERR_TAIL_LINES:]
        raise RuntimeError(" ".join(tail) or f"manager.py perm-answer exit {done.returncode}")
    return {"id": request_id, "decision": ANSWERS[reply], "session_id": session_id}


def match_call(request, calls):
    """요청 파일의 미리보기(가림·200자 자름)와 맞는 미응답 호출. 가린 자리를 건너뛰고 남은 조각이 호출 입력
    JSON 의 맨 앞부터 순서대로 들어 있으면 같은 호출로 본다. 여럿이면 가장 최근 것. 못 찾으면 None"""
    preview = request.get("preview") or ""
    pieces = preview.split(REDACTED)
    pieces[-1] = _strip_partial_mark(pieces[-1])
    for call in reversed(calls):
        if call.get("name") != request.get("tool_name"):
            continue
        if _in_order(json.dumps(call.get("input") or {}, ensure_ascii=False), pieces):
            return call
    return None


def _item(row, request, live_row, latest, root, now):
    sid = row["claude_session_id"]
    prompting = bool(live_row) and live_row.get("waitingFor") == PROMPT_WAITING
    if request:
        mode = MODE_GATE
    elif prompting:
        mode = MODE_TERMINAL
    elif not live_row and latest and row.get("waiting") == WAITING_PERMISSION:
        mode = MODE_ENDED
    else:
        return None
    short = (live_row or {}).get("id") or sid[:8]
    session = {
        "id": row["id"],
        "claude_session_id": sid,
        "short": short,
        "name": (live_row or {}).get("name") or "",
        "cwd": row.get("cwd") or "",
    }
    calls = transcript.pending_tool_uses(sid, root)
    if mode == MODE_GATE:
        return _view(mode, session, request, calls, match_call(request, calls), now)
    if not calls:
        return None  # 무엇을 기다리는지 찾지 못했다 — 보여 줄 것이 없다
    return _view(mode, session, None, calls, None, now)


def gate_view(request, session, now=None, root=None):
    """매니저 권한대기 목록의 걸린 요청 한 건(permission_gate 가 결정을 기다림)을 권한 요청 카드 모양으로.
    매니저 탭 '권한 대기' 칸이 쓴다 — 할일 상세 카드와 같은 확인 규칙(전문을 찾은 호출만 허용 가능)을 따른다.
    session = {"id", "claude_session_id", "short", "name", "cwd"}"""
    calls = transcript.pending_tool_uses(session["claude_session_id"], root)
    return _view(MODE_GATE, session, request, calls, match_call(request, calls), now or _now())


def _view(mode, session, request, calls, matched, now):
    shown = ([matched] if matched else []) if mode == MODE_GATE else calls
    if request:
        requested = _local_time(request.get("created_at"))
    else:
        requested = _utc_time(shown[0].get("at"))
    return {
        "key": f"{session['claude_session_id']}:{request['id'] if request else shown[0]['tool_use_id']}",
        "mode": mode,
        "session": session,
        "request": _request_view(request),
        "calls": [_call_view(call) for call in shown],
        "verified": bool(matched),
        "requested_at": _iso(requested),
        "waited_sec": max(0, int((now - requested).total_seconds())) if requested else None,
        "deadline_at": _iso(requested + timedelta(seconds=MANAGER_GATE_WAIT_SEC)) if request and requested else None,
        "attach": f"claude attach {session['short']}" if mode == MODE_TERMINAL else None,
    }


def _request_view(request):
    if not request:
        return None
    return {
        "id": request["id"],
        "created_at": request.get("created_at") or "",
        "tool_name": request.get("tool_name") or "",
        "deliver": request.get("deliver") or "",
        "preview": request.get("preview") or "",
    }


def _call_view(call):
    """명령 전문. Bash 류는 command 글 그대로, 그 밖의 도구는 입력 전체를 JSON 으로 — 자르지 않는다"""
    data = call.get("input") or {}
    command = data.get(COMMAND_FIELD) if isinstance(data.get(COMMAND_FIELD), str) else None
    target = next((data[field] for field in TARGET_FIELDS if isinstance(data.get(field), str)), None)
    return {
        "tool_use_id": call.get("tool_use_id") or "",
        "tool": call.get("name") or "",
        "description": data.get("description") if isinstance(data.get("description"), str) else None,
        "target": target,
        "text": command if command is not None else json.dumps(data, ensure_ascii=False, indent=2),
        "is_command": command is not None,
        "at": call.get("at") or "",
    }


def _strip_partial_mark(piece):
    """200자에서 잘린 미리보기 끝이 가림 표지의 앞부분('[RED')으로 끝나면 떼어 낸다"""
    for size in range(len(REDACTED) - 1, 0, -1):
        if piece.endswith(REDACTED[:size]):
            return piece[:-size]
    return piece


def _in_order(full, pieces):
    position = 0
    for index, piece in enumerate(pieces):
        if not piece:
            continue
        found = full.find(piece, position)
        if found < 0 or (index == 0 and found != 0):
            return False
        position = found + len(piece)
    return True


def _local_time(text):
    """요청 파일의 created_at — 매니저 훅이 time.strftime 으로 찍은 이 PC 지역 시각(시간대 없음)"""
    try:
        stamp = datetime.fromisoformat(text or "")
    except ValueError:
        return None
    return stamp.astimezone() if stamp.tzinfo is None else stamp


def _utc_time(text):
    try:
        stamp = datetime.fromisoformat((text or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)


def _iso(stamp):
    return stamp.astimezone().isoformat(timespec="seconds") if stamp else None


def _now():
    return datetime.now().astimezone()
