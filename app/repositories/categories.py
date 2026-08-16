"""카테고리 저장·조회. 비어 있을 때만 삭제 허용"""
from app import ordering
from app.db import clean_color, now, palette_color, transaction
from app.errors import Conflict, NeedsConfirm, NotFound, Validation

TABLE = "categories"
ALL_SCOPE = ("1=1", ())
OCCUPANT_TABLES = (("workspaces", "워크스페이스"), ("todos", "할일"))


def create(con, name):
    """맨 뒤에 붙임. 색은 순번대로 팔레트에서 자동 배정하고 이후 수정 가능"""
    cleaned = _clean_name(name)
    _reject_duplicate(con, cleaned)
    order = ordering.next_order(con, TABLE, *ALL_SCOPE)
    with transaction(con):
        cursor = con.execute(
            "INSERT INTO categories(name, sort_order, color, created_at)"
            " VALUES(?,?,?,?)",
            (cleaned, order, palette_color(order), now()),
        )
    return get(con, cursor.lastrowid)


def list_all(con):
    return [
        dict(row)
        for row in con.execute("SELECT * FROM categories ORDER BY sort_order, id")
    ]


def set_google_list_id(con, category_id, list_id):
    """이 카테고리를 담는 구글 목록 id. 목록 제목을 바꿔도 연결이 안 끊기게 id 로 붙든다"""
    with transaction(con):
        con.execute(
            "UPDATE categories SET google_list_id=? WHERE id=?", (list_id, category_id)
        )


def set_gtasks_enabled(con, category_id, enabled):
    """이 카테고리를 동기화 대상으로 볼지. 끄면 연결(google_list_id)은 그대로 남는다

    링크를 지우면 다시 켤 때 목록을 새로 만들어 폰에 같은 이름이 둘 생긴다
    """
    get(con, category_id)
    with transaction(con):
        con.execute(
            "UPDATE categories SET gtasks_enabled=? WHERE id=?",
            (1 if enabled else 0, category_id),
        )
    return get(con, category_id)


def get(con, category_id):
    row = con.execute("SELECT * FROM categories WHERE id=?", (category_id,)).fetchone()
    if not row:
        raise NotFound("카테고리를 찾을 수 없습니다")
    return dict(row)


def get_by_name(con, name):
    row = con.execute(
        "SELECT * FROM categories WHERE name=?", (_clean_name(name),)
    ).fetchone()
    if not row:
        raise NotFound(f"'{name}' 카테고리를 찾을 수 없습니다")
    return dict(row)


def rename(con, category_id, name):
    return update(con, category_id, name=name)


def update(con, category_id, **fields):
    """이름·색을 부분 수정. 준 필드만 건드림"""
    get(con, category_id)
    changes = {}
    if "name" in fields:
        cleaned = _clean_name(fields["name"])
        _reject_duplicate(con, cleaned, exclude_id=category_id)
        changes["name"] = cleaned
    if "color" in fields:
        changes["color"] = clean_color(fields["color"])
    if not changes:
        raise Validation("수정할 필드가 없음 (name·color)")
    assignments = ", ".join(f"{key}=?" for key in changes)
    with transaction(con):
        con.execute(
            f"UPDATE categories SET {assignments} WHERE id=?",
            (*changes.values(), category_id),
        )
    return get(con, category_id)


def delete(con, category_id, force=False):
    """워크스페이스나 할일이 남아 있으면 거부. cascade 미지원

    세션은 옮길 대상이 아니라 분류 기록일 뿐이고 category_id 가 nullable 이라
    미분류로 되돌리고 지운다. 안 그러면 sessions FK 에 걸려 IntegrityError 가 난다.
    다만 분류가 조용히 사라지므로 붙어 있는 세션이 있으면 force 로 확인을 받는다
    """
    get(con, category_id)
    _reject_if_occupied(con, category_id)
    sessions = _count_sessions(con, category_id)
    if sessions and not force:
        raise NeedsConfirm(
            f"이 카테고리로 분류된 세션 {sessions}건이 미분류로 바뀝니다. 삭제할까요?"
        )
    with transaction(con):
        con.execute(
            "UPDATE sessions SET category_id=NULL WHERE category_id=?", (category_id,)
        )
        con.execute("DELETE FROM categories WHERE id=?", (category_id,))


def reorder(con, ids):
    ordering.reorder(con, TABLE, ids, *ALL_SCOPE)


def _clean_name(name):
    cleaned = (name or "").strip()
    if not cleaned:
        raise Validation("카테고리 이름을 입력해 주세요")
    return cleaned


def _reject_duplicate(con, name, exclude_id=None):
    row = con.execute(
        "SELECT id FROM categories WHERE name=? AND id IS NOT ?", (name, exclude_id)
    ).fetchone()
    if row:
        raise Conflict(f"'{name}' 카테고리가 이미 있습니다")


def _count_sessions(con, category_id):
    return con.execute(
        "SELECT COUNT(*) AS n FROM sessions WHERE category_id=?", (category_id,)
    ).fetchone()["n"]


def _reject_if_occupied(con, category_id):
    for table, label in OCCUPANT_TABLES:
        count = con.execute(
            f"SELECT COUNT(*) AS n FROM {table} WHERE category_id=?", (category_id,)
        ).fetchone()["n"]
        if count:
            raise Conflict(
                f"{label} {count}건이 남아 있어 삭제할 수 없습니다."
                " 먼저 다른 카테고리로 옮겨 주세요"
            )
