"""결과물(Result) 저장·조회. 코드 이외 산출물 — Figma·블로그·Jira 댓글·배포 등.

워크트리와 달리 git 으로 되짚을 자국이 없어 세션이 dash.py add-result 로 직접 남긴다.
링크는 여러 개일 수 있어(배포는 구성마다 하나) 조인 테이블 대신 JSON 배열로 둔다.
"""
import json
from datetime import datetime, timedelta, timezone

from app.constants import RESULT_DATE_PRESETS, RESULTS_PAGE_SIZE
from app.db import now, transaction
from app.errors import NotFound, Validation
from app.repositories import todos as todo_repo

TABLE = "results"


def create(con, todo_id, kind, summary=None, session_cwd=None, links=None):
    todo_repo.get(con, todo_id)
    cleaned_kind = _clean_kind(kind)
    cleaned_links = _clean_links(links)
    stamp = now()
    with transaction(con):
        cursor = con.execute(
            "INSERT INTO results(todo_id, kind, summary, session_cwd, links_json,"
            " created_at, updated_at) VALUES(?,?,?,?,?,?,?)",
            (
                todo_id,
                cleaned_kind,
                (summary or "").strip() or None,
                session_cwd,
                json.dumps(cleaned_links, ensure_ascii=False),
                stamp,
                stamp,
            ),
        )
    return get(con, cursor.lastrowid)


def get(con, result_id):
    row = con.execute("SELECT * FROM results WHERE id=?", (result_id,)).fetchone()
    if not row:
        raise NotFound("결과물을 찾을 수 없습니다")
    return _shaped(row)


def list_by_todo_ids(con, todo_ids):
    """세션·할일 팝업의 결과물 탭. 최근 작업 순"""
    ids = list(todo_ids)
    if not ids:
        return []
    placeholders = ",".join("?" * len(ids))
    rows = con.execute(
        f"SELECT results.*, todos.title AS todo_title FROM results"
        f" JOIN todos ON todos.id = results.todo_id"
        f" WHERE results.todo_id IN ({placeholders})"
        " ORDER BY results.updated_at DESC, results.id DESC",
        ids,
    )
    return [_shaped(row) for row in rows]


def list_page(con, preset=None, date_from=None, date_to=None, page=1, page_size=RESULTS_PAGE_SIZE):
    """결과물 메뉴 카드 그리드. 날짜 필터 + 페이징"""
    start, end = _resolve_range(preset, date_from, date_to)
    where, params = _date_where(start, end)
    total = con.execute(
        f"SELECT COUNT(*) AS n FROM results WHERE {where}", params
    ).fetchone()["n"]
    safe_page = max(1, page)
    offset = (safe_page - 1) * page_size
    rows = con.execute(
        f"SELECT results.*, todos.title AS todo_title FROM results"
        f" JOIN todos ON todos.id = results.todo_id"
        f" WHERE {where} ORDER BY results.updated_at DESC, results.id DESC"
        " LIMIT ? OFFSET ?",
        (*params, page_size, offset),
    )
    return {
        "items": [_shaped(row) for row in rows],
        "total": total,
        "page": safe_page,
        "page_size": page_size,
    }


def delete(con, result_id):
    get(con, result_id)
    with transaction(con):
        con.execute("DELETE FROM results WHERE id=?", (result_id,))


def _shaped(row):
    result = dict(row)
    result["links"] = json.loads(result.pop("links_json") or "[]")
    return result


def _clean_kind(kind):
    cleaned = (kind or "").strip()
    if not cleaned:
        raise Validation("결과물 형태를 입력해 주세요")
    return cleaned


def _clean_links(links):
    cleaned = []
    for link in links or ():
        url = (link.get("url") or "").strip()
        if not url:
            raise Validation("링크 URL 을 입력해 주세요")
        cleaned.append({"label": (link.get("label") or "").strip(), "url": url})
    return cleaned


def _resolve_range(preset, date_from, date_to):
    if preset:
        return _range_for_preset(preset)
    start = _parse_date(date_from) if date_from else None
    end = _parse_date(date_to) if date_to else None
    return start, end


def _range_for_preset(preset):
    if preset not in RESULT_DATE_PRESETS:
        raise Validation(f"알 수 없는 날짜 프리셋: {preset}")
    today = datetime.now(timezone.utc).date()
    monday = today - timedelta(days=today.weekday())
    if preset == "today":
        return today, today
    if preset == "this_week":
        return monday, monday + timedelta(days=6)
    last_monday = monday - timedelta(days=7)
    return last_monday, last_monday + timedelta(days=6)


def _parse_date(text):
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        raise Validation("날짜 형식은 YYYY-MM-DD 여야 함")


def _date_where(start, end):
    """updated_at 날짜 부분 비교. ISO8601 이라 문자열 비교로도 순서가 맞는다.
    todos 도 같은 이름의 컬럼을 가져 JOIN 에서 모호해지므로 테이블을 명시한다"""
    if start and end:
        return (
            "substr(results.updated_at,1,10) BETWEEN ? AND ?",
            (start.isoformat(), end.isoformat()),
        )
    if start:
        return "substr(results.updated_at,1,10) >= ?", (start.isoformat(),)
    if end:
        return "substr(results.updated_at,1,10) <= ?", (end.isoformat(),)
    return "1=1", ()
