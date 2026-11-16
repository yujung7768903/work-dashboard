"""매니저 탭 줄을 대시보드 트리에 잇는다.

- 카드: 그 일을 하는 세션이 지금 붙잡은 할일(가장 최근 연결 = sessions 의 LATEST_LINKED)과 그 할일의
  트리(워크스페이스). 매니저 할일은 session_id 로, 보조 세션은 자기 세션 id 로 찾는다.
- 사용자 요청: 그 세션이 맨 처음 받은 사람의 지시 전문. 무엇 때문에 시작한 일인지를 보이려는 것이다.
  보조 세션의 첫 지시는 매니저 spawn 지시문이고, 끝에 spawn 이 자동으로 붙이는 안내 문단
  (진행률·산출물·결정·권한·완료 보고·매니저 자체 작업)은 사람이 쓴 요청이 아니라 걷어낸다.

transcript·매니저 레포는 읽기만 한다
"""
import ast
import json
import os
import re

from app.repositories import sessions as session_repo
from app.services import transcript

# manager spawn.py 가 지시 끝에 붙이는 문단 상수 (spawn.with_self_stop). 문구를 여기 베끼지 않고
# 매니저 코드에서 읽는다 — 매니저가 문구를 고쳐도 따라간다
SPAWN_FILE = "spawn.py"
SPAWN_SUFFIXES = ("PROGRESS", "OPEN_RESULT", "DECISION", "BLOCKED", "SELF_STOP", "MANAGER_WORK")
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
    """세션 id → 카드 {todo_id, title, status, workspace_id, workspace_name, category_color}.
    연결된 할일이 없거나 대시보드 DB 가 없으면 그 세션은 빠진다"""
    if con is None:
        return {}
    return session_repo.current_cards(con, [sid for sid in session_ids if sid])


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
