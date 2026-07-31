"""할일 저장·조회. 워크스페이스 배정 시 카테고리 동기화가 여기서 강제됨"""
from app import ordering
from app.constants import (
    STATE_IDLE,
    STATE_WORKING,
    STATUS_DOING,
    STATUS_DONE,
    STATUS_TODO,
    TODO_STATUSES,
)
from app.db import now, transaction
from app.errors import NotFound, Validation
from app.repositories import categories as category_repo
from app.repositories import workspaces as workspace_repo

TABLE = "todos"
EDITABLE_FIELDS = ("title", "note", "status", "workspace_id")


def create(con, title, category_id=None, workspace_id=None, note=None):
    """workspace_id 가 있으면 카테고리는 그 워크스페이스에서 가져옴"""
    cleaned = _clean_title(title)
    resolved_category = _resolve_category(con, category_id, workspace_id)
    order = ordering.next_order(con, TABLE, *_group_scope(workspace_id))
    stamp = now()
    with transaction(con):
        cursor = con.execute(
            "INSERT INTO todos(category_id, workspace_id, title, note, status,"
            " sort_order, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?)",
            (resolved_category, workspace_id, cleaned, note, STATUS_TODO, order, stamp, stamp),
        )
    return get(con, cursor.lastrowid)


def get(con, todo_id):
    row = con.execute("SELECT * FROM todos WHERE id=?", (todo_id,)).fetchone()
    if not row:
        raise NotFound(f"할일 {todo_id} 없음")
    return dict(row)


def list_by_workspace(con, workspace_id):
    """workspace_id 가 None 이면 미분류 목록"""
    where, params = _group_scope(workspace_id)
    return [
        dict(row)
        for row in con.execute(
            f"SELECT * FROM todos WHERE {where} ORDER BY sort_order, id", params
        )
    ]


def list_by_category(con, category_id):
    return [
        dict(row)
        for row in con.execute(
            "SELECT * FROM todos WHERE category_id=? ORDER BY sort_order, id",
            (category_id,),
        )
    ]


def update(con, todo_id, **fields):
    current = get(con, todo_id)
    assignments = _validated_assignments(con, current, fields)
    if not assignments:
        return current
    assignments["updated_at"] = now()
    clause = ",".join(f"{key}=?" for key in assignments)
    with transaction(con):
        con.execute(
            f"UPDATE todos SET {clause} WHERE id=?",
            tuple(assignments.values()) + (todo_id,),
        )
    return get(con, todo_id)


def delete(con, todo_id):
    """하위할일까지 cascade. 하위할일은 할일에 종속되어 독립 존재 의미가 없음"""
    get(con, todo_id)
    with transaction(con):
        con.execute("DELETE FROM subtasks WHERE todo_id=?", (todo_id,))
        con.execute("DELETE FROM todos WHERE id=?", (todo_id,))


def reorder(con, ids, workspace_id):
    ordering.reorder(con, TABLE, ids, *_group_scope(workspace_id))


def demote_by_workspace(con, workspace_id):
    """워크스페이스 삭제 시 소속 할일을 미분류로 내림. 카테고리는 유지"""
    members = list_by_workspace(con, workspace_id)
    base = ordering.next_order(con, TABLE, *_group_scope(None))
    stamp = now()
    with transaction(con):
        for offset, todo in enumerate(members):
            con.execute(
                "UPDATE todos SET workspace_id=NULL, sort_order=?, updated_at=? WHERE id=?",
                (base + offset, stamp, todo["id"]),
            )


def sync_category(con, workspace_id, category_id):
    """워크스페이스 카테고리 변경 시 소속 할일 전부 따라가게 함"""
    with transaction(con):
        con.execute(
            "UPDATE todos SET category_id=?, updated_at=? WHERE workspace_id=?",
            (category_id, now(), workspace_id),
        )


def list_completed_on(con, date_prefix):
    """completed_at 날짜 부분이 일치하는 할일. daily-todo 집계용"""
    return [
        dict(row)
        for row in con.execute(
            "SELECT * FROM todos WHERE completed_at LIKE ? ORDER BY completed_at",
            (f"{date_prefix}%",),
        )
    ]


def ids_claimed_by_others(con, claude_session_id=None):
    """다른 활성(working/idle) 세션이 session_todos 로 잡고 있는 할일 id 집합.

    단계는 todos.status, 소유는 session_todos 로 나눠 봄. 세션을 안 주면 활성 세션이
    잡은 것 전부가 남의 일
    """
    rows = con.execute(
        """SELECT DISTINCT st.todo_id FROM session_todos st
           JOIN sessions s ON s.id = st.session_id
           WHERE s.state IN (?,?) AND s.claude_session_id IS NOT ?""",
        (STATE_WORKING, STATE_IDLE, claude_session_id),
    )
    return {row["todo_id"] for row in rows}


def list_doing_before(con, before_text):
    """updated_at 이 기준 시각보다 오래된 doing. 오래 붙잡고 있는 할일 경고용"""
    return [
        dict(row)
        for row in con.execute(
            "SELECT * FROM todos WHERE status=? AND updated_at<? ORDER BY updated_at",
            (STATUS_DOING, before_text),
        )
    ]


def _require_subtasks_done(con, todo_id):
    """하위할일이 남아 있으면 할일을 done 으로 올리지 못하게 막음"""
    remaining = [
        row["title"]
        for row in con.execute(
            "SELECT title FROM subtasks WHERE todo_id=? AND status<>?"
            " ORDER BY sort_order, id",
            (todo_id, STATUS_DONE),
        )
    ]
    if remaining:
        raise Validation("하위할일이 남아 완료할 수 없음: " + ", ".join(remaining))


def _validated_assignments(con, current, fields):
    assignments = {}
    for key, value in fields.items():
        if key not in EDITABLE_FIELDS:
            raise Validation(f"수정할 수 없는 필드: {key}")
        assignments[key] = value
    if "title" in assignments:
        assignments["title"] = _clean_title(assignments["title"])
    if "status" in assignments:
        _validate_status(assignments["status"])
        if assignments["status"] == STATUS_DONE:
            _require_subtasks_done(con, current["id"])
        assignments["completed_at"] = (
            now() if assignments["status"] == STATUS_DONE else None
        )
    if "workspace_id" in assignments:
        target = assignments["workspace_id"]
        assignments["category_id"] = _resolve_category(con, current["category_id"], target)
        assignments["sort_order"] = ordering.next_order(con, TABLE, *_group_scope(target))
    return assignments


def _group_scope(workspace_id):
    """미분류는 workspace_id IS NULL 로 묶임"""
    if workspace_id is None:
        return ("workspace_id IS NULL", ())
    return ("workspace_id=?", (workspace_id,))


def _resolve_category(con, category_id, workspace_id):
    """워크스페이스가 있으면 그쪽 카테고리가 이김"""
    if workspace_id is not None:
        return workspace_repo.get(con, workspace_id)["category_id"]
    if category_id is None:
        raise Validation("카테고리나 워크스페이스 중 하나는 필요함")
    category_repo.get(con, category_id)
    return category_id


def _clean_title(title):
    cleaned = (title or "").strip()
    if not cleaned:
        raise Validation("할일 제목이 비어 있음")
    return cleaned


def _validate_status(status):
    if status not in TODO_STATUSES:
        raise Validation(f"할일 상태는 {TODO_STATUSES} 중 하나여야 함")
