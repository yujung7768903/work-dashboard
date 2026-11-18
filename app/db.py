"""sqlite 연결과 스키마. 다른 모듈은 connect() 만 씀"""
import os
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from app.constants import (
    BUSY_TIMEOUT_MS,
    CATEGORY_PALETTE,
    COLOR_PATTERN,
    DB_PATH_ENV,
    DEFAULT_DB_PATH,
    SEED_CATEGORIES,
)
from app.errors import Validation

SCHEMA = """
CREATE TABLE IF NOT EXISTS categories(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    sort_order INTEGER NOT NULL,
    color TEXT,
    created_at TEXT NOT NULL
);
-- 라벨은 카테고리와 달리 한 할일에 여러 개 붙는다 (github 이슈 라벨과 같은 뜻).
-- 카테고리는 소속이라 하나, 라벨은 성격이라 여럿 — 그래서 조인 테이블을 따로 둔다
CREATE TABLE IF NOT EXISTS labels(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    sort_order INTEGER NOT NULL,
    color TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS todo_labels(
    todo_id INTEGER NOT NULL REFERENCES todos(id),
    label_id INTEGER NOT NULL REFERENCES labels(id),
    PRIMARY KEY(todo_id, label_id)
);
CREATE TABLE IF NOT EXISTS workspaces(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category_id INTEGER NOT NULL REFERENCES categories(id),
    name TEXT NOT NULL,
    background TEXT, purpose TEXT, goal TEXT, considerations TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    sort_order INTEGER NOT NULL,
    jira_id TEXT,
    cwd TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS todos(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category_id INTEGER NOT NULL REFERENCES categories(id),
    workspace_id INTEGER REFERENCES workspaces(id),
    title TEXT NOT NULL,
    note TEXT,
    precondition TEXT,
    cwd TEXT,
    status TEXT NOT NULL DEFAULT 'todo',
    sort_order INTEGER NOT NULL,
    completed_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS meta(
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    claude_session_id TEXT NOT NULL UNIQUE,
    cwd TEXT,
    git_branch TEXT,
    category_id INTEGER REFERENCES categories(id),
    state TEXT NOT NULL DEFAULT 'idle',
    last_prompt TEXT,
    started_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    ended_at TEXT
);
CREATE TABLE IF NOT EXISTS session_todos(
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    todo_id INTEGER NOT NULL REFERENCES todos(id),
    created_at TEXT NOT NULL,
    PRIMARY KEY(session_id, todo_id)
);
-- 한도 %는 어디에도 이력이 남지 않는다(사이드카는 매번 덮어씀). 추이를 그리려면
-- 우리가 스냅샷을 쌓아야 한다. source_ts 는 사이드카의 timestamp 라, 같은 스냅샷이
-- 두 번 들어오는 걸 PK 가 그대로 막아준다
CREATE TABLE IF NOT EXISTS usage_samples(
    source_ts INTEGER PRIMARY KEY,
    five_hour_pct REAL,
    five_hour_resets_at INTEGER,
    seven_day_pct REAL,
    seven_day_resets_at INTEGER,
    created_at TEXT NOT NULL
);
-- 워크트리 이력. 병합·삭제된 워크트리는 git 에 아무 자국이 없어(브랜치도 디렉터리도
-- 사라짐) 살아 있는 동안 본 것을 여기 적어 둔다. 병합 사실은 기준 브랜치 reflog 에서
-- 되짚어 채운다 — 그것도 지워지므로(기본 90일) 처음 본 때 해시까지 남긴다
CREATE TABLE IF NOT EXISTS worktrees(
    path TEXT PRIMARY KEY,
    repo TEXT NOT NULL,
    branch TEXT NOT NULL,
    created_at TEXT NOT NULL,
    merged_at TEXT,
    merge_hash TEXT,
    merge_from TEXT,
    deleted_at TEXT
);
-- ④ 자율 실행. 설정은 필드 셋뿐이라 키-값 테이블 대신 단일 행을 쓴다
CREATE TABLE IF NOT EXISTS autorun_state(
    id INTEGER PRIMARY KEY CHECK (id = 1),
    enabled INTEGER NOT NULL DEFAULT 0,
    blocked_streak INTEGER NOT NULL DEFAULT 0,
    last_tick_at TEXT,
    last_tick_reason TEXT,
    updated_at TEXT NOT NULL
);
-- 실행 1건 = 할일 1건. ended_at 이 NULL 이면 아직 도는 잡이라 다음 tick 이 시작하지 않는다
CREATE TABLE IF NOT EXISTS autorun_runs(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    todo_id INTEGER NOT NULL REFERENCES todos(id),
    claude_session_id TEXT,
    job_id TEXT,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    outcome TEXT,
    requested_note TEXT,
    finished_at TEXT
);
-- 방치된 doing 판정 기록. 상태 변경은 todos 에, 판정 자체는 여기 남긴다 — keep 으로 본
-- 할일을 매일 다시 묻지 않으려면 마지막 판정 시각이 필요하고, 틀린 판정을 되짚으려면
-- 사유가 필요하다
CREATE TABLE IF NOT EXISTS stale_judgments(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    todo_id INTEGER NOT NULL REFERENCES todos(id),
    judged_at TEXT NOT NULL,
    verdict TEXT NOT NULL,
    confidence REAL,
    reason TEXT,
    applied INTEGER NOT NULL DEFAULT 0
);
-- 할일 관계 그래프(속성 그래프). 노드는 (종류, id) 쌍이다 — todo 는 todos.id, session 은
-- sessions.claude_session_id, context 는 graph_nodes.id, doc 은 graph_nodes.ref('jira:PFD-6350').
-- 그래프 DB 로 옮길 때는 graph_nodes·todos·sessions 를 노드로, graph_edges 뷰를 관계로 그대로 내보낸다
CREATE TABLE IF NOT EXISTS graph_nodes(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    ref TEXT,
    title TEXT NOT NULL,
    url TEXT,
    note TEXT,
    workspace_id INTEGER REFERENCES workspaces(id),
    category_id INTEGER REFERENCES categories(id),
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(kind, ref)
);
-- 관계 하나 = 행 하나. basis 는 상위 연결의 기준(trigger·purpose·background), evidence 는 근거 문장.
-- state 가 rejected 인 행은 지우지 않는다 — 자동 제안이 같은 연결을 되살리지 않게 막는 기록이다
CREATE TABLE IF NOT EXISTS edges(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    src_kind TEXT NOT NULL,
    src_id TEXT NOT NULL,
    dst_kind TEXT NOT NULL,
    dst_id TEXT NOT NULL,
    relation TEXT NOT NULL,
    basis TEXT,
    evidence TEXT,
    state TEXT NOT NULL DEFAULT 'confirmed',
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(src_kind, src_id, dst_kind, dst_id, relation)
);
CREATE INDEX IF NOT EXISTS edges_by_dst ON edges(dst_kind, dst_id, relation);
CREATE INDEX IF NOT EXISTS edges_by_src ON edges(src_kind, src_id, relation);
-- 수행(세션 → 할일)은 session_todos 가 정본이다. 두 곳에 적지 않고 뷰로 합쳐 한 그래프로 본다
CREATE VIEW IF NOT EXISTS graph_edges AS
    SELECT id, src_kind, src_id, dst_kind, dst_id, relation, basis, evidence, state,
           created_by, created_at, updated_at
    FROM edges
    UNION ALL
    SELECT NULL, 'session', s.claude_session_id, 'todo', CAST(st.todo_id AS TEXT), 'performs',
           NULL, NULL, 'confirmed', 'session', st.created_at, st.created_at
    FROM session_todos st JOIN sessions s ON s.id = st.session_id;
-- 매니저 spawn 이 띄운 세션이 어디서 왔는지. 띄우는 순간에는 그 세션의 할일이 아직 없을 수 있어
-- 출처만 적어 두고, 세션이 할일을 잡으면(link_todo) 출처 세션의 할일을 상위 제안으로 잇는다
CREATE TABLE IF NOT EXISTS session_origins(
    claude_session_id TEXT PRIMARY KEY,
    origin_session_id TEXT,
    manager_task_id INTEGER,
    title TEXT,
    created_at TEXT NOT NULL
);
-- 세션 결과물 수집이 transcript 를 어디까지 읽었는지. 훅은 턴마다 새로 붙은 꼬리만 읽는다 —
-- 수십 MB transcript 를 매 턴 처음부터 읽으면 훅 시간 제한을 넘는다. 서브에이전트 transcript 도
-- 파일마다 한 행이고 결과는 부모 세션(claude_session_id) 몫이다
CREATE TABLE IF NOT EXISTS transcript_scans(
    path TEXT PRIMARY KEY,
    claude_session_id TEXT NOT NULL,
    offset INTEGER NOT NULL DEFAULT 0,
    scanned_at TEXT NOT NULL
);
-- ⑤ 구글 태스크 연동. autorun_state 와 같은 이유로 단일 행. 문제가 생겨도 enabled 를
-- 건드리지 않고 last_error 만 채운다 — 끄고 켜는 것은 사람의 판단이다
CREATE TABLE IF NOT EXISTS gtasks_state(
    id INTEGER PRIMARY KEY CHECK (id = 1),
    enabled INTEGER NOT NULL DEFAULT 0,
    last_sync_at TEXT,
    last_error TEXT,
    updated_at TEXT NOT NULL
);
"""

SEEDED_FLAG = "categories_seeded"


def now():
    """ISO8601 UTC 초 단위"""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def palette_color(sort_order):
    """카테고리 기본 색. 팔레트를 다 쓰면 처음으로 돌아감"""
    return CATEGORY_PALETTE[(sort_order - 1) % len(CATEGORY_PALETTE)]


def clean_color(color):
    """#rrggbb 만 통과. 카테고리·라벨이 같은 규칙을 쓴다"""
    cleaned = (color or "").strip()
    if not re.match(COLOR_PATTERN, cleaned):
        raise Validation("색은 #rrggbb 형식으로 입력해 주세요")
    return cleaned.lower()


def resolve_path(path=None):
    """인자 > 환경변수 > 기본 경로 순"""
    return path or os.environ.get(DB_PATH_ENV) or DEFAULT_DB_PATH


def connect(path=None):
    """스키마 초기화와 시드까지 끝낸 연결 반환"""
    resolved = resolve_path(path)
    parent = os.path.dirname(resolved)
    if parent:
        os.makedirs(parent, exist_ok=True)
    con = sqlite3.connect(resolved)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA journal_mode=WAL")
    con.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
    con.executescript(SCHEMA)
    con.commit()
    _add_category_style_columns(con)
    _add_manager_columns(con)
    _add_precondition_columns(con)
    _add_autorun_order_column(con)
    _add_usage_account_column(con)
    _add_requested_note_column(con)
    _add_finished_at_column(con)
    _add_tick_reason_column(con)
    _add_workspace_cwd_column(con)
    _add_todo_cwd_column(con)
    _add_todo_priority_column(con)
    _add_todo_parent_column(con)
    _add_manager_task_columns(con)
    _add_gtasks_columns(con)
    _rename_paused_status(con)
    _drop_session_workspace_column(con)
    _drop_subtasks_table(con)
    _migrate_parent_edges(con)
    _seed_categories(con)
    return con


@contextmanager
def transaction(con):
    """실패 시 롤백. 짧게 유지"""
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise


def meta_get(con, key):
    """내부 플래그. 없으면 None"""
    row = con.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row["value"] if row else None


def meta_set(con, key, value=None):
    """내부 플래그. 값을 안 주면 기록 시각을 값으로 쓴다 (플래그 용도)"""
    con.execute(
        "INSERT INTO meta(key, value) VALUES(?,?)"
        " ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value if value is not None else now()),
    )
    con.commit()


def _seed_categories(con):
    """최초 1회만 삽입. 사용자가 지운 카테고리가 되살아나면 안 되므로 meta 플래그로 판단"""
    if meta_get(con, SEEDED_FLAG):
        return
    stamp = now()
    for order, name in enumerate(SEED_CATEGORIES, start=1):
        con.execute(
            "INSERT INTO categories(name, sort_order, color, created_at)"
            " VALUES(?,?,?,?)",
            (name, order, palette_color(order), stamp),
        )
    meta_set(con, SEEDED_FLAG, stamp)


def _rename_paused_status(con):
    """워크스페이스의 보류 상태를 paused 에서 inactive 로 바꾼 자국.

    화면이 상태 값을 그대로 찍으므로 값 자체가 사용자에게 보이는 문구다.
    active 의 반대말이라는 것이 paused 로는 읽히지 않았다
    """
    con.execute("UPDATE workspaces SET status='inactive' WHERE status='paused'")
    con.commit()


def _drop_session_workspace_column(con):
    """세션의 워크스페이스 소속을 없애고 할일 연결에서 파생하도록 바꾼 자국.

    소속이 세션과 할일 두 군데 있어 서로를 모르는 것이 문제였다 — 세션을 워크스페이스로
    분류해도 보드는 todos.workspace_id 로만 그리므로 아무것도 나타나지 않았다.
    카테고리는 분류 때 워크스페이스에서 파생돼 이미 들어가 있으므로 잃는 정보가 없다
    """
    columns = {row["name"] for row in con.execute("PRAGMA table_info(sessions)")}
    if "workspace_id" in columns:
        con.execute("ALTER TABLE sessions DROP COLUMN workspace_id")
        con.commit()


def _drop_subtasks_table(con):
    """하위할일을 걷어낸 자국. 한 할일을 더 쪼개 관리하는 일이 실제로 없었고,
    구글 태스크에는 대응하는 개념이 없어 내보낼 수도 없었다. 남아 있던 행은 함께 사라진다"""
    con.execute("DROP TABLE IF EXISTS subtasks")
    con.commit()


def _add_precondition_columns(con):
    """착수 가능 조건 컬럼을 뒤늦게 붙임. 이미 쓰던 DB 도 그냥 열리게"""
    columns = {row["name"] for row in con.execute("PRAGMA table_info(todos)")}
    if "precondition" not in columns:
        con.execute("ALTER TABLE todos ADD COLUMN precondition TEXT")
    con.commit()


def _add_autorun_order_column(con):
    """자율 수행 후보 목록에서 사람이 끌어 정한 순서.

    todos.sort_order 로는 담을 수 없다 — 후보는 여러 워크스페이스에 걸쳐 있고
    보드 순서는 워크스페이스가 먼저이므로, 다른 워크스페이스 할일을 위로 끌어올린
    결과를 그 열로는 표현할 수 없다. NULL 은 '사람이 안 정함' 이고 기존 순위를 따른다
    """
    columns = {row["name"] for row in con.execute("PRAGMA table_info(todos)")}
    if "autorun_order" not in columns:
        con.execute("ALTER TABLE todos ADD COLUMN autorun_order INTEGER")
    con.commit()


def _add_usage_account_column(con):
    """한도 샘플에 계정 uuid·플랜을 뒤늦게 붙임

    이 열을 받기 전에 쌓인 행은 NULL 로 남는다 — 어느 계정이었는지 되짚을 방법이 없다.
    주차를 트랙으로 묶는 쪽에서 초기화 시각으로 이어 붙인다.

    플랜은 계정마다 다르고 설정 파일에는 지금 로그인한 계정 것만 있다. 계정을 번갈아
    쓰는 동안 여기 쌓이면서 트랙별 플랜이 채워진다
    """
    columns = {row["name"] for row in con.execute("PRAGMA table_info(usage_samples)")}
    for column in ("account_uuid", "account_plan"):
        if column not in columns:
            con.execute(f"ALTER TABLE usage_samples ADD COLUMN {column} TEXT")
    con.commit()


def _add_gtasks_columns(con):
    """구글 태스크 연결 열을 뒤늦게 붙임. 연동을 안 쓰면 계속 NULL 로 남는다

    구글 목록 하나가 카테고리 하나, 그 안의 최상위 태스크가 워크스페이스,
    최상위에 딸린 하위 태스크가 그 워크스페이스의 할일이다 (구글은 1단계만 중첩된다)
    """
    pairs = (
        ("categories", "google_list_id"),
        ("workspaces", "google_task_id"),
        ("todos", "google_task_id"),
    )
    for table, column in pairs:
        columns = {row["name"] for row in con.execute(f"PRAGMA table_info({table})")}
        if column not in columns:
            con.execute(f"ALTER TABLE {table} ADD COLUMN {column} TEXT")
    # 카테고리별 연동 여부. 기본 0 — 목록을 맞추는 것과 할일을 주고받는 것은 다른 결정이다.
    # 켜진 채로 시작하면 첫 동기화가 전 카테고리의 할일을 한꺼번에 폰으로 올린다
    columns = {row["name"] for row in con.execute("PRAGMA table_info(categories)")}
    if "gtasks_enabled" not in columns:
        con.execute(
            "ALTER TABLE categories ADD COLUMN gtasks_enabled INTEGER NOT NULL DEFAULT 0"
        )
    con.commit()


def _add_requested_note_column(con):
    """요청(판단 보류) 사유 컬럼을 뒤늦게 붙임. 이미 쓰던 DB 도 그냥 열리게"""
    columns = {row["name"] for row in con.execute("PRAGMA table_info(autorun_runs)")}
    if "requested_note" not in columns:
        con.execute("ALTER TABLE autorun_runs ADD COLUMN requested_note TEXT")
    con.commit()


def _add_finished_at_column(con):
    """자율 세션이 스스로 '다 끝냄'을 남기는 컬럼을 뒤늦게 붙임.

    todo.status 로 성공 여부를 재구성하지 않으려고 만든 별도 신호다 — 이 세션이 직접
    보고한 것만 review 로 본다(mark_finished/outcome_for_close 참고)
    """
    columns = {row["name"] for row in con.execute("PRAGMA table_info(autorun_runs)")}
    if "finished_at" not in columns:
        con.execute("ALTER TABLE autorun_runs ADD COLUMN finished_at TEXT")
    con.commit()


def _add_tick_reason_column(con):
    """마지막 tick 의 판정 사유를 뒤늦게 붙임. 이 열을 받기 전 상태는 NULL 로 남는다"""
    columns = {row["name"] for row in con.execute("PRAGMA table_info(autorun_state)")}
    if "last_tick_reason" not in columns:
        con.execute("ALTER TABLE autorun_state ADD COLUMN last_tick_reason TEXT")
    con.commit()


def _add_workspace_cwd_column(con):
    """사람이 지정한 작업 위치 컬럼을 뒤늦게 붙임.

    세션 이력으로 추론하는 것(autorun.target_cwd)만으로는 그 워크스페이스에서 아직
    저장소에서 일해 본 적이 없으면 위치가 영영 안 잡힌다 — 사람이 한 번 지정하면
    그 뒤로는 물어볼 필요가 없게 여기 남긴다
    """
    columns = {row["name"] for row in con.execute("PRAGMA table_info(workspaces)")}
    if "cwd" not in columns:
        con.execute("ALTER TABLE workspaces ADD COLUMN cwd TEXT")
    con.commit()


def _add_todo_cwd_column(con):
    """워크스페이스가 없는 할일의 작업 위치.

    위치는 워크스페이스 단위 속성(workspaces.cwd)이지만, 소속 없는 할일은 적어 둘
    워크스페이스가 없어 자율 수행 후보의 "작업 위치 미정" 을 영영 풀 수 없었다 —
    그 할일에만 직접 남긴다
    """
    columns = {row["name"] for row in con.execute("PRAGMA table_info(todos)")}
    if "cwd" not in columns:
        con.execute("ALTER TABLE todos ADD COLUMN cwd TEXT")
    con.commit()


def _add_todo_priority_column(con):
    """할일 우선순위 숫자. 클수록 높고, NULL 은 '정하지 않음'.

    보드 순서(sort_order)는 한 워크스페이스 안의 줄 세우기라 워크스페이스끼리 견줄 수 없다 —
    워크스페이스를 열린 할일의 최고 우선순위로 세우려면 워크스페이스를 넘어 비교되는 값이 필요하다
    """
    columns = {row["name"] for row in con.execute("PRAGMA table_info(todos)")}
    if "priority" not in columns:
        con.execute("ALTER TABLE todos ADD COLUMN priority INTEGER")
    con.commit()


def _add_todo_parent_column(con):
    """할일 트리의 상위 할일. NULL 이면 워크스페이스 바로 아래다.

    워크스페이스 하나가 트리 하나(루트)이고, 깊이는 이 자기 참조로 제한 없이 내려간다.
    기존 행은 그대로 NULL 이라 옮길 데이터가 없다 — 보드·세션 연결·구글 태스크는
    지금처럼 workspace_id 만 보고 돌아간다. 같은 워크스페이스·순환 금지는
    app/repositories/todos.py 가 저장 전에 막는다
    """
    columns = {row["name"] for row in con.execute("PRAGMA table_info(todos)")}
    if "parent_id" not in columns:
        con.execute("ALTER TABLE todos ADD COLUMN parent_id INTEGER REFERENCES todos(id)")
    con.commit()


PARENT_EDGES_FLAG = "parent_edges_migrated"


def _migrate_parent_edges(con):
    """todos.parent_id 를 상위 연결(edges)로 한 번 옮긴다. 열은 지우지 않는다 — 이 코드를 되돌려도
    옛 트리가 그대로 열리게. 그 뒤로는 parent_id 를 바꾸는 쪽(todos 저장소)이 연결을 같이 맞춘다"""
    if meta_get(con, PARENT_EDGES_FLAG):
        return
    columns = {row["name"] for row in con.execute("PRAGMA table_info(todos)")}
    if "parent_id" not in columns:
        return
    stamp = now()
    with transaction(con):
        con.execute(
            "INSERT OR IGNORE INTO edges(src_kind, src_id, dst_kind, dst_id, relation, basis,"
            " evidence, state, created_by, created_at, updated_at)"
            " SELECT 'todo', CAST(parent_id AS TEXT), 'todo', CAST(id AS TEXT), 'parent',"
            " 'background', '기존 상위 할일(parent_id)에서 옮김', 'confirmed', 'parent_id', ?, ?"
            " FROM todos WHERE parent_id IS NOT NULL",
            (stamp, stamp),
        )
    meta_set(con, PARENT_EDGES_FLAG, stamp)


def _add_category_style_columns(con):
    """색 컬럼을 뒤늦게 붙이고 빈 값을 팔레트 색으로 채움"""
    columns = {row["name"] for row in con.execute("PRAGMA table_info(categories)")}
    if "color" not in columns:
        con.execute("ALTER TABLE categories ADD COLUMN color TEXT")
    rows = con.execute(
        "SELECT id, sort_order FROM categories WHERE color IS NULL OR color = ''"
    ).fetchall()
    for row in rows:
        con.execute(
            "UPDATE categories SET color=? WHERE id=?",
            (palette_color(row["sort_order"]), row["id"]),
        )
    con.commit()


def _add_manager_columns(con):
    """매니저가 읽는 세션 대기 상태와 마지막 답변 요약을 뒤늦게 붙임"""
    columns = {row["name"] for row in con.execute("PRAGMA table_info(sessions)")}
    if "waiting" not in columns:
        con.execute("ALTER TABLE sessions ADD COLUMN waiting TEXT")
    if "last_reply" not in columns:
        con.execute("ALTER TABLE sessions ADD COLUMN last_reply TEXT")
    con.commit()


# 매니저 할일(사용자 결정·직접 할 일)을 이 todos 하나로 합친다(사용자 지시 11-18). 매니저 쪽 칸은 mgr_ 를 붙여 두고
# 매니저가 쓰던 이름 그대로 보이는 뷰(manager_tasks)를 둔다 — 매니저 코드는 연결마다 이 뷰를 TEMP VIEW tasks 로
# 덮어 기존 SQL 을 그대로 쓴다. mgr_kind 가 있는 행만 매니저 할일이다(대시보드 일감 중 사용자 결정·조치를 기다리는 것).
# 상태는 둘이다: status(todo·doing·done)는 일의 진행, mgr_status(open·confirm·done·invalid)는 사용자 답의 상태 —
# 결정에 답했다고 일이 끝난 것이 아니라서 섞지 않는다. 매니저가 만든 행(origin=manager)만 답이 끝나면 일도 끝난다
MANAGER_TASK_PLAIN = (
    "kind", "detail", "next_step", "source", "source_ref", "session_id", "official", "reason", "answer",
    "answered_at", "delivered_at", "notified_at", "plan", "plan_status", "plan_at", "open_target", "due_at",
    "due_unsure", "snooze_until", "hold_until", "hold_session", "handoff", "remind_at", "validated_at", "blocked",
    "options", "recommend", "answer_choice", "answer_feedback", "answer_via", "delivery", "delivery_at",
    "after_ids", "steps", "await_screen", "await_until", "await_result",
)
# 매니저 이름 → todos 칸. title·priority 는 대시보드 칸과 나눠 쓴다(아래 뷰 정의)
MANAGER_TASK_RENAMED = {"status": "mgr_status", "created_at": "mgr_created_at", "updated_at": "mgr_updated_at"}
MANAGER_ORIGIN = "manager"  # 매니저가 만든 행 — 대시보드 일감과 합쳐진 행은 origin 이 NULL(대시보드)이다
MANAGER_DEFAULT_PRIORITY = 2
UNIFIED_FLAG = "unified_todos"  # 이관(매니저 tasks → todos)이 끝났다 — 매니저가 이 표시를 보고 통합 테이블로 바꾼다


def manager_task_columns():
    """뷰 manager_tasks 의 칸 이름 → todos 칸 (title·priority 제외)"""
    columns = {name: f"mgr_{name}" for name in MANAGER_TASK_PLAIN}
    columns.update(MANAGER_TASK_RENAMED)
    return columns


def manager_tasks_view_sql():
    mapped = ", ".join(f"{todo_col} AS {name}" for name, todo_col in manager_task_columns().items())
    return (
        "CREATE VIEW manager_tasks AS SELECT id, COALESCE(mgr_title, title) AS title, "
        f"COALESCE(priority, {MANAGER_DEFAULT_PRIORITY}) AS priority, {mapped}, "
        "id AS todo_id, status AS todo_status, origin, legacy_task_id, role, parent_id "
        "FROM todos WHERE mgr_kind IS NOT NULL"
    )


# 할일과 단계(사용자 결정 11-18): 할일은 끝나면 결과가 하나 나오는 일이다. 그 과정의 파생 요청(컬럼 추가·셀 수정·
# 되돌리기·확인 필요 해소 등)과 결정·확인 질문은 새 할일이 아니라 그 할일의 단계로 쌓는다. 단계는 todos 행이고
# role='step' 이며 상위 연결(edges parent, src=할일 → dst=단계)과 parent_id 로 그 할일 아래에 붙는다. 순서는 sort_order.
# 결정·확인은 그 단계 행의 mgr_* 칸에 둔다 — 선택지·버튼·답 흐름이 단계 단위로 그대로 돈다.
# 새 할일로 나누는 것은 결과물이 다를 때뿐이다. role 이 NULL 이면 할일이다.
# 이 단계가 할일 상세의 '진행 단계'(끝난 단계·멈춘 단계·넘어가는 조건, 그 아래 피드백)다 — 따로 두지 않는다.
# 단계 행: title=단계 이름, status todo·doing(멈춘·진행 중 단계)·done, step_by=누가(세션 이름·사용자),
# completed_at=언제 끝났나, step_result=결과 한 줄, step_unblock=사용자가 무엇을 하면 넘어가는지
ROLE_STEP = "step"
STEP_COLUMNS = ("step_by", "step_result", "step_unblock")


def _add_manager_task_columns(con):
    """매니저 할일 칸(mgr_*)·출처(origin)·옛 매니저 id(legacy_task_id)·단계 표시(role)와 뷰 manager_tasks.
    mgr_title 은 대시보드 일감과 합쳐진 행에서 매니저가 물은 제목이다(일감 제목 title 은 그대로 둔다)"""
    columns = {row["name"] for row in con.execute("PRAGMA table_info(todos)")}
    wanted = [*manager_task_columns().values(), "mgr_title", "origin", "legacy_task_id", "role", *STEP_COLUMNS]
    for name in wanted:
        if name not in columns:
            kind = "INTEGER" if name == "legacy_task_id" else "TEXT"
            con.execute(f"ALTER TABLE todos ADD COLUMN {name} {kind}")
    con.execute("CREATE INDEX IF NOT EXISTS todos_mgr_status ON todos(mgr_status)")
    con.execute("CREATE INDEX IF NOT EXISTS todos_mgr_session ON todos(mgr_session_id)")
    view = con.execute("SELECT sql FROM sqlite_master WHERE type='view' AND name='manager_tasks'").fetchone()
    if view is None or view["sql"] != manager_tasks_view_sql():
        con.execute("DROP VIEW IF EXISTS manager_tasks")
        con.execute(manager_tasks_view_sql())
    con.commit()
