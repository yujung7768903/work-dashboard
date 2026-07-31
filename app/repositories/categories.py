"""카테고리 저장·조회. 비어 있을 때만 삭제 허용"""
import re

from app import ordering
from app.constants import COLOR_PATTERN
from app.db import now, palette_color, transaction
from app.errors import Conflict, NotFound, Validation

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


def get(con, category_id):
    row = con.execute("SELECT * FROM categories WHERE id=?", (category_id,)).fetchone()
    if not row:
        raise NotFound(f"카테고리 {category_id} 없음")
    return dict(row)


def get_by_name(con, name):
    row = con.execute(
        "SELECT * FROM categories WHERE name=?", (_clean_name(name),)
    ).fetchone()
    if not row:
        raise NotFound(f"카테고리 '{name}' 없음")
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
        changes["color"] = _clean_color(fields["color"])
    if not changes:
        raise Validation("수정할 필드가 없음 (name·color)")
    assignments = ", ".join(f"{key}=?" for key in changes)
    with transaction(con):
        con.execute(
            f"UPDATE categories SET {assignments} WHERE id=?",
            (*changes.values(), category_id),
        )
    return get(con, category_id)


def delete(con, category_id):
    """워크스페이스나 할일이 남아 있으면 거부. cascade 미지원"""
    get(con, category_id)
    _reject_if_occupied(con, category_id)
    with transaction(con):
        con.execute("DELETE FROM categories WHERE id=?", (category_id,))


def reorder(con, ids):
    ordering.reorder(con, TABLE, ids, *ALL_SCOPE)


def _clean_name(name):
    cleaned = (name or "").strip()
    if not cleaned:
        raise Validation("카테고리 이름이 비어 있음")
    return cleaned


def _clean_color(color):
    cleaned = (color or "").strip()
    if not re.match(COLOR_PATTERN, cleaned):
        raise Validation(f"색은 #rrggbb 형식이어야 함: {color!r}")
    return cleaned.lower()


def _reject_duplicate(con, name, exclude_id=None):
    row = con.execute(
        "SELECT id FROM categories WHERE name=? AND id IS NOT ?", (name, exclude_id)
    ).fetchone()
    if row:
        raise Conflict(f"카테고리 '{name}' 이미 있음")


def _reject_if_occupied(con, category_id):
    for table, label in OCCUPANT_TABLES:
        count = con.execute(
            f"SELECT COUNT(*) AS n FROM {table} WHERE category_id=?", (category_id,)
        ).fetchone()["n"]
        if count:
            raise Conflict(
                f"{label} {count}건이 남아 있어 삭제할 수 없음. 먼저 다른 카테고리로 옮기세요"
            )
