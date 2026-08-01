"""대시보드에서 세션을 워크스페이스로 분류할 때 할일을 만들어 붙인다.

CLI 로 분류하면 Claude 가 지시를 읽고 할일을 만든다. 그런데 웹에서 세션 줄을 눌러
분류하면 그 자리에 Claude 가 없어 할일이 생기지 않는다 — 보드는 그 작업을 모르고,
다음 세션도 무엇을 하던 중인지 알 수 없다.

그래서 여기서는 코드가 판단할 수 있는 것만 만든다: 제목·note 는 지시 원문에서,
하위할일은 지시에 목록 표기가 있을 때만. 의미 판단(범위 쪼개기·요약)은 그 세션의
Claude 가 이어서 다듬는다
"""
import re

from app.constants import (
    AUTO_TODO_MAX_SUBTASKS,
    AUTO_TODO_MIN_SUBTASKS,
    AUTO_TODO_NOTE_HEAD,
    AUTO_TODO_NOTE_PROMPTS,
    AUTO_TODO_TITLE_CHARS,
)
from app.repositories import sessions as session_repo
from app.repositories import subtasks as subtask_repo
from app.repositories import todos as todo_repo
from app.services import transcript

ITEM_PATTERN = re.compile(r"^\s*(?:[-*•·]|\d+[.)])\s+(?P<item>\S.*)$")
SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")
# 목록 표기가 없는 지시는 요청 문장 여러 개를 한 문단에 붙여 쓴다
# ("...연결해줘. ...추출해주고. note 도 채워주고"). 그 문장들만 하위할일로 본다.
# ponytail: 요청 어미로 끝나는 문장만 — 아무 문장이나 쪼개면 설명·군더더기가 할일로 올라온다
REQUEST_ENDINGS = ("줘", "주고", "줄래", "달라", "부탁", "싶어", "필요해")
TRAILING_PUNCT = " .!?~"
ELLIPSIS = "…"
MIN_ITEM_CHARS = 2


def ensure_from_session(con, session_row_id, root=None):
    """분류 직후 호출. 만든 할일(하위할일 포함) 또는 만들지 않았으면 None"""
    session = session_repo.get_by_row_id(con, session_row_id)
    if session["workspace_id"] is None:
        return None
    # 이미 잡은 할일이 있으면 그게 이 세션의 작업이다. 새로 만들면 같은 일이 두 줄 된다
    if session_repo.linked_todo_ids(con, session["claude_session_id"]):
        return None
    prompts = _prompts(session, root)
    if not prompts:
        return None

    todo = todo_repo.create(
        con,
        _title(prompts[0]),
        workspace_id=session["workspace_id"],
        note=_note(session, prompts),
    )
    for title in _item_titles(prompts):
        subtask_repo.create(con, todo["id"], title)
    session_repo.link_todo(con, session["claude_session_id"], todo["id"])
    return {**todo_repo.get(con, todo["id"]), "subtasks": subtask_repo.list_by_todo(con, todo["id"])}


def _prompts(session, root):
    """지시 원문. transcript 를 못 찾으면 DB 에 남은 마지막 지시 한 줄이라도 쓴다"""
    found = transcript.user_prompts(session["claude_session_id"], root)
    if found:
        return found
    return [session["last_prompt"]] if session["last_prompt"] else []


def _title(prompt):
    """첫 지시의 첫 문장. 목록 표기로 시작하는 줄은 항목이라 제목이 못 된다"""
    lines = [line.strip() for line in prompt.splitlines() if line.strip()]
    head = next((line for line in lines if not ITEM_PATTERN.match(line)), lines[0])
    first = _sentences(head)[0] if _sentences(head) else head
    if len(first) <= AUTO_TODO_TITLE_CHARS:
        return first
    return first[: AUTO_TODO_TITLE_CHARS - len(ELLIPSIS)].rstrip() + ELLIPSIS


def _note(session, prompts):
    """착수할 때 필요한 것 — 어디서 무엇을 하라고 했는지. 요약하지 않고 원문을 남긴다"""
    lines = [
        AUTO_TODO_NOTE_HEAD,
        f"위치: {session['cwd'] or '(모름)'} / 브랜치: {session['git_branch'] or '(없음)'}",
        f"세션: {session['claude_session_id']}",
        "지시:",
    ]
    lines.extend(
        f"{index}) {_reflow(prompt)}"
        for index, prompt in enumerate(prompts[:AUTO_TODO_NOTE_PROMPTS], start=1)
    )
    return "\n".join(lines)


def _reflow(prompt):
    """여러 줄 지시는 줄바꿈을 살리고 번호 아래로 들여쓴다 — 목록으로 적은 지시가 뭉개지지 않게"""
    return "\n   ".join(line.strip() for line in prompt.splitlines() if line.strip())


def _item_titles(prompts):
    """지시에서 뽑은 하위할일. 하나뿐이면 할일과 같은 말이라 버린다"""
    items = _marked_items(prompts) or _request_sentences(prompts[0])
    if len(items) < AUTO_TODO_MIN_SUBTASKS:
        return []
    return items[:AUTO_TODO_MAX_SUBTASKS]


def _marked_items(prompts):
    """목록 표기로 적은 항목들. 지시가 여러 건이면 전부 모은다"""
    items = []
    for prompt in prompts:
        for line in prompt.splitlines():
            match = ITEM_PATTERN.match(line)
            item = match.group("item").strip() if match else ""
            if len(item) >= MIN_ITEM_CHARS and item not in items:
                items.append(item)
    return items


def _request_sentences(prompt):
    """첫 지시의 둘째 문장부터 나오는 요청들.

    첫 지시만 보는 이유 — 뒤따라오는 지시는 대개 수정·곁가지라 그것까지 하위할일로
    올리면 '아니 그거 말고' 가 할일이 된다. 첫 문장을 건너뛰는 이유 — 그건 제목이 됐다
    """
    items = []
    for sentence in _sentences(prompt)[1:]:
        item = sentence.strip(TRAILING_PUNCT)
        if item.endswith(REQUEST_ENDINGS) and len(item) >= MIN_ITEM_CHARS and item not in items:
            items.append(item)
    return items


def _sentences(text):
    return [part.strip() for part in SENTENCE_SPLIT.split(text) if part.strip()]
