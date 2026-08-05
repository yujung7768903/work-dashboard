"""하위할일 저장·조회. 할일에 종속"""
from app import ordering
from app.constants import STATUS_TODO, TODO_STATUSES
from app.db import now, transaction
from app.errors import NotFound, Validation
from app.repositories import todos as todo_repo

TABLE = "subtasks"
EDITABLE_FIELDS = ("title", "precondition", "status")


def create(con, todo_id, title, precondition=None):
    todo_repo.get(con, todo_id)
    cleaned = _clean_title(title)
    order = ordering.next_order(con, TABLE, *_group_scope(todo_id))
    with transaction(con):
        cursor = con.execute(
            "INSERT INTO subtasks(todo_id, title, precondition, status, sort_order,"
            " created_at) VALUES(?,?,?,?,?,?)",
            (todo_id, cleaned, precondition, STATUS_TODO, order, now()),
        )
    return get(con, cursor.lastrowid)


def list_by_todo(con, todo_id):
    where, params = _group_scope(todo_id)
    return [
        dict(row)
        for row in con.execute(
            f"SELECT * FROM subtasks WHERE {where} ORDER BY sort_order, id", params
        )
    ]


def get(con, subtask_id):
    row = con.execute("SELECT * FROM subtasks WHERE id=?", (subtask_id,)).fetchone()
    if not row:
        raise NotFound("하위 할 일을 찾을 수 없습니다")
    return dict(row)


def update(con, subtask_id, **fields):
    get(con, subtask_id)
    assignments = {}
    for key, value in fields.items():
        if key not in EDITABLE_FIELDS:
            raise Validation(f"수정할 수 없는 필드: {key}")
        assignments[key] = value
    if "title" in assignments:
        assignments["title"] = _clean_title(assignments["title"])
    if "status" in assignments and assignments["status"] not in TODO_STATUSES:
        raise Validation(f"하위할일 상태는 {TODO_STATUSES} 중 하나여야 함")
    if not assignments:
        return get(con, subtask_id)
    clause = ",".join(f"{key}=?" for key in assignments)
    with transaction(con):
        con.execute(
            f"UPDATE subtasks SET {clause} WHERE id=?",
            tuple(assignments.values()) + (subtask_id,),
        )
    return get(con, subtask_id)


def delete(con, subtask_id):
    get(con, subtask_id)
    with transaction(con):
        con.execute("DELETE FROM subtasks WHERE id=?", (subtask_id,))


def reorder(con, ids, todo_id):
    ordering.reorder(con, TABLE, ids, *_group_scope(todo_id))


def _group_scope(todo_id):
    return ("todo_id=?", (todo_id,))


def _clean_title(title):
    cleaned = (title or "").strip()
    if not cleaned:
        raise Validation("하위 할 일 제목을 입력해 주세요")
    return cleaned
