"""워크스페이스 저장·조회. sort_order 는 카테고리를 가로지르는 전역 순위"""
from app import ordering
from app.constants import WORKSPACE_ACTIVE, WORKSPACE_STATUSES
from app.db import now, transaction
from app.errors import NotFound, Validation
from app.repositories import categories as category_repo

TABLE = "workspaces"
ALL_SCOPE = ("1=1", ())
CONTEXT_FIELDS = ("background", "purpose", "goal", "considerations")
# cwd = 사람이 지정한 작업 위치. 세션 이력으로 추론이 안 될 때 자율 실행이 쓴다
OPTIONAL_FIELDS = CONTEXT_FIELDS + ("jira_id", "cwd")
EDITABLE_FIELDS = ("name", "status", "category_id") + OPTIONAL_FIELDS


def create(con, category_id, name, **fields):
    category_repo.get(con, category_id)
    cleaned = _clean_name(name)
    order = ordering.next_order(con, TABLE, *ALL_SCOPE)
    stamp = now()
    columns = ["category_id", "name", "status", "sort_order", "created_at", "updated_at"]
    values = [category_id, cleaned, WORKSPACE_ACTIVE, order, stamp, stamp]
    for key in OPTIONAL_FIELDS:
        columns.append(key)
        values.append(fields.get(key))
    placeholders = ",".join("?" * len(columns))
    with transaction(con):
        cursor = con.execute(
            f"INSERT INTO workspaces({','.join(columns)}) VALUES({placeholders})",
            tuple(values),
        )
    return get(con, cursor.lastrowid)


def list_all(con, status=None):
    sql = "SELECT * FROM workspaces"
    params = ()
    if status:
        _validate_status(status)
        sql += " WHERE status=?"
        params = (status,)
    return [dict(row) for row in con.execute(sql + " ORDER BY sort_order, id", params)]


def get(con, workspace_id):
    row = con.execute("SELECT * FROM workspaces WHERE id=?", (workspace_id,)).fetchone()
    if not row:
        raise NotFound("워크스페이스를 찾을 수 없습니다")
    return dict(row)


def get_by_jira(con, jira_id):
    """대소문자 무시. 없으면 None — scope-guard 연결점"""
    row = con.execute(
        "SELECT * FROM workspaces WHERE UPPER(jira_id)=UPPER(?)", (jira_id,)
    ).fetchone()
    return dict(row) if row else None


def update(con, workspace_id, **fields):
    get(con, workspace_id)
    assignments = _validated_assignments(con, fields)
    if not assignments:
        return get(con, workspace_id)
    assignments["updated_at"] = now()
    clause = ",".join(f"{key}=?" for key in assignments)
    with transaction(con):
        con.execute(
            f"UPDATE workspaces SET {clause} WHERE id=?",
            tuple(assignments.values()) + (workspace_id,),
        )
    if "category_id" in assignments:
        _todo_repo().sync_category(con, workspace_id, assignments["category_id"])
    return get(con, workspace_id)


def set_google_link(con, workspace_id, task_id):
    """구글 태스크 링크만 갱신. updated_at 은 일부러 건드리지 않는다

    updated_at 은 양방향 동기화에서 '누가 최신인가'를 가르는 기준이다. 링크를 붙이는
    것만으로 시각이 올라가면 그 뒤로는 로컬이 늘 이겨 폰의 수정이 영영 안 들어온다
    """
    with transaction(con):
        con.execute(
            "UPDATE workspaces SET google_task_id=? WHERE id=?", (task_id, workspace_id)
        )


def delete(con, workspace_id):
    """소속 할일은 미분류로 강등하고 워크스페이스만 지움. 데이터 손실 없음"""
    get(con, workspace_id)
    _todo_repo().demote_by_workspace(con, workspace_id)
    with transaction(con):
        con.execute("DELETE FROM workspaces WHERE id=?", (workspace_id,))


def reorder(con, ids):
    ordering.reorder(con, TABLE, ids, *ALL_SCOPE)


def _validated_assignments(con, fields):
    assignments = {}
    for key, value in fields.items():
        if key not in EDITABLE_FIELDS:
            raise Validation(f"수정할 수 없는 필드: {key}")
        if key == "status":
            _validate_status(value)
        if key == "name":
            value = _clean_name(value)
        if key == "category_id":
            category_repo.get(con, value)
        assignments[key] = value
    return assignments


def _clean_name(name):
    cleaned = (name or "").strip()
    if not cleaned:
        raise Validation("워크스페이스 이름을 입력해 주세요")
    return cleaned


def _validate_status(status):
    if status not in WORKSPACE_STATUSES:
        raise Validation(f"워크스페이스 상태는 {WORKSPACE_STATUSES} 중 하나여야 함")


def _todo_repo():
    """todos 가 workspaces 를 import 하므로 순환을 피해 지연 로드"""
    from app.repositories import todos

    return todos
