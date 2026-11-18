"""매니저 spawn 이 띄운 보조 세션을 할일 그래프에 잇는다.

보조 세션이 스스로 분류·할일 연결을 하게 두면 조사·분석 일은 '단발 조회' 로 보고 할일을 만들지 않아
(11-11~16 비매니저 보조 99개 중 83개) 트리에서 그 일과 맥락이 통째로 사라졌다. 그래서 띄우는 쪽이:
1) 출처(원래 세션·매니저 할일)를 남기고 — 원래 세션이 잡고 있던 할일이 새 할일의 상위(계기) 제안이 된다
2) 할일을 바로 만들어 수행(session_todos)으로 잇는다. 할일 통합 뒤 매니저 할일에서 띄운 세션이면 새 할일이 아니라
   그 할일의 단계(role='step')를 만들어 잇는다. 자리는 원래 세션 할일의 워크스페이스, 모르면 워크스페이스
   없이 임시 카테고리. 세션이 나중에 분류되면 그 임시 할일만 분류한 곳으로 옮긴다(follow_classification)
매니저는 이 모듈을 import 해 부른다(~/work/manager manager.py _launch)
"""
import re

from app.constants import (
    SPAWN_FALLBACK_CATEGORY,
    SPAWN_NOTE_CHARS,
    SPAWN_TODO_MARK,
    STATUS_DONE,
)
from app.db import ROLE_STEP, UNIFIED_FLAG, meta_get, now, transaction
from app.errors import NotFound
from app.repositories import categories as category_repo
from app.repositories import graph as graph_repo
from app.repositories import sessions as session_repo
from app.repositories import todos as todo_repo

HELPER_PREFIX = re.compile(r"^보조\d+\s*\|\s*")
PROVISIONAL_LINE = "자리: 임시 카테고리 — 이 세션이 분류하면 그 워크스페이스·카테고리로 옮겨진다"


def on_spawn(con, claude_session_id, title, origin_session_id=None, manager_task_id=None, detail=None):
    """출처를 남기고 할일을 만들어 잇는다 → 그 세션의 할일. 이미 할일을 잡은 세션이면 새로 만들지 않는다"""
    if not session_repo.find(con, claude_session_id):
        session_repo.register(con, claude_session_id)
    # 출처를 먼저 적어야 아래 연결(link_todo)이 원래 세션의 할일을 상위 제안으로 잇는다
    graph_repo.record_spawn(con, claude_session_id, origin_session_id, manager_task_id, title)
    linked = session_repo.linked_todo_ids(con, claude_session_id)
    if linked:
        return todo_repo.get(con, linked[-1])
    task = _manager_task(con, manager_task_id)
    if task:
        return _spawn_step(con, claude_session_id, task, title, manager_task_id, detail)
    _, origins = graph_repo.origin_todos(con, claude_session_id)
    origin = todo_repo.get(con, origins[0]) if origins else None
    todo = todo_repo.create(
        con,
        clean_title(title),
        category_id=origin["category_id"] if origin else _fallback_category(con),
        workspace_id=origin["workspace_id"] if origin else None,
        note=_note(origin, manager_task_id, detail),
    )
    session_repo.link_todo(con, claude_session_id, todo["id"])
    return todo_repo.get(con, todo["id"])


def _manager_task(con, manager_task_id):
    """할일 통합 뒤(meta unified_todos) 매니저 할일 id 는 대시보드 todos id 다 → 그 일의 할일(단계면 그 상위 할일).
    통합 전이거나 그 행이 없으면 None — 예전처럼 새 할일을 만든다"""
    if not manager_task_id or not meta_get(con, UNIFIED_FLAG):
        return None
    try:
        row = con.execute(
            "SELECT id, role, parent_id FROM todos WHERE id=?", (int(manager_task_id),)
        ).fetchone()
    except (TypeError, ValueError):
        return None
    if not row:
        return None
    task_id = row["parent_id"] if row["role"] == ROLE_STEP and row["parent_id"] else row["id"]
    return todo_repo.get(con, task_id)


def _spawn_step(con, claude_session_id, task, title, manager_task_id, detail):
    """보조 세션의 일은 그 할일의 단계다(사용자 결정 11-18) — 할일은 결과 하나로 끝나고, 거기서 나온 파생 일은
    새 카드가 아니라 단계로 쌓는다. 매니저 할일마다 새 할일을 만들던 때는 같은 일이 두 장(매니저 할일·spawn 할일)으로 보였다"""
    step = todo_repo.create(
        con,
        clean_title(title),
        category_id=task["category_id"],
        workspace_id=task["workspace_id"],
        note=_step_note(task, manager_task_id, detail),
    )
    # 상위는 todo_repo 검사(워크스페이스 안에서만 상위)를 거치지 않고 직접 단다 — 할일 통합 뒤에는 워크스페이스가 없다
    with transaction(con):
        con.execute("UPDATE todos SET role=?, parent_id=? WHERE id=?", (ROLE_STEP, task["id"], step["id"]))
        graph_repo.sync_parent_column(con, step["id"], None, task["id"])
    session_repo.link_todo(con, claude_session_id, step["id"])
    return todo_repo.get(con, step["id"])


def _step_note(task, manager_task_id, detail):
    lines = [f"{SPAWN_TODO_MARK} 매니저가 띄운 보조 세션의 일 — 할일 #{task['id']} 의 단계."]
    if manager_task_id and int(manager_task_id) != task["id"]:
        lines.append(f"매니저 할일 {manager_task_id}")
    text = (detail or "").strip()
    if text:
        lines.append(text[:SPAWN_NOTE_CHARS] + ("…" if len(text) > SPAWN_NOTE_CHARS else ""))
    return "\n".join(lines)


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


def _fallback_category(con):
    try:
        return category_repo.get_by_name(con, SPAWN_FALLBACK_CATEGORY)["id"]
    except NotFound:
        # 사용자가 그 카테고리를 지웠으면 맨 앞 카테고리 — 할일은 카테고리 없이 만들 수 없다
        return category_repo.list_all(con)[0]["id"]
