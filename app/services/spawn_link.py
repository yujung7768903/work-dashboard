"""매니저 spawn 이 띄운 보조 세션을 할일 그래프에 잇는다.

보조 세션이 스스로 분류·할일 연결을 하게 두면 조사·분석 일은 '단발 조회' 로 보고 할일을 만들지 않아
(11-11~16 비매니저 보조 99개 중 83개) 트리에서 그 일과 맥락이 통째로 사라졌다. 그래서 띄우는 쪽이:
1) 출처(원래 세션·매니저 할일)를 남기고 — 원래 세션이 잡고 있던 할일이 새 할일의 상위(계기) 제안이 된다
2) 할일을 바로 만들어 수행(session_todos)으로 잇는다. 자리는 원래 세션 할일의 워크스페이스, 모르면 워크스페이스
   없이 임시 카테고리. 세션이 나중에 분류하면(dash.py classify) 그 임시 할일만 분류한 곳으로 옮긴다
매니저는 이 모듈을 import 해 부른다(~/work/manager manager.py _launch)
"""
import re

from app.constants import (
    SPAWN_FALLBACK_CATEGORY,
    SPAWN_NOTE_CHARS,
    SPAWN_PROVISIONAL_LINE,
    SPAWN_TODO_MARK,
    STATUS_DONE,
)
from app.db import now, transaction
from app.errors import NotFound
from app.repositories import categories as category_repo
from app.repositories import graph as graph_repo
from app.repositories import sessions as session_repo
from app.repositories import todos as todo_repo
from app.services import auto_classify

HELPER_PREFIX = re.compile(r"^보조\d+\s*\|\s*")
PROVISIONAL_LINE = SPAWN_PROVISIONAL_LINE


def on_spawn(con, claude_session_id, title, origin_session_id=None, manager_task_id=None, detail=None):
    """출처를 남기고 할일을 만들어 잇는다 → 그 세션의 할일. 이미 할일을 잡은 세션이면 새로 만들지 않는다"""
    if not session_repo.find(con, claude_session_id):
        session_repo.register(con, claude_session_id)
    # 출처를 먼저 적어야 아래 연결(link_todo)이 원래 세션의 할일을 상위 제안으로 잇는다
    graph_repo.record_spawn(con, claude_session_id, origin_session_id, manager_task_id, title)
    linked = session_repo.linked_todo_ids(con, claude_session_id)
    if linked:
        return todo_repo.get(con, linked[-1])
    _, origins = graph_repo.origin_todos(con, claude_session_id)
    origin = todo_repo.get(con, origins[0]) if origins else None
    todo = todo_repo.create(
        con,
        clean_title(title),
        category_id=origin["category_id"] if origin else _guessed_category(con, title, detail),
        workspace_id=origin["workspace_id"] if origin else None,
        note=_note(origin, manager_task_id, detail),
    )
    session_repo.link_todo(con, claude_session_id, todo["id"])
    return todo_repo.get(con, todo["id"])


def follow_classification(con, claude_session_id, category_id, workspace_id=None):
    """세션이 분류되면 spawn 이 임시 자리에 만든 그 세션의 할일만 따라 옮긴다 → 옮긴 할일 id.
    다른 할일은 건드리지 않는다 — 오래 산 세션이 여러 워크스페이스 할일을 거쳐 왔을 수 있다"""
    moved = []
    for todo_id in session_repo.linked_todo_ids(con, claude_session_id):
        todo = todo_repo.get(con, todo_id)
        if not _provisional(todo):
            continue
        if workspace_id is not None:
            todo_repo.update(con, todo_id, workspace_id=workspace_id, note=_settled(todo["note"]))
        elif category_id is not None and category_id != todo["category_id"]:
            with transaction(con):
                con.execute(
                    "UPDATE todos SET category_id=?, updated_at=? WHERE id=?", (category_id, now(), todo_id)
                )
            todo_repo.update(con, todo_id, note=_settled(todo["note"]))
        else:
            continue
        moved.append(todo_id)
    return moved


def clean_title(title):
    """세션 이름 '보조N | 제목' 의 번호는 그 세션의 것이지 할일 제목이 아니다"""
    return HELPER_PREFIX.sub("", (title or "").strip()) or (title or "").strip()


def _provisional(todo):
    note = todo.get("note") or ""
    return (
        todo["workspace_id"] is None
        and todo["status"] != STATUS_DONE
        and note.startswith(SPAWN_TODO_MARK)
        and PROVISIONAL_LINE in note
    )


def _settled(note):
    return "\n".join(line for line in (note or "").splitlines() if line != PROVISIONAL_LINE)


def _note(origin, manager_task_id, detail):
    lines = [f"{SPAWN_TODO_MARK} 매니저가 띄운 보조 세션의 일."]
    if origin:
        lines.append(f"자리: 원래 세션의 할일 #{origin['id']} 을 따름")
    else:
        lines.append(PROVISIONAL_LINE)
    if manager_task_id:
        lines.append(f"매니저 할일 {manager_task_id}")
    text = (detail or "").strip()
    if text:
        lines.append(text[:SPAWN_NOTE_CHARS] + ("…" if len(text) > SPAWN_NOTE_CHARS else ""))
    return "\n".join(lines)


def _guessed_category(con, title, detail):
    """원래 세션이 없을 때 할일을 둘 카테고리. 제목·지시가 확실히 가리키는 카테고리가 있으면 그것,
    애매하면 대체 카테고리. 어느 쪽이든 임시 자리라 세션이 분류하면 그곳으로 옮겨진다"""
    guessed = auto_classify.category_for_new_todo(con, clean_title(title), detail or "")
    if guessed["category"]:
        try:
            return category_repo.get_by_name(con, guessed["category"])["id"]
        except NotFound:
            pass
    return _fallback_category(con)


def _fallback_category(con):
    try:
        return category_repo.get_by_name(con, SPAWN_FALLBACK_CATEGORY)["id"]
    except NotFound:
        # 사용자가 그 카테고리를 지웠으면 맨 앞 카테고리 — 할일은 카테고리 없이 만들 수 없다
        return category_repo.list_all(con)[0]["id"]
