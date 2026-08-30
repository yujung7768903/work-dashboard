"""세션 저장·조회. 훅이 부르므로 없는 세션에는 예외 대신 None 을 돌려주는 함수를 따로 둠"""
from datetime import datetime, timedelta, timezone

from app.constants import (
    ENDED_RETENTION_DAYS,
    LAST_PROMPT_MAX_CHARS,
    SCOPE_REQUIRED_MSG,
    SESSION_STATES,
    STALE_IDLE_HOURS,
    STATE_ENDED,
    STATE_IDLE,
    STATE_WORKING,
    STATUS_DOING,
    STATUS_DONE,
    STATUS_TODO,
)
from app.db import now, transaction
from app.errors import NotFound, Validation
from app.repositories import categories as category_repo
from app.repositories import workspaces as workspace_repo

TABLE = "sessions"
ACTIVE_STATES = (STATE_WORKING, STATE_IDLE)
# 세션의 워크스페이스는 저장하지 않고 연결된 할일에서 파생한다 — 소속이 세션과 할일
# 두 군데 있으면 세션을 분류해도 보드에 안 나타나는 어긋남이 생긴다.
# 할일이 여럿이면 가장 최근 연결된 것이 이 세션의 현재 작업이다
LATEST_LINKED = """FROM session_todos st JOIN todos t ON t.id = st.todo_id
                   WHERE st.session_id = s.id
                   ORDER BY st.created_at DESC, st.todo_id DESC LIMIT 1"""
WITH_NAMES = f"""SELECT s.*, c.name AS category_name,
                (SELECT t.workspace_id {LATEST_LINKED}) AS workspace_id,
                (SELECT (SELECT w.name FROM workspaces w WHERE w.id = t.workspace_id)
                 {LATEST_LINKED}) AS workspace_name
            FROM sessions s
            LEFT JOIN categories c ON c.id = s.category_id"""
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
        raise NotFound("세션을 찾을 수 없습니다")
    return found


def find(con, claude_session_id):
    row = con.execute(
        f"{WITH_NAMES} WHERE s.claude_session_id=?", (claude_session_id,)
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
    """워크스페이스를 주면 카테고리는 그 워크스페이스의 것이 이김.

    워크스페이스 자체는 저장하지 않는다 — 세션이 어느 워크스페이스 일감인지는
    할일을 연결하는 것으로 정해진다. 여기서는 카테고리를 고르는 데만 쓴다
    """
    get(con, claude_session_id)
    category_id = _resolve_category(con, category_name, workspace_id)
    with transaction(con):
        con.execute(
            "UPDATE sessions SET category_id=?, last_seen_at=? WHERE claude_session_id=?",
            (category_id, now(), claude_session_id),
        )
    return get(con, claude_session_id)


def classify_by_ids(con, session_row_id, category_id=None, workspace_id=None):
    """대시보드에서 손으로 고칠 때. 내부 정수 id 로 받음"""
    if not _row_by_id(con, session_row_id):
        raise NotFound("세션을 찾을 수 없습니다")
    if workspace_id is not None:
        category_id = workspace_repo.get(con, workspace_id)["category_id"]
    elif category_id is not None:
        category_repo.get(con, category_id)
    else:
        raise Validation(SCOPE_REQUIRED_MSG)
    with transaction(con):
        con.execute(
            "UPDATE sessions SET category_id=?, last_seen_at=? WHERE id=?",
            (category_id, now(), session_row_id),
        )
    return _row_by_id(con, session_row_id)


def link_todo(con, claude_session_id, todo_id, claim=True, status=None):
    """중복 연결은 무시. PK 가 (session_id, todo_id).

    연결하며 할일의 상태도 정한다. 기본은 doing(착수 선언)이고, 이미 끝난 작업을
    뒤늦게 연결하는 것이면 done 을 넘긴다 — 무엇이 끝난 것인지는 작업 내용을 본
    쪽만 알 수 있으므로 여기서 추측하지 않고 받은 값을 쓴다.

    doing 은 status=todo 인 것만 바꾼다. 이미 done 인 할일이 연결만으로 되살아나면 안 된다.

    claim=False 는 끝난 히스토리 세션을 소급 연결할 때 쓴다 — 그건 착수 선언이 아니라
    기록이므로 상태를 건드리면 안 된다 (온보딩이 추정해 넣은 상태가 뒤집힌다)
    """
    session = get(con, claude_session_id)
    _require_todo(con, todo_id)
    target = _validated_link_status(status)
    stamp = now()
    with transaction(con):
        con.execute(
            "INSERT OR IGNORE INTO session_todos(session_id, todo_id, created_at)"
            " VALUES(?,?,?)",
            (session["id"], todo_id, stamp),
        )
        if not claim:
            return
        if target == STATUS_DONE:
            con.execute(
                "UPDATE todos SET status=?, completed_at=?, updated_at=? WHERE id=?",
                (STATUS_DONE, stamp, stamp, todo_id),
            )
        else:
            con.execute(
                "UPDATE todos SET status=?, updated_at=? WHERE id=? AND status=?",
                (STATUS_DOING, stamp, todo_id, STATUS_TODO),
            )


def _validated_link_status(status):
    """연결할 때 넣을 수 있는 상태는 doing·done 뿐. todo 는 연결하지 않은 것과 같은 말"""
    if status is None:
        return STATUS_DOING
    if status not in (STATUS_DOING, STATUS_DONE):
        raise Validation(f"연결 상태는 {STATUS_DOING} 또는 {STATUS_DONE} 이어야 함: {status!r}")
    return status


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


def last_activity_by_todo(con):
    """할일마다 그것을 잡은 세션이 마지막으로 살아 있던 시각. 상태별 뷰가 카드를 이 순서로
    세운다 — 방금 손댄 것이 위로 온다. 끝난 세션도 센다(last_seen_at 이 그대로 남는다)"""
    rows = con.execute(
        """SELECT st.todo_id AS todo_id, MAX(s.last_seen_at) AS seen FROM sessions s
            JOIN session_todos st ON st.session_id = s.id
            GROUP BY st.todo_id"""
    )
    return {row["todo_id"]: row["seen"] for row in rows}


def cwds_by_workspace(con, workspace_id):
    """그 워크스페이스에서 돌았던 작업 위치. 최근 순.
    워크스페이스에는 저장소 경로가 없어 워크트리 뷰가 여기서 저장소를 유추한다"""
    rows = con.execute(
        """SELECT s.cwd AS cwd, MAX(s.last_seen_at) AS seen FROM sessions s
            JOIN session_todos st ON st.session_id = s.id
            JOIN todos t ON t.id = st.todo_id
            WHERE t.workspace_id=? AND COALESCE(s.cwd,'') <> ''
            GROUP BY s.cwd ORDER BY seen DESC""",
        (workspace_id,),
    )
    return [row["cwd"] for row in rows]


def all_cwds(con):
    """세션이 남긴 모든 작업 위치, 워크스페이스·할일 연결 여부와 무관하게. 최근 순.
    워크트리 뷰의 프로젝트 모드가 저장소를 유추할 때 쓴다 — cwds_by_workspace 와 달리
    todos 조인이 없어 어느 워크스페이스에도 속하지 않은 위치까지 잡힌다"""
    rows = con.execute(
        "SELECT cwd, MAX(last_seen_at) AS seen FROM sessions"
        " WHERE COALESCE(cwd,'') <> '' GROUP BY cwd ORDER BY seen DESC"
    )
    return [row["cwd"] for row in rows]


def cwd_counts_by_workspace(con, workspace_id):
    """그 워크스페이스에서 돈 작업 위치 → 세션 수. 많이 돈 순, 같으면 최근 순.

    cwds_by_workspace 와 갈라 두는 이유 — 워크트리 뷰는 '어느 저장소들을 봐야 하나'라
    목록이 필요하고, 자율 실행은 '어디가 이 워크스페이스의 본거지인가'라 무게가 필요하다.
    한 번 스쳐간 위치가 최근이라는 이유로 이기면 자율 잡이 엉뚱한 저장소에서 돈다
    """
    rows = con.execute(
        """SELECT s.cwd AS cwd, COUNT(*) AS sessions, MAX(s.last_seen_at) AS seen
             FROM sessions s
             JOIN session_todos st ON st.session_id = s.id
             JOIN todos t ON t.id = st.todo_id
            WHERE t.workspace_id=? AND COALESCE(s.cwd,'') <> ''
            GROUP BY s.cwd ORDER BY sessions DESC, seen DESC""",
        (workspace_id,),
    )
    return [(row["cwd"], row["sessions"]) for row in rows]


def _latest_todo_by_cwd(con):
    """작업 위치 → 거기서 마지막으로 돌던 세션이 잡은 할일 행.
    오래된 것부터 훑어 같은 위치는 가장 최근 세션의 것이 남는다"""
    rows = con.execute(
        """SELECT s.cwd AS cwd, t.id AS todo_id, t.title AS title
             FROM sessions s
             JOIN session_todos st ON st.session_id = s.id
             JOIN todos t ON t.id = st.todo_id
            WHERE COALESCE(s.cwd,'') <> ''
            ORDER BY s.last_seen_at ASC"""
    )
    return {row["cwd"]: row for row in rows}


def todo_titles_by_cwd(con):
    """워크트리 뷰의 작업 요약용 제목"""
    return {cwd: row["title"] for cwd, row in _latest_todo_by_cwd(con).items()}


def todo_id_by_cwd(con):
    """워크트리 뷰가 줄 클릭으로 상세 팝업을 열 때 쓰는 할일 id.
    제목과 같은 행에서 뽑으므로 보이는 요약과 열리는 할일이 어긋나지 않는다"""
    return {cwd: row["todo_id"] for cwd, row in _latest_todo_by_cwd(con).items()}


def todo_ids_by_cwd(con):
    """작업 위치 → 거기서 돌던 세션들이 연결한 할일 id 전부(중복 없이).
    워크트리 적용(병합 후 할일 done 처리)이 한 위치에 여러 세션이 걸쳐 있어도
    다 잡아야 해서, 요약과 달리 최근 하나가 아니라 전체를 모은다"""
    rows = con.execute(
        """SELECT DISTINCT s.cwd AS cwd, st.todo_id AS todo_id
             FROM sessions s
             JOIN session_todos st ON st.session_id = s.id
            WHERE COALESCE(s.cwd,'') <> ''"""
    )
    found = {}
    for row in rows:
        found.setdefault(row["cwd"], set()).add(row["todo_id"])
    return found


def get_by_row_id(con, session_row_id):
    """대시보드 팝업용. 목록과 같은 모양(이름 포함)으로 한 건"""
    row = con.execute(f"{WITH_NAMES} WHERE s.id=?", (session_row_id,)).fetchone()
    if not row:
        raise NotFound("세션을 찾을 수 없습니다")
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
        raise Validation(SCOPE_REQUIRED_MSG)
    return category_repo.get_by_name(con, category_name)["id"]


def _require_todo(con, todo_id):
    row = con.execute("SELECT id FROM todos WHERE id=?", (todo_id,)).fetchone()
    if not row:
        raise NotFound("할 일을 찾을 수 없습니다")


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
