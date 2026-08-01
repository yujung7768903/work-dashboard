"""세션 저장·조회. 훅이 부르므로 없는 세션에는 예외 대신 None 을 돌려주는 함수를 따로 둠"""
from datetime import datetime, timedelta, timezone

from app.constants import (
    ENDED_RETENTION_DAYS,
    LAST_PROMPT_MAX_CHARS,
    SESSION_STATES,
    STALE_IDLE_HOURS,
    STATE_ENDED,
    STATE_IDLE,
    STATE_WORKING,
    STATUS_DOING,
    STATUS_TODO,
)
from app.db import now, transaction
from app.errors import NotFound, Validation
from app.repositories import categories as category_repo
from app.repositories import workspaces as workspace_repo

TABLE = "sessions"
ACTIVE_STATES = (STATE_WORKING, STATE_IDLE)
WITH_NAMES = """SELECT s.*, c.name AS category_name, w.name AS workspace_name
            FROM sessions s
            LEFT JOIN categories c ON c.id = s.category_id
            LEFT JOIN workspaces w ON w.id = s.workspace_id"""
# 데몬이 미리 띄우는 spare 프로세스도 SessionStart 로 등록된다. 프롬프트가 한 번도
# 없던 세션은 목록·미분류 집계 양쪽에서 같이 빠져야 개수와 목록이 어긋나지 않는다.
PROMPTED = "COALESCE(last_prompt,'') <> ''"


def register(con, claude_session_id, cwd=None, git_branch=None):
    """없으면 생성, 있으면 위치·시각만 갱신. 분류는 건드리지 않음"""
    session_id = _clean_id(claude_session_id)
    stamp = now()
    existing = find(con, session_id)
    with transaction(con):
        if existing:
            con.execute(
                "UPDATE sessions SET cwd=?, git_branch=?, last_seen_at=?"
                " WHERE claude_session_id=?",
                (cwd, git_branch, stamp, session_id),
            )
        else:
            con.execute(
                "INSERT INTO sessions(claude_session_id, cwd, git_branch, state,"
                " started_at, last_seen_at) VALUES(?,?,?,?,?,?)",
                (session_id, cwd, git_branch, STATE_IDLE, stamp, stamp),
            )
    return get(con, session_id)


def get(con, claude_session_id):
    found = find(con, claude_session_id)
    if not found:
        raise NotFound(f"세션 {claude_session_id} 없음")
    return found


def find(con, claude_session_id):
    row = con.execute(
        "SELECT * FROM sessions WHERE claude_session_id=?", (claude_session_id,)
    ).fetchone()
    return dict(row) if row else None


def set_state(con, claude_session_id, state):
    """없는 세션이면 None. 지워진 뒤 늦게 온 훅 이벤트를 조용히 무시하기 위함"""
    _validate_state(state)
    if not find(con, claude_session_id):
        return None
    stamp = now()
    ended_at = stamp if state == STATE_ENDED else None
    with transaction(con):
        con.execute(
            "UPDATE sessions SET state=?, last_seen_at=?, ended_at=?"
            " WHERE claude_session_id=?",
            (state, stamp, ended_at, claude_session_id),
        )
    return find(con, claude_session_id)


def set_last_prompt(con, claude_session_id, text):
    if not find(con, claude_session_id):
        return None
    with transaction(con):
        con.execute(
            "UPDATE sessions SET last_prompt=?, last_seen_at=? WHERE claude_session_id=?",
            (_one_line(text), now(), claude_session_id),
        )
    return find(con, claude_session_id)


def classify(con, claude_session_id, category_name=None, workspace_id=None):
    """워크스페이스를 주면 카테고리는 그 워크스페이스의 것이 이김"""
    get(con, claude_session_id)
    category_id = _resolve_category(con, category_name, workspace_id)
    with transaction(con):
        con.execute(
            "UPDATE sessions SET category_id=?, workspace_id=?, last_seen_at=?"
            " WHERE claude_session_id=?",
            (category_id, workspace_id, now(), claude_session_id),
        )
    return get(con, claude_session_id)


def classify_by_ids(con, session_row_id, category_id=None, workspace_id=None):
    """대시보드에서 손으로 고칠 때. 내부 정수 id 로 받음"""
    if not _row_by_id(con, session_row_id):
        raise NotFound(f"세션 {session_row_id} 없음")
    if workspace_id is not None:
        category_id = workspace_repo.get(con, workspace_id)["category_id"]
    elif category_id is not None:
        category_repo.get(con, category_id)
    else:
        raise Validation("카테고리나 워크스페이스 중 하나는 필요함")
    with transaction(con):
        con.execute(
            "UPDATE sessions SET category_id=?, workspace_id=?, last_seen_at=? WHERE id=?",
            (category_id, workspace_id, now(), session_row_id),
        )
    return _row_by_id(con, session_row_id)


def link_todo(con, claude_session_id, todo_id):
    """중복 연결은 무시. PK 가 (session_id, todo_id).

    연결은 착수 선언이므로 할일을 doing 으로 올림. status=todo 인 것만 바꿔서
    이미 done 인 할일이 되살아나지 않게 함
    """
    session = get(con, claude_session_id)
    _require_todo(con, todo_id)
    stamp = now()
    with transaction(con):
        con.execute(
            "INSERT OR IGNORE INTO session_todos(session_id, todo_id, created_at)"
            " VALUES(?,?,?)",
            (session["id"], todo_id, stamp),
        )
        con.execute(
            "UPDATE todos SET status=?, updated_at=? WHERE id=? AND status=?",
            (STATUS_DOING, stamp, todo_id, STATUS_TODO),
        )


def linked_todo_ids(con, claude_session_id):
    session = get(con, claude_session_id)
    return [
        row["todo_id"]
        for row in con.execute(
            "SELECT todo_id FROM session_todos WHERE session_id=? ORDER BY todo_id",
            (session["id"],),
        )
    ]


def count_unclassified(con):
    return con.execute(
        "SELECT COUNT(*) AS n FROM sessions WHERE category_id IS NULL"
        f" AND {PROMPTED}"
        f" AND state IN ({_placeholders(ACTIVE_STATES)})",
        ACTIVE_STATES,
    ).fetchone()["n"]


def list_active(con):
    """working/idle 중 프롬프트가 한 번이라도 있던 세션만.
    카테고리·워크스페이스 이름을 붙여 목록용으로 반환"""
    rows = con.execute(
        f"""{WITH_NAMES}
            WHERE s.state IN ({_placeholders(ACTIVE_STATES)})
              AND {PROMPTED}
            ORDER BY s.last_seen_at DESC""",
        ACTIVE_STATES,
    )
    return [dict(row) for row in rows]


def list_by_todo(con, todo_id):
    """그 할일을 잡은 세션. 상태를 가리지 않는다 — 끝난 세션도 누가 했는지 남아야 함"""
    rows = con.execute(
        f"""{WITH_NAMES}
            JOIN session_todos st ON st.session_id = s.id
            WHERE st.todo_id=? ORDER BY s.last_seen_at DESC""",
        (todo_id,),
    )
    return [dict(row) for row in rows]


def get_by_row_id(con, session_row_id):
    """대시보드 팝업용. 목록과 같은 모양(이름 포함)으로 한 건"""
    row = con.execute(f"{WITH_NAMES} WHERE s.id=?", (session_row_id,)).fetchone()
    if not row:
        raise NotFound(f"세션 {session_row_id} 없음")
    return dict(row)


def sweep(con):
    """오래된 idle 은 ended 로, 보존기간 지난 ended 는 삭제. 조회할 때마다 호출됨"""
    stale_before = _ago_text(hours=STALE_IDLE_HOURS)
    delete_before = _ago_text(days=ENDED_RETENTION_DAYS)
    stamp = now()
    with transaction(con):
        expired = con.execute(
            "UPDATE sessions SET state=?, ended_at=? WHERE state=? AND last_seen_at<?",
            (STATE_ENDED, stamp, STATE_IDLE, stale_before),
        ).rowcount
        deleted = con.execute(
            """DELETE FROM sessions WHERE state=? AND ended_at IS NOT NULL
               AND ended_at<? AND id NOT IN (SELECT session_id FROM session_todos)""",
            (STATE_ENDED, delete_before),
        ).rowcount
    return {"expired": expired, "deleted": deleted}


def _row_by_id(con, session_row_id):
    row = con.execute("SELECT * FROM sessions WHERE id=?", (session_row_id,)).fetchone()
    return dict(row) if row else None


def _resolve_category(con, category_name, workspace_id):
    if workspace_id is not None:
        return workspace_repo.get(con, workspace_id)["category_id"]
    if not category_name:
        raise Validation("카테고리나 워크스페이스 중 하나는 필요함")
    return category_repo.get_by_name(con, category_name)["id"]


def _require_todo(con, todo_id):
    row = con.execute("SELECT id FROM todos WHERE id=?", (todo_id,)).fetchone()
    if not row:
        raise NotFound(f"할일 {todo_id} 없음")


def _clean_id(claude_session_id):
    cleaned = (claude_session_id or "").strip()
    if not cleaned:
        raise Validation("세션 id 가 비어 있음")
    return cleaned


def _one_line(text):
    """목록에 한 줄로 보여줄 용도. 전문은 transcript 에 있음"""
    collapsed = " ".join((text or "").split())
    return collapsed[:LAST_PROMPT_MAX_CHARS]


def _validate_state(state):
    if state not in SESSION_STATES:
        raise Validation(f"세션 상태는 {SESSION_STATES} 중 하나여야 함")


def _placeholders(values):
    return ",".join("?" * len(values))


def _ago_text(**kwargs):
    return (datetime.now(timezone.utc) - timedelta(**kwargs)).isoformat(timespec="seconds")
