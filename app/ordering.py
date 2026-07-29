"""sort_order 공통 처리. 재정렬은 범위 전체를 1..N 으로 통째 재부여"""
from app.constants import FIRST_SORT_ORDER
from app.db import transaction
from app.errors import Validation


def next_order(con, table, where, params):
    """해당 범위의 마지막 순번 + 1"""
    row = con.execute(
        f"SELECT MAX(sort_order) AS last FROM {table} WHERE {where}", params
    ).fetchone()
    last = row["last"]
    return FIRST_SORT_ORDER if last is None else last + 1


def reorder(con, table, ids, where, params):
    """주어진 순서대로 1..N 재부여. 범위의 id 집합과 정확히 일치해야 함"""
    existing = [
        row["id"] for row in con.execute(f"SELECT id FROM {table} WHERE {where}", params)
    ]
    if sorted(ids) != sorted(existing):
        raise Validation(
            f"재정렬 대상이 범위와 일치하지 않음 (요청 {len(ids)}건, 범위 {len(existing)}건)"
        )
    with transaction(con):
        for order, item_id in enumerate(ids, start=FIRST_SORT_ORDER):
            con.execute(f"UPDATE {table} SET sort_order=? WHERE id=?", (order, item_id))
