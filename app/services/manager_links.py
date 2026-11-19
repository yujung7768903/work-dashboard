"""매니저 탭 줄을 대시보드 트리에 잇는다.

- 카드: 그 일을 하는 세션이 지금 붙잡은 할일(가장 최근 연결 = sessions 의 LATEST_LINKED)과 그 할일의
  트리(맨 위 할일 — root_id·root_title·tree_key). 매니저 할일은 session_id 로, 보조 세션은 자기 세션 id 로 찾는다.
- 사용자 요청: 그 세션이 맨 처음 받은 사람의 지시 전문. 무엇 때문에 시작한 일인지를 보이려는 것이다.
  보조 세션의 첫 지시는 매니저 spawn 지시문이고, 끝에 spawn 이 자동으로 붙이는 안내 문단
  (진행률·산출물·결정·권한·완료 보고·매니저 자체 작업)은 사람이 쓴 요청이 아니라 걷어낸다.

transcript·매니저 레포는 읽기만 한다
"""
import ast
import json
import os
import re
import sqlite3

from app.db import UNIFIED_FLAG, meta_get
from app.repositories import sessions as session_repo
from app.services import transcript

# manager spawn.py 가 지시 끝에 붙이는 문단 상수 (spawn.with_self_stop). 문구를 여기 베끼지 않고
# 매니저 코드에서 읽는다 — 매니저가 문구를 고쳐도 따라간다
SPAWN_FILE = "spawn.py"
SPAWN_SUFFIXES = ("PROGRESS", "OPEN_RESULT", "DECISION", "BLOCKED", "DASH_TODO", "SELF_STOP", "MANAGER_WORK")
# 문단 머리 몇 자로 알아본다. 예전에 붙은 지시는 문구 끝이 지금과 조금 다를 수 있다
SUFFIX_HEAD_CHARS = 16
PARAGRAPH = "\n\n"
# 사람이 친 지시가 아닌 user 줄. 세션 팝업과 달리 슬래시 명령도 요청으로 치지 않는다
NOT_REQUEST = (
    "<command-",
    "<local-command",
    "Caveat:",
    "Below is a conversation log",
    "Please write a 5-10 word title",
)
REMINDER = re.compile(r"<system-reminder>.*?</system-reminder>", re.S)
STATUS_OK = "ok"
STATUS_NO_SESSION = "no_session"
STATUS_NOT_FOUND = "not_found"
STATUS_EMPTY = "empty"

# 첫 요청은 세션이 사는 동안 바뀌지 않는다 — 찾은 것은 다시 읽지 않는다
_request_cache = {}


def cards(con, session_ids):
    """세션 id → 카드 {todo_id, title, status, category_color, root_id, root_title, tree_key}.
    root_* 는 그 할일 트리의 맨 위 할일, tree_key 는 트리 화면의 트리 id(t12·c3).
    workspace_id(늘 None)·workspace_name(=root_title)은 옛 소비자용 별칭이다(sessions.current_cards).
    연결된 할일이 없거나 대시보드 DB 가 없으면 그 세션은 빠진다"""
    if con is None:
        return {}
    return session_repo.current_cards(con, [sid for sid in session_ids if sid])


def task_cards(con, task_ids):
    """매니저 할일 id → 그 할일 자신의 카드. 통합 뒤(unified)에만 — 매니저 할일이 곧 대시보드 할일이다.
    통합 전에는 매니저 할일과 대시보드 할일이 다른 번호라 빈 dict(줄은 세션 카드 cards 로 그린다)"""
    if not unified(con):
        return {}
    return session_repo.todo_cards(con, task_ids)


# 대기 종류 (대시보드 sessions.waiting). 매니저 tasks.BLOCKED_PERMISSION 도 같은 낱말이다
WAIT_INPUT = "input"
WAIT_PERMISSION = "permission"


def waiting(con, session_ids, blocked=None):
    """세션 id → 사람 대기 종류(permission·input). 트리 카드의 대기 표시와 같은 신호(대시보드 sessions.waiting).
    답 대기(input)인데 그 세션이 권한 막힘을 남겼으면 권한 대기다(blocked — 없으면 permission_sessions() 로 읽는다).
    대기 중이 아니거나 대시보드 DB 가 없으면 그 세션은 빠진다"""
    if con is None:
        return {}
    found = session_repo.waiting_by_session(con, session_ids)
    if blocked is None and WAIT_INPUT in found.values():
        blocked = permission_sessions(con=con)
    return {sid: promote(kind, sid, blocked) for sid, kind in found.items()}


def promote(kind, session_id, blocked):
    """답 대기(input) → 권한 대기(permission), 그 세션이 ask --blocked permission 으로 남긴 열린 할일이 있을 때.
    매니저 Stop 훅은 열린 결정·권한 막힘을 가리지 않고 waiting=input 을 찍는다 — sessions.waiting=permission 은
    '권한 창이 떠 있다'는 뜻으로 권한 요청 카드(permission_answer)가 쓰므로 훅이 그 값을 찍게 바꾸지 않고 화면에서 올린다"""
    return WAIT_PERMISSION if kind == WAIT_INPUT and session_id in (blocked or ()) else kind


def unified(con):
    """대시보드 DB 가 매니저 할일을 함께 들고 있는지 — 이관(매니저 tasks → todos)이 끝나면 meta 에 표시가 남는다.
    그 뒤로 정본은 대시보드 todos(뷰 manager_tasks)이고 매니저 state/manager.db 의 tasks 는 더 갱신되지 않는다"""
    if con is None:
        return False
    try:
        return meta_get(con, UNIFIED_FLAG) is not None
    except sqlite3.Error:
        return False


def permission_sessions(manager_home=None, con=None):
    """ask --blocked permission 으로 남긴 열린 매니저 할일이 있는 세션 id 집합. 통합 뒤(unified)면 대시보드 DB 의
    뷰 manager_tasks 를, 그 전이면 매니저 DB 를 읽기 전용으로 읽는다.
    매니저가 없거나 blocked 칸이 없는 예전 DB 면 빈 집합 — 대기 표시는 원래 신호대로 둔다"""
    query = "SELECT DISTINCT session_id FROM {} WHERE status='open' AND blocked=? AND session_id IS NOT NULL"
    if unified(con):
        try:
            rows = con.execute(query.format("manager_tasks"), (WAIT_PERMISSION,)).fetchall()
        except sqlite3.Error:
            return frozenset()
        return frozenset(row[0] for row in rows)
    if manager_home is None:
        from app.services import manager_panel

        manager_home = manager_panel.manager_home()
    path = os.path.join(manager_home, "state", "manager.db")
    if not os.path.isfile(path):
        return frozenset()
    try:
        manager_con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            rows = manager_con.execute(query.format("tasks"), (WAIT_PERMISSION,)).fetchall()
        finally:
            manager_con.close()
    except sqlite3.Error:
        return frozenset()
    return frozenset(row[0] for row in rows)


def first_request(session_id, manager_home=None, root=None):
    """{"status": ok|no_session|not_found|empty, "text": 전문(ok 일 때)}"""
    if not session_id:
        return {"status": STATUS_NO_SESSION}
    path = transcript.find_path(session_id, root)
    if not path:
        return {"status": STATUS_NOT_FOUND}
    if path not in _request_cache:
        text = first_user_text(path)
        if text is None:
            return {"status": STATUS_EMPTY}
        _request_cache[path] = strip_spawn_suffix(text, spawn_heads(manager_home))
    return {"status": STATUS_OK, "text": _request_cache[path]}


def first_user_text(path):
    """transcript 에서 사람이 보낸 첫 지시 전문. 훅·리마인더가 넣은 글은 뺀다.
    앞에서부터 읽다 찾으면 멈춘다 — 첫 지시는 파일 앞쪽에 있다"""
    try:
        with open(path, encoding="utf-8", errors="ignore") as handle:
            for line in handle:
                text = _user_text(line)
                if text:
                    return text
    except OSError:
        return None
    return None


def _user_text(line):
    try:
        entry = json.loads(line)
    except ValueError:
        return None
    if not isinstance(entry, dict) or entry.get("type") != "user":
        return None
    if entry.get("isSidechain") or entry.get("isMeta"):
        return None
    content = (entry.get("message") or {}).get("content")
    if isinstance(content, str):
        blocks = [content]
    elif isinstance(content, list):
        # 도구 결과(tool_result)는 사람이 친 글이 아니다
        blocks = [
            block.get("text") or ""
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        ]
    else:
        return None
    text = REMINDER.sub("", "\n".join(blocks)).strip()
    if not text or text.startswith(NOT_REQUEST):
        return None
    return text


def strip_spawn_suffix(text, heads):
    """끝에서부터 spawn 안내 문단을 걷어낸다. 끝이 아닌 자리에 같은 말이 있으면 사람이 쓴 것이라 둔다"""
    parts = text.rstrip().split(PARAGRAPH)
    while len(parts) > 1 and parts[-1].strip().startswith(heads):
        parts.pop()
    return PARAGRAPH.join(parts).rstrip()


def spawn_heads(manager_home=None):
    """spawn 안내 문단 머리 글자들. 매니저 레포가 없으면 빈 튜플 — 그때는 걷어내지 않는다"""
    if not manager_home:
        from app.services import manager_panel

        manager_home = manager_panel.manager_home()
    path = os.path.join(manager_home, SPAWN_FILE)
    try:
        with open(path, encoding="utf-8") as handle:
            tree = ast.parse(handle.read())
    except (OSError, SyntaxError):
        return ()
    heads = []
    for node in tree.body:
        if not (isinstance(node, ast.Assign) and len(node.targets) == 1):
            continue
        target = node.targets[0]
        if not (isinstance(target, ast.Name) and target.id in SPAWN_SUFFIXES):
            continue
        try:
            value = ast.literal_eval(node.value)
        except ValueError:
            continue
        if isinstance(value, str) and value.strip():
            heads.append(value.strip()[:SUFFIX_HEAD_CHARS])
    return tuple(heads)
