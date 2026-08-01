"""sqlite 연결과 스키마. 다른 모듈은 connect() 만 씀"""
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from app.constants import (
    BUSY_TIMEOUT_MS,
    CATEGORY_PALETTE,
    DB_PATH_ENV,
    DEFAULT_DB_PATH,
    SEED_CATEGORIES,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS categories(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    sort_order INTEGER NOT NULL,
    color TEXT,
    created_at TEXT NOT NULL
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
CREATE TABLE IF NOT EXISTS subtasks(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    todo_id INTEGER NOT NULL REFERENCES todos(id),
    title TEXT NOT NULL,
    precondition TEXT,
    status TEXT NOT NULL DEFAULT 'todo',
    sort_order INTEGER NOT NULL,
    created_at TEXT NOT NULL
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
    workspace_id INTEGER REFERENCES workspaces(id),
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
"""

SEEDED_FLAG = "categories_seeded"


def now():
    """ISO8601 UTC 초 단위"""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def palette_color(sort_order):
    """카테고리 기본 색. 팔레트를 다 쓰면 처음으로 돌아감"""
    return CATEGORY_PALETTE[(sort_order - 1) % len(CATEGORY_PALETTE)]


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


def _add_precondition_columns(con):
    """착수 가능 조건 컬럼을 뒤늦게 붙임. 이미 쓰던 DB 도 그냥 열리게"""
    for table in ("todos", "subtasks"):
        columns = {row["name"] for row in con.execute(f"PRAGMA table_info({table})")}
        if "precondition" not in columns:
            con.execute(f"ALTER TABLE {table} ADD COLUMN precondition TEXT")
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
