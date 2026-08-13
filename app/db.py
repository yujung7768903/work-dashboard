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
    _add_precondition_columns(con)
    _add_usage_account_column(con)
    _add_requested_note_column(con)
    _add_finished_at_column(con)
    _add_tick_reason_column(con)
    _drop_session_workspace_column(con)
    _drop_subtasks_table(con)
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
