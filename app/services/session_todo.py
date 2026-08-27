"""대시보드에서 세션을 워크스페이스로 분류할 때 할일을 만들어 붙인다.

CLI 로 분류하면 Claude 가 지시를 읽고 할일을 만든다. 그런데 웹에서 세션 줄을 눌러
분류하면 그 자리에 Claude 가 없어 할일이 생기지 않는다 — 보드는 그 작업을 모르고,
다음 세션도 무엇을 하던 중인지 알 수 없다.

그래서 제목만 요약을 부르고(app/services/summary.py — claude CLI), 나머지는 코드가
판단할 수 있는 것만 만든다: note 는 지시 원문 그대로.
요약은 CLI 기동만 7~8초라 분류 응답을 붙잡지 않고 뒷일(스레드)로 돌린다. 할일은 지시
첫 문장을 제목으로 먼저 만들어 두고, 요약이 오면 제목만 갈아 끼운다 — 요약 하나 때문에
할일이 안 생기거나 저장이 멈춘 것처럼 보이면 안 된다
"""
import contextlib
import re
import threading

from app.constants import (
    AUTO_TODO_NOTE_HEAD,
    AUTO_TODO_NOTE_PROMPTS,
    AUTO_TODO_NOTE_RAW_TITLE,
    AUTO_TODO_TITLE_CHARS,
)
from app.db import connect
from app.repositories import sessions as session_repo
from app.repositories import todos as todo_repo
from app.services import summary, transcript

ITEM_PATTERN = re.compile(r"^\s*(?:[-*•·]|\d+[.)])\s+(?P<item>\S.*)$")
SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")
ELLIPSIS = "…"


def schedule(work):
    """뒷일 실행. 테스트는 이 함수를 동기 실행으로 갈아끼워 스레드를 기다리지 않는다"""
    threading.Thread(target=work, daemon=True).start()


def ensure_from_session(con, session_row_id, workspace_id, root=None):
    """분류 직후 호출. 만든 할일 또는 만들지 않았으면 None.

    워크스페이스를 인자로 받는 이유 — 세션에는 워크스페이스가 저장되지 않는다.
    세션의 소속은 여기서 만드는 할일 연결로 비로소 생긴다. 그래서 이미 할일이 붙어
    있으면 새로 만들지 않고 그 할일을 옮긴다 — 안 옮기면 다시 분류한 것이 어디에도
    남지 않아 저장이 조용히 무시된다

    제목 요약은 기다리지 않는다 — 첫 문장 제목으로 바로 돌려주고 요약은 뒤따라 붙는다
    """
    if workspace_id is None:
        return None
    session = session_repo.get_by_row_id(con, session_row_id)
    # 이미 잡은 할일이 있으면 그게 이 세션의 작업이다. 새로 만들면 같은 일이 두 줄 된다
    linked = session_repo.linked_todo_ids(con, session["claude_session_id"])
    if linked:
        _move(con, linked, workspace_id)
        return None
    prompts = _prompts(session, root)
    if not prompts:
        return None

    raw_title = _title(prompts[0])
    todo = todo_repo.create(
        con,
        raw_title,
        workspace_id=workspace_id,
        note=_note(session, prompts),
    )
    session_repo.link_todo(con, session["claude_session_id"], todo["id"])
    # 응답은 여기서 확정한다 — 요약은 이 뒤에 붙으므로 사용자가 받는 제목은 첫 문장이다
    created = todo_repo.get(con, todo["id"])
    # 경로는 여기서 꺼낸다 — con 을 뒷일 스레드에서 만지면 sqlite 가 거부한다
    db_path = _db_path(con)
    schedule(lambda: retitle(db_path, todo["id"], prompts[0], raw_title))
    return created


def _move(con, todo_ids, workspace_id):
    # 같은 곳이면 건드리지 않는다 — update 는 sort_order 를 새로 매겨 목록 끝으로 밀어낸다
    for todo_id in todo_ids:
        if todo_repo.get(con, todo_id)["workspace_id"] != workspace_id:
            todo_repo.update(con, todo_id, workspace_id=workspace_id)


def retitle(db_path, todo_id, prompt, raw_title):
    """요약이 오면 제목을 갈아 끼우고 note 의 표시를 지운다.

    실패하면 아무것도 안 한다 — 표시가 note 에 남아 보드·팝업에서 '손봐야 할 제목' 으로 보인다
    """
    title = summary.one_line(prompt)
    if not title:
        return
    # 경로가 비면 connect() 가 기본 경로(사용자의 실제 DB)로 떨어진다 — 남의 DB 에 쓰는 것보다
    # 제목을 못 고치는 편이 낫다
    if not db_path:
        return
    try:
        # 연결을 새로 연다 — 요청 스레드의 연결은 sqlite 가 다른 스레드에서 쓰게 해주지 않는다
        with contextlib.closing(connect(db_path)) as con:
            current = todo_repo.get(con, todo_id)
            if current["title"] != raw_title:
                return  # 그 사이 사용자가 고친 제목을 요약이 덮으면 안 된다
            todo_repo.update(con, todo_id, title=title, note=_without_raw_mark(current["note"]))
    except Exception as error:  # 뒷일이라 응답으로 알릴 데가 없어 서버 로그에만 남긴다
        print(f"제목 요약 반영 실패 (할일 {todo_id}): {error}", flush=True)


def _db_path(con):
    """뒷일 스레드가 같은 DB 를 다시 열 수 있게 지금 열려 있는 파일 경로를 꺼낸다"""
    return con.execute("PRAGMA database_list").fetchone()["file"]


def _prompts(session, root):
    """지시 원문. transcript 를 못 찾으면 DB 에 남은 마지막 지시 한 줄이라도 쓴다"""
    found = transcript.user_prompts(session["claude_session_id"], root)
    if found:
        return found
    return [session["last_prompt"]] if session["last_prompt"] else []


def _title(prompt):
    """요약이 붙기 전(또는 실패했을 때)의 제목 — 첫 지시의 첫 문장.

    목록 표기로 시작하는 줄은 항목이라 제목이 못 된다
    """
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
        # 만들 때는 늘 첫 문장 제목이다. 요약이 붙으면 retitle 이 이 줄을 지운다
        AUTO_TODO_NOTE_RAW_TITLE,
    ]
    lines.append("지시:")
    lines.extend(
        f"{index}) {_reflow(prompt)}"
        for index, prompt in enumerate(prompts[:AUTO_TODO_NOTE_PROMPTS], start=1)
    )
    return "\n".join(lines)


def _without_raw_mark(note):
    """요약이 붙었으니 '첫 문장을 그대로 씀' 표시를 지운다 — 남으면 손봐야 할 제목으로 보인다"""
    return "\n".join(
        line for line in (note or "").splitlines() if line != AUTO_TODO_NOTE_RAW_TITLE
    )


def _reflow(prompt):
    """여러 줄 지시는 줄바꿈을 살리고 번호 아래로 들여쓴다 — 목록으로 적은 지시가 뭉개지지 않게"""
    return "\n   ".join(line.strip() for line in prompt.splitlines() if line.strip())


def _sentences(text):
    return [part.strip() for part in SENTENCE_SPLIT.split(text) if part.strip()]
