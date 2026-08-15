"""라벨 저장·조회와 할일 붙이기. 한 할일에 여러 개 붙는다는 점만 카테고리와 다름"""
from app import ordering
from app.db import clean_color, now, palette_color, transaction
from app.errors import Conflict, NeedsConfirm, NotFound, Validation

TABLE = "labels"
ALL_SCOPE = ("1=1", ())
COLUMNS = "l.id, l.name, l.color, l.sort_order"


def create(con, name):
    """맨 뒤에 붙임. 색은 카테고리와 같은 팔레트에서 순번대로 배정하고 이후 수정 가능"""
    cleaned = _clean_name(name)
    _reject_duplicate(con, cleaned)
    order = ordering.next_order(con, TABLE, *ALL_SCOPE)
    with transaction(con):
        cursor = con.execute(
            "INSERT INTO labels(name, sort_order, color, created_at) VALUES(?,?,?,?)",
            (cleaned, order, palette_color(order), now()),
        )
    return get(con, cursor.lastrowid)


def list_all(con):
    return [
        dict(row)
        for row in con.execute("SELECT * FROM labels ORDER BY sort_order, id")
    ]


def get(con, label_id):
    row = con.execute("SELECT * FROM labels WHERE id=?", (label_id,)).fetchone()
    if not row:
        raise NotFound("라벨을 찾을 수 없습니다")
    return dict(row)


def update(con, label_id, **fields):
    """이름·색을 부분 수정. 준 필드만 건드림"""
    get(con, label_id)
    changes = {}
    if "name" in fields:
        cleaned = _clean_name(fields["name"])
        _reject_duplicate(con, cleaned, exclude_id=label_id)
        changes["name"] = cleaned
    if "color" in fields:
        changes["color"] = clean_color(fields["color"])
    if not changes:
        raise Validation("수정할 필드가 없음 (name·color)")
    assignments = ", ".join(f"{key}=?" for key in changes)
    with transaction(con):
        con.execute(
            f"UPDATE labels SET {assignments} WHERE id=?",
            (*changes.values(), label_id),
        )
    return get(con, label_id)


def delete(con, label_id, force=False):
    """붙어 있는 할일에서 조용히 떨어져 나가므로 몇 건인지 알리고 확인을 받는다"""
    get(con, label_id)
    attached = con.execute(
        "SELECT COUNT(*) AS n FROM todo_labels WHERE label_id=?", (label_id,)
    ).fetchone()["n"]
    if attached and not force:
        raise NeedsConfirm(f"할일 {attached}건에서 이 라벨이 떨어집니다. 삭제할까요?")
    with transaction(con):
        con.execute("DELETE FROM todo_labels WHERE label_id=?", (label_id,))
        con.execute("DELETE FROM labels WHERE id=?", (label_id,))


def reorder(con, ids):
    ordering.reorder(con, TABLE, ids, *ALL_SCOPE)


def list_by_todo(con, todo_id):
    return [
        dict(row)
        for row in con.execute(
            f"SELECT {COLUMNS} FROM todo_labels tl JOIN labels l ON l.id=tl.label_id"
            " WHERE tl.todo_id=? ORDER BY l.sort_order, l.id",
            (todo_id,),
        )
    ]


def map_by_todo(con):
    """할일 id → 라벨 목록 전체. 보드가 한 번에 가져가 할일마다 다시 묻지 않는다"""
    grouped = {}
    rows = con.execute(
        f"SELECT tl.todo_id, {COLUMNS} FROM todo_labels tl"
        " JOIN labels l ON l.id=tl.label_id ORDER BY l.sort_order, l.id"
    )
    for row in rows:
        item = dict(row)
        grouped.setdefault(item.pop("todo_id"), []).append(item)
    return grouped


def set_for_todo(con, todo_id, label_ids):
    """할일의 라벨을 통째로 교체. 없는 라벨 id 가 섞이면 전체를 거부한다"""
    resolved = [get(con, int(label_id))["id"] for label_id in label_ids or []]
    with transaction(con):
        con.execute("DELETE FROM todo_labels WHERE todo_id=?", (todo_id,))
        con.executemany(
            "INSERT INTO todo_labels(todo_id, label_id) VALUES(?,?)",
            [(todo_id, label_id) for label_id in dict.fromkeys(resolved)],
        )


def _clean_name(name):
    cleaned = (name or "").strip()
    if not cleaned:
        raise Validation("라벨 이름을 입력해 주세요")
    return cleaned


def _reject_duplicate(con, name, exclude_id=None):
    row = con.execute(
        "SELECT id FROM labels WHERE name=? AND id IS NOT ?", (name, exclude_id)
    ).fetchone()
    if row:
        raise Conflict(f"'{name}' 라벨이 이미 있습니다")
