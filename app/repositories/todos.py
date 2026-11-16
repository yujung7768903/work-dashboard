"""할일 저장·조회. 워크스페이스 배정 시 카테고리 동기화가 여기서 강제됨"""
from app import ordering
from app.constants import (
    AUTO_TODO_NOTE_RAW_TITLE,
    PARENT_CYCLE_MSG,
    PARENT_INVALID_MSG,
    PARENT_NEEDS_WORKSPACE_MSG,
    PARENT_OTHER_WORKSPACE_MSG,
    PRIORITY_INVALID_MSG,
    REVIEW_LOCKED_MSG,
    SCOPE_REQUIRED_MSG,
    STATE_IDLE,
    STATE_WORKING,
    STATUS_DOING,
    STATUS_DONE,
    STATUS_TODO,
    TODO_STATUSES,
)
from app.db import now, transaction
from app.errors import NotFound, Validation
from app.repositories import autorun as autorun_repo
from app.repositories import categories as category_repo
from app.repositories import graph as graph_repo
from app.repositories import labels as label_repo
from app.repositories import workspaces as workspace_repo

TABLE = "todos"
# cwd = 워크스페이스가 없는 할일의 작업 위치. 소속이 있으면 workspaces.cwd 가 그 역할이다
EDITABLE_FIELDS = (
    "title", "note", "precondition", "status", "workspace_id", "cwd", "priority",
    "parent_id",
)
LABEL_FIELD = "label_ids"  # 컬럼이 아니라 조인 테이블이라 따로 뗀다


def create(
    con,
    title,
    category_id=None,
    workspace_id=None,
    note=None,
    precondition=None,
    parent_id=None,
):
    """workspace_id 가 있으면 카테고리는 그 워크스페이스에서 가져옴.

    parent_id 만 주면 워크스페이스는 상위 할일의 것을 따른다 — 하위 할일은 늘 부모와
    같은 트리(워크스페이스)에 있어야 하므로 따로 받을 이유가 없다
    """
    cleaned = _clean_title(title)
    parent_id = clean_parent(parent_id)
    if parent_id is not None and workspace_id is None:
        workspace_id = get(con, parent_id)["workspace_id"]
    if parent_id is not None:
        _validate_parent(con, None, parent_id, workspace_id)
    resolved_category = _resolve_category(con, category_id, workspace_id)
    order = ordering.next_order(con, TABLE, *_group_scope(workspace_id))
    stamp = now()
    with transaction(con):
        cursor = con.execute(
            "INSERT INTO todos(category_id, workspace_id, parent_id, title, note,"
            " precondition, status, sort_order, created_at, updated_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                resolved_category,
                workspace_id,
                parent_id,
                cleaned,
                note,
                precondition,
                STATUS_TODO,
                order,
                stamp,
                stamp,
            ),
        )
        graph_repo.sync_parent_column(con, cursor.lastrowid, None, parent_id)
    graph_repo.sync_text_evidence(con, cursor.lastrowid, cleaned, note)
    return get(con, cursor.lastrowid)


def get(con, todo_id):
    row = con.execute("SELECT * FROM todos WHERE id=?", (todo_id,)).fetchone()
    if not row:
        raise NotFound("할 일을 찾을 수 없습니다")
    return _shaped(row)


def list_by_workspace(con, workspace_id):
    """workspace_id 가 None 이면 미분류 목록"""
    where, params = _group_scope(workspace_id)
    return [
        _shaped(row)
        for row in con.execute(
            f"SELECT * FROM todos WHERE {where} ORDER BY sort_order, id", params
        )
    ]


def list_by_category(con, category_id):
    return [
        _shaped(row)
        for row in con.execute(
            "SELECT * FROM todos WHERE category_id=? ORDER BY sort_order, id",
            (category_id,),
        )
    ]


def update(con, todo_id, **fields):
    current = get(con, todo_id)
    if LABEL_FIELD in fields:
        label_repo.set_for_todo(con, todo_id, fields.pop(LABEL_FIELD))
    assignments = _validated_assignments(con, current, fields)
    if not assignments:
        return get(con, todo_id)
    assignments["updated_at"] = now()
    clause = ",".join(f"{key}=?" for key in assignments)
    moved = (
        "workspace_id" in assignments
        and assignments["workspace_id"] != current["workspace_id"]
    )
    # 하위 할일은 부모를 따라간다 — 남겨 두면 다른 워크스페이스의 부모를 가리키게 된다
    followers = descendant_ids(con, todo_id) if moved else []
    with transaction(con):
        con.execute(
            f"UPDATE todos SET {clause} WHERE id=?",
            tuple(assignments.values()) + (todo_id,),
        )
        _carry_descendants(con, followers, assignments)
        if "parent_id" in assignments:
            graph_repo.sync_parent_column(
                con, todo_id, current["parent_id"], assignments["parent_id"]
            )
    # 근거 문서는 제목·note 에서 뽑는다 — 둘 중 하나가 바뀌면 다시 맞춘다
    if {"title", "note"} & set(assignments):
        updated = get(con, todo_id)
        graph_repo.sync_text_evidence(con, todo_id, updated["title"], updated["note"])
    return get(con, todo_id)


def set_google_link(con, todo_id, task_id):
    """구글 태스크 링크만 갱신. updated_at 은 일부러 건드리지 않는다

    updated_at 은 양방향 동기화에서 '누가 최신인가'를 가르는 기준이다. 링크를 붙이는
    것만으로 시각이 올라가면 그 뒤로는 로컬이 늘 이겨 폰의 수정이 영영 안 들어온다
    """
    with transaction(con):
        con.execute(
            "UPDATE todos SET google_task_id=? WHERE id=?", (task_id, todo_id)
        )


def delete(con, todo_id):
    """붙어 있던 라벨은 연결만 끊는다 — 라벨 자체는 다른 할일도 쓰는 공용이다.

    하위 할일은 지우지 않고 한 단계 위(지운 할일의 부모)로 올린다. 할일 하나를
    지웠다고 그 아래 가지가 통째로 사라지면 되돌릴 방법이 없다
    """
    current = get(con, todo_id)
    partners = graph_repo.shared_doc_partners(con, todo_id)
    with transaction(con):
        # 관계 그래프에서도 하위를 한 단계 올리고 그 할일에 닿은 연결을 걷는다
        graph_repo.drop_todo(con, todo_id)
        con.execute(
            "UPDATE todos SET parent_id=? WHERE parent_id=?",
            (current["parent_id"], todo_id),
        )
        if current["parent_id"] is not None:
            for child in con.execute(
                "SELECT id FROM todos WHERE parent_id=?", (current["parent_id"],)
            ).fetchall():
                graph_repo.sync_parent_column(con, child["id"], None, current["parent_id"])
        con.execute("DELETE FROM todo_labels WHERE todo_id=?", (todo_id,))
        con.execute("DELETE FROM todos WHERE id=?", (todo_id,))
    # 같은 문서를 공유하던 할일끼리의 관련은 그 할일이 빠져 묶음 크기가 바뀌었을 수 있다
    for partner in partners:
        graph_repo.refresh_shared_related(con, partner)


def reorder(con, ids, workspace_id):
    ordering.reorder(con, TABLE, ids, *_group_scope(workspace_id))


def set_autorun_order(con, ids):
    """자율 수행 후보 목록에서 사람이 끌어 정한 순서를 그대로 저장한다.

    ordering.reorder 를 쓰지 않는 이유 — 그쪽은 한 묶음(워크스페이스) 안의 전원이
    목록에 있다고 보고 검증한다. 후보 목록은 여러 워크스페이스에서 상위 몇 건만
    뽑아 온 것이라 그 검증에 걸린다. 목록에 없는 할일은 건드리지 않고 NULL 로 둔다
    """
    stamp = now()
    with transaction(con):
        for index, todo_id in enumerate(ids):
            con.execute(
                "UPDATE todos SET autorun_order=?, updated_at=? WHERE id=?",
                (index, stamp, todo_id),
            )


def demote_by_workspace(con, workspace_id):
    """워크스페이스 삭제 시 소속 할일을 미분류로 내림. 카테고리는 유지.

    트리는 워크스페이스가 루트라 루트가 사라지면 상하 관계도 함께 풀린다 —
    미분류에는 트리가 없다 (할일 자체는 하나도 지우지 않는다)
    """
    members = list_by_workspace(con, workspace_id)
    base = ordering.next_order(con, TABLE, *_group_scope(None))
    stamp = now()
    with transaction(con):
        for offset, todo in enumerate(members):
            con.execute(
                "UPDATE todos SET workspace_id=NULL, parent_id=NULL, sort_order=?,"
                " updated_at=? WHERE id=?",
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
        _shaped(row)
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
        _shaped(row)
        for row in con.execute(
            "SELECT * FROM todos WHERE status=? AND updated_at<? ORDER BY updated_at",
            (STATUS_DOING, before_text),
        )
    ]


def _validated_assignments(con, current, fields):
    assignments = {}
    for key, value in fields.items():
        if key not in EDITABLE_FIELDS:
            raise Validation(f"수정할 수 없는 필드: {key}")
        assignments[key] = value
    if "title" in assignments:
        assignments["title"] = _clean_title(assignments["title"])
    if "priority" in assignments:
        assignments["priority"] = clean_priority(assignments["priority"])
    if "status" in assignments:
        if current["id"] in autorun_repo.locked_todo_ids(con):
            raise Validation(REVIEW_LOCKED_MSG)
        _validate_status(assignments["status"])
        assignments["completed_at"] = (
            now() if assignments["status"] == STATUS_DONE else None
        )
    if "workspace_id" in assignments:
        target = assignments["workspace_id"]
        assignments["category_id"] = _resolve_category(con, current["category_id"], target)
        assignments["sort_order"] = ordering.next_order(con, TABLE, *_group_scope(target))
        # 다른 트리로 옮기면 옛 부모는 남의 트리에 있다. 새 부모를 같이 안 줬으면 루트 바로 아래로
        if target != current["workspace_id"] and "parent_id" not in assignments:
            assignments["parent_id"] = None
    if "parent_id" in assignments:
        assignments["parent_id"] = clean_parent(assignments["parent_id"])
        if assignments["parent_id"] is not None:
            _validate_parent(
                con,
                current["id"],
                assignments["parent_id"],
                assignments.get("workspace_id", current["workspace_id"]),
            )
    return assignments


def descendant_ids(con, todo_id):
    """그 할일 아래 전부(자식·손자…). 저장소가 순환을 막지만 손으로 고친 DB 에서도
    멈추도록 본 것은 다시 보지 않는다"""
    found, frontier, seen = [], [todo_id], {todo_id}
    while frontier:
        marks = ",".join("?" * len(frontier))
        rows = con.execute(
            f"SELECT id FROM todos WHERE parent_id IN ({marks})", tuple(frontier)
        ).fetchall()
        frontier = [row["id"] for row in rows if row["id"] not in seen]
        seen.update(frontier)
        found += frontier
    return found


def _carry_descendants(con, ids, assignments):
    """옮긴 할일의 하위를 같은 워크스페이스·카테고리로. 순서는 새 묶음의 뒤에 붙인다"""
    if not ids:
        return
    target = assignments["workspace_id"]
    base = ordering.next_order(con, TABLE, *_group_scope(target))
    for offset, child_id in enumerate(ids):
        con.execute(
            "UPDATE todos SET workspace_id=?, category_id=?, sort_order=?, updated_at=?"
            " WHERE id=?",
            (
                target,
                assignments["category_id"],
                base + offset,
                assignments["updated_at"],
                child_id,
            ),
        )


def clean_parent(value):
    """상위 할일 id 또는 None(워크스페이스 바로 아래). 빈 값·'none' 도 None 으로 받는다 —
    CLI 에서 none 을 주거나 화면이 null 을 보내는 것이 '부모 없앰' 이다"""
    if value is None or (isinstance(value, str) and value.strip().lower() in ("", "none")):
        return None
    if isinstance(value, bool):
        raise Validation(PARENT_INVALID_MSG)
    try:
        return int(str(value).strip())
    except ValueError:
        raise Validation(PARENT_INVALID_MSG)


def _validate_parent(con, todo_id, parent_id, workspace_id):
    """부모는 같은 워크스페이스의 할일이고, 자기 자신·자기 하위가 아니어야 한다.

    부모가 자기 하위면 트리가 고리가 되어 루트에서 닿지 않는 가지가 생긴다.
    부모 쪽에서 위로 올라가며 자기를 만나는지 본다 (깊이만큼만 돈다)
    """
    if workspace_id is None:
        raise Validation(PARENT_NEEDS_WORKSPACE_MSG)
    parent = get(con, parent_id)
    if parent["workspace_id"] != workspace_id:
        raise Validation(PARENT_OTHER_WORKSPACE_MSG)
    node, seen = parent_id, set()
    while node is not None and node not in seen:
        if node == todo_id:
            raise Validation(PARENT_CYCLE_MSG)
        seen.add(node)
        row = con.execute("SELECT parent_id FROM todos WHERE id=?", (node,)).fetchone()
        node = row["parent_id"] if row else None


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
        raise Validation(SCOPE_REQUIRED_MSG)
    category_repo.get(con, category_id)
    return category_id


def _shaped(row):
    """조회 결과에 needs_title 을 얹는다 — 제목이 요약 안 된 자동 생성 할일.

    컬럼을 늘리지 않고 note 표시 한 줄로 판단한다. 여기서 한 번 계산해 보드·팝업이
    같은 답을 쓰게 한다 (사용자가 note 를 정리하면 표시도 함께 사라진다)
    """
    todo = dict(row)
    todo["needs_title"] = AUTO_TODO_NOTE_RAW_TITLE in (todo.get("note") or "")
    return todo


def clean_priority(value):
    """1 이상 정수 또는 None(정하지 않음). 빈 문자열·'-' 도 None 으로 받는다 — 화면 입력칸을
    비우거나 CLI 에서 '-' 를 주는 것이 '우선순위 없앰' 이다"""
    if value is None or (isinstance(value, str) and value.strip() in ("", "-")):
        return None
    if isinstance(value, bool):
        raise Validation(PRIORITY_INVALID_MSG)
    try:
        number = int(str(value).strip())
    except ValueError:
        raise Validation(PRIORITY_INVALID_MSG)
    if number < 1:
        raise Validation(PRIORITY_INVALID_MSG)
    return number


def _clean_title(title):
    cleaned = (title or "").strip()
    if not cleaned:
        raise Validation("할 일 제목을 입력해 주세요")
    return cleaned


def _validate_status(status):
    if status not in TODO_STATUSES:
        raise Validation(f"할일 상태는 {TODO_STATUSES} 중 하나여야 함")
