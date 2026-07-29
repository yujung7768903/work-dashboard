# 작업 대시보드 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 카테고리 > 워크스페이스 > 할일 > 하위할일 4계층 작업 관리 대시보드를 로컬 웹 + CLI 두 진입점으로 만든다.

**Architecture:** 진입점(`dash.py` CLI, `server.py` HTTP) → service(`board`, `planning`) → repository(엔티티별) → `db.py` 3계층. 두 진입점이 같은 도메인 계층을 호출하므로 로직이 두 벌 생기지 않는다. 프론트엔드는 번들러 없이 브라우저 네이티브 ES 모듈.

**Tech Stack:** Python 3.12 표준 라이브러리만 (`sqlite3`, `http.server`, `argparse`, `unittest`). 프론트엔드는 순수 HTML/CSS/ES 모듈. 외부 의존성 0.

## Global Constraints

- 외부 의존성 0. `pip install` 대상 패키지를 추가하지 않는다. 프론트엔드 빌드 도구도 없다.
- DB 경로: 환경변수 `WORK_DASHBOARD_DB`, 없으면 `~/.claude/work-dashboard/dash.db`. 코드와 분리한다.
- 날짜·시각은 전부 ISO8601 UTC 문자열 (`datetime.now(timezone.utc).isoformat(timespec="seconds")`).
- 진입점은 도메인 로직을 갖지 않는다. 파싱·위임·출력만 한다.
- repository는 한 엔티티의 저장·조회를 담당하고, 엔티티 간 정합성 규칙도 repository 안에서 지킨다.
- service는 실제 로직이 있는 곳에만 둔다. 단순 CRUD는 진입점이 repository를 직접 부른다.
- 예외는 `app/errors.py`의 도메인 타입으로 던진다. HTTP는 타입만 보고 상태 코드를 정한다: `NotFound`→404, `Conflict`→409, `Validation`→400.
- 파일이 300줄을 넘으면 책임이 섞였다는 신호로 보고 나눌 자리를 찾는다.
- 주석은 결정 배경이 아니라 역할·특이사항만. 명사형 또는 음슴체, 한 문장, 마침표 생략 가능.
- 매직넘버 금지. 상수로 뺀다.
- 상수 값 (스펙에서 그대로 옮김):
  ```python
  DEFAULT_HOST = "127.0.0.1"
  DEFAULT_PORT = 9080
  BUSY_TIMEOUT_MS = 5000
  UNASSIGNED_LABEL = "미분류"
  SEED_CATEGORIES = ("개발", "운영", "장애 대응", "개발환경 개선", "스킬 개발", "프로세스 개선")
  TODO_STATUSES = ("todo", "doing", "done")
  WORKSPACE_STATUSES = ("active", "paused", "done")
  ALLOWED_STATIC_SUFFIXES = (".html", ".css", ".js")
  ```
- 테스트는 `python3 -m tests` 한 방으로 전부 돈다. 프레임워크 없이 표준 `unittest`.
- 각 테스트는 임시 DB를 새로 만들어 서로 간섭하지 않는다.

## File Structure

| 파일 | 책임 |
|------|------|
| `app/constants.py` | 위 상수 모음. 다른 모듈이 여기서만 가져간다 |
| `app/db.py` | 연결, WAL·busy_timeout, 스키마 초기화, 시드, 트랜잭션 헬퍼 |
| `app/errors.py` | `NotFound` / `Conflict` / `Validation` 도메인 예외 |
| `app/ordering.py` | `sort_order` 다음값 계산과 1..N 재부여 |
| `app/repositories/categories.py` | 카테고리 CRUD, 비어 있을 때만 삭제 |
| `app/repositories/workspaces.py` | 워크스페이스 CRUD, 삭제 시 할일 강등, 카테고리 변경 시 할일 동기화 |
| `app/repositories/todos.py` | 할일 CRUD, 워크스페이스 배정 시 카테고리 동기화, `completed_at` 관리, 삭제 시 하위할일 cascade |
| `app/repositories/subtasks.py` | 하위할일 CRUD |
| `app/services/board.py` | 그룹핑 트리 조립 (워크스페이스 기준 / 카테고리 기준) |
| `app/services/planning.py` | `next_todo`, `done_on` |
| `dash.py` | CLI 진입점 |
| `server.py` | HTTP 진입점, 정적 파일 서빙 |
| `static/index.html` | 마크업 |
| `static/css/app.css` | 스타일 |
| `static/js/api.js` | fetch 래퍼 전담 |
| `static/js/board.js` | 보드 렌더, 빠른 추가, 상태 토글, 오늘 완료 |
| `static/js/dnd.js` | 드래그 재정렬·이동 |
| `static/js/workspace.js` | 워크스페이스 상세 |
| `static/js/categories.js` | 카테고리 관리 |
| `static/js/main.js` | 탭 전환, 초기 로드 |
| `tests/__main__.py` | 테스트 러너 |
| `tests/support.py` | 임시 DB 픽스처 |
| `tests/test_repositories.py` | repository 계층 |
| `tests/test_services.py` | service 계층 |
| `tests/test_cli.py` | CLI 인자 파싱·종료 코드 |
| `tests/test_static.py` | 정적 파일 경로 방어, 예외→상태코드 매핑 |

---

### Task 1: 기반 — 상수, 예외, DB 스키마, 테스트 러너

**Files:**
- Create: `app/__init__.py`, `app/constants.py`, `app/errors.py`, `app/db.py`
- Create: `tests/__init__.py`, `tests/__main__.py`, `tests/support.py`, `tests/test_repositories.py`

**Interfaces:**
- Consumes: 없음 (첫 태스크)
- Produces:
  - `app.db.connect(path: str | None = None) -> sqlite3.Connection` — 스키마 초기화와 시드까지 끝낸 연결
  - `app.db.now() -> str`, `app.db.transaction(con)` 컨텍스트 매니저
  - `app.errors.NotFound`, `app.errors.Conflict`, `app.errors.Validation` (모두 `DomainError` 상속)
  - `app.constants` 의 상수 전부
  - `tests.support.temp_db() -> sqlite3.Connection` — 임시 파일 DB 연결

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/support.py`:
```python
"""테스트용 임시 DB 픽스처."""
import os
import tempfile

from app.db import connect


def temp_db():
    """호출마다 새 임시 파일 DB에 연결. 경로는 con.temp_path 로 붙여둠"""
    path = os.path.join(tempfile.mkdtemp(), "test.db")
    con = connect(path)
    con.temp_path = path
    return con
```

`tests/test_repositories.py`:
```python
import unittest

from app.constants import SEED_CATEGORIES
from app.db import connect
from tests.support import temp_db


class SchemaTest(unittest.TestCase):
    def test_creates_four_tables(self):
        con = temp_db()
        names = {
            row["name"]
            for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        self.assertTrue({"categories", "workspaces", "todos", "subtasks"} <= names)

    def test_seeds_default_categories(self):
        con = temp_db()
        rows = con.execute("SELECT name FROM categories ORDER BY sort_order").fetchall()
        self.assertEqual([row["name"] for row in rows], list(SEED_CATEGORIES))

    def test_seed_runs_only_once(self):
        con = temp_db()
        con.execute("DELETE FROM categories WHERE name=?", (SEED_CATEGORIES[0],))
        con.commit()
        reopened = connect(con.temp_path)
        count = reopened.execute("SELECT COUNT(*) AS n FROM categories").fetchone()["n"]
        self.assertEqual(count, len(SEED_CATEGORIES) - 1)

    def test_wal_mode_enabled(self):
        con = temp_db()
        mode = con.execute("PRAGMA journal_mode").fetchone()[0]
        self.assertEqual(mode.lower(), "wal")
```

`tests/__main__.py`:
```python
"""python3 -m tests 로 전체 테스트 실행."""
import sys
import unittest

if __name__ == "__main__":
    suite = unittest.defaultTestLoader.discover("tests", pattern="test_*.py")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
```

`tests/__init__.py`: 빈 파일.

- [ ] **Step 2: 실패 확인**

Run: `python3 -m tests`
Expected: FAIL — `ModuleNotFoundError: No module named 'app'`

- [ ] **Step 3: 최소 구현**

`app/__init__.py`: 빈 파일.

`app/constants.py`:
```python
"""프로젝트 전역 상수. 매직넘버는 전부 여기로 모음"""
import os

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9080
BUSY_TIMEOUT_MS = 5000

DEFAULT_DB_PATH = os.path.expanduser("~/.claude/work-dashboard/dash.db")
DB_PATH_ENV = "WORK_DASHBOARD_DB"

UNASSIGNED_LABEL = "미분류"
SEED_CATEGORIES = ("개발", "운영", "장애 대응", "개발환경 개선", "스킬 개발", "프로세스 개선")

TODO_STATUSES = ("todo", "doing", "done")
WORKSPACE_STATUSES = ("active", "paused", "done")
STATUS_TODO, STATUS_DOING, STATUS_DONE = TODO_STATUSES
WORKSPACE_ACTIVE = WORKSPACE_STATUSES[0]

ALLOWED_STATIC_SUFFIXES = (".html", ".css", ".js")
FIRST_SORT_ORDER = 1
```

`app/errors.py`:
```python
"""도메인 예외. HTTP 계층이 타입만 보고 상태 코드를 정함"""


class DomainError(Exception):
    """모든 도메인 예외의 부모"""


class NotFound(DomainError):
    """대상 리소스 없음 → 404"""


class Conflict(DomainError):
    """현재 상태와 충돌하는 요청 → 409"""


class Validation(DomainError):
    """입력값이 규칙 위반 → 400"""
```

`app/db.py`:
```python
"""sqlite 연결과 스키마. 다른 모듈은 connect() 만 씀"""
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from app.constants import BUSY_TIMEOUT_MS, DB_PATH_ENV, DEFAULT_DB_PATH, SEED_CATEGORIES

SCHEMA = """
CREATE TABLE IF NOT EXISTS categories(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    sort_order INTEGER NOT NULL,
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
    status TEXT NOT NULL DEFAULT 'todo',
    sort_order INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS meta(
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

SEEDED_FLAG = "categories_seeded"


def now():
    """ISO8601 UTC 초 단위"""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


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


def _seed_categories(con):
    """최초 1회만 삽입. 사용자가 지운 카테고리가 되살아나면 안 되므로 meta 플래그로 판단"""
    done = con.execute("SELECT value FROM meta WHERE key=?", (SEEDED_FLAG,)).fetchone()
    if done:
        return
    stamp = now()
    for order, name in enumerate(SEED_CATEGORIES, start=1):
        con.execute(
            "INSERT INTO categories(name, sort_order, created_at) VALUES(?,?,?)",
            (name, order, stamp),
        )
    con.execute("INSERT INTO meta(key, value) VALUES(?,?)", (SEEDED_FLAG, stamp))
    con.commit()
```

- [ ] **Step 4: 통과 확인**

Run: `python3 -m tests`
Expected: PASS (4 tests)

- [ ] **Step 5: 커밋**

```bash
git add app tests
git commit -m "feat: DB 스키마·상수·도메인 예외와 테스트 러너 추가"
```

---

### Task 2: ordering.py — sort_order 계산과 재부여

**Files:**
- Create: `app/ordering.py`
- Modify: `tests/test_repositories.py` (OrderingTest 추가)

**Interfaces:**
- Consumes: `app.db.transaction`, `app.errors.Validation`, `app.constants.FIRST_SORT_ORDER`
- Produces:
  - `next_order(con, table: str, where: str, params: tuple) -> int` — 해당 범위의 마지막+1
  - `reorder(con, table: str, ids: list[int], where: str, params: tuple) -> None` — 주어진 순서대로 1..N 재부여. 범위 id 집합과 다르면 `Validation`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_repositories.py`에 추가:
```python
from app import ordering
from app.errors import Validation


class OrderingTest(unittest.TestCase):
    def setUp(self):
        self.con = temp_db()
        self.con.execute("DELETE FROM categories")
        for order, name in enumerate(["a", "b", "c"], start=1):
            self.con.execute(
                "INSERT INTO categories(name, sort_order, created_at) VALUES(?,?,?)",
                (name, order, "2026-07-29T00:00:00+00:00"),
            )
        self.con.commit()

    def _orders(self):
        rows = self.con.execute(
            "SELECT name, sort_order FROM categories ORDER BY sort_order"
        ).fetchall()
        return [(row["name"], row["sort_order"]) for row in rows]

    def test_next_order_is_last_plus_one(self):
        self.assertEqual(ordering.next_order(self.con, "categories", "1=1", ()), 4)

    def test_next_order_on_empty_range_is_first(self):
        self.con.execute("DELETE FROM categories")
        self.con.commit()
        self.assertEqual(ordering.next_order(self.con, "categories", "1=1", ()), 1)

    def test_reorder_reassigns_one_to_n(self):
        ids = [
            row["id"]
            for row in self.con.execute("SELECT id FROM categories ORDER BY name DESC")
        ]
        ordering.reorder(self.con, "categories", ids, "1=1", ())
        self.assertEqual(self._orders(), [("c", 1), ("b", 2), ("a", 3)])

    def test_reorder_rejects_foreign_id(self):
        with self.assertRaises(Validation):
            ordering.reorder(self.con, "categories", [999], "1=1", ())

    def test_reorder_rejects_partial_id_set(self):
        one = self.con.execute("SELECT id FROM categories LIMIT 1").fetchone()["id"]
        with self.assertRaises(Validation):
            ordering.reorder(self.con, "categories", [one], "1=1", ())
```

- [ ] **Step 2: 실패 확인**

Run: `python3 -m tests`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.ordering'`

- [ ] **Step 3: 최소 구현**

`app/ordering.py`:
```python
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
```

- [ ] **Step 4: 통과 확인**

Run: `python3 -m tests`
Expected: PASS (9 tests)

- [ ] **Step 5: 커밋**

```bash
git add app/ordering.py tests/test_repositories.py
git commit -m "feat: sort_order 계산·재부여 공통 모듈 추가"
```

---

### Task 3: categories repository

**Files:**
- Create: `app/repositories/__init__.py`, `app/repositories/categories.py`
- Modify: `tests/test_repositories.py` (CategoryRepoTest 추가)

**Interfaces:**
- Consumes: `app.ordering`, `app.db`, `app.errors`
- Produces:
  - `create(con, name: str) -> dict`
  - `list_all(con) -> list[dict]` — sort_order 순
  - `get(con, category_id: int) -> dict` — 없으면 `NotFound`
  - `get_by_name(con, name: str) -> dict` — 없으면 `NotFound`
  - `rename(con, category_id: int, name: str) -> dict`
  - `delete(con, category_id: int) -> None` — 워크스페이스나 할일이 남아 있으면 `Conflict`
  - `reorder(con, ids: list[int]) -> None`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
from app.errors import Conflict, NotFound
from app.repositories import categories as category_repo


class CategoryRepoTest(unittest.TestCase):
    def setUp(self):
        self.con = temp_db()

    def test_create_appends_to_end(self):
        created = category_repo.create(self.con, "신규")
        self.assertEqual(created["name"], "신규")
        self.assertEqual(created["sort_order"], len(SEED_CATEGORIES) + 1)

    def test_create_rejects_duplicate_name(self):
        with self.assertRaises(Conflict):
            category_repo.create(self.con, SEED_CATEGORIES[0])

    def test_create_rejects_blank_name(self):
        with self.assertRaises(Validation):
            category_repo.create(self.con, "   ")

    def test_get_missing_raises_not_found(self):
        with self.assertRaises(NotFound):
            category_repo.get(self.con, 9999)

    def test_get_by_name_finds_seeded(self):
        self.assertEqual(category_repo.get_by_name(self.con, "개발")["name"], "개발")

    def test_rename_changes_name(self):
        target = category_repo.get_by_name(self.con, "운영")
        renamed = category_repo.rename(self.con, target["id"], "운영업무")
        self.assertEqual(renamed["name"], "운영업무")

    def test_rename_rejects_duplicate(self):
        target = category_repo.get_by_name(self.con, "운영")
        with self.assertRaises(Conflict):
            category_repo.rename(self.con, target["id"], "개발")

    def test_delete_empty_category_succeeds(self):
        target = category_repo.get_by_name(self.con, "운영")
        category_repo.delete(self.con, target["id"])
        with self.assertRaises(NotFound):
            category_repo.get(self.con, target["id"])

    def test_delete_rejects_non_empty_category(self):
        target = category_repo.get_by_name(self.con, "개발")
        self.con.execute(
            "INSERT INTO todos(category_id, title, status, sort_order, created_at, updated_at)"
            " VALUES(?,?,?,?,?,?)",
            (target["id"], "남은 할일", "todo", 1, "t", "t"),
        )
        self.con.commit()
        with self.assertRaises(Conflict):
            category_repo.delete(self.con, target["id"])
```

- [ ] **Step 2: 실패 확인**

Run: `python3 -m tests`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.repositories'`

- [ ] **Step 3: 최소 구현**

`app/repositories/__init__.py`: 빈 파일.

`app/repositories/categories.py`:
```python
"""카테고리 저장·조회. 비어 있을 때만 삭제 허용"""
from app import ordering
from app.db import now, transaction
from app.errors import Conflict, NotFound, Validation

TABLE = "categories"
ALL_SCOPE = ("1=1", ())
OCCUPANT_TABLES = (("workspaces", "워크스페이스"), ("todos", "할일"))


def create(con, name):
    """맨 뒤에 붙임"""
    cleaned = _clean_name(name)
    _reject_duplicate(con, cleaned)
    order = ordering.next_order(con, TABLE, *ALL_SCOPE)
    with transaction(con):
        cursor = con.execute(
            "INSERT INTO categories(name, sort_order, created_at) VALUES(?,?,?)",
            (cleaned, order, now()),
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
    get(con, category_id)
    cleaned = _clean_name(name)
    _reject_duplicate(con, cleaned, exclude_id=category_id)
    with transaction(con):
        con.execute("UPDATE categories SET name=? WHERE id=?", (cleaned, category_id))
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
```

- [ ] **Step 4: 통과 확인**

Run: `python3 -m tests`
Expected: PASS (18 tests)

- [ ] **Step 5: 커밋**

```bash
git add app/repositories tests/test_repositories.py
git commit -m "feat: 카테고리 repository 추가 (비어 있을 때만 삭제)"
```

---

### Task 4: workspaces repository — CRUD

삭제와 카테고리 변경 동기화는 할일 repository가 필요하므로 Task 7로 분리한다.

**Files:**
- Create: `app/repositories/workspaces.py`
- Modify: `tests/test_repositories.py` (WorkspaceRepoTest 추가)

**Interfaces:**
- Consumes: `app.repositories.categories.get`, `app.ordering`, `app.db`
- Produces:
  - `create(con, category_id, name, **fields) -> dict` — fields: `background`, `purpose`, `goal`, `considerations`, `jira_id`
  - `list_all(con, status=None) -> list[dict]` — sort_order 순
  - `get(con, workspace_id) -> dict`
  - `get_by_jira(con, jira_id) -> dict | None`
  - `update(con, workspace_id, **fields) -> dict` — `category_id` 처리는 Task 7에서 추가
  - `reorder(con, ids) -> None`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
from app.constants import WORKSPACE_ACTIVE
from app.repositories import workspaces as workspace_repo


class WorkspaceRepoTest(unittest.TestCase):
    def setUp(self):
        self.con = temp_db()
        self.dev = category_repo.get_by_name(self.con, "개발")["id"]

    def test_create_defaults_to_active(self):
        created = workspace_repo.create(self.con, self.dev, "KT 동시성")
        self.assertEqual(created["status"], WORKSPACE_ACTIVE)
        self.assertEqual(created["sort_order"], 1)

    def test_create_stores_four_context_fields(self):
        created = workspace_repo.create(
            self.con,
            self.dev,
            "KT 동시성",
            background="엑셀 동시 저장 충돌",
            purpose="서버사이드 차단",
            goal="락 재설계 완료",
            considerations="웹소켓 영향 확인",
        )
        self.assertEqual(created["background"], "엑셀 동시 저장 충돌")
        self.assertEqual(created["considerations"], "웹소켓 영향 확인")

    def test_create_rejects_missing_category(self):
        with self.assertRaises(NotFound):
            workspace_repo.create(self.con, 9999, "이름")

    def test_create_rejects_blank_name(self):
        with self.assertRaises(Validation):
            workspace_repo.create(self.con, self.dev, "  ")

    def test_sort_order_is_global_across_categories(self):
        ops = category_repo.get_by_name(self.con, "운영")["id"]
        first = workspace_repo.create(self.con, self.dev, "첫번째")
        second = workspace_repo.create(self.con, ops, "두번째")
        self.assertEqual([first["sort_order"], second["sort_order"]], [1, 2])

    def test_update_rejects_unknown_status(self):
        created = workspace_repo.create(self.con, self.dev, "KT")
        with self.assertRaises(Validation):
            workspace_repo.update(self.con, created["id"], status="종료됨")

    def test_update_rejects_unknown_field(self):
        created = workspace_repo.create(self.con, self.dev, "KT")
        with self.assertRaises(Validation):
            workspace_repo.update(self.con, created["id"], sort_order=5)

    def test_update_touches_updated_at(self):
        created = workspace_repo.create(self.con, self.dev, "KT")
        stale = "2000-01-01T00:00:00+00:00"
        self.con.execute(
            "UPDATE workspaces SET updated_at=? WHERE id=?", (stale, created["id"])
        )
        self.con.commit()
        updated = workspace_repo.update(self.con, created["id"], goal="새 목표")
        self.assertNotEqual(updated["updated_at"], stale)

    def test_get_by_jira_returns_none_when_absent(self):
        self.assertIsNone(workspace_repo.get_by_jira(self.con, "KT-9999"))

    def test_get_by_jira_is_case_insensitive(self):
        workspace_repo.create(self.con, self.dev, "KT", jira_id="KT-1530")
        self.assertIsNotNone(workspace_repo.get_by_jira(self.con, "kt-1530"))

    def test_list_all_filters_by_status(self):
        active = workspace_repo.create(self.con, self.dev, "진행중")
        paused = workspace_repo.create(self.con, self.dev, "보류")
        workspace_repo.update(self.con, paused["id"], status="paused")
        names = [
            item["name"]
            for item in workspace_repo.list_all(self.con, status=WORKSPACE_ACTIVE)
        ]
        self.assertEqual(names, [active["name"]])
```

- [ ] **Step 2: 실패 확인**

Run: `python3 -m tests`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.repositories.workspaces'`

- [ ] **Step 3: 최소 구현**

`app/repositories/workspaces.py`:
```python
"""워크스페이스 저장·조회. sort_order 는 카테고리를 가로지르는 전역 순위"""
from app import ordering
from app.constants import WORKSPACE_ACTIVE, WORKSPACE_STATUSES
from app.db import now, transaction
from app.errors import NotFound, Validation
from app.repositories import categories as category_repo

TABLE = "workspaces"
ALL_SCOPE = ("1=1", ())
CONTEXT_FIELDS = ("background", "purpose", "goal", "considerations")
OPTIONAL_FIELDS = CONTEXT_FIELDS + ("jira_id",)
EDITABLE_FIELDS = ("name", "status") + OPTIONAL_FIELDS


def create(con, category_id, name, **fields):
    category_repo.get(con, category_id)
    cleaned = _clean_name(name)
    order = ordering.next_order(con, TABLE, *ALL_SCOPE)
    stamp = now()
    columns = ["category_id", "name", "status", "sort_order", "created_at", "updated_at"]
    values = [category_id, cleaned, WORKSPACE_ACTIVE, order, stamp, stamp]
    for key in OPTIONAL_FIELDS:
        columns.append(key)
        values.append(fields.get(key))
    placeholders = ",".join("?" * len(columns))
    with transaction(con):
        cursor = con.execute(
            f"INSERT INTO workspaces({','.join(columns)}) VALUES({placeholders})",
            tuple(values),
        )
    return get(con, cursor.lastrowid)


def list_all(con, status=None):
    sql = "SELECT * FROM workspaces"
    params = ()
    if status:
        _validate_status(status)
        sql += " WHERE status=?"
        params = (status,)
    return [dict(row) for row in con.execute(sql + " ORDER BY sort_order, id", params)]


def get(con, workspace_id):
    row = con.execute("SELECT * FROM workspaces WHERE id=?", (workspace_id,)).fetchone()
    if not row:
        raise NotFound(f"워크스페이스 {workspace_id} 없음")
    return dict(row)


def get_by_jira(con, jira_id):
    """대소문자 무시. 없으면 None — scope-guard 연결점"""
    row = con.execute(
        "SELECT * FROM workspaces WHERE UPPER(jira_id)=UPPER(?)", (jira_id,)
    ).fetchone()
    return dict(row) if row else None


def update(con, workspace_id, **fields):
    get(con, workspace_id)
    assignments = _validated_assignments(fields)
    if not assignments:
        return get(con, workspace_id)
    assignments["updated_at"] = now()
    clause = ",".join(f"{key}=?" for key in assignments)
    with transaction(con):
        con.execute(
            f"UPDATE workspaces SET {clause} WHERE id=?",
            tuple(assignments.values()) + (workspace_id,),
        )
    return get(con, workspace_id)


def reorder(con, ids):
    ordering.reorder(con, TABLE, ids, *ALL_SCOPE)


def _validated_assignments(fields):
    assignments = {}
    for key, value in fields.items():
        if key not in EDITABLE_FIELDS:
            raise Validation(f"수정할 수 없는 필드: {key}")
        if key == "status":
            _validate_status(value)
        if key == "name":
            value = _clean_name(value)
        assignments[key] = value
    return assignments


def _clean_name(name):
    cleaned = (name or "").strip()
    if not cleaned:
        raise Validation("워크스페이스 이름이 비어 있음")
    return cleaned


def _validate_status(status):
    if status not in WORKSPACE_STATUSES:
        raise Validation(f"워크스페이스 상태는 {WORKSPACE_STATUSES} 중 하나여야 함")
```

- [ ] **Step 4: 통과 확인**

Run: `python3 -m tests`
Expected: PASS (29 tests)

- [ ] **Step 5: 커밋**

```bash
git add app/repositories/workspaces.py tests/test_repositories.py
git commit -m "feat: 워크스페이스 repository CRUD 추가"
```

---

### Task 5: todos repository

**Files:**
- Create: `app/repositories/todos.py`
- Modify: `tests/test_repositories.py` (TodoRepoTest 추가)

**Interfaces:**
- Consumes: `app.repositories.categories.get`, `app.repositories.workspaces.get`, `app.ordering`
- Produces:
  - `create(con, title, category_id=None, workspace_id=None, note=None) -> dict`
  - `get(con, todo_id) -> dict`
  - `list_by_workspace(con, workspace_id) -> list[dict]` — `None`이면 미분류
  - `list_by_category(con, category_id) -> list[dict]`
  - `update(con, todo_id, **fields) -> dict` — `title`, `note`, `status`, `workspace_id`
  - `delete(con, todo_id) -> None` — 하위할일 cascade
  - `reorder(con, ids, workspace_id) -> None`
  - `demote_by_workspace(con, workspace_id) -> None`
  - `sync_category(con, workspace_id, category_id) -> None`
  - `list_completed_on(con, date_prefix: str) -> list[dict]`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
from app.constants import STATUS_DOING, STATUS_DONE, STATUS_TODO
from app.repositories import todos as todo_repo


class TodoRepoTest(unittest.TestCase):
    def setUp(self):
        self.con = temp_db()
        self.dev = category_repo.get_by_name(self.con, "개발")["id"]
        self.ops = category_repo.get_by_name(self.con, "운영")["id"]
        self.workspace = workspace_repo.create(self.con, self.dev, "KT 동시성")

    def test_create_requires_category_or_workspace(self):
        with self.assertRaises(Validation):
            todo_repo.create(self.con, "제목만")

    def test_create_with_category_is_unassigned(self):
        created = todo_repo.create(self.con, "문의 회신", category_id=self.ops)
        self.assertIsNone(created["workspace_id"])
        self.assertEqual(created["category_id"], self.ops)

    def test_create_with_workspace_inherits_its_category(self):
        created = todo_repo.create(
            self.con, "락 재설계", workspace_id=self.workspace["id"], category_id=self.ops
        )
        self.assertEqual(created["category_id"], self.dev)

    def test_assigning_workspace_syncs_category(self):
        created = todo_repo.create(self.con, "문의", category_id=self.ops)
        moved = todo_repo.update(self.con, created["id"], workspace_id=self.workspace["id"])
        self.assertEqual(moved["category_id"], self.dev)

    def test_clearing_workspace_keeps_category(self):
        created = todo_repo.create(self.con, "락", workspace_id=self.workspace["id"])
        cleared = todo_repo.update(self.con, created["id"], workspace_id=None)
        self.assertIsNone(cleared["workspace_id"])
        self.assertEqual(cleared["category_id"], self.dev)

    def test_done_stamps_completed_at(self):
        created = todo_repo.create(self.con, "락", workspace_id=self.workspace["id"])
        done = todo_repo.update(self.con, created["id"], status=STATUS_DONE)
        self.assertIsNotNone(done["completed_at"])

    def test_leaving_done_clears_completed_at(self):
        created = todo_repo.create(self.con, "락", workspace_id=self.workspace["id"])
        todo_repo.update(self.con, created["id"], status=STATUS_DONE)
        reopened = todo_repo.update(self.con, created["id"], status=STATUS_DOING)
        self.assertIsNone(reopened["completed_at"])

    def test_update_rejects_unknown_status(self):
        created = todo_repo.create(self.con, "락", workspace_id=self.workspace["id"])
        with self.assertRaises(Validation):
            todo_repo.update(self.con, created["id"], status="보류")

    def test_delete_cascades_subtasks(self):
        created = todo_repo.create(self.con, "락", workspace_id=self.workspace["id"])
        self.con.execute(
            "INSERT INTO subtasks(todo_id, title, status, sort_order, created_at)"
            " VALUES(?,?,?,?,?)",
            (created["id"], "k6 시나리오", STATUS_TODO, 1, "t"),
        )
        self.con.commit()
        todo_repo.delete(self.con, created["id"])
        left = self.con.execute("SELECT COUNT(*) AS n FROM subtasks").fetchone()["n"]
        self.assertEqual(left, 0)

    def test_sort_order_is_per_group(self):
        first = todo_repo.create(self.con, "1", workspace_id=self.workspace["id"])
        second = todo_repo.create(self.con, "2", workspace_id=self.workspace["id"])
        unassigned = todo_repo.create(self.con, "3", category_id=self.ops)
        self.assertEqual(
            [first["sort_order"], second["sort_order"], unassigned["sort_order"]],
            [1, 2, 1],
        )

    def test_demote_by_workspace_moves_to_unassigned(self):
        created = todo_repo.create(self.con, "락", workspace_id=self.workspace["id"])
        todo_repo.demote_by_workspace(self.con, self.workspace["id"])
        demoted = todo_repo.get(self.con, created["id"])
        self.assertIsNone(demoted["workspace_id"])
        self.assertEqual(demoted["category_id"], self.dev)

    def test_sync_category_updates_member_todos(self):
        created = todo_repo.create(self.con, "락", workspace_id=self.workspace["id"])
        todo_repo.sync_category(self.con, self.workspace["id"], self.ops)
        self.assertEqual(todo_repo.get(self.con, created["id"])["category_id"], self.ops)

    def test_list_completed_on_filters_by_date(self):
        created = todo_repo.create(self.con, "락", workspace_id=self.workspace["id"])
        todo_repo.update(self.con, created["id"], status=STATUS_DONE)
        self.con.execute(
            "UPDATE todos SET completed_at=? WHERE id=?",
            ("2026-07-28T10:00:00+00:00", created["id"]),
        )
        self.con.commit()
        self.assertEqual(len(todo_repo.list_completed_on(self.con, "2026-07-28")), 1)
        self.assertEqual(len(todo_repo.list_completed_on(self.con, "2026-07-29")), 0)
```

- [ ] **Step 2: 실패 확인**

Run: `python3 -m tests`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.repositories.todos'`

- [ ] **Step 3: 최소 구현**

`app/repositories/todos.py`:
```python
"""할일 저장·조회. 워크스페이스 배정 시 카테고리 동기화가 여기서 강제됨"""
from app import ordering
from app.constants import STATUS_DONE, STATUS_TODO, TODO_STATUSES
from app.db import now, transaction
from app.errors import NotFound, Validation
from app.repositories import categories as category_repo
from app.repositories import workspaces as workspace_repo

TABLE = "todos"
EDITABLE_FIELDS = ("title", "note", "status", "workspace_id")


def create(con, title, category_id=None, workspace_id=None, note=None):
    """workspace_id 가 있으면 카테고리는 그 워크스페이스에서 가져옴"""
    cleaned = _clean_title(title)
    resolved_category = _resolve_category(con, category_id, workspace_id)
    order = ordering.next_order(con, TABLE, *_group_scope(workspace_id))
    stamp = now()
    with transaction(con):
        cursor = con.execute(
            "INSERT INTO todos(category_id, workspace_id, title, note, status,"
            " sort_order, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?)",
            (resolved_category, workspace_id, cleaned, note, STATUS_TODO, order, stamp, stamp),
        )
    return get(con, cursor.lastrowid)


def get(con, todo_id):
    row = con.execute("SELECT * FROM todos WHERE id=?", (todo_id,)).fetchone()
    if not row:
        raise NotFound(f"할일 {todo_id} 없음")
    return dict(row)


def list_by_workspace(con, workspace_id):
    """workspace_id 가 None 이면 미분류 목록"""
    where, params = _group_scope(workspace_id)
    return [
        dict(row)
        for row in con.execute(
            f"SELECT * FROM todos WHERE {where} ORDER BY sort_order, id", params
        )
    ]


def list_by_category(con, category_id):
    return [
        dict(row)
        for row in con.execute(
            "SELECT * FROM todos WHERE category_id=? ORDER BY sort_order, id",
            (category_id,),
        )
    ]


def update(con, todo_id, **fields):
    current = get(con, todo_id)
    assignments = _validated_assignments(con, current, fields)
    if not assignments:
        return current
    assignments["updated_at"] = now()
    clause = ",".join(f"{key}=?" for key in assignments)
    with transaction(con):
        con.execute(
            f"UPDATE todos SET {clause} WHERE id=?",
            tuple(assignments.values()) + (todo_id,),
        )
    return get(con, todo_id)


def delete(con, todo_id):
    """하위할일까지 cascade. 하위할일은 할일에 종속되어 독립 존재 의미가 없음"""
    get(con, todo_id)
    with transaction(con):
        con.execute("DELETE FROM subtasks WHERE todo_id=?", (todo_id,))
        con.execute("DELETE FROM todos WHERE id=?", (todo_id,))


def reorder(con, ids, workspace_id):
    ordering.reorder(con, TABLE, ids, *_group_scope(workspace_id))


def demote_by_workspace(con, workspace_id):
    """워크스페이스 삭제 시 소속 할일을 미분류로 내림. 카테고리는 유지"""
    members = list_by_workspace(con, workspace_id)
    base = ordering.next_order(con, TABLE, *_group_scope(None))
    stamp = now()
    with transaction(con):
        for offset, todo in enumerate(members):
            con.execute(
                "UPDATE todos SET workspace_id=NULL, sort_order=?, updated_at=? WHERE id=?",
                (base + offset, stamp, todo["id"]),
            )


def sync_category(con, workspace_id, category_id):
    """워크스페이스 카테고리 변경 시 소속 할일 전부 따라가게 함"""
    with transaction(con):
        con.execute(
            "UPDATE todos SET category_id=?, updated_at=? WHERE workspace_id=?",
            (category_id, now(), workspace_id),
        )


def list_completed_on(con, date_prefix):
    """completed_at 날짜 부분이 일치하는 할일. daily-todo 집계용"""
    return [
        dict(row)
        for row in con.execute(
            "SELECT * FROM todos WHERE completed_at LIKE ? ORDER BY completed_at",
            (f"{date_prefix}%",),
        )
    ]


def _validated_assignments(con, current, fields):
    assignments = {}
    for key, value in fields.items():
        if key not in EDITABLE_FIELDS:
            raise Validation(f"수정할 수 없는 필드: {key}")
        assignments[key] = value
    if "title" in assignments:
        assignments["title"] = _clean_title(assignments["title"])
    if "status" in assignments:
        _validate_status(assignments["status"])
        assignments["completed_at"] = (
            now() if assignments["status"] == STATUS_DONE else None
        )
    if "workspace_id" in assignments:
        target = assignments["workspace_id"]
        assignments["category_id"] = _resolve_category(con, current["category_id"], target)
        assignments["sort_order"] = ordering.next_order(con, TABLE, *_group_scope(target))
    return assignments


def _group_scope(workspace_id):
    """미분류는 workspace_id IS NULL 로 묶임"""
    if workspace_id is None:
        return ("workspace_id IS NULL", ())
    return ("workspace_id=?", (workspace_id,))


def _resolve_category(con, category_id, workspace_id):
    """워크스페이스가 있으면 그쪽 카테고리가 이김"""
    if workspace_id is not None:
        return workspace_repo.get(con, workspace_id)["category_id"]
    if category_id is None:
        raise Validation("카테고리나 워크스페이스 중 하나는 필요함")
    category_repo.get(con, category_id)
    return category_id


def _clean_title(title):
    cleaned = (title or "").strip()
    if not cleaned:
        raise Validation("할일 제목이 비어 있음")
    return cleaned


def _validate_status(status):
    if status not in TODO_STATUSES:
        raise Validation(f"할일 상태는 {TODO_STATUSES} 중 하나여야 함")
```

- [ ] **Step 4: 통과 확인**

Run: `python3 -m tests`
Expected: PASS (42 tests)

- [ ] **Step 5: 커밋**

```bash
git add app/repositories/todos.py tests/test_repositories.py
git commit -m "feat: 할일 repository 추가 (카테고리 동기화·completed_at·cascade)"
```

---

### Task 6: subtasks repository

**Files:**
- Create: `app/repositories/subtasks.py`
- Modify: `tests/test_repositories.py` (SubtaskRepoTest 추가)

**Interfaces:**
- Consumes: `app.repositories.todos.get`, `app.ordering`
- Produces:
  - `create(con, todo_id, title) -> dict`
  - `list_by_todo(con, todo_id) -> list[dict]`
  - `get(con, subtask_id) -> dict`
  - `update(con, subtask_id, **fields) -> dict` — `title`, `status`
  - `delete(con, subtask_id) -> None`
  - `reorder(con, ids, todo_id) -> None`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
from app.repositories import subtasks as subtask_repo


class SubtaskRepoTest(unittest.TestCase):
    def setUp(self):
        self.con = temp_db()
        dev = category_repo.get_by_name(self.con, "개발")["id"]
        workspace = workspace_repo.create(self.con, dev, "KT 동시성")
        self.todo = todo_repo.create(self.con, "재현 테스트", workspace_id=workspace["id"])

    def test_create_appends_within_todo(self):
        first = subtask_repo.create(self.con, self.todo["id"], "k6 시나리오")
        second = subtask_repo.create(self.con, self.todo["id"], "결과 정리")
        self.assertEqual([first["sort_order"], second["sort_order"]], [1, 2])

    def test_create_rejects_missing_todo(self):
        with self.assertRaises(NotFound):
            subtask_repo.create(self.con, 9999, "제목")

    def test_create_rejects_blank_title(self):
        with self.assertRaises(Validation):
            subtask_repo.create(self.con, self.todo["id"], "")

    def test_update_status_validated(self):
        created = subtask_repo.create(self.con, self.todo["id"], "k6")
        with self.assertRaises(Validation):
            subtask_repo.update(self.con, created["id"], status="보류")

    def test_delete_removes_only_target(self):
        keep = subtask_repo.create(self.con, self.todo["id"], "유지")
        drop = subtask_repo.create(self.con, self.todo["id"], "삭제")
        subtask_repo.delete(self.con, drop["id"])
        left = [item["id"] for item in subtask_repo.list_by_todo(self.con, self.todo["id"])]
        self.assertEqual(left, [keep["id"]])
```

- [ ] **Step 2: 실패 확인**

Run: `python3 -m tests`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.repositories.subtasks'`

- [ ] **Step 3: 최소 구현**

`app/repositories/subtasks.py`:
```python
"""하위할일 저장·조회. 할일에 종속"""
from app import ordering
from app.constants import STATUS_TODO, TODO_STATUSES
from app.db import now, transaction
from app.errors import NotFound, Validation
from app.repositories import todos as todo_repo

TABLE = "subtasks"
EDITABLE_FIELDS = ("title", "status")


def create(con, todo_id, title):
    todo_repo.get(con, todo_id)
    cleaned = _clean_title(title)
    order = ordering.next_order(con, TABLE, *_group_scope(todo_id))
    with transaction(con):
        cursor = con.execute(
            "INSERT INTO subtasks(todo_id, title, status, sort_order, created_at)"
            " VALUES(?,?,?,?,?)",
            (todo_id, cleaned, STATUS_TODO, order, now()),
        )
    return get(con, cursor.lastrowid)


def list_by_todo(con, todo_id):
    where, params = _group_scope(todo_id)
    return [
        dict(row)
        for row in con.execute(
            f"SELECT * FROM subtasks WHERE {where} ORDER BY sort_order, id", params
        )
    ]


def get(con, subtask_id):
    row = con.execute("SELECT * FROM subtasks WHERE id=?", (subtask_id,)).fetchone()
    if not row:
        raise NotFound(f"하위할일 {subtask_id} 없음")
    return dict(row)


def update(con, subtask_id, **fields):
    get(con, subtask_id)
    assignments = {}
    for key, value in fields.items():
        if key not in EDITABLE_FIELDS:
            raise Validation(f"수정할 수 없는 필드: {key}")
        assignments[key] = value
    if "title" in assignments:
        assignments["title"] = _clean_title(assignments["title"])
    if "status" in assignments and assignments["status"] not in TODO_STATUSES:
        raise Validation(f"하위할일 상태는 {TODO_STATUSES} 중 하나여야 함")
    if not assignments:
        return get(con, subtask_id)
    clause = ",".join(f"{key}=?" for key in assignments)
    with transaction(con):
        con.execute(
            f"UPDATE subtasks SET {clause} WHERE id=?",
            tuple(assignments.values()) + (subtask_id,),
        )
    return get(con, subtask_id)


def delete(con, subtask_id):
    get(con, subtask_id)
    with transaction(con):
        con.execute("DELETE FROM subtasks WHERE id=?", (subtask_id,))


def reorder(con, ids, todo_id):
    ordering.reorder(con, TABLE, ids, *_group_scope(todo_id))


def _group_scope(todo_id):
    return ("todo_id=?", (todo_id,))


def _clean_title(title):
    cleaned = (title or "").strip()
    if not cleaned:
        raise Validation("하위할일 제목이 비어 있음")
    return cleaned
```

- [ ] **Step 4: 통과 확인**

Run: `python3 -m tests`
Expected: PASS (47 tests)

- [ ] **Step 5: 커밋**

```bash
git add app/repositories/subtasks.py tests/test_repositories.py
git commit -m "feat: 하위할일 repository 추가"
```

---

### Task 7: workspaces 삭제와 카테고리 변경 동기화

**Files:**
- Modify: `app/repositories/workspaces.py`
- Modify: `tests/test_repositories.py` (WorkspaceLifecycleTest 추가)

**Interfaces:**
- Consumes: `app.repositories.todos.demote_by_workspace`, `app.repositories.todos.sync_category`
- Produces:
  - `delete(con, workspace_id) -> None` — 소속 할일은 미분류로 강등
  - `update(con, workspace_id, category_id=...)` — 소속 할일 카테고리 동기화

**주의:** `todos.py`가 `workspaces.py`를 모듈 최상단에서 import하므로 반대 방향 import는 순환이 된다. 함수 안에서 지연 import한다.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
class WorkspaceLifecycleTest(unittest.TestCase):
    def setUp(self):
        self.con = temp_db()
        self.dev = category_repo.get_by_name(self.con, "개발")["id"]
        self.ops = category_repo.get_by_name(self.con, "운영")["id"]
        self.workspace = workspace_repo.create(self.con, self.dev, "KT 동시성")

    def test_delete_demotes_member_todos(self):
        todo = todo_repo.create(self.con, "락", workspace_id=self.workspace["id"])
        workspace_repo.delete(self.con, self.workspace["id"])
        demoted = todo_repo.get(self.con, todo["id"])
        self.assertIsNone(demoted["workspace_id"])
        self.assertEqual(demoted["category_id"], self.dev)

    def test_delete_removes_workspace(self):
        workspace_repo.delete(self.con, self.workspace["id"])
        with self.assertRaises(NotFound):
            workspace_repo.get(self.con, self.workspace["id"])

    def test_delete_missing_raises_not_found(self):
        with self.assertRaises(NotFound):
            workspace_repo.delete(self.con, 9999)

    def test_category_change_syncs_member_todos(self):
        todo = todo_repo.create(self.con, "락", workspace_id=self.workspace["id"])
        workspace_repo.update(self.con, self.workspace["id"], category_id=self.ops)
        self.assertEqual(todo_repo.get(self.con, todo["id"])["category_id"], self.ops)

    def test_category_change_rejects_missing_category(self):
        with self.assertRaises(NotFound):
            workspace_repo.update(self.con, self.workspace["id"], category_id=9999)
```

- [ ] **Step 2: 실패 확인**

Run: `python3 -m tests`
Expected: FAIL — `AttributeError: module 'app.repositories.workspaces' has no attribute 'delete'`

- [ ] **Step 3: 최소 구현**

`app/repositories/workspaces.py` 수정 — `EDITABLE_FIELDS`에 `category_id` 추가:
```python
EDITABLE_FIELDS = ("name", "status", "category_id") + OPTIONAL_FIELDS
```

`_validated_assignments`에 카테고리 존재 확인 추가:
```python
def _validated_assignments(fields):
    assignments = {}
    for key, value in fields.items():
        if key not in EDITABLE_FIELDS:
            raise Validation(f"수정할 수 없는 필드: {key}")
        if key == "status":
            _validate_status(value)
        if key == "name":
            value = _clean_name(value)
        if key == "category_id":
            category_repo.get(_assignment_con, value) if False else None
        assignments[key] = value
    return assignments
```

위 형태는 연결 객체를 못 받아 어색하므로, `_validated_assignments`가 `con`을 받도록 시그니처를 바꾼다. `update` 안의 호출부도 함께 고친다:
```python
def update(con, workspace_id, **fields):
    get(con, workspace_id)
    assignments = _validated_assignments(con, fields)
    if not assignments:
        return get(con, workspace_id)
    assignments["updated_at"] = now()
    clause = ",".join(f"{key}=?" for key in assignments)
    with transaction(con):
        con.execute(
            f"UPDATE workspaces SET {clause} WHERE id=?",
            tuple(assignments.values()) + (workspace_id,),
        )
    if "category_id" in assignments:
        _todo_repo().sync_category(con, workspace_id, assignments["category_id"])
    return get(con, workspace_id)


def _validated_assignments(con, fields):
    assignments = {}
    for key, value in fields.items():
        if key not in EDITABLE_FIELDS:
            raise Validation(f"수정할 수 없는 필드: {key}")
        if key == "status":
            _validate_status(value)
        if key == "name":
            value = _clean_name(value)
        if key == "category_id":
            category_repo.get(con, value)
        assignments[key] = value
    return assignments
```

`delete`와 지연 import 헬퍼 추가:
```python
def delete(con, workspace_id):
    """소속 할일은 미분류로 강등하고 워크스페이스만 지움. 데이터 손실 없음"""
    get(con, workspace_id)
    _todo_repo().demote_by_workspace(con, workspace_id)
    with transaction(con):
        con.execute("DELETE FROM workspaces WHERE id=?", (workspace_id,))


def _todo_repo():
    """todos 가 workspaces 를 import 하므로 순환을 피해 지연 로드"""
    from app.repositories import todos

    return todos
```

- [ ] **Step 4: 통과 확인**

Run: `python3 -m tests`
Expected: PASS (52 tests)

- [ ] **Step 5: 커밋**

```bash
git add app/repositories/workspaces.py tests/test_repositories.py
git commit -m "feat: 워크스페이스 삭제 시 할일 강등, 카테고리 변경 시 동기화"
```

---

### Task 8: board service — 그룹핑 트리

**Files:**
- Create: `app/services/__init__.py`, `app/services/board.py`
- Create: `tests/test_services.py`

**Interfaces:**
- Consumes: 모든 repository
- Produces:
  - `GROUP_BY_WORKSPACE = "workspace"`, `GROUP_BY_CATEGORY = "category"`, `GROUP_BY_CHOICES`
  - `tree(con, group_by: str) -> dict`
    ```python
    {
      "group_by": "workspace",
      "groups": [
        {
          "kind": "workspace",       # 또는 "category" / "unassigned"
          "id": 1,                   # unassigned 는 None
          "name": "KT 동시성",
          "sort_order": 1,
          "done_count": 3,
          "total_count": 7,
          "todos": [ {...todo, "subtasks": [...]} ],
          "category_name": "개발",   # workspace 기준일 때만
          "status": "active",        # workspace 기준일 때만
          "jira_id": None,           # workspace 기준일 때만
        }
      ],
    }
    ```

**규칙:** 할일이 없는 그룹은 제외한다. 미분류 그룹은 비어 있어도 항상 포함하고 항상 마지막에 둔다. `workspace` 기준에서는 `paused`·`done` 워크스페이스도 할일이 있으면 표시한다(우선순위 후보에서만 빠짐).

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_services.py`:
```python
import unittest

from app.constants import STATUS_DONE, UNASSIGNED_LABEL
from app.errors import Validation
from app.repositories import categories as category_repo
from app.repositories import subtasks as subtask_repo
from app.repositories import todos as todo_repo
from app.repositories import workspaces as workspace_repo
from app.services import board
from tests.support import temp_db


class BoardTreeTest(unittest.TestCase):
    def setUp(self):
        self.con = temp_db()
        self.dev = category_repo.get_by_name(self.con, "개발")["id"]
        self.ops = category_repo.get_by_name(self.con, "운영")["id"]
        self.kt = workspace_repo.create(self.con, self.dev, "KT 동시성")
        self.empty = workspace_repo.create(self.con, self.dev, "빈 워크스페이스")
        self.todo = todo_repo.create(self.con, "락 재설계", workspace_id=self.kt["id"])
        subtask_repo.create(self.con, self.todo["id"], "k6 시나리오")
        todo_repo.create(self.con, "문의 회신", category_id=self.ops)

    def _names(self, group_by):
        return [group["name"] for group in board.tree(self.con, group_by)["groups"]]

    def test_rejects_unknown_group_by(self):
        with self.assertRaises(Validation):
            board.tree(self.con, "priority")

    def test_workspace_grouping_hides_empty_workspace(self):
        self.assertNotIn(self.empty["name"], self._names("workspace"))

    def test_workspace_grouping_includes_unassigned_last(self):
        self.assertEqual(self._names("workspace")[-1], UNASSIGNED_LABEL)

    def test_unassigned_group_shown_even_when_empty(self):
        con = temp_db()
        self.assertEqual(
            [group["name"] for group in board.tree(con, "workspace")["groups"]],
            [UNASSIGNED_LABEL],
        )

    def test_workspace_group_carries_category_name(self):
        self.assertEqual(
            board.tree(self.con, "workspace")["groups"][0]["category_name"], "개발"
        )

    def test_todos_carry_subtasks(self):
        group = board.tree(self.con, "workspace")["groups"][0]
        self.assertEqual(group["todos"][0]["subtasks"][0]["title"], "k6 시나리오")

    def test_counts_reflect_done_state(self):
        todo_repo.update(self.con, self.todo["id"], status=STATUS_DONE)
        group = board.tree(self.con, "workspace")["groups"][0]
        self.assertEqual((group["done_count"], group["total_count"]), (1, 1))

    def test_category_grouping_includes_unassigned_todos(self):
        titles = [
            todo["title"]
            for group in board.tree(self.con, "category")["groups"]
            for todo in group["todos"]
        ]
        self.assertIn("문의 회신", titles)

    def test_category_grouping_hides_empty_categories(self):
        self.assertEqual(sorted(self._names("category")), ["개발", "운영"])
```

- [ ] **Step 2: 실패 확인**

Run: `python3 -m tests`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services'`

- [ ] **Step 3: 최소 구현**

`app/services/__init__.py`: 빈 파일.

`app/services/board.py`:
```python
"""보드 그룹핑 트리 조립. 여러 엔티티에 걸치므로 service 계층"""
from app.constants import STATUS_DONE, UNASSIGNED_LABEL
from app.errors import Validation
from app.repositories import categories as category_repo
from app.repositories import subtasks as subtask_repo
from app.repositories import todos as todo_repo
from app.repositories import workspaces as workspace_repo

GROUP_BY_WORKSPACE = "workspace"
GROUP_BY_CATEGORY = "category"
GROUP_BY_CHOICES = (GROUP_BY_WORKSPACE, GROUP_BY_CATEGORY)
KIND_UNASSIGNED = "unassigned"


def tree(con, group_by):
    """빈 그룹은 제외. 미분류는 비어 있어도 항상 마지막에 포함"""
    if group_by not in GROUP_BY_CHOICES:
        raise Validation(f"group_by 는 {GROUP_BY_CHOICES} 중 하나여야 함")
    builder = _workspace_groups if group_by == GROUP_BY_WORKSPACE else _category_groups
    return {"group_by": group_by, "groups": builder(con)}


def _workspace_groups(con):
    names = {row["id"]: row["name"] for row in category_repo.list_all(con)}
    groups = []
    for workspace in workspace_repo.list_all(con):
        todos = _with_subtasks(con, todo_repo.list_by_workspace(con, workspace["id"]))
        if not todos:
            continue
        groups.append(
            _group(
                kind=GROUP_BY_WORKSPACE,
                item_id=workspace["id"],
                name=workspace["name"],
                sort_order=workspace["sort_order"],
                todos=todos,
                category_name=names.get(workspace["category_id"]),
                status=workspace["status"],
                jira_id=workspace["jira_id"],
            )
        )
    groups.append(_unassigned_group(con))
    return groups


def _category_groups(con):
    groups = []
    for category in category_repo.list_all(con):
        todos = _with_subtasks(con, todo_repo.list_by_category(con, category["id"]))
        if not todos:
            continue
        groups.append(
            _group(
                kind=GROUP_BY_CATEGORY,
                item_id=category["id"],
                name=category["name"],
                sort_order=category["sort_order"],
                todos=todos,
            )
        )
    return groups


def _unassigned_group(con):
    return _group(
        kind=KIND_UNASSIGNED,
        item_id=None,
        name=UNASSIGNED_LABEL,
        sort_order=None,
        todos=_with_subtasks(con, todo_repo.list_by_workspace(con, None)),
    )


def _with_subtasks(con, todos):
    enriched = []
    for todo in todos:
        item = dict(todo)
        item["subtasks"] = subtask_repo.list_by_todo(con, todo["id"])
        enriched.append(item)
    return enriched


def _group(kind, item_id, name, sort_order, todos, **extra):
    group = {
        "kind": kind,
        "id": item_id,
        "name": name,
        "sort_order": sort_order,
        "done_count": sum(1 for todo in todos if todo["status"] == STATUS_DONE),
        "total_count": len(todos),
        "todos": todos,
    }
    group.update(extra)
    return group
```

- [ ] **Step 4: 통과 확인**

Run: `python3 -m tests`
Expected: PASS (61 tests)

- [ ] **Step 5: 커밋**

```bash
git add app/services tests/test_services.py
git commit -m "feat: 보드 그룹핑 트리 service 추가"
```

---

### Task 9: planning service — next, done_on

**Files:**
- Create: `app/services/planning.py`
- Modify: `tests/test_services.py` (PlanningTest 추가)

**Interfaces:**
- Consumes: `app.repositories.workspaces.list_all`, `app.repositories.todos`
- Produces:
  - `today_text() -> str` — 로컬 기준 `YYYY-MM-DD`
  - `next_todo(con) -> dict | None` — `{"todo": {...}, "workspace": {...} | None}`
  - `done_on(con, date_text: str | None = None) -> list[dict]` — 각 항목에 `workspace_name` 추가

**규칙:** `active` 워크스페이스를 `sort_order` 순으로 훑어 첫 미완료 할일을 고른다. 같은 워크스페이스 안에서는 `doing`이 `todo`보다 먼저다. active를 다 훑어도 없으면 미분류 할일을 본다. `paused`·`done` 워크스페이스는 후보에서 빠진다.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
from app.constants import STATUS_DOING
from app.services import planning


class PlanningTest(unittest.TestCase):
    def setUp(self):
        self.con = temp_db()
        self.dev = category_repo.get_by_name(self.con, "개발")["id"]
        self.ops = category_repo.get_by_name(self.con, "운영")["id"]
        self.first = workspace_repo.create(self.con, self.dev, "KT 동시성")
        self.second = workspace_repo.create(self.con, self.dev, "헤르메스 테스트")

    def test_returns_none_when_nothing_to_do(self):
        self.assertIsNone(planning.next_todo(self.con))

    def test_picks_first_workspace_first_todo(self):
        todo_repo.create(self.con, "락 재설계", workspace_id=self.first["id"])
        todo_repo.create(self.con, "시나리오 정리", workspace_id=self.second["id"])
        picked = planning.next_todo(self.con)
        self.assertEqual(picked["todo"]["title"], "락 재설계")
        self.assertEqual(picked["workspace"]["name"], "KT 동시성")

    def test_doing_beats_todo_within_workspace(self):
        todo_repo.create(self.con, "먼저 등록", workspace_id=self.first["id"])
        started = todo_repo.create(self.con, "벌여둔 것", workspace_id=self.first["id"])
        todo_repo.update(self.con, started["id"], status=STATUS_DOING)
        self.assertEqual(planning.next_todo(self.con)["todo"]["title"], "벌여둔 것")

    def test_skips_done_todos(self):
        finished = todo_repo.create(self.con, "끝난 것", workspace_id=self.first["id"])
        todo_repo.update(self.con, finished["id"], status=STATUS_DONE)
        todo_repo.create(self.con, "남은 것", workspace_id=self.first["id"])
        self.assertEqual(planning.next_todo(self.con)["todo"]["title"], "남은 것")

    def test_skips_paused_workspace(self):
        todo_repo.create(self.con, "보류된 일", workspace_id=self.first["id"])
        workspace_repo.update(self.con, self.first["id"], status="paused")
        todo_repo.create(self.con, "진행할 일", workspace_id=self.second["id"])
        self.assertEqual(planning.next_todo(self.con)["todo"]["title"], "진행할 일")

    def test_falls_back_to_unassigned(self):
        todo_repo.create(self.con, "문의 회신", category_id=self.ops)
        picked = planning.next_todo(self.con)
        self.assertEqual(picked["todo"]["title"], "문의 회신")
        self.assertIsNone(picked["workspace"])

    def test_done_on_attaches_workspace_name(self):
        finished = todo_repo.create(self.con, "락", workspace_id=self.first["id"])
        todo_repo.update(self.con, finished["id"], status=STATUS_DONE)
        rows = planning.done_on(self.con, planning.today_text())
        self.assertEqual(rows[0]["workspace_name"], "KT 동시성")

    def test_done_on_excludes_other_dates(self):
        finished = todo_repo.create(self.con, "락", workspace_id=self.first["id"])
        todo_repo.update(self.con, finished["id"], status=STATUS_DONE)
        self.assertEqual(planning.done_on(self.con, "2020-01-01"), [])

    def test_done_on_labels_unassigned(self):
        finished = todo_repo.create(self.con, "문의", category_id=self.ops)
        todo_repo.update(self.con, finished["id"], status=STATUS_DONE)
        rows = planning.done_on(self.con, planning.today_text())
        self.assertEqual(rows[0]["workspace_name"], UNASSIGNED_LABEL)
```

- [ ] **Step 2: 실패 확인**

Run: `python3 -m tests`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.planning'`

- [ ] **Step 3: 최소 구현**

`app/services/planning.py`:
```python
"""다음에 할 일 선정과 완료분 집계"""
from datetime import datetime, timezone

from app.constants import STATUS_DOING, STATUS_DONE, UNASSIGNED_LABEL, WORKSPACE_ACTIVE
from app.repositories import todos as todo_repo
from app.repositories import workspaces as workspace_repo

DOING_RANK = 0
DEFAULT_RANK = 1


def today_text():
    """완료 시각이 UTC 로 저장되므로 집계 기준도 UTC 날짜"""
    return datetime.now(timezone.utc).date().isoformat()


def next_todo(con):
    """active 워크스페이스 순위대로 훑고, 없으면 미분류. doing 이 todo 보다 먼저"""
    for workspace in workspace_repo.list_all(con, status=WORKSPACE_ACTIVE):
        picked = _first_open(todo_repo.list_by_workspace(con, workspace["id"]))
        if picked:
            return {"todo": picked, "workspace": workspace}
    picked = _first_open(todo_repo.list_by_workspace(con, None))
    if picked:
        return {"todo": picked, "workspace": None}
    return None


def done_on(con, date_text=None):
    """해당 날짜 완료분에 워크스페이스 이름을 붙여 반환. daily-todo 로 넘기는 입력"""
    target = date_text or today_text()
    rows = []
    for todo in todo_repo.list_completed_on(con, target):
        item = dict(todo)
        item["workspace_name"] = _workspace_name(con, todo["workspace_id"])
        rows.append(item)
    return rows


def _first_open(todos):
    """미완료 중 doing 우선, 그 다음 sort_order"""
    open_todos = [todo for todo in todos if todo["status"] != STATUS_DONE]
    if not open_todos:
        return None
    return min(open_todos, key=_priority_key)


def _priority_key(todo):
    rank = DOING_RANK if todo["status"] == STATUS_DOING else DEFAULT_RANK
    return (rank, todo["sort_order"])


def _workspace_name(con, workspace_id):
    if workspace_id is None:
        return UNASSIGNED_LABEL
    return workspace_repo.get(con, workspace_id)["name"]
```

- [ ] **Step 4: 통과 확인**

Run: `python3 -m tests`
Expected: PASS (70 tests)

- [ ] **Step 5: 커밋**

```bash
git add app/services/planning.py tests/test_services.py
git commit -m "feat: next·done-today 계획 service 추가"
```

---

### Task 10: dash.py CLI 진입점

**Files:**
- Create: `dash.py`
- Create: `tests/test_cli.py`

**Interfaces:**
- Consumes: 모든 repository와 service
- Produces: `main(argv: list[str] | None = None) -> int` — 도메인 예외는 stderr + 종료코드 1

**명령 목록 (스펙과 일치):**
```
ls [--group-by workspace|category] [--json]
next [--json]
show <workspace-id|JIRA> [--json]
add-category <name>
add-workspace <category> <name> [--background .. --purpose .. --goal .. --considerations .. --jira ..]
add-todo <title> (--category NAME | --workspace ID)
add-subtask <todo-id> <title>
move-todo <todo-id> --workspace <ID|none>
set-status <todo|subtask|workspace> <id> <status>
reorder <kind> [--scope ID] <id...>
rm-category <id>
done-today [--date YYYY-MM-DD] [--json]
```

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_cli.py`:
```python
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

import dash
from app.constants import DB_PATH_ENV


class CliTest(unittest.TestCase):
    def setUp(self):
        os.environ[DB_PATH_ENV] = os.path.join(tempfile.mkdtemp(), "cli.db")

    def tearDown(self):
        os.environ.pop(DB_PATH_ENV, None)

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = dash.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_ls_succeeds_on_fresh_db(self):
        code, out, _ = self.run_cli("ls")
        self.assertEqual(code, 0)
        self.assertIn("미분류", out)

    def test_json_flag_emits_parseable_output(self):
        code, out, _ = self.run_cli("ls", "--json")
        self.assertEqual(code, 0)
        self.assertIn("groups", json.loads(out))

    def test_add_workspace_then_add_todo(self):
        self.run_cli("add-workspace", "개발", "KT 동시성", "--goal", "락 재설계")
        code, out, _ = self.run_cli("add-todo", "락 초안", "--workspace", "1")
        self.assertEqual(code, 0)
        self.assertIn("락 초안", out)

    def test_add_todo_requires_category_or_workspace(self):
        code, _, err = self.run_cli("add-todo", "제목만")
        self.assertEqual(code, 1)
        self.assertIn("카테고리", err)

    def test_next_reports_nothing_when_empty(self):
        code, out, _ = self.run_cli("next")
        self.assertEqual(code, 0)
        self.assertIn("없", out)

    def test_move_todo_to_none_unassigns(self):
        self.run_cli("add-workspace", "개발", "KT")
        self.run_cli("add-todo", "락", "--workspace", "1")
        code, out, _ = self.run_cli("move-todo", "1", "--workspace", "none")
        self.assertEqual(code, 0)
        self.assertIn("미분류", out)

    def test_show_by_jira_id(self):
        self.run_cli("add-workspace", "개발", "KT", "--jira", "KT-1530")
        code, out, _ = self.run_cli("show", "KT-1530")
        self.assertEqual(code, 0)
        self.assertIn("KT", out)

    def test_rm_category_conflict_exits_one(self):
        self.run_cli("add-todo", "문의", "--category", "운영")
        code, _, err = self.run_cli("rm-category", "2")
        self.assertEqual(code, 1)
        self.assertIn("남아", err)

    def test_unknown_command_exits_nonzero(self):
        with self.assertRaises(SystemExit):
            self.run_cli("nope")

    def test_done_today_json_is_list(self):
        code, out, _ = self.run_cli("done-today", "--json")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out), [])
```

- [ ] **Step 2: 실패 확인**

Run: `python3 -m tests`
Expected: FAIL — `ModuleNotFoundError: No module named 'dash'`

- [ ] **Step 3: 최소 구현**

`dash.py`:
```python
#!/usr/bin/env python3
"""작업 대시보드 CLI. 파싱·위임·출력만 하고 도메인 로직은 갖지 않음"""
import argparse
import json
import sys

from app.constants import UNASSIGNED_LABEL
from app.db import connect
from app.errors import DomainError, NotFound
from app.repositories import categories as category_repo
from app.repositories import subtasks as subtask_repo
from app.repositories import todos as todo_repo
from app.repositories import workspaces as workspace_repo
from app.services import board, planning

NONE_LITERAL = "none"
REORDER_KINDS = ("categories", "workspaces", "todos", "subtasks")
STATUS_TARGETS = ("todo", "subtask", "workspace")
CONTEXT_ARGS = ("background", "purpose", "goal", "considerations")
DETAIL_LABELS = (("배경", "background"), ("목적", "purpose"),
                 ("목표", "goal"), ("고려사항", "considerations"))
EXIT_OK = 0
EXIT_ERROR = 1


def main(argv=None):
    args = _build_parser().parse_args(argv)
    con = connect()
    try:
        args.handler(con, args)
    except DomainError as error:
        print(str(error), file=sys.stderr)
        return EXIT_ERROR
    return EXIT_OK


def _build_parser():
    parser = argparse.ArgumentParser(description="작업 대시보드 CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    listing = sub.add_parser("ls", help="전체 트리 개요")
    listing.add_argument("--group-by", default=board.GROUP_BY_WORKSPACE,
                         choices=board.GROUP_BY_CHOICES, dest="group_by")
    _add_json_flag(listing)
    listing.set_defaults(handler=_cmd_ls)

    upcoming = sub.add_parser("next", help="다음에 할 일 1건")
    _add_json_flag(upcoming)
    upcoming.set_defaults(handler=_cmd_next)

    show = sub.add_parser("show", help="워크스페이스 상세")
    show.add_argument("target", help="워크스페이스 id 또는 Jira ID")
    _add_json_flag(show)
    show.set_defaults(handler=_cmd_show)

    add_category = sub.add_parser("add-category")
    add_category.add_argument("name")
    add_category.set_defaults(handler=_cmd_add_category)

    add_workspace = sub.add_parser("add-workspace")
    add_workspace.add_argument("category")
    add_workspace.add_argument("name")
    for field in CONTEXT_ARGS:
        add_workspace.add_argument(f"--{field}", default=None)
    add_workspace.add_argument("--jira", default=None)
    add_workspace.set_defaults(handler=_cmd_add_workspace)

    add_todo = sub.add_parser("add-todo")
    add_todo.add_argument("title")
    add_todo.add_argument("--category", default=None)
    add_todo.add_argument("--workspace", default=None)
    add_todo.set_defaults(handler=_cmd_add_todo)

    add_subtask = sub.add_parser("add-subtask")
    add_subtask.add_argument("todo_id", type=int)
    add_subtask.add_argument("title")
    add_subtask.set_defaults(handler=_cmd_add_subtask)

    move_todo = sub.add_parser("move-todo")
    move_todo.add_argument("todo_id", type=int)
    move_todo.add_argument("--workspace", required=True, help="워크스페이스 id 또는 none")
    move_todo.set_defaults(handler=_cmd_move_todo)

    set_status = sub.add_parser("set-status")
    set_status.add_argument("target", choices=STATUS_TARGETS)
    set_status.add_argument("item_id", type=int)
    set_status.add_argument("status")
    set_status.set_defaults(handler=_cmd_set_status)

    reorder = sub.add_parser("reorder")
    reorder.add_argument("kind", choices=REORDER_KINDS)
    reorder.add_argument("--scope", default=None,
                         help="todos 면 워크스페이스 id(미분류는 none), subtasks 면 할일 id")
    reorder.add_argument("ids", nargs="+", type=int)
    reorder.set_defaults(handler=_cmd_reorder)

    remove_category = sub.add_parser("rm-category")
    remove_category.add_argument("category_id", type=int)
    remove_category.set_defaults(handler=_cmd_rm_category)

    done_today = sub.add_parser("done-today")
    done_today.add_argument("--date", default=None)
    _add_json_flag(done_today)
    done_today.set_defaults(handler=_cmd_done_today)

    return parser


def _add_json_flag(parser):
    parser.add_argument("--json", action="store_true", dest="as_json",
                        help="Claude 파싱용 JSON 출력")


def _cmd_ls(con, args):
    tree = board.tree(con, args.group_by)
    if args.as_json:
        _emit_json(tree)
        return
    for group in tree["groups"]:
        print(f"{group['name']}  {group['done_count']}/{group['total_count']}")
        for todo in group["todos"]:
            print(f"  [{todo['status']}] {todo['id']}. {todo['title']}")
            for subtask in todo["subtasks"]:
                print(f"      - [{subtask['status']}] {subtask['title']}")


def _cmd_next(con, args):
    picked = planning.next_todo(con)
    if args.as_json:
        _emit_json(picked)
        return
    if not picked:
        print("다음에 할 일이 없음")
        return
    scope = picked["workspace"]["name"] if picked["workspace"] else UNASSIGNED_LABEL
    print(f"{scope} / {picked['todo']['title']}")


def _cmd_show(con, args):
    workspace = _resolve_workspace(con, args.target)
    todos = todo_repo.list_by_workspace(con, workspace["id"])
    if args.as_json:
        _emit_json({"workspace": workspace, "todos": todos})
        return
    print(f"{workspace['name']} [{workspace['status']}]")
    for label, key in DETAIL_LABELS:
        print(f"{label}: {workspace[key] or '(미입력)'}")
    for todo in todos:
        print(f"  [{todo['status']}] {todo['id']}. {todo['title']}")


def _cmd_add_category(con, args):
    print(category_repo.create(con, args.name)["name"])


def _cmd_add_workspace(con, args):
    category = category_repo.get_by_name(con, args.category)
    created = workspace_repo.create(
        con, category["id"], args.name,
        background=args.background, purpose=args.purpose, goal=args.goal,
        considerations=args.considerations, jira_id=args.jira,
    )
    print(f"{created['id']}. {created['name']}")


def _cmd_add_todo(con, args):
    category_id = (
        category_repo.get_by_name(con, args.category)["id"] if args.category else None
    )
    workspace_id = int(args.workspace) if args.workspace else None
    created = todo_repo.create(
        con, args.title, category_id=category_id, workspace_id=workspace_id
    )
    print(f"{created['id']}. {created['title']}")


def _cmd_add_subtask(con, args):
    created = subtask_repo.create(con, args.todo_id, args.title)
    print(f"{created['id']}. {created['title']}")


def _cmd_move_todo(con, args):
    workspace_id = None if args.workspace == NONE_LITERAL else int(args.workspace)
    moved = todo_repo.update(con, args.todo_id, workspace_id=workspace_id)
    scope = (
        workspace_repo.get(con, workspace_id)["name"] if workspace_id else UNASSIGNED_LABEL
    )
    print(f"{moved['title']} → {scope}")


def _cmd_set_status(con, args):
    updaters = {
        "workspace": workspace_repo.update,
        "subtask": subtask_repo.update,
        "todo": todo_repo.update,
    }
    updated = updaters[args.target](con, args.item_id, status=args.status)
    print(f"{updated.get('title') or updated.get('name')} → {updated['status']}")


def _cmd_reorder(con, args):
    if args.kind == "categories":
        category_repo.reorder(con, args.ids)
    elif args.kind == "workspaces":
        workspace_repo.reorder(con, args.ids)
    elif args.kind == "todos":
        scope = None if args.scope in (None, NONE_LITERAL) else int(args.scope)
        todo_repo.reorder(con, args.ids, scope)
    else:
        subtask_repo.reorder(con, args.ids, int(args.scope))
    print(f"{len(args.ids)}건 재정렬")


def _cmd_rm_category(con, args):
    category_repo.delete(con, args.category_id)
    print("삭제됨")


def _cmd_done_today(con, args):
    rows = planning.done_on(con, args.date)
    if args.as_json:
        _emit_json(rows)
        return
    if not rows:
        print("완료한 할일이 없음")
        return
    for row in rows:
        print(f"- {row['workspace_name']} / {row['title']}")


def _resolve_workspace(con, target):
    """숫자면 id, 아니면 Jira ID 로 조회"""
    if target.isdigit():
        return workspace_repo.get(con, int(target))
    found = workspace_repo.get_by_jira(con, target)
    if not found:
        raise NotFound(f"'{target}' 에 해당하는 워크스페이스 없음")
    return found


def _emit_json(payload):
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: 통과 확인**

Run: `python3 -m tests`
Expected: PASS (80 tests)

- [ ] **Step 5: 커밋**

```bash
git add dash.py tests/test_cli.py
git commit -m "feat: CLI 진입점 추가"
```

---

### Task 11: server.py HTTP 진입점

**Files:**
- Create: `server.py`
- Create: `tests/test_static.py`

**Interfaces:**
- Consumes: 모든 repository와 service
- Produces:
  - `status_for(error) -> int` — 도메인 예외 타입 → HTTP 상태 코드
  - `resolve_static(url_path: str) -> str | None`
  - `route(con, method, path, query, body) -> object`
  - `Handler`, `main(argv=None)`

**엔드포인트 (스펙과 일치):**
```
GET    /api/tree?group_by=workspace|category
GET    /api/next
GET    /api/done-today?date=YYYY-MM-DD
GET    /api/categories
POST   /api/categories                {name}
PATCH  /api/categories/<id>           {name?}
DELETE /api/categories/<id>
GET    /api/workspaces/<id>
POST   /api/workspaces                {category_id, name, ...}
PATCH  /api/workspaces/<id>           {...}
DELETE /api/workspaces/<id>
POST   /api/todos                     {category_id?, workspace_id?, title}
PATCH  /api/todos/<id>                {...}
DELETE /api/todos/<id>
POST   /api/subtasks                  {todo_id, title}
PATCH  /api/subtasks/<id>             {...}
DELETE /api/subtasks/<id>
POST   /api/reorder                   {kind, scope_id?, ids}
```

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_static.py`:
```python
import os
import tempfile
import unittest

import server
from app.constants import DB_PATH_ENV
from app.db import connect
from app.errors import Conflict, NotFound, Validation


class StaticPathTest(unittest.TestCase):
    def test_root_maps_to_index(self):
        resolved = server.resolve_static("/")
        self.assertTrue(resolved.endswith(os.path.join("static", "index.html")))

    def test_allows_nested_module(self):
        self.assertIsNotNone(server.resolve_static("/js/api.js"))

    def test_rejects_parent_traversal(self):
        self.assertIsNone(server.resolve_static("/../server.py"))

    def test_rejects_encoded_traversal(self):
        self.assertIsNone(server.resolve_static("/%2e%2e/server.py"))

    def test_rejects_disallowed_suffix(self):
        self.assertIsNone(server.resolve_static("/index.txt"))

    def test_rejects_directory_without_index(self):
        self.assertIsNone(server.resolve_static("/js"))


class ErrorMappingTest(unittest.TestCase):
    def test_maps_domain_errors_to_status(self):
        self.assertEqual(server.status_for(NotFound("x")), 404)
        self.assertEqual(server.status_for(Conflict("x")), 409)
        self.assertEqual(server.status_for(Validation("x")), 400)

    def test_unknown_error_is_server_error(self):
        self.assertEqual(server.status_for(RuntimeError("x")), 500)


class RouteTest(unittest.TestCase):
    def setUp(self):
        path = os.path.join(tempfile.mkdtemp(), "route.db")
        os.environ[DB_PATH_ENV] = path
        self.con = connect(path)

    def tearDown(self):
        os.environ.pop(DB_PATH_ENV, None)

    def test_tree_endpoint_returns_groups(self):
        payload = server.route(self.con, "GET", "/api/tree", {}, {})
        self.assertIn("groups", payload)

    def test_create_category_endpoint(self):
        payload = server.route(self.con, "POST", "/api/categories", {}, {"name": "새것"})
        self.assertEqual(payload["name"], "새것")

    def test_unknown_endpoint_raises_not_found(self):
        with self.assertRaises(NotFound):
            server.route(self.con, "GET", "/api/nope", {}, {})

    def test_reorder_endpoint_rejects_unknown_kind(self):
        with self.assertRaises(Validation):
            server.route(self.con, "POST", "/api/reorder", {}, {"kind": "x", "ids": []})
```

- [ ] **Step 2: 실패 확인**

Run: `python3 -m tests`
Expected: FAIL — `ModuleNotFoundError: No module named 'server'`

- [ ] **Step 3: 최소 구현**

`server.py`:
```python
#!/usr/bin/env python3
"""작업 대시보드 HTTP 진입점. 라우팅과 직렬화만 담당"""
import argparse
import json
import os
import posixpath
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

from app.constants import ALLOWED_STATIC_SUFFIXES, DEFAULT_HOST, DEFAULT_PORT
from app.db import connect
from app.errors import Conflict, DomainError, NotFound, Validation
from app.repositories import categories as category_repo
from app.repositories import subtasks as subtask_repo
from app.repositories import todos as todo_repo
from app.repositories import workspaces as workspace_repo
from app.services import board, planning

STATIC_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
INDEX_FILE = "index.html"
API_PREFIX = "/api/"
NONE_LITERAL = "none"
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
}
STATUS_BY_ERROR = (
    (NotFound, HTTPStatus.NOT_FOUND),
    (Conflict, HTTPStatus.CONFLICT),
    (Validation, HTTPStatus.BAD_REQUEST),
)
WORKSPACE_CREATE_FIELDS = ("background", "purpose", "goal", "considerations", "jira_id")


def status_for(error):
    """도메인 예외 타입만 보고 상태 코드 결정. 메시지 문자열은 보지 않음"""
    for error_type, status in STATUS_BY_ERROR:
        if isinstance(error, error_type):
            return int(status)
    return int(HTTPStatus.INTERNAL_SERVER_ERROR)


def resolve_static(url_path):
    """static/ 안의 허용 확장자 파일만 통과. 벗어나면 None"""
    decoded = unquote(url_path)
    if decoded.endswith("/"):
        decoded += INDEX_FILE
    normalized = posixpath.normpath(decoded).lstrip("/")
    if normalized.startswith(".."):
        return None
    candidate = os.path.normpath(os.path.join(STATIC_ROOT, normalized))
    if os.path.commonpath([candidate, STATIC_ROOT]) != STATIC_ROOT:
        return None
    if not candidate.endswith(ALLOWED_STATIC_SUFFIXES):
        return None
    return candidate


def route(con, method, path, query, body):
    """경로와 메서드를 도메인 호출로 연결. 도메인 로직은 갖지 않음"""
    segments = [part for part in path.strip("/").split("/") if part][1:]
    if not segments:
        raise NotFound("알 수 없는 엔드포인트")
    head = segments[0]
    item_id = int(segments[1]) if len(segments) > 1 else None
    routers = {
        "GET": lambda: _route_get(con, head, item_id, query),
        "POST": lambda: _route_post(con, head, body),
        "PATCH": lambda: _route_patch(con, head, item_id, body),
        "DELETE": lambda: _route_delete(con, head, item_id),
    }
    if method not in routers:
        raise Validation(f"지원하지 않는 메서드: {method}")
    return routers[method]()


def _route_get(con, head, item_id, query):
    if head == "tree":
        return board.tree(con, _single(query, "group_by", board.GROUP_BY_WORKSPACE))
    if head == "next":
        return planning.next_todo(con)
    if head == "done-today":
        return planning.done_on(con, _single(query, "date", None))
    if head == "categories":
        return category_repo.list_all(con)
    if head == "workspaces" and item_id:
        return {
            "workspace": workspace_repo.get(con, item_id),
            "todos": todo_repo.list_by_workspace(con, item_id),
        }
    raise NotFound("알 수 없는 엔드포인트")


def _route_post(con, head, body):
    if head == "categories":
        return category_repo.create(con, body.get("name"))
    if head == "workspaces":
        extra = {key: body.get(key) for key in WORKSPACE_CREATE_FIELDS}
        return workspace_repo.create(
            con, body.get("category_id"), body.get("name"), **extra
        )
    if head == "todos":
        return todo_repo.create(
            con, body.get("title"), category_id=body.get("category_id"),
            workspace_id=body.get("workspace_id"), note=body.get("note"),
        )
    if head == "subtasks":
        return subtask_repo.create(con, body.get("todo_id"), body.get("title"))
    if head == "reorder":
        return _reorder(con, body)
    raise NotFound("알 수 없는 엔드포인트")


def _route_patch(con, head, item_id, body):
    if not item_id:
        raise Validation("id 가 필요함")
    if head == "categories":
        return category_repo.rename(con, item_id, body.get("name"))
    if head == "workspaces":
        return workspace_repo.update(con, item_id, **body)
    if head == "todos":
        return todo_repo.update(con, item_id, **body)
    if head == "subtasks":
        return subtask_repo.update(con, item_id, **body)
    raise NotFound("알 수 없는 엔드포인트")


def _route_delete(con, head, item_id):
    if not item_id:
        raise Validation("id 가 필요함")
    deleters = {
        "categories": category_repo.delete,
        "workspaces": workspace_repo.delete,
        "todos": todo_repo.delete,
        "subtasks": subtask_repo.delete,
    }
    if head not in deleters:
        raise NotFound("알 수 없는 엔드포인트")
    deleters[head](con, item_id)
    return {"deleted": item_id}


def _reorder(con, body):
    kind, ids = body.get("kind"), body.get("ids") or []
    scope = body.get("scope_id")
    if kind == "categories":
        category_repo.reorder(con, ids)
    elif kind == "workspaces":
        workspace_repo.reorder(con, ids)
    elif kind == "todos":
        todo_repo.reorder(con, ids, None if scope in (None, NONE_LITERAL) else scope)
    elif kind == "subtasks":
        subtask_repo.reorder(con, ids, scope)
    else:
        raise Validation(f"알 수 없는 reorder 종류: {kind}")
    return {"reordered": len(ids)}


def _single(query, key, default):
    values = query.get(key)
    return values[0] if values else default


class Handler(BaseHTTPRequestHandler):
    server_version = "work-dashboard"

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path.startswith(API_PREFIX):
            self._dispatch("GET", parsed)
            return
        self._serve_static(parsed.path)

    def do_POST(self):
        self._dispatch("POST", urlparse(self.path))

    def do_PATCH(self):
        self._dispatch("PATCH", urlparse(self.path))

    def do_DELETE(self):
        self._dispatch("DELETE", urlparse(self.path))

    def log_message(self, fmt, *args):
        """기본 형식 대신 메서드와 경로만"""
        print(f"{self.command} {self.path}")

    def _dispatch(self, method, parsed):
        con = connect()
        try:
            payload = route(con, method, parsed.path,
                            parse_qs(parsed.query), self._read_body())
            self._send_json(int(HTTPStatus.OK), payload)
        except DomainError as error:
            self._send_json(status_for(error), {"error": str(error)})
        except Exception as error:  # 예상 못한 오류도 JSON 으로 알려줌
            self._send_json(int(HTTPStatus.INTERNAL_SERVER_ERROR),
                            {"error": f"{type(error).__name__}: {error}"})

    def _read_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def _send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_static(self, url_path):
        resolved = resolve_static(url_path)
        if not resolved or not os.path.isfile(resolved):
            self.send_error(int(HTTPStatus.NOT_FOUND))
            return
        with open(resolved, "rb") as handle:
            body = handle.read()
        self.send_response(int(HTTPStatus.OK))
        self.send_header("Content-Type", CONTENT_TYPES[os.path.splitext(resolved)[1]])
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main(argv=None):
    parser = argparse.ArgumentParser(description="작업 대시보드 서버")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args(argv)
    connect()
    try:
        httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    except OSError as error:
        raise SystemExit(f"포트 {args.port} 를 열 수 없음: {error}")
    print(f"http://{args.host}:{args.port}")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 통과 확인**

Run: `python3 -m tests`
Expected: PASS (90 tests)

- [ ] **Step 5: 서버 수동 확인**

```bash
WORK_DASHBOARD_DB=/tmp/smoke.db python3 server.py --port 8099 &
sleep 1
curl -s "http://127.0.0.1:8099/api/tree?group_by=workspace"
curl -s -X POST -H 'Content-Type: application/json' -d '{"name":"임시"}' \
  http://127.0.0.1:8099/api/categories
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8099/../server.py
kill %1
```
Expected: 트리 JSON, 생성된 카테고리 JSON, traversal 요청은 404

- [ ] **Step 6: 커밋**

```bash
git add server.py tests/test_static.py
git commit -m "feat: HTTP 진입점과 정적 파일 경로 방어 추가"
```

---

### Task 12: 프론트엔드 골격 — index.html, app.css, api.js, main.js

**Files:**
- Create: `static/index.html`, `static/css/app.css`, `static/js/api.js`, `static/js/main.js`

**Interfaces:**
- Consumes: `/api/*`
- Produces:
  - `api.js`: `getTree(groupBy)`, `getNext()`, `getDoneToday(date)`, `getCategories()`, `getWorkspace(id)`, `createCategory(name)`, `renameCategory(id, name)`, `deleteCategory(id)`, `createWorkspace(fields)`, `updateWorkspace(id, fields)`, `deleteWorkspace(id)`, `createTodo(fields)`, `updateTodo(id, fields)`, `deleteTodo(id)`, `createSubtask(todoId, title)`, `updateSubtask(id, fields)`, `deleteSubtask(id)`, `reorder(kind, ids, scopeId)`
  - `main.js`: `run(action)`, `showError(message)`

- [ ] **Step 1: 마크업 작성**

`static/index.html`:
```html
<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>작업 대시보드</title>
  <link rel="stylesheet" href="/css/app.css">
</head>
<body>
  <header>
    <h1>작업 대시보드</h1>
    <nav id="tabs">
      <button data-tab="board" class="active">보드</button>
      <button data-tab="workspace">워크스페이스</button>
      <button data-tab="categories">카테고리</button>
    </nav>
  </header>

  <p id="error" hidden></p>

  <section id="tab-board" class="tab">
    <p id="next-line">다음에 할 일 ▸ <span id="next-text">불러오는 중</span></p>
    <form id="quick-add">
      <input id="quick-title" placeholder="빠른 추가 (장애·문의)" required>
      <select id="quick-category"></select>
      <button type="submit">+</button>
    </form>
    <div id="board-controls">
      <label><input type="radio" name="group-by" value="workspace" checked> 워크스페이스</label>
      <label><input type="radio" name="group-by" value="category"> 카테고리</label>
      <label><input type="checkbox" id="show-done"> 완료 항목 표시</label>
    </div>
    <div id="groups"></div>
    <details id="done-today">
      <summary>오늘 완료</summary>
      <ul id="done-list"></ul>
    </details>
  </section>

  <section id="tab-workspace" class="tab" hidden>
    <select id="workspace-picker"></select>
    <div id="workspace-detail"></div>
  </section>

  <section id="tab-categories" class="tab" hidden>
    <form id="category-add">
      <input id="category-name" placeholder="새 카테고리" required>
      <button type="submit">추가</button>
    </form>
    <ul id="category-list"></ul>
  </section>

  <script type="module" src="/js/main.js"></script>
</body>
</html>
```

- [ ] **Step 2: 스타일 작성**

`static/css/app.css`:
```css
:root {
  --bg: #fbfbfa;
  --fg: #2f3437;
  --muted: #8a8f98;
  --line: #e6e6e4;
  --accent: #2d6cdf;
  --gap: 12px;
}

* { box-sizing: border-box; }

body {
  margin: 0;
  padding: var(--gap);
  background: var(--bg);
  color: var(--fg);
  font: 14px/1.5 -apple-system, "Segoe UI", "Noto Sans KR", sans-serif;
}

header { display: flex; align-items: baseline; gap: var(--gap); flex-wrap: wrap; }
h1 { font-size: 18px; margin: 0; }
nav button { background: none; border: none; color: var(--muted); cursor: pointer; padding: 4px 8px; }
nav button.active { color: var(--accent); font-weight: 600; }

#error { background: #fdecec; color: #a12222; padding: 8px; border-radius: 4px; }

#next-line { background: #fff; border: 1px solid var(--line); border-radius: 6px; padding: 10px; }
#next-text { font-weight: 600; }

form { display: flex; gap: 6px; margin: var(--gap) 0; flex-wrap: wrap; }
input, select, textarea { padding: 6px 8px; border: 1px solid var(--line); border-radius: 4px; background: #fff; color: inherit; }
#quick-title { flex: 1 1 200px; }
button { padding: 6px 10px; border: 1px solid var(--line); border-radius: 4px; background: #fff; color: inherit; cursor: pointer; }

#board-controls { display: flex; gap: var(--gap); color: var(--muted); flex-wrap: wrap; }

.group { background: #fff; border: 1px solid var(--line); border-radius: 6px; margin: var(--gap) 0; }
.group > summary { padding: 10px; cursor: grab; display: flex; justify-content: space-between; gap: 8px; }
.group.unassigned > summary { color: var(--muted); }
.group-meta { color: var(--muted); font-size: 12px; }

.todo { display: flex; align-items: center; gap: 8px; padding: 6px 10px; border-top: 1px solid var(--line); }
.todo .title { flex: 1; }
.todo.done .title { color: var(--muted); text-decoration: line-through; }
.subtasks { margin: 0; padding: 4px 10px 8px 34px; list-style: none; color: var(--muted); }
.drop-target { outline: 2px dashed var(--accent); }

.field { margin-bottom: var(--gap); }
.field label { display: block; color: var(--muted); font-size: 12px; }
.field textarea { width: 100%; min-height: 60px; }

#category-list { list-style: none; padding: 0; }
#category-list li { display: flex; gap: 6px; align-items: center; margin-bottom: 6px; }

@media (prefers-color-scheme: dark) {
  :root { --bg: #191919; --fg: #e9e9e7; --muted: #8f8f8f; --line: #333; }
  input, select, textarea, button, .group, #next-line { background: #222; }
}
```

- [ ] **Step 3: API 래퍼 작성**

`static/js/api.js`:
```javascript
// 서버 통신 전담. 다른 모듈은 fetch 를 직접 부르지 않음
const JSON_HEADERS = { "Content-Type": "application/json" };

async function request(method, path, body) {
  const options = { method };
  if (body !== undefined) {
    options.headers = JSON_HEADERS;
    options.body = JSON.stringify(body);
  }
  const response = await fetch(`/api${path}`, options);
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    throw new Error(payload?.error ?? `요청 실패 (${response.status})`);
  }
  return payload;
}

export const getTree = (groupBy) => request("GET", `/tree?group_by=${groupBy}`);
export const getNext = () => request("GET", "/next");
export const getDoneToday = (date) =>
  request("GET", date ? `/done-today?date=${date}` : "/done-today");
export const getCategories = () => request("GET", "/categories");
export const getWorkspace = (id) => request("GET", `/workspaces/${id}`);

export const createCategory = (name) => request("POST", "/categories", { name });
export const renameCategory = (id, name) => request("PATCH", `/categories/${id}`, { name });
export const deleteCategory = (id) => request("DELETE", `/categories/${id}`);

export const createWorkspace = (fields) => request("POST", "/workspaces", fields);
export const updateWorkspace = (id, fields) => request("PATCH", `/workspaces/${id}`, fields);
export const deleteWorkspace = (id) => request("DELETE", `/workspaces/${id}`);

export const createTodo = (fields) => request("POST", "/todos", fields);
export const updateTodo = (id, fields) => request("PATCH", `/todos/${id}`, fields);
export const deleteTodo = (id) => request("DELETE", `/todos/${id}`);

export const createSubtask = (todoId, title) =>
  request("POST", "/subtasks", { todo_id: todoId, title });
export const updateSubtask = (id, fields) => request("PATCH", `/subtasks/${id}`, fields);
export const deleteSubtask = (id) => request("DELETE", `/subtasks/${id}`);

export const reorder = (kind, ids, scopeId) =>
  request("POST", "/reorder", { kind, ids, scope_id: scopeId ?? null });
```

- [ ] **Step 4: 탭 전환과 초기 로드 작성**

`static/js/main.js`:
```javascript
// 탭 전환과 에러 표시. 각 탭 내용은 해당 모듈이 그림
import { renderBoard } from "./board.js";
import { renderCategories } from "./categories.js";
import { renderWorkspaceTab } from "./workspace.js";

const RENDERERS = {
  board: renderBoard,
  workspace: renderWorkspaceTab,
  categories: renderCategories,
};

export function showError(message) {
  const box = document.getElementById("error");
  box.textContent = message;
  box.hidden = !message;
}

export async function run(action) {
  try {
    showError("");
    await action();
  } catch (error) {
    showError(error.message);
  }
}

function showTab(name) {
  document.querySelectorAll("#tabs button").forEach((button) => {
    button.classList.toggle("active", button.dataset.tab === name);
  });
  Object.keys(RENDERERS).forEach((key) => {
    document.getElementById(`tab-${key}`).hidden = key !== name;
  });
  run(RENDERERS[name]);
}

document.getElementById("tabs").addEventListener("click", (event) => {
  const tab = event.target.dataset?.tab;
  if (tab) showTab(tab);
});

showTab("board");
```

- [ ] **Step 5: 서빙 확인**

```bash
WORK_DASHBOARD_DB=/tmp/smoke.db python3 server.py --port 8099 &
sleep 1
curl -s -o /dev/null -w '%{http_code} ' http://127.0.0.1:8099/
curl -s -o /dev/null -w '%{http_code} ' http://127.0.0.1:8099/css/app.css
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8099/js/api.js
kill %1
```
Expected: `200 200 200`

- [ ] **Step 6: 커밋**

```bash
git add static
git commit -m "feat: 프론트엔드 골격과 API 래퍼 추가"
```

---

### Task 13: board.js — 보드 렌더, 빠른 추가, 상태 토글, 오늘 완료

**Files:**
- Create: `static/js/dnd.js` (자리만), `static/js/board.js`

**Interfaces:**
- Consumes: `api.js`, `main.js`의 `run`, `dnd.js`의 `attachDragHandlers(refresh)`
- Produces: `renderBoard()`, `currentGroupBy()`

- [ ] **Step 1: dnd.js 자리 만들기**

`static/js/dnd.js`:
```javascript
// 드래그 재정렬·이동. Task 14 에서 구현
export function attachDragHandlers() {}
```

- [ ] **Step 2: board.js 작성**

```javascript
// 보드 탭 렌더. 그룹핑 전환, 빠른 추가, 상태 토글, 오늘 완료
import * as api from "./api.js";
import { attachDragHandlers } from "./dnd.js";
import { run } from "./main.js";

const STATUS_CYCLE = { todo: "doing", doing: "done", done: "todo" };
const UNASSIGNED_KIND = "unassigned";
const DONE = "done";

export function currentGroupBy() {
  return document.querySelector('input[name="group-by"]:checked').value;
}

function showDone() {
  return document.getElementById("show-done").checked;
}

export async function renderBoard() {
  const [tree, next, categories, doneToday] = await Promise.all([
    api.getTree(currentGroupBy()),
    api.getNext(),
    api.getCategories(),
    api.getDoneToday(),
  ]);
  renderNext(next);
  renderCategoryOptions(categories);
  renderGroups(tree.groups);
  renderDoneToday(doneToday);
  attachDragHandlers(renderBoard);
}

function renderNext(next) {
  const target = document.getElementById("next-text");
  if (!next) {
    target.textContent = "없음";
    return;
  }
  const scope = next.workspace ? next.workspace.name : "미분류";
  target.textContent = `${scope} / ${next.todo.title}`;
}

function renderCategoryOptions(categories) {
  const select = document.getElementById("quick-category");
  const rendered = categories
    .map((category) => `<option value="${category.id}">${category.name}</option>`)
    .join("");
  if (select.innerHTML !== rendered) select.innerHTML = rendered;
}

function renderGroups(groups) {
  const container = document.getElementById("groups");
  container.innerHTML = "";
  groups.forEach((group) => container.appendChild(groupElement(group)));
}

function groupElement(group) {
  const details = document.createElement("details");
  details.open = true;
  details.className = `group ${group.kind}`;
  details.dataset.groupId = group.id ?? "";
  details.dataset.kind = group.kind;
  if (group.kind !== UNASSIGNED_KIND) details.draggable = true;

  const summary = document.createElement("summary");
  const meta = [group.category_name, `${group.done_count}/${group.total_count}`]
    .filter(Boolean)
    .join("  ");
  summary.innerHTML = `<span>${group.name}</span><span class="group-meta">${meta}</span>`;
  details.appendChild(summary);

  group.todos
    .filter((todo) => showDone() || todo.status !== DONE)
    .forEach((todo) => {
      details.appendChild(todoElement(todo));
      if (todo.subtasks.length) details.appendChild(subtaskList(todo));
    });
  return details;
}

function todoElement(todo) {
  const row = document.createElement("div");
  row.className = `todo ${todo.status}`;
  row.dataset.todoId = todo.id;
  row.draggable = true;

  const statusButton = document.createElement("button");
  statusButton.textContent = todo.status;
  statusButton.title = "상태 순환 (todo → doing → done)";
  statusButton.addEventListener("click", () =>
    run(async () => {
      await api.updateTodo(todo.id, { status: STATUS_CYCLE[todo.status] });
      await renderBoard();
    })
  );

  const title = document.createElement("span");
  title.className = "title";
  title.textContent = todo.title;

  const addSubtask = document.createElement("button");
  addSubtask.textContent = "+하위";
  addSubtask.addEventListener("click", () =>
    run(async () => {
      const value = prompt("하위 할일 제목");
      if (!value) return;
      await api.createSubtask(todo.id, value);
      await renderBoard();
    })
  );

  const remove = document.createElement("button");
  remove.textContent = "×";
  remove.addEventListener("click", () =>
    run(async () => {
      if (!confirm(`"${todo.title}" 삭제할까요? 하위 할일도 함께 사라집니다.`)) return;
      await api.deleteTodo(todo.id);
      await renderBoard();
    })
  );

  row.append(statusButton, title, addSubtask, remove);
  return row;
}

function subtaskList(todo) {
  const list = document.createElement("ul");
  list.className = "subtasks";
  todo.subtasks.forEach((subtask) => {
    const item = document.createElement("li");
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = subtask.status === DONE;
    checkbox.addEventListener("change", () =>
      run(async () => {
        await api.updateSubtask(subtask.id, {
          status: checkbox.checked ? DONE : "todo",
        });
        await renderBoard();
      })
    );
    item.append(checkbox, document.createTextNode(` ${subtask.title}`));
    list.appendChild(item);
  });
  return list;
}

function renderDoneToday(rows) {
  document.querySelector("#done-today summary").textContent = `오늘 완료 ${rows.length}건`;
  document.getElementById("done-list").innerHTML = rows
    .map((row) => `<li>${row.workspace_name} / ${row.title}</li>`)
    .join("");
}

document.getElementById("quick-add").addEventListener("submit", (event) => {
  event.preventDefault();
  const title = document.getElementById("quick-title");
  const categoryId = Number(document.getElementById("quick-category").value);
  run(async () => {
    await api.createTodo({ title: title.value, category_id: categoryId });
    title.value = "";
    await renderBoard();
  });
});

document.getElementById("board-controls").addEventListener("change", () => run(renderBoard));
```

- [ ] **Step 3: 브라우저 수동 확인**

```bash
WORK_DASHBOARD_DB=/tmp/smoke.db python3 dash.py add-workspace 개발 "KT 동시성" --goal "락 재설계"
WORK_DASHBOARD_DB=/tmp/smoke.db python3 dash.py add-todo "락 초안" --workspace 1
WORK_DASHBOARD_DB=/tmp/smoke.db python3 server.py --port 8099
```
브라우저에서 `http://127.0.0.1:8099` 확인: 다음에 할 일 한 줄, 그룹과 할일 표시, 상태 버튼 순환, 빠른 추가로 미분류 생성, 그룹핑 라디오 전환, 오늘 완료 건수.

- [ ] **Step 4: 커밋**

```bash
git add static/js/board.js static/js/dnd.js
git commit -m "feat: 보드 렌더·빠른추가·상태토글·오늘완료 추가"
```

---

### Task 14: dnd.js — 드래그 재정렬과 워크스페이스 이동

**Files:**
- Modify: `static/js/dnd.js`

**Interfaces:**
- Consumes: `api.reorder`, `api.updateTodo`, `board.js`의 `currentGroupBy`, `main.js`의 `run`
- Produces: `attachDragHandlers(refresh)` — 렌더 후 호출되어 현재 DOM에 리스너를 붙인다

**규칙:** 그룹 헤더 드래그는 워크스페이스 순위 변경. 할일 드래그는 같은 그룹이면 할일 순서 변경, 다른 그룹이면 워크스페이스 이동. 미분류 그룹은 순위 변경 대상이 아니다. 카테고리 기준 그룹핑에서는 그룹 간 이동을 막는다 — 카테고리는 워크스페이스를 통해서만 바뀐다.

- [ ] **Step 1: 구현**

```javascript
// 드래그 재정렬·이동. 렌더 직후 attachDragHandlers 로 리스너를 붙임
import * as api from "./api.js";
import { currentGroupBy } from "./board.js";
import { run } from "./main.js";

const GROUP_BY_WORKSPACE = "workspace";
const UNASSIGNED_KIND = "unassigned";
const DROP_CLASS = "drop-target";

let dragged = null;

export function attachDragHandlers(refresh) {
  document.querySelectorAll(".group").forEach((group) => {
    attachGroupHandlers(group, refresh);
    group.querySelectorAll(".todo").forEach(attachTodoHandlers);
  });
}

function attachGroupHandlers(group, refresh) {
  group.addEventListener("dragstart", (event) => {
    if (event.target !== group) return;
    dragged = { type: "group", element: group };
    event.stopPropagation();
  });
  group.addEventListener("dragover", (event) => {
    event.preventDefault();
    group.classList.add(DROP_CLASS);
  });
  group.addEventListener("dragleave", () => group.classList.remove(DROP_CLASS));
  group.addEventListener("drop", (event) => {
    event.preventDefault();
    event.stopPropagation();
    group.classList.remove(DROP_CLASS);
    const payload = dragged;
    dragged = null;
    if (!payload) return;
    run(async () => {
      if (payload.type === "group") await dropGroup(payload.element, group);
      else await dropTodo(payload.element, group);
      await refresh();
    });
  });
}

function attachTodoHandlers(todo) {
  todo.addEventListener("dragstart", (event) => {
    dragged = { type: "todo", element: todo };
    event.stopPropagation();
  });
}

async function dropGroup(source, target) {
  if (source === target) return;
  if (currentGroupBy() !== GROUP_BY_WORKSPACE) {
    throw new Error("워크스페이스 기준 그룹핑에서만 순위를 바꿀 수 있습니다");
  }
  if (source.dataset.kind === UNASSIGNED_KIND || target.dataset.kind === UNASSIGNED_KIND) {
    throw new Error("미분류 그룹은 순위를 바꿀 수 없습니다");
  }
  await api.reorder("workspaces", orderedGroupIds(source, target));
}

async function dropTodo(todoElement, group) {
  const todoId = Number(todoElement.dataset.todoId);
  const sourceGroup = todoElement.closest(".group");
  if (sourceGroup === group) {
    const ids = [...group.querySelectorAll(".todo")].map((node) =>
      Number(node.dataset.todoId)
    );
    await api.reorder("todos", ids, scopeOf(group));
    return;
  }
  if (currentGroupBy() !== GROUP_BY_WORKSPACE) {
    throw new Error("카테고리 기준에서는 그룹 간 이동을 할 수 없습니다");
  }
  await api.updateTodo(todoId, { workspace_id: scopeOf(group) });
}

function orderedGroupIds(source, target) {
  const groups = [...document.querySelectorAll(".group")].filter(
    (node) => node.dataset.kind !== UNASSIGNED_KIND
  );
  const ids = groups.map((node) => Number(node.dataset.groupId));
  const from = groups.indexOf(source);
  const to = groups.indexOf(target);
  const [moved] = ids.splice(from, 1);
  ids.splice(to, 0, moved);
  return ids;
}

function scopeOf(group) {
  return group.dataset.kind === UNASSIGNED_KIND ? null : Number(group.dataset.groupId);
}
```

**주의:** `board.js`가 `dnd.js`를, `dnd.js`가 `board.js`의 `currentGroupBy`를 import한다. ES 모듈은 순환 import를 지원하고 호출이 모듈 평가 이후에만 일어나므로 동작한다. 모듈 최상단에서 서로를 호출하면 안 된다.

**주의:** `api.reorder("workspaces", ids)`는 전체 워크스페이스 집합과 일치해야 통과한다. 보드는 빈 워크스페이스를 숨기므로, 숨겨진 워크스페이스가 있으면 재정렬이 `Validation`으로 거부된다. 그래서 `orderedGroupIds`는 서버가 보내준 전체 목록이 아니라 화면의 그룹만 쓴다 — 이 제약은 알려진 한계이며, 에러 메시지가 상단에 그대로 표시된다. 근본 해결은 Task 15 이후 별도 작업으로 남긴다.

- [ ] **Step 2: 브라우저 수동 확인**

서버를 띄우고 확인: 그룹 헤더를 다른 그룹 위로 끌면 순위가 바뀌고 새로고침 후 유지됨(단 빈 워크스페이스가 없을 때). 할일을 다른 그룹으로 끌면 워크스페이스가 바뀜. 미분류 그룹을 끌면 에러 메시지. 카테고리 기준에서 그룹 간 이동 시 에러 메시지.

- [ ] **Step 3: 커밋**

```bash
git add static/js/dnd.js
git commit -m "feat: 드래그 재정렬과 워크스페이스 이동 추가"
```

---

### Task 15: 워크스페이스 전체 목록 API와 workspace.js 상세

Task 14에서 드러난 문제를 여기서 함께 해결한다. 보드 트리는 빈 워크스페이스를 숨기므로 워크스페이스 목록을 트리에서 뽑을 수 없다. 전용 엔드포인트를 추가한다.

**Files:**
- Modify: `server.py` (`GET /api/workspaces` 추가)
- Modify: `tests/test_static.py` (RouteTest에 케이스 추가)
- Create: `static/js/workspace.js`
- Modify: `static/js/dnd.js` (전체 목록 기준 재정렬로 교체)

**Interfaces:**
- Produces:
  - `GET /api/workspaces` → `list[dict]` — 전역 sort_order 순 전체 목록
  - `api.js`의 `getWorkspaces()` (Task 12의 `api.js`에 한 줄 추가)
  - `workspace.js`의 `renderWorkspaceTab()`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_static.py`의 `RouteTest`에 추가:
```python
    def test_workspaces_list_endpoint(self):
        from app.repositories import categories as category_repo
        from app.repositories import workspaces as workspace_repo

        dev = category_repo.get_by_name(self.con, "개발")["id"]
        workspace_repo.create(self.con, dev, "빈 워크스페이스")
        payload = server.route(self.con, "GET", "/api/workspaces", {}, {})
        self.assertEqual([item["name"] for item in payload], ["빈 워크스페이스"])
```

- [ ] **Step 2: 실패 확인**

Run: `python3 -m tests`
Expected: FAIL — `NotFound: 알 수 없는 엔드포인트`

- [ ] **Step 3: 서버에 목록 엔드포인트 추가**

`server.py`의 `_route_get` 안에서 `workspaces` 처리를 아래로 교체:
```python
    if head == "workspaces":
        if item_id:
            return {
                "workspace": workspace_repo.get(con, item_id),
                "todos": todo_repo.list_by_workspace(con, item_id),
            }
        return workspace_repo.list_all(con)
```

- [ ] **Step 4: 통과 확인**

Run: `python3 -m tests`
Expected: PASS (91 tests)

- [ ] **Step 5: api.js에 한 줄 추가**

`static/js/api.js`의 `getWorkspace` 아래에 추가:
```javascript
export const getWorkspaces = () => request("GET", "/workspaces");
```

- [ ] **Step 6: dnd.js를 전체 목록 기준으로 교체**

`orderedGroupIds`와 `dropGroup`을 아래로 교체한다. 화면에 없는 워크스페이스도 순서에 포함시켜야 `reorder`가 통과한다.

```javascript
async function dropGroup(source, target) {
  if (source === target) return;
  if (currentGroupBy() !== GROUP_BY_WORKSPACE) {
    throw new Error("워크스페이스 기준 그룹핑에서만 순위를 바꿀 수 있습니다");
  }
  if (source.dataset.kind === UNASSIGNED_KIND || target.dataset.kind === UNASSIGNED_KIND) {
    throw new Error("미분류 그룹은 순위를 바꿀 수 없습니다");
  }
  const all = await api.getWorkspaces();
  await api.reorder("workspaces", movedOrder(all, source, target));
}

function movedOrder(all, source, target) {
  const ids = all.map((item) => item.id);
  const sourceId = Number(source.dataset.groupId);
  const targetId = Number(target.dataset.groupId);
  const from = ids.indexOf(sourceId);
  const [moved] = ids.splice(from, 1);
  ids.splice(ids.indexOf(targetId), 0, moved);
  return ids;
}
```

`orderedGroupIds` 함수는 제거한다.

- [ ] **Step 7: workspace.js 작성**

```javascript
// 워크스페이스 상세. 네 칸 컨텍스트를 blur 시 저장
import * as api from "./api.js";
import { run } from "./main.js";

const CONTEXT_FIELDS = [
  ["background", "배경"],
  ["purpose", "목적"],
  ["goal", "목표"],
  ["considerations", "추가 고려사항"],
];
const WORKSPACE_STATUSES = ["active", "paused", "done"];

let selectedId = null;

export async function renderWorkspaceTab() {
  const [workspaces, categories] = await Promise.all([
    api.getWorkspaces(),
    api.getCategories(),
  ]);
  const picker = document.getElementById("workspace-picker");
  picker.innerHTML = workspaces
    .map((item) => `<option value="${item.id}">${item.name}</option>`)
    .join("");
  const detail = document.getElementById("workspace-detail");
  if (!workspaces.length) {
    detail.textContent = "워크스페이스가 없습니다. 카테고리 탭에서 만들 수 있습니다.";
    return;
  }
  selectedId = workspaces.some((item) => item.id === selectedId)
    ? selectedId
    : workspaces[0].id;
  picker.value = String(selectedId);
  await renderDetail(categories);
}

async function renderDetail(categories) {
  const { workspace, todos } = await api.getWorkspace(selectedId);
  const container = document.getElementById("workspace-detail");
  container.innerHTML = "";
  container.appendChild(headerRow(workspace, categories));
  CONTEXT_FIELDS.forEach(([key, label]) =>
    container.appendChild(contextField(workspace, key, label))
  );
  container.appendChild(todoList(todos));
  container.appendChild(deleteButton(workspace));
}

function headerRow(workspace, categories) {
  const wrapper = document.createElement("div");
  wrapper.className = "field";

  const name = document.createElement("input");
  name.value = workspace.name;
  name.addEventListener("blur", () => save(workspace.id, { name: name.value }));

  const status = document.createElement("select");
  status.innerHTML = WORKSPACE_STATUSES.map(
    (value) =>
      `<option value="${value}" ${value === workspace.status ? "selected" : ""}>${value}</option>`
  ).join("");
  status.addEventListener("change", () => save(workspace.id, { status: status.value }));

  const category = document.createElement("select");
  category.innerHTML = categories
    .map(
      (item) =>
        `<option value="${item.id}" ${item.id === workspace.category_id ? "selected" : ""}>${item.name}</option>`
    )
    .join("");
  category.addEventListener("change", () =>
    save(workspace.id, { category_id: Number(category.value) })
  );

  const jira = document.createElement("input");
  jira.placeholder = "Jira ID";
  jira.value = workspace.jira_id ?? "";
  jira.addEventListener("blur", () =>
    save(workspace.id, { jira_id: jira.value || null })
  );

  wrapper.append(name, status, category, jira);
  return wrapper;
}

function contextField(workspace, key, label) {
  const wrapper = document.createElement("div");
  wrapper.className = "field";
  const caption = document.createElement("label");
  caption.textContent = label;
  const area = document.createElement("textarea");
  area.value = workspace[key] ?? "";
  area.addEventListener("blur", () => save(workspace.id, { [key]: area.value }));
  wrapper.append(caption, area);
  return wrapper;
}

function todoList(todos) {
  const wrapper = document.createElement("div");
  wrapper.className = "field";
  const caption = document.createElement("label");
  caption.textContent = `할일 ${todos.length}건`;
  const list = document.createElement("ul");
  list.innerHTML = todos
    .map((todo) => `<li>[${todo.status}] ${todo.title}</li>`)
    .join("");
  wrapper.append(caption, list);
  return wrapper;
}

function deleteButton(workspace) {
  const button = document.createElement("button");
  button.textContent = "이 워크스페이스 삭제";
  button.addEventListener("click", () =>
    run(async () => {
      if (!confirm("삭제하면 소속 할일은 미분류로 내려갑니다. 진행할까요?")) return;
      await api.deleteWorkspace(workspace.id);
      selectedId = null;
      await renderWorkspaceTab();
    })
  );
  return button;
}

function save(id, fields) {
  run(async () => {
    await api.updateWorkspace(id, fields);
    await renderWorkspaceTab();
  });
}

document.getElementById("workspace-picker").addEventListener("change", (event) => {
  selectedId = Number(event.target.value);
  run(renderWorkspaceTab);
});
```

- [ ] **Step 8: 브라우저 수동 확인**

워크스페이스 탭에서 네 칸을 채우고 포커스를 옮기면 저장되는지, 새로고침 후 유지되는지, 카테고리를 바꾸면 소속 할일의 카테고리도 따라가는지(보드 탭 카테고리 기준으로 확인), 삭제 시 할일이 미분류로 내려가는지. 그리고 빈 워크스페이스가 있는 상태에서 보드의 그룹 순위 드래그가 성공하는지.

- [ ] **Step 9: 커밋**

```bash
git add server.py tests/test_static.py static/js/api.js static/js/dnd.js static/js/workspace.js
git commit -m "feat: 워크스페이스 목록 API와 상세 편집 추가, 재정렬을 전체 목록 기준으로 수정"
```

---

### Task 16: categories.js — 카테고리 관리와 워크스페이스 생성

**Files:**
- Create: `static/js/categories.js`

**Interfaces:**
- Consumes: `api.js`, `main.js`의 `run`
- Produces: `renderCategories()`

**규칙:** 카테고리 추가·이름수정·삭제·순서변경. 각 카테고리 줄에 "워크스페이스 추가" 버튼. 삭제가 409로 거부되면 서버 메시지를 그대로 보여준다.

- [ ] **Step 1: 구현**

```javascript
// 카테고리 관리. 각 줄에서 워크스페이스를 바로 만들 수 있음
import * as api from "./api.js";
import { run } from "./main.js";

export async function renderCategories() {
  const categories = await api.getCategories();
  const list = document.getElementById("category-list");
  list.innerHTML = "";
  categories.forEach((category, index) =>
    list.appendChild(categoryRow(category, index, categories))
  );
}

function categoryRow(category, index, categories) {
  const item = document.createElement("li");

  const name = document.createElement("input");
  name.value = category.name;
  name.addEventListener("blur", () =>
    run(async () => {
      if (name.value === category.name) return;
      await api.renameCategory(category.id, name.value);
      await renderCategories();
    })
  );

  item.append(
    name,
    moveButton(category, index, categories, -1),
    moveButton(category, index, categories, 1),
    addWorkspaceButton(category),
    removeButton(category)
  );
  return item;
}

function moveButton(category, index, categories, offset) {
  const target = index + offset;
  const button = document.createElement("button");
  button.textContent = offset < 0 ? "↑" : "↓";
  button.disabled = target < 0 || target >= categories.length;
  button.addEventListener("click", () =>
    run(async () => {
      const ids = categories.map((item) => item.id);
      const [moved] = ids.splice(index, 1);
      ids.splice(target, 0, moved);
      await api.reorder("categories", ids);
      await renderCategories();
    })
  );
  return button;
}

function addWorkspaceButton(category) {
  const button = document.createElement("button");
  button.textContent = "워크스페이스 추가";
  button.addEventListener("click", () =>
    run(async () => {
      const name = prompt(`"${category.name}" 에 만들 워크스페이스 이름`);
      if (!name) return;
      await api.createWorkspace({ category_id: category.id, name });
      alert("생성됨. 워크스페이스 탭에서 배경·목적·목표를 채우세요.");
    })
  );
  return button;
}

function removeButton(category) {
  const button = document.createElement("button");
  button.textContent = "×";
  button.addEventListener("click", () =>
    run(async () => {
      await api.deleteCategory(category.id);
      await renderCategories();
    })
  );
  return button;
}

document.getElementById("category-add").addEventListener("submit", (event) => {
  event.preventDefault();
  const input = document.getElementById("category-name");
  run(async () => {
    await api.createCategory(input.value);
    input.value = "";
    await renderCategories();
  });
});
```

- [ ] **Step 2: 브라우저 수동 확인**

카테고리 추가·이름수정·순서변경 동작, 비어 있지 않은 카테고리 삭제 시 "남아 있어 삭제할 수 없음" 메시지가 상단에 표시, 워크스페이스 추가 버튼으로 만든 워크스페이스가 워크스페이스 탭에 나타남.

- [ ] **Step 3: 커밋**

```bash
git add static/js/categories.js
git commit -m "feat: 카테고리 관리와 워크스페이스 생성 추가"
```

---

### Task 17: README

**Files:**
- Create: `README.md`

- [ ] **Step 1: README 작성**

````markdown
# 작업 대시보드

카테고리 > 워크스페이스 > 할일 > 하위할일 4계층으로 작업을 관리하는 1인용 로컬 도구.
사람은 웹으로, Claude는 CLI로 같은 sqlite DB를 쓴다. 외부 의존성 0.

## 실행

```bash
python3 server.py                    # http://127.0.0.1:9080
python3 server.py --host 0.0.0.0     # 폰에서 볼 때 (인증 없음, LAN 노출 주의)
```

## CLI

```bash
python3 dash.py ls                                   # 전체 트리
python3 dash.py next                                 # 다음에 할 일
python3 dash.py add-workspace 개발 "KT 동시성" --goal "락 재설계"
python3 dash.py add-todo "락 초안" --workspace 1
python3 dash.py add-todo "문의 회신" --category 운영   # 미분류로 들어감
python3 dash.py move-todo 3 --workspace none          # 미분류로 내리기
python3 dash.py set-status todo 3 doing
python3 dash.py done-today --json                    # daily-todo 로 넘길 입력
```

## 테스트

```bash
python3 -m tests
```

## 데이터

DB는 `~/.claude/work-dashboard/dash.db`. 환경변수 `WORK_DASHBOARD_DB`로 바꿀 수 있다.

## 구조

```
dash.py / server.py   진입점. 파싱·위임·출력만
app/services/         여러 엔티티에 걸치는 로직 (보드 트리, 계획)
app/repositories/     엔티티별 저장·조회와 정합성 규칙
app/db.py             연결·스키마·트랜잭션
static/               ES 모듈 프론트엔드 (번들러 없음)
```

## 설계 문서

- 설계: `docs/superpowers/specs/2026-07-29-work-dashboard-design.md`
- 구현 계획: `docs/superpowers/plans/2026-07-29-work-dashboard.md`

## 아직 없는 것

- Claude 세션 매핑과 컨텍스트 자동 주입 (②)
- 결정 대기 큐 (③)
- 자율 실행 (④)
- scope-guard 흡수 — 지금은 scope-guard가 자기 `scope.db`를 계속 본다 (②에서 전환)
- 완료 항목 아카이브, 할일 의존성, 카테고리 우선순위
````

- [ ] **Step 2: 전체 테스트 후 커밋**

```bash
python3 -m tests
git add README.md
git commit -m "docs: README 추가"
```

---

## Self-Review

**1. 스펙 커버리지**

| 스펙 요구 | 담당 태스크 |
|-----------|-------------|
| 4계층 CRUD | 3, 4, 5, 6, 7 |
| 워크스페이스 기준 / 카테고리 기준 그룹핑 | 8 |
| 배경·목적·목표·추가 고려사항 | 4, 15 |
| 미분류 그룹, 항상 맨 아래, 비어도 표시 | 8, 13, 14 |
| 빈 그룹 숨김 | 8 |
| 우선순위 = sort_order, 재정렬 1..N | 2, 14, 15, 16 |
| 다음에 할 일 (doing 우선, 미분류 폴백, paused 제외) | 9 |
| 카테고리 정합성 양방향 | 5, 7 |
| 삭제 정책 3종 (카테고리 거부 / 워크스페이스 강등 / 할일 cascade) | 3, 5, 7 |
| completed_at, done-today | 5, 9 |
| daily-todo 연결 경로 | 9, 10, 17 |
| HTTP API 전체 | 11, 15 |
| CLI 전체 | 10 |
| 정적 파일 경로 방어 | 11 |
| 예외 → 상태코드 매핑 | 1, 11 |
| WAL·busy_timeout | 1 |
| 시드 카테고리 6개 | 1 |
| jira_id (scope-guard 연결점 준비) | 1, 4, 10 |
| 3계층 구조와 계층 규칙 | 전 태스크 |
| ES 모듈 프론트엔드 | 12~16 |
| 화면 3탭 (보드 / 워크스페이스 상세 / 카테고리 관리) | 13, 15, 16 |
| 테스트 `python3 -m tests` | 1 |

빠진 항목 없음. `scope_db.py` 수정과 `scope.db` 마이그레이션은 스펙이 ②로 이월했으므로 이 계획에 없는 것이 맞다.

**2. 플레이스홀더 스캔**

TBD·TODO·"적절히 처리" 없음. Task 13이 `dnd.js`를 빈 함수로 먼저 만드는 것은 플레이스홀더가 아니라 import 순환을 피하려는 명시적 2단계 구현이고, Task 14가 같은 파일을 채운다. Task 14가 남긴 재정렬 제약은 Task 15에서 실제로 해결하며 코드까지 제시했다.

**3. 타입·이름 일관성**

- `board.tree(con, group_by)`, `board.GROUP_BY_WORKSPACE`, `board.GROUP_BY_CHOICES` — Task 8 정의, Task 10·11에서 동일하게 사용
- `planning.next_todo(con)` / `planning.done_on(con, date_text)` / `planning.today_text()` — Task 9 정의, Task 10·11·테스트에서 동일
- `todo_repo.reorder(con, ids, workspace_id)` — Task 5 정의, Task 10·11 인자 순서 동일
- `subtask_repo.reorder(con, ids, todo_id)` — Task 6 정의, Task 10·11 동일
- `workspace_repo.list_all(con, status=None)` — Task 4 정의, Task 9는 `status=WORKSPACE_ACTIVE`, Task 15는 인자 없이 호출
- `workspace_repo._validated_assignments(con, fields)` — Task 4는 `(fields)`로 정의하고 Task 7에서 `(con, fields)`로 시그니처를 바꾼다. Task 7이 `update` 호출부까지 함께 교체하도록 명시했다
- `server.status_for` / `server.resolve_static` / `server.route` — Task 11 정의, `tests/test_static.py`에서 동일
- `api.reorder(kind, ids, scopeId)` — Task 12 정의, Task 14·15·16에서 동일
- `api.getWorkspaces()` — Task 15에서 추가, 같은 태스크의 `dnd.js`·`workspace.js`가 사용
- `attachDragHandlers(refresh)` — Task 13에서 빈 함수, Task 14에서 인자 사용. Task 13의 호출부가 `renderBoard`를 넘기므로 일치
- `run(action)` / `showError(message)` — Task 12 정의, Task 13·14·15·16에서 사용

`"workspace"` 문자열이 파이썬(`board.GROUP_BY_WORKSPACE`)과 JS(`dnd.js`의 `GROUP_BY_WORKSPACE`) 양쪽에 중복 정의된다. 언어 경계라 공유할 수단이 없고 값이 하나뿐이므로 그대로 둔다.
