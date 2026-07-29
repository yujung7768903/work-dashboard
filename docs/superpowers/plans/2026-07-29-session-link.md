# ② Claude 세션 연동 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Claude 세션을 자동 등록·분류하고 워크스페이스 배경·목적을 주입하며, 활성 세션을 대시보드에 실시간 표시한다.

**Architecture:** ①의 3계층을 그대로 확장한다. 훅 진입점(`hooks/dash_hook.py`)이 파싱·위임·주입만 하고, `sessions` repository가 저장·상태·정리를, `session_link` service가 주입 컨텍스트 조립을 담당한다. 프론트는 세션 영역만 2초 폴링한다.

**Tech Stack:** Python 3.12 표준 라이브러리(`sqlite3`, `argparse`, `unittest`, `subprocess`). 프론트는 ES 모듈. 외부 의존성 0.

## Global Constraints

- 외부 의존성 0. 프론트엔드 빌드 도구 없음.
- DB 경로: 환경변수 `WORK_DASHBOARD_DB`, 없으면 `~/.claude/work-dashboard/dash.db`.
- 날짜·시각은 ISO8601 UTC (`app.db.now()`).
- 기존 4테이블(`categories`, `workspaces`, `todos`, `subtasks`)은 변경하지 않는다. 추가만 한다.
- 진입점(`dash.py`, `server.py`, `hooks/dash_hook.py`)은 도메인 로직을 갖지 않는다.
- **훅은 절대 작업을 막지 않는다.** 모든 실패에서 `exit 0`, 무출력.
- 예외는 `app/errors.py` 도메인 타입으로. `NotFound`→404, `Conflict`→409, `Validation`→400.
- 파일이 300줄을 넘으면 나눌 자리를 찾는다.
- 주석은 역할·특이사항만. 명사형 또는 음슴체, 한 문장, 마침표 생략 가능.
- 매직넘버 금지. 아래 상수를 `app/constants.py`에 추가한다.
  ```python
  SESSION_STATES = ("working", "idle", "ended")
  STATE_WORKING, STATE_IDLE, STATE_ENDED = SESSION_STATES
  HOOK_EVENTS = ("SessionStart", "UserPromptSubmit", "Stop", "SessionEnd")
  STALE_IDLE_HOURS = 24
  ENDED_RETENTION_DAYS = 7
  LAST_PROMPT_MAX_CHARS = 120
  POLL_INTERVAL_MS = 2000
  JIRA_PATTERN = r"[A-Za-z]+-[0-9]+"
  ```
- 테스트는 `python3 -m tests` 한 방으로 전부 돈다.
- **용어**: 세션의 `category_id IS NULL` = "분류 전". 할일의 `workspace_id IS NULL` = "미분류". 섞지 않는다.

## File Structure

| 파일 | 책임 |
|------|------|
| `app/repositories/sessions.py` | 세션 등록·분류·상태 갱신·정리, `session_todos` 연결 |
| `app/services/session_link.py` | 주입 컨텍스트 조립(분류됨/분류 전), 활성 목록 조립, scope-guard 블록 |
| `hooks/dash_hook.py` | 훅 단일 진입점. 이벤트별 분기, 실패 시 조용히 종료 |
| `static/js/sessions.js` | 활성 세션 렌더 + 2초 폴링 |
| `tests/test_sessions.py` | repository·service 계층 |
| `tests/test_hook.py` | 훅 진입점 서브프로세스 검증 |

수정: `app/constants.py`(상수), `app/db.py`(스키마 2테이블), `dash.py`(명령 3개), `server.py`(엔드포인트 2개), `static/index.html`(세션 영역), `static/js/api.js`·`static/js/board.js`(연결), `static/css/app.css`(스타일), `README.md`(훅 등록·롤백), `~/.claude/skills/scope-guard/scope_db.py`(어댑터 교체), `~/.claude/settings.json`(훅 등록)

---

### Task 1: 스키마와 상수

**Files:**
- Modify: `app/constants.py`, `app/db.py`
- Test: `tests/test_sessions.py` (신규)

**Interfaces:**
- Consumes: `app.db.connect`
- Produces: `sessions`·`session_todos` 테이블, 위 Global Constraints의 상수 전부

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_sessions.py`:
```python
import unittest

from app.constants import SESSION_STATES, STATE_IDLE
from tests.support import temp_db


class SessionSchemaTest(unittest.TestCase):
    def test_creates_session_tables(self):
        con = temp_db()
        names = {
            row["name"]
            for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        self.assertTrue({"sessions", "session_todos"} <= names)

    def test_session_state_default_is_idle(self):
        con = temp_db()
        con.execute(
            "INSERT INTO sessions(claude_session_id, started_at, last_seen_at)"
            " VALUES(?,?,?)",
            ("abc", "2026-07-29T00:00:00+00:00", "2026-07-29T00:00:00+00:00"),
        )
        con.commit()
        row = con.execute("SELECT state FROM sessions").fetchone()
        self.assertEqual(row["state"], STATE_IDLE)

    def test_claude_session_id_is_unique(self):
        import sqlite3

        con = temp_db()
        con.execute(
            "INSERT INTO sessions(claude_session_id, started_at, last_seen_at)"
            " VALUES(?,?,?)",
            ("dup", "t", "t"),
        )
        con.commit()
        with self.assertRaises(sqlite3.IntegrityError):
            con.execute(
                "INSERT INTO sessions(claude_session_id, started_at, last_seen_at)"
                " VALUES(?,?,?)",
                ("dup", "t", "t"),
            )

    def test_states_are_three(self):
        self.assertEqual(SESSION_STATES, ("working", "idle", "ended"))
```

- [ ] **Step 2: 실패 확인**

Run: `python3 -m tests`
Expected: FAIL — `ImportError: cannot import name 'SESSION_STATES'`

- [ ] **Step 3: 최소 구현**

`app/constants.py` 끝에 추가:
```python
SESSION_STATES = ("working", "idle", "ended")
STATE_WORKING, STATE_IDLE, STATE_ENDED = SESSION_STATES
HOOK_EVENTS = ("SessionStart", "UserPromptSubmit", "Stop", "SessionEnd")
STALE_IDLE_HOURS = 24
ENDED_RETENTION_DAYS = 7
LAST_PROMPT_MAX_CHARS = 120
POLL_INTERVAL_MS = 2000
JIRA_PATTERN = r"[A-Za-z]+-[0-9]+"
```

`app/db.py`의 `SCHEMA` 문자열 끝(`meta` 테이블 뒤)에 추가:
```sql
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
```

- [ ] **Step 4: 통과 확인**

Run: `python3 -m tests`
Expected: PASS (103 tests)

- [ ] **Step 5: 커밋**

```bash
git add app/constants.py app/db.py tests/test_sessions.py
git commit -m "feat: 세션 테이블과 상수 추가"
```

---

### Task 2: sessions repository — 등록·상태·마지막 지시

**Files:**
- Create: `app/repositories/sessions.py`
- Modify: `tests/test_sessions.py`

**Interfaces:**
- Consumes: `app.db.now/transaction`, `app.errors`
- Produces:
  - `register(con, claude_session_id, cwd=None, git_branch=None) -> dict` — 없으면 생성, 있으면 `cwd`·`git_branch`·`last_seen_at` 갱신하고 분류 유지
  - `get(con, claude_session_id) -> dict` — 없으면 `NotFound`
  - `find(con, claude_session_id) -> dict | None`
  - `set_state(con, claude_session_id, state) -> dict | None` — 없는 세션이면 `None`(조용히 무시)
  - `set_last_prompt(con, claude_session_id, text) -> dict | None` — `LAST_PROMPT_MAX_CHARS` 로 자름

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_sessions.py`에 추가:
```python
from app.constants import LAST_PROMPT_MAX_CHARS, STATE_ENDED, STATE_WORKING
from app.errors import NotFound, Validation
from app.repositories import sessions as session_repo

SID = "sess-1"


class SessionRepoTest(unittest.TestCase):
    def setUp(self):
        self.con = temp_db()

    def test_register_creates_session(self):
        created = session_repo.register(self.con, SID, cwd="/tmp", git_branch="master")
        self.assertEqual(created["claude_session_id"], SID)
        self.assertEqual(created["state"], STATE_IDLE)
        self.assertEqual(created["cwd"], "/tmp")

    def test_register_twice_updates_and_keeps_classification(self):
        session_repo.register(self.con, SID, cwd="/a")
        self.con.execute(
            "UPDATE sessions SET category_id=1 WHERE claude_session_id=?", (SID,)
        )
        self.con.commit()
        again = session_repo.register(self.con, SID, cwd="/b")
        self.assertEqual(again["cwd"], "/b")
        self.assertEqual(again["category_id"], 1)

    def test_register_rejects_blank_id(self):
        with self.assertRaises(Validation):
            session_repo.register(self.con, "  ")

    def test_get_missing_raises_not_found(self):
        with self.assertRaises(NotFound):
            session_repo.get(self.con, "nope")

    def test_find_missing_returns_none(self):
        self.assertIsNone(session_repo.find(self.con, "nope"))

    def test_set_state_transitions(self):
        session_repo.register(self.con, SID)
        working = session_repo.set_state(self.con, SID, STATE_WORKING)
        self.assertEqual(working["state"], STATE_WORKING)
        ended = session_repo.set_state(self.con, SID, STATE_ENDED)
        self.assertIsNotNone(ended["ended_at"])

    def test_set_state_rejects_unknown(self):
        session_repo.register(self.con, SID)
        with self.assertRaises(Validation):
            session_repo.set_state(self.con, SID, "paused")

    def test_set_state_on_missing_session_is_ignored(self):
        self.assertIsNone(session_repo.set_state(self.con, "gone", STATE_WORKING))

    def test_last_prompt_is_truncated(self):
        session_repo.register(self.con, SID)
        updated = session_repo.set_last_prompt(self.con, SID, "가" * 500)
        self.assertEqual(len(updated["last_prompt"]), LAST_PROMPT_MAX_CHARS)

    def test_last_prompt_collapses_whitespace(self):
        session_repo.register(self.con, SID)
        updated = session_repo.set_last_prompt(self.con, SID, "여러\n줄   지시")
        self.assertEqual(updated["last_prompt"], "여러 줄 지시")
```

- [ ] **Step 2: 실패 확인**

Run: `python3 -m tests`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.repositories.sessions'`

- [ ] **Step 3: 최소 구현**

`app/repositories/sessions.py`:
```python
"""세션 저장·조회. 훅이 부르므로 없는 세션에는 예외 대신 None 을 돌려주는 함수를 따로 둠"""
from app.constants import (
    LAST_PROMPT_MAX_CHARS,
    SESSION_STATES,
    STATE_ENDED,
    STATE_IDLE,
)
from app.db import now, transaction
from app.errors import NotFound, Validation

TABLE = "sessions"


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
```

- [ ] **Step 4: 통과 확인**

Run: `python3 -m tests`
Expected: PASS (113 tests)

- [ ] **Step 5: 커밋**

```bash
git add app/repositories/sessions.py tests/test_sessions.py
git commit -m "feat: 세션 등록·상태·마지막 지시 repository 추가"
```

---

### Task 3: 분류·할일 연결·정리

**Files:**
- Modify: `app/repositories/sessions.py`, `tests/test_sessions.py`

**Interfaces:**
- Consumes: `app.repositories.categories.get_by_name/get`, `app.repositories.workspaces.get`
- Produces:
  - `classify(con, claude_session_id, category_name=None, workspace_id=None) -> dict` — 워크스페이스를 주면 카테고리는 그쪽 것으로 덮어씀. 둘 다 없으면 `Validation`
  - `classify_by_ids(con, session_row_id, category_id=None, workspace_id=None) -> dict` — 대시보드 PATCH 용
  - `link_todo(con, claude_session_id, todo_id) -> None` — 중복은 무시
  - `linked_todo_ids(con, claude_session_id) -> list[int]`
  - `sweep(con) -> dict` — `{"expired": n, "deleted": m}`
  - `list_active(con) -> list[dict]` — `working`/`idle`만, 카테고리·워크스페이스 이름 포함
  - `count_unclassified(con) -> int`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_sessions.py`에 추가:
```python
from datetime import datetime, timedelta, timezone

from app.constants import ENDED_RETENTION_DAYS, STALE_IDLE_HOURS
from app.repositories import categories as category_repo
from app.repositories import todos as todo_repo
from app.repositories import workspaces as workspace_repo


def _ago(**kwargs):
    return (datetime.now(timezone.utc) - timedelta(**kwargs)).isoformat(timespec="seconds")


class SessionClassifyTest(unittest.TestCase):
    def setUp(self):
        self.con = temp_db()
        self.dev = category_repo.get_by_name(self.con, "개발")["id"]
        self.ops = category_repo.get_by_name(self.con, "운영")["id"]
        self.workspace = workspace_repo.create(self.con, self.dev, "KT 동시성")
        session_repo.register(self.con, SID, cwd="/tmp")

    def test_classify_category_only(self):
        result = session_repo.classify(self.con, SID, category_name="운영")
        self.assertEqual(result["category_id"], self.ops)
        self.assertIsNone(result["workspace_id"])

    def test_classify_with_workspace_overrides_category(self):
        result = session_repo.classify(
            self.con, SID, category_name="운영", workspace_id=self.workspace["id"]
        )
        self.assertEqual(result["workspace_id"], self.workspace["id"])
        self.assertEqual(result["category_id"], self.dev)

    def test_classify_requires_something(self):
        with self.assertRaises(Validation):
            session_repo.classify(self.con, SID)

    def test_classify_rejects_unknown_category(self):
        with self.assertRaises(NotFound):
            session_repo.classify(self.con, SID, category_name="없는카테고리")

    def test_classify_rejects_unknown_workspace(self):
        with self.assertRaises(NotFound):
            session_repo.classify(self.con, SID, workspace_id=9999)

    def test_classify_by_ids_for_dashboard(self):
        row_id = session_repo.get(self.con, SID)["id"]
        result = session_repo.classify_by_ids(self.con, row_id, category_id=self.ops)
        self.assertEqual(result["category_id"], self.ops)

    def test_link_todo_ignores_duplicate(self):
        todo = todo_repo.create(self.con, "락", workspace_id=self.workspace["id"])
        session_repo.link_todo(self.con, SID, todo["id"])
        session_repo.link_todo(self.con, SID, todo["id"])
        self.assertEqual(session_repo.linked_todo_ids(self.con, SID), [todo["id"]])

    def test_link_todo_rejects_missing_todo(self):
        with self.assertRaises(NotFound):
            session_repo.link_todo(self.con, SID, 9999)

    def test_count_unclassified(self):
        session_repo.register(self.con, "sess-2")
        session_repo.classify(self.con, SID, category_name="운영")
        self.assertEqual(session_repo.count_unclassified(self.con), 1)

    def test_list_active_carries_names(self):
        session_repo.classify(self.con, SID, workspace_id=self.workspace["id"])
        row = session_repo.list_active(self.con)[0]
        self.assertEqual(row["workspace_name"], "KT 동시성")
        self.assertEqual(row["category_name"], "개발")


class SessionSweepTest(unittest.TestCase):
    def setUp(self):
        self.con = temp_db()
        self.dev = category_repo.get_by_name(self.con, "개발")["id"]
        self.workspace = workspace_repo.create(self.con, self.dev, "KT")

    def _age(self, session_id, last_seen=None, ended_at=None):
        self.con.execute(
            "UPDATE sessions SET last_seen_at=COALESCE(?, last_seen_at),"
            " ended_at=COALESCE(?, ended_at) WHERE claude_session_id=?",
            (last_seen, ended_at, session_id),
        )
        self.con.commit()

    def test_stale_idle_becomes_ended(self):
        session_repo.register(self.con, SID)
        self._age(SID, last_seen=_ago(hours=STALE_IDLE_HOURS + 1))
        session_repo.sweep(self.con)
        self.assertEqual(session_repo.get(self.con, SID)["state"], STATE_ENDED)

    def test_fresh_idle_survives_sweep(self):
        session_repo.register(self.con, SID)
        session_repo.sweep(self.con)
        self.assertEqual(session_repo.get(self.con, SID)["state"], STATE_IDLE)

    def test_ended_without_todo_is_deleted_after_retention(self):
        session_repo.register(self.con, SID)
        session_repo.set_state(self.con, SID, STATE_ENDED)
        self._age(SID, ended_at=_ago(days=ENDED_RETENTION_DAYS + 1))
        session_repo.sweep(self.con)
        self.assertIsNone(session_repo.find(self.con, SID))

    def test_ended_with_todo_survives(self):
        session_repo.register(self.con, SID)
        todo = todo_repo.create(self.con, "락", workspace_id=self.workspace["id"])
        session_repo.link_todo(self.con, SID, todo["id"])
        session_repo.set_state(self.con, SID, STATE_ENDED)
        self._age(SID, ended_at=_ago(days=ENDED_RETENTION_DAYS + 1))
        session_repo.sweep(self.con)
        self.assertIsNotNone(session_repo.find(self.con, SID))

    def test_list_active_excludes_ended(self):
        session_repo.register(self.con, SID)
        session_repo.set_state(self.con, SID, STATE_ENDED)
        self.assertEqual(session_repo.list_active(self.con), [])
```

- [ ] **Step 2: 실패 확인**

Run: `python3 -m tests`
Expected: FAIL — `AttributeError: module 'app.repositories.sessions' has no attribute 'classify'`

- [ ] **Step 3: 최소 구현**

`app/repositories/sessions.py` 상단 import 블록을 아래로 교체 (`STATE_WORKING`과 날짜·repository import 추가):
```python
from datetime import datetime, timedelta, timezone

from app.constants import (
    ENDED_RETENTION_DAYS,
    LAST_PROMPT_MAX_CHARS,
    SESSION_STATES,
    STALE_IDLE_HOURS,
    STATE_ENDED,
    STATE_IDLE,
    STATE_WORKING,
)
from app.db import now, transaction
from app.errors import NotFound, Validation
from app.repositories import categories as category_repo
from app.repositories import workspaces as workspace_repo

TABLE = "sessions"
ACTIVE_STATES = (STATE_WORKING, STATE_IDLE)
```

같은 파일 끝에 추가:
```python
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
    """중복 연결은 무시. PK 가 (session_id, todo_id)"""
    session = get(con, claude_session_id)
    _require_todo(con, todo_id)
    with transaction(con):
        con.execute(
            "INSERT OR IGNORE INTO session_todos(session_id, todo_id, created_at)"
            " VALUES(?,?,?)",
            (session["id"], todo_id, now()),
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
        f" AND state IN ({_placeholders(ACTIVE_STATES)})",
        ACTIVE_STATES,
    ).fetchone()["n"]


def list_active(con):
    """working/idle 만. 카테고리·워크스페이스 이름을 붙여 목록용으로 반환"""
    rows = con.execute(
        f"""SELECT s.*, c.name AS category_name, w.name AS workspace_name
            FROM sessions s
            LEFT JOIN categories c ON c.id = s.category_id
            LEFT JOIN workspaces w ON w.id = s.workspace_id
            WHERE s.state IN ({_placeholders(ACTIVE_STATES)})
            ORDER BY s.last_seen_at DESC""",
        ACTIVE_STATES,
    )
    return [dict(row) for row in rows]


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


def _placeholders(values):
    return ",".join("?" * len(values))


def _ago_text(**kwargs):
    return (datetime.now(timezone.utc) - timedelta(**kwargs)).isoformat(timespec="seconds")
```

- [ ] **Step 4: 통과 확인**

Run: `python3 -m tests`
Expected: PASS (128 tests)

- [ ] **Step 5: 커밋**

```bash
git add app/repositories/sessions.py tests/test_sessions.py
git commit -m "feat: 세션 분류·할일 연결·정리 추가"
```

---

### Task 4: session_link service — 주입 컨텍스트

**Files:**
- Create: `app/services/session_link.py`
- Modify: `tests/test_sessions.py`

**Interfaces:**
- Consumes: `app.repositories.sessions/categories/workspaces/todos`
- Produces:
  - `jira_from_branch(branch) -> str | None`
  - `attach_by_branch(con, claude_session_id, branch) -> dict | None`
  - `render_context(con, claude_session_id) -> str`
  - `active_payload(con) -> dict` — `{"unclassified_count": n, "sessions": [...]}`. 호출 시 `sweep` 수행

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_sessions.py`에 추가:
```python
from app.services import session_link


class SessionLinkTest(unittest.TestCase):
    def setUp(self):
        self.con = temp_db()
        self.dev = category_repo.get_by_name(self.con, "개발")["id"]
        self.workspace = workspace_repo.create(
            self.con, self.dev, "KT 동시성", background="엑셀 충돌",
            purpose="서버사이드 차단", goal="락 재설계", jira_id="KT-1530",
        )

    def test_jira_from_branch(self):
        self.assertEqual(session_link.jira_from_branch("KT-1530-phase1-lock"), "KT-1530")
        self.assertEqual(session_link.jira_from_branch("kt-1530"), "KT-1530")
        self.assertIsNone(session_link.jira_from_branch("master"))
        self.assertIsNone(session_link.jira_from_branch(None))

    def test_attach_by_branch_finds_workspace(self):
        session_repo.register(self.con, SID)
        attached = session_link.attach_by_branch(self.con, SID, "feature/KT-1530-lock")
        self.assertEqual(attached["workspace_id"], self.workspace["id"])

    def test_attach_by_branch_returns_none_without_match(self):
        session_repo.register(self.con, SID)
        self.assertIsNone(session_link.attach_by_branch(self.con, SID, "master"))

    def test_classified_context_has_workspace_fields(self):
        session_repo.register(self.con, SID)
        session_link.attach_by_branch(self.con, SID, "KT-1530")
        text = session_link.render_context(self.con, SID)
        self.assertIn('state="classified"', text)
        self.assertIn("엑셀 충돌", text)
        self.assertIn("락 재설계", text)

    def test_unclassified_context_lists_catalog(self):
        session_repo.register(self.con, SID, cwd="/home/ujung/work")
        text = session_link.render_context(self.con, SID)
        self.assertIn('state="unclassified"', text)
        self.assertIn("개발", text)
        self.assertIn("KT 동시성", text)
        self.assertIn("/home/ujung/work", text)

    def test_context_for_missing_session_is_empty(self):
        self.assertEqual(session_link.render_context(self.con, "gone"), "")

    def test_active_payload_shape(self):
        session_repo.register(self.con, SID)
        payload = session_link.active_payload(self.con)
        self.assertEqual(payload["unclassified_count"], 1)
        self.assertEqual(len(payload["sessions"]), 1)
```

- [ ] **Step 2: 실패 확인**

Run: `python3 -m tests`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.session_link'`

- [ ] **Step 3: 최소 구현**

`app/services/session_link.py`:
```python
"""세션에 주입할 컨텍스트 조립. 여러 엔티티에 걸치므로 service 계층"""
import re

from app.constants import JIRA_PATTERN, WORKSPACE_ACTIVE
from app.repositories import categories as category_repo
from app.repositories import sessions as session_repo
from app.repositories import todos as todo_repo
from app.repositories import workspaces as workspace_repo

BLOCK_OPEN = '<work-dashboard session="{session}" state="{state}">'
BLOCK_CLOSE = "</work-dashboard>"
STATE_CLASSIFIED = "classified"
STATE_UNCLASSIFIED = "unclassified"
CONTEXT_LABELS = (
    ("배경", "background"),
    ("목적", "purpose"),
    ("목표", "goal"),
    ("고려사항", "considerations"),
)
CLASSIFIED_GUIDE = (
    "지침: 이 세션은 위 워크스페이스 작업이다. 배경·목적에 맞게 진행하고 "
    "범위를 벗어나는 작업은 착수 전 사용자에게 확인받는다."
)
UNCLASSIFIED_GUIDE = (
    "지침: 이번 세션을 한 번 분류한다. "
    "(1) 위치와 질문 내용으로 카테고리를 정하고 확인 없이 등록한다. "
    "(2) 관련된 진행 중 워크스페이스가 있다고 판단되면 사용자에게 확인받고 등록한다. "
    "없으면 카테고리만 등록한다. "
    "등록: python3 dash.py classify <session> --category <이름> [--workspace <id>] "
    "코드·문서를 바꾸거나 여러 턴에 걸치거나 산출물이 남는 작업이면 "
    "dash.py add-todo 로 할일을 만들고 dash.py link-todo <session> <todo-id> 로 연결한다. "
    "단발 조회·설명 질문이면 할일을 만들지 않는다."
)


def jira_from_branch(branch):
    """브랜치명 첫 Jira 패턴. 대문자 정규화"""
    match = re.search(JIRA_PATTERN, branch or "")
    return match.group(0).upper() if match else None


def attach_by_branch(con, claude_session_id, branch):
    """브랜치 Jira 로 워크스페이스를 찾으면 확인 없이 분류. 못 찾으면 None"""
    jira = jira_from_branch(branch)
    if not jira:
        return None
    workspace = workspace_repo.get_by_jira(con, jira)
    if not workspace:
        return None
    return session_repo.classify(con, claude_session_id, workspace_id=workspace["id"])


def render_context(con, claude_session_id):
    """주입할 블록. 세션이 없으면 빈 문자열"""
    session = session_repo.find(con, claude_session_id)
    if not session:
        return ""
    if session["workspace_id"]:
        return _classified_block(con, session)
    return _unclassified_block(con, session)


def active_payload(con):
    """폴링 응답. 조회할 때마다 정리도 함께 수행"""
    session_repo.sweep(con)
    return {
        "unclassified_count": session_repo.count_unclassified(con),
        "sessions": session_repo.list_active(con),
    }


def _classified_block(con, session):
    workspace = workspace_repo.get(con, session["workspace_id"])
    category = category_repo.get(con, workspace["category_id"])
    jira = f" [{workspace['jira_id']}]" if workspace["jira_id"] else ""
    lines = [
        BLOCK_OPEN.format(session=session["claude_session_id"], state=STATE_CLASSIFIED),
        f"워크스페이스: {workspace['name']} ({category['name']}){jira}",
    ]
    for label, key in CONTEXT_LABELS:
        lines.append(f"{label}: {workspace[key] or '(미입력)'}")
    lines.append("할일:")
    todos = todo_repo.list_by_workspace(con, workspace["id"])
    if todos:
        for todo in todos:
            lines.append(f"  {todo['sort_order']}. [{todo['status']}] {todo['title']}")
    else:
        lines.append("  (없음)")
    lines.append(CLASSIFIED_GUIDE)
    lines.append(BLOCK_CLOSE)
    return "\n".join(lines)


def _unclassified_block(con, session):
    categories = category_repo.list_all(con)
    names = {row["id"]: row["name"] for row in categories}
    lines = [
        BLOCK_OPEN.format(session=session["claude_session_id"], state=STATE_UNCLASSIFIED),
        f"현재 위치: {session['cwd'] or '(알 수 없음)'}"
        f" (브랜치 {session['git_branch'] or '없음'})",
        "카테고리: " + " / ".join(row["name"] for row in categories),
        "진행 중 워크스페이스:",
    ]
    active = workspace_repo.list_all(con, status=WORKSPACE_ACTIVE)
    if active:
        for workspace in active:
            goal = (workspace["goal"] or "").strip() or "(목표 미입력)"
            category_name = names.get(workspace["category_id"], "?")
            lines.append(
                f"  {workspace['id']}. {workspace['name']} ({category_name}) — {goal}"
            )
    else:
        lines.append("  (없음)")
    lines.append(UNCLASSIFIED_GUIDE)
    lines.append(BLOCK_CLOSE)
    return "\n".join(lines)
```

- [ ] **Step 4: 통과 확인**

Run: `python3 -m tests`
Expected: PASS (135 tests)

- [ ] **Step 5: 커밋**

```bash
git add app/services/session_link.py tests/test_sessions.py
git commit -m "feat: 세션 주입 컨텍스트 조립 service 추가"
```

---

### Task 5: 훅 진입점

**Files:**
- Create: `hooks/dash_hook.py`, `tests/test_hook.py`

**Interfaces:**
- Consumes: `app.db.connect`, `app.repositories.sessions`, `app.services.session_link`
- Produces: `main(argv=None, stdin=None) -> int` — 항상 `0`. 주입할 내용은 stdout

**동작:** stdin JSON 에서 `session_id`·`cwd`·`prompt` 를 읽는다. 브랜치는 `cwd` 에서 `git branch --show-current` 로 얻는다(훅 입력에 브랜치가 없다).

| 이벤트 | 동작 |
|--------|------|
| `SessionStart` | 등록 → 브랜치로 자동 분류 시도 → 컨텍스트 출력 |
| `UserPromptSubmit` | `working` 전환 + `last_prompt` 저장 → 분류 전이면 컨텍스트 출력 |
| `Stop` | `idle` 전환, 출력 없음 |
| `SessionEnd` | `ended` 전환, 출력 없음 |

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_hook.py`:
```python
import json
import os
import subprocess
import sys
import unittest

from app.constants import DB_PATH_ENV, STATE_ENDED, STATE_IDLE, STATE_WORKING
from app.db import connect
from app.repositories import categories as category_repo
from app.repositories import sessions as session_repo
from app.repositories import workspaces as workspace_repo
from tests.support import temp_db_path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOK = os.path.join(ROOT, "hooks", "dash_hook.py")
SID = "hook-sess"


class HookTest(unittest.TestCase):
    def setUp(self):
        self.path = temp_db_path()
        self.env = dict(os.environ, **{DB_PATH_ENV: self.path})
        self.con = connect(self.path)

    def run_hook(self, event, payload, raw=None):
        result = subprocess.run(
            [sys.executable, HOOK, event],
            input=raw if raw is not None else json.dumps(payload),
            capture_output=True,
            text=True,
            env=self.env,
        )
        return result.returncode, result.stdout

    def test_session_start_registers_and_injects_catalog(self):
        code, out = self.run_hook("SessionStart", {"session_id": SID, "cwd": "/tmp"})
        self.assertEqual(code, 0)
        self.assertIn('state="unclassified"', out)
        self.assertIsNotNone(session_repo.find(self.con, SID))

    def test_prompt_submit_sets_working_and_prompt(self):
        self.run_hook("SessionStart", {"session_id": SID, "cwd": "/tmp"})
        code, _ = self.run_hook(
            "UserPromptSubmit", {"session_id": SID, "prompt": "락 확인해줘"}
        )
        self.assertEqual(code, 0)
        session = session_repo.get(self.con, SID)
        self.assertEqual(session["state"], STATE_WORKING)
        self.assertEqual(session["last_prompt"], "락 확인해줘")

    def test_prompt_submit_reinjects_while_unclassified(self):
        self.run_hook("SessionStart", {"session_id": SID, "cwd": "/tmp"})
        _, out = self.run_hook("UserPromptSubmit", {"session_id": SID, "prompt": "x"})
        self.assertIn('state="unclassified"', out)

    def test_prompt_submit_silent_after_classified(self):
        self.run_hook("SessionStart", {"session_id": SID, "cwd": "/tmp"})
        session_repo.classify(self.con, SID, category_name="운영")
        _, out = self.run_hook("UserPromptSubmit", {"session_id": SID, "prompt": "x"})
        self.assertEqual(out.strip(), "")

    def test_stop_sets_idle(self):
        self.run_hook("SessionStart", {"session_id": SID, "cwd": "/tmp"})
        self.run_hook("UserPromptSubmit", {"session_id": SID, "prompt": "x"})
        self.run_hook("Stop", {"session_id": SID})
        self.assertEqual(session_repo.get(self.con, SID)["state"], STATE_IDLE)

    def test_session_end_sets_ended(self):
        self.run_hook("SessionStart", {"session_id": SID, "cwd": "/tmp"})
        self.run_hook("SessionEnd", {"session_id": SID})
        self.assertEqual(session_repo.get(self.con, SID)["state"], STATE_ENDED)

    def test_broken_json_exits_zero_silently(self):
        code, out = self.run_hook("SessionStart", None, raw="{not json")
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "")

    def test_unknown_event_exits_zero_silently(self):
        code, out = self.run_hook("Nope", {"session_id": SID})
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "")

    def test_missing_session_id_exits_zero(self):
        code, out = self.run_hook("SessionStart", {"cwd": "/tmp"})
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "")

    def test_branch_jira_attaches_workspace(self):
        dev = category_repo.get_by_name(self.con, "개발")["id"]
        workspace_repo.create(
            self.con, dev, "KT 동시성", jira_id="KT-1530", background="엑셀 충돌"
        )
        repo_dir = os.path.join(os.path.dirname(self.path), "repo")
        os.makedirs(repo_dir, exist_ok=True)
        subprocess.run(["git", "init", "-q"], cwd=repo_dir, capture_output=True)
        subprocess.run(
            ["git", "checkout", "-q", "-b", "KT-1530-lock"],
            cwd=repo_dir,
            capture_output=True,
        )
        code, out = self.run_hook("SessionStart", {"session_id": SID, "cwd": repo_dir})
        self.assertEqual(code, 0)
        self.assertIn('state="classified"', out)
        self.assertIn("엑셀 충돌", out)
```

- [ ] **Step 2: 실패 확인**

Run: `python3 -m tests`
Expected: FAIL — `can't open file '.../hooks/dash_hook.py'`

- [ ] **Step 3: 최소 구현**

`hooks/dash_hook.py`:
```python
#!/usr/bin/env python3
"""작업 대시보드 훅 진입점. 어떤 실패에서도 exit 0 무출력 — 세션을 막지 않음"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.constants import STATE_ENDED, STATE_IDLE, STATE_WORKING  # noqa: E402
from app.db import connect  # noqa: E402
from app.repositories import sessions as session_repo  # noqa: E402
from app.services import session_link  # noqa: E402

EXIT_OK = 0
GIT_BRANCH_TIMEOUT_SEC = 1


def main(argv=None, stdin=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        return EXIT_OK
    try:
        payload = json.loads((stdin or sys.stdin).read() or "{}")
        session_id = (payload.get("session_id") or "").strip()
        handler = HANDLERS.get(argv[0])
        if not session_id or not handler:
            return EXIT_OK
        text = handler(connect(), session_id, payload)
        if text:
            print(text)
    except Exception:  # 훅 실패가 세션을 막으면 안 됨
        return EXIT_OK
    return EXIT_OK


def _on_session_start(con, session_id, payload):
    cwd = payload.get("cwd") or ""
    branch = _current_branch(cwd)
    session_repo.register(con, session_id, cwd=cwd or None, git_branch=branch)
    session_link.attach_by_branch(con, session_id, branch)
    return session_link.render_context(con, session_id)


def _on_prompt_submit(con, session_id, payload):
    """분류 전이면 지시를 다시 주입. 분류되면 조용해짐"""
    session_repo.set_state(con, session_id, STATE_WORKING)
    session_repo.set_last_prompt(con, session_id, payload.get("prompt") or "")
    session = session_repo.find(con, session_id)
    if not session or session["category_id"]:
        return ""
    return session_link.render_context(con, session_id)


def _on_stop(con, session_id, payload):
    session_repo.set_state(con, session_id, STATE_IDLE)
    return ""


def _on_session_end(con, session_id, payload):
    session_repo.set_state(con, session_id, STATE_ENDED)
    return ""


def _current_branch(cwd):
    """훅 입력에 브랜치가 없어 git 으로 직접 확인. 저장소가 아니면 None"""
    if not cwd or not os.path.isdir(cwd):
        return None
    try:
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=GIT_BRANCH_TIMEOUT_SEC,
        )
    except Exception:
        return None
    return result.stdout.strip() or None


HANDLERS = {
    "SessionStart": _on_session_start,
    "UserPromptSubmit": _on_prompt_submit,
    "Stop": _on_stop,
    "SessionEnd": _on_session_end,
}


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: 통과 확인**

Run: `python3 -m tests`
Expected: PASS (145 tests)

- [ ] **Step 5: 커밋**

```bash
git add hooks/dash_hook.py tests/test_hook.py
git commit -m "feat: 훅 진입점 추가 (등록·상태·자동분류·재주입)"
```

---

### Task 6: CLI 명령 3개

**Files:**
- Modify: `dash.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: `app.repositories.sessions`, `app.services.session_link`
- Produces: `dash.py sessions [--json]`, `dash.py classify <session> --category NAME [--workspace ID]`, `dash.py link-todo <session> <todo-id>`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_cli.py`의 `CliTest` 에 추가:
```python
    def test_sessions_empty(self):
        code, out, _ = self.run_cli("sessions")
        self.assertEqual(code, 0)
        self.assertIn("없", out)

    def test_classify_and_list(self):
        from app.db import connect
        from app.repositories import sessions as session_repo

        session_repo.register(connect(), "cli-sess", cwd="/tmp")
        code, _, _ = self.run_cli("classify", "cli-sess", "--category", "운영")
        self.assertEqual(code, 0)
        code, out, _ = self.run_cli("sessions", "--json")
        payload = json.loads(out)
        self.assertEqual(payload["sessions"][0]["category_name"], "운영")
        self.assertEqual(payload["unclassified_count"], 0)

    def test_classify_unknown_session_exits_one(self):
        code, _, err = self.run_cli("classify", "nope", "--category", "운영")
        self.assertEqual(code, 1)
        self.assertIn("없음", err)

    def test_link_todo_connects(self):
        from app.db import connect
        from app.repositories import sessions as session_repo

        session_repo.register(connect(), "cli-sess")
        self.run_cli("add-todo", "문의", "--category", "운영")
        code, out, _ = self.run_cli("link-todo", "cli-sess", "1")
        self.assertEqual(code, 0)
        self.assertIn("연결", out)
```

- [ ] **Step 2: 실패 확인**

Run: `python3 -m tests`
Expected: FAIL — `SystemExit: 2` (argparse: invalid choice 'sessions')

- [ ] **Step 3: 최소 구현**

`dash.py` 의 import 두 줄을 교체:
```python
from app.repositories import sessions as session_repo
from app.services import board, planning, session_link
```
(기존 `from app.services import board, planning` 를 위 두 줄로 바꾼다)

`_build_parser()` 의 `done_today` 등록 뒤에 추가:
```python
    sessions = sub.add_parser("sessions", help="활성 세션 목록")
    _add_json_flag(sessions)
    sessions.set_defaults(handler=_cmd_sessions)

    classify = sub.add_parser("classify", help="세션 분류 등록")
    classify.add_argument("session")
    classify.add_argument("--category", default=None)
    classify.add_argument("--workspace", type=int, default=None)
    classify.set_defaults(handler=_cmd_classify)

    link_todo = sub.add_parser("link-todo", help="세션이 만든 할일 연결")
    link_todo.add_argument("session")
    link_todo.add_argument("todo_id", type=int)
    link_todo.set_defaults(handler=_cmd_link_todo)
```

`_cmd_done_today` 뒤에 추가:
```python
def _cmd_sessions(con, args):
    payload = session_link.active_payload(con)
    if args.as_json:
        _emit_json(payload)
        return
    if not payload["sessions"]:
        print("돌고 있는 세션이 없음")
    for session in payload["sessions"]:
        scope = session["workspace_name"] or session["category_name"] or "분류 전"
        print(f"[{session['state']}] {scope} / {session['last_prompt'] or '(지시 없음)'}")
    if payload["unclassified_count"]:
        print(f"분류 전 {payload['unclassified_count']}건")


def _cmd_classify(con, args):
    updated = session_repo.classify(
        con, args.session, category_name=args.category, workspace_id=args.workspace
    )
    scope = updated["workspace_id"] or "-"
    print(f"분류됨: category={updated['category_id']} workspace={scope}")


def _cmd_link_todo(con, args):
    session_repo.link_todo(con, args.session, args.todo_id)
    print(f"할일 {args.todo_id} 연결됨")
```

- [ ] **Step 4: 통과 확인**

Run: `python3 -m tests`
Expected: PASS (149 tests)

- [ ] **Step 5: 커밋**

```bash
git add dash.py tests/test_cli.py
git commit -m "feat: sessions·classify·link-todo CLI 추가"
```

---

### Task 7: HTTP 엔드포인트 2개

**Files:**
- Modify: `server.py`, `tests/test_static.py`

**Interfaces:**
- Consumes: `app.repositories.sessions.classify_by_ids`, `app.services.session_link.active_payload`
- Produces: `GET /api/sessions`, `PATCH /api/sessions/<id>`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_static.py`의 `RouteTest` 에 추가:
```python
    def test_sessions_endpoint_shape(self):
        from app.repositories import sessions as session_repo

        session_repo.register(self.con, "route-sess", cwd="/tmp")
        payload = server.route(self.con, "GET", "/api/sessions", {}, {})
        self.assertEqual(payload["unclassified_count"], 1)
        self.assertEqual(len(payload["sessions"]), 1)

    def test_patch_session_classifies(self):
        from app.repositories import sessions as session_repo

        session_repo.register(self.con, "route-sess")
        row_id = session_repo.get(self.con, "route-sess")["id"]
        ops = category_repo.get_by_name(self.con, "운영")["id"]
        payload = server.route(
            self.con, "PATCH", f"/api/sessions/{row_id}", {}, {"category_id": ops}
        )
        self.assertEqual(payload["category_id"], ops)

    def test_patch_session_without_id_is_validation(self):
        with self.assertRaises(Validation):
            server.route(self.con, "PATCH", "/api/sessions", {}, {"category_id": 1})
```

- [ ] **Step 2: 실패 확인**

Run: `python3 -m tests`
Expected: FAIL — `NotFound: 알 수 없는 엔드포인트`

- [ ] **Step 3: 최소 구현**

`server.py` 의 import 를 교체:
```python
from app.repositories import sessions as session_repo
from app.services import board, planning, session_link
```

`_route_get` 의 `workspaces` 블록 뒤에 추가:
```python
    if head == "sessions":
        return session_link.active_payload(con)
```

`_route_patch` 의 `subtasks` 블록 뒤에 추가:
```python
    if head == "sessions":
        return session_repo.classify_by_ids(
            con,
            item_id,
            category_id=body.get("category_id"),
            workspace_id=body.get("workspace_id"),
        )
```

- [ ] **Step 4: 통과 확인**

Run: `python3 -m tests`
Expected: PASS (152 tests)

- [ ] **Step 5: 커밋**

```bash
git add server.py tests/test_static.py
git commit -m "feat: 세션 조회·분류 수정 엔드포인트 추가"
```

---

### Task 8: 세션 영역 UI와 폴링

**Files:**
- Create: `static/js/sessions.js`
- Modify: `static/index.html`, `static/js/api.js`, `static/js/board.js`, `static/css/app.css`

**Interfaces:**
- Consumes: `api.js`
- Produces: `api.getSessions()`, `sessions.js` 의 `renderSessions(onPick)`·`startSessionPolling(onPick)`

- [ ] **Step 1: index.html 에 세션 영역 추가**

`<p id="next-line">…</p>` 바로 뒤에 삽입:
```html
    <div id="session-panel">
      <div id="session-head">
        <span id="session-count">돌고 있는 세션 0</span>
        <span id="session-warn" hidden></span>
      </div>
      <ul id="session-list"></ul>
    </div>
```

- [ ] **Step 2: api.js 에 한 줄 추가**

`getWorkspaces` 아래에 추가:
```javascript
export const getSessions = () => request("GET", "/sessions");
```

- [ ] **Step 3: app.css 끝에 스타일 추가**

```css
#session-panel { background: #fff; border: 1px solid var(--line); border-radius: 6px; padding: 10px; margin: var(--gap) 0; }
#session-head { display: flex; justify-content: space-between; gap: 8px; }
#session-warn { color: #a12222; }
#session-list { list-style: none; margin: 6px 0 0; padding: 0; }
#session-list li { display: flex; gap: 8px; align-items: baseline; padding: 2px 0; }
#session-list li.working { cursor: pointer; }
#session-list li.idle { color: var(--muted); }
#session-list .scope { min-width: 12em; }
#session-list .prompt { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

@media (prefers-color-scheme: dark) {
  #session-panel { background: #222; }
}
```

- [ ] **Step 4: sessions.js 작성**

```javascript
// 활성 세션 영역. 이 영역만 폴링해 편집 중인 입력을 건드리지 않음
import * as api from "./api.js";

const POLL_INTERVAL_MS = 2000;
const WORKING = "working";
const NO_WORKSPACE = "―";
const UNCLASSIFIED_LABEL = "분류 전";

let timer = null;

export async function renderSessions(onPick) {
  const payload = await api.getSessions();
  document.getElementById("session-count").textContent =
    `돌고 있는 세션 ${payload.sessions.length}`;
  const warn = document.getElementById("session-warn");
  warn.hidden = !payload.unclassified_count;
  warn.textContent = payload.unclassified_count
    ? `분류 전 ${payload.unclassified_count}건 ⚠`
    : "";

  const list = document.getElementById("session-list");
  list.innerHTML = "";
  payload.sessions.forEach((session) =>
    list.appendChild(sessionRow(session, onPick))
  );
}

function sessionRow(session, onPick) {
  const item = document.createElement("li");
  item.className = session.state === WORKING ? "working" : "idle";

  const mark = document.createElement("span");
  mark.textContent = session.state === WORKING ? "●" : "○";

  const scope = document.createElement("span");
  scope.className = "scope";
  scope.textContent = session.workspace_name || NO_WORKSPACE;

  const category = document.createElement("span");
  category.textContent = `(${session.category_name || UNCLASSIFIED_LABEL})`;

  const prompt = document.createElement("span");
  prompt.className = "prompt";
  prompt.textContent = session.last_prompt || "";

  item.append(mark, scope, category, prompt);
  if (session.workspace_id && onPick) {
    item.addEventListener("click", () => onPick(session.workspace_id));
  }
  return item;
}

export function startSessionPolling(onPick) {
  if (timer) clearInterval(timer);
  // 폴링 실패는 삼킨다 — 2초마다 배너를 덮어쓰면 다른 조작의 에러가 지워짐
  const tick = () => renderSessions(onPick).catch(() => {});
  tick();
  timer = setInterval(tick, POLL_INTERVAL_MS);
}
```

- [ ] **Step 5: board.js 에서 폴링 시작**

import 에 추가:
```javascript
import { startSessionPolling } from "./sessions.js";
```

`renderBoard()` 의 `attachDragHandlers(renderBoard);` 뒤에 추가:
```javascript
  startSessionPolling(openWorkspace);
```

파일 끝에 추가:
```javascript
function openWorkspace(workspaceId) {
  // 세션 줄 클릭 → 워크스페이스 탭으로 이동
  const picker = document.getElementById("workspace-picker");
  picker.value = String(workspaceId);
  picker.dispatchEvent(new Event("change"));
  document.querySelector('#tabs button[data-tab="workspace"]').click();
}
```

- [ ] **Step 6: 정적 서빙 확인**

```bash
WORK_DASHBOARD_DB=/tmp/session-smoke.db python3 server.py --port 8099 &
sleep 1
curl -s -o /dev/null -w '%{http_code} ' http://127.0.0.1:8099/js/sessions.js
curl -s 'http://127.0.0.1:8099/api/sessions'
kill %1
```
Expected: `200` 과 `{"unclassified_count": 0, "sessions": []}`

- [ ] **Step 7: 브라우저 수동 확인**

세션 영역이 보이고 2초마다 갱신되는지, 다른 터미널에서 Claude 세션을 열면 목록에 나타나는지, `dash.py classify` 로 분류하면 2초 안에 반영되는지, 세션 줄 클릭 시 워크스페이스 탭으로 이동하는지, 서버를 껐다 켜도 화면이 스스로 복구되는지 확인한다.

- [ ] **Step 8: 커밋**

```bash
git add static
git commit -m "feat: 활성 세션 영역과 2초 폴링 추가"
```

---

### Task 9: scope-guard 흡수와 훅 등록

**Files:**
- Modify: `app/services/session_link.py`, `tests/test_sessions.py`, `README.md`
- Modify (저장소 밖): `~/.claude/skills/scope-guard/scope_db.py`, `~/.claude/settings.json`

**Interfaces:**
- Produces: `session_link.scope_guard_block(con, jira_id) -> str` — 기존 `<scope-guard>` 형식 유지

**주의:** `scope_db.py` 와 `settings.json` 은 저장소 밖에 있다. 되돌릴 수 있도록 먼저 백업한다.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_sessions.py` 에 추가:
```python
class ScopeGuardRenderTest(unittest.TestCase):
    def test_scope_block_has_background_goal_and_steps(self):
        con = temp_db()
        dev = category_repo.get_by_name(con, "개발")["id"]
        workspace = workspace_repo.create(
            con, dev, "KT 동시성", background="엑셀 충돌", purpose="차단",
            goal="락 재설계", jira_id="KT-1530",
        )
        todo_repo.create(con, "락 초안", workspace_id=workspace["id"])
        text = session_link.scope_guard_block(con, "kt-1530")
        self.assertIn('<scope-guard active="KT-1530"', text)
        self.assertIn("배경: 엑셀 충돌", text)
        self.assertIn("목표: 락 재설계", text)
        self.assertIn("1. [todo] 락 초안", text)

    def test_scope_block_missing_jira(self):
        con = temp_db()
        self.assertIn('missing="KT-9999"', session_link.scope_guard_block(con, "KT-9999"))
```

- [ ] **Step 2: 실패 확인**

Run: `python3 -m tests`
Expected: FAIL — `AttributeError: module 'app.services.session_link' has no attribute 'scope_guard_block'`

- [ ] **Step 3: service 에 scope-guard 형식 렌더 추가**

`app/services/session_link.py` 끝에 추가:
```python
SCOPE_GUIDE = (
    "지침: 이 브랜치 작업은 위 하위단계 범위 내에서만 진행한다. "
    "범위를 벗어나는 작업은 착수 전 사용자에게 안내하고 확인받는다."
)


def scope_guard_block(con, jira_id):
    """scope-guard 가 쓰던 블록 형식 유지. SKILL.md 를 고치지 않기 위함"""
    normalized = (jira_id or "").upper()
    workspace = workspace_repo.get_by_jira(con, normalized)
    if not workspace:
        return (
            f'<scope-guard missing="{normalized}">\n'
            f"이 브랜치({normalized})에 등록된 워크스페이스가 없다.\n"
            "지침: 첫 응답에서 사용자에게 배경·목적·목표를 물어보고, "
            "답을 받으면 dash.py add-workspace 로 저장한다.\n"
            "</scope-guard>"
        )
    lines = [
        f'<scope-guard active="{normalized}" status="{workspace["status"]}">',
        f"배경: {workspace['background'] or '(미입력)'}",
        f"목적: {workspace['purpose'] or '(미입력)'}",
        f"목표: {workspace['goal'] or '(미입력)'}",
        "하위단계:",
    ]
    todos = todo_repo.list_by_workspace(con, workspace["id"])
    if todos:
        for todo in todos:
            lines.append(f"  {todo['sort_order']}. [{todo['status']}] {todo['title']}")
    else:
        lines.append("  (없음)")
    lines.append(SCOPE_GUIDE)
    lines.append("</scope-guard>")
    return "\n".join(lines)
```

- [ ] **Step 4: 통과 확인**

Run: `python3 -m tests`
Expected: PASS (154 tests)

- [ ] **Step 5: 백업**

```bash
cp ~/.claude/skills/scope-guard/scope_db.py ~/.claude/skills/scope-guard/scope_db.py.bak
cp ~/.claude/scope-guard/scope.db ~/.claude/scope-guard/scope.db.bak
cp ~/.claude/settings.json ~/.claude/settings.json.bak
```

- [ ] **Step 6: scope_db.py 를 어댑터로 교체**

`~/.claude/skills/scope-guard/scope_db.py` 전체를 아래로 교체:
```python
#!/usr/bin/env python3
"""scope-guard: 작업 대시보드(dash.db)를 보는 얇은 어댑터.

목표·하위단계는 이제 대시보드의 워크스페이스·할일이다.
블록 형식은 기존과 같게 유지해 SKILL.md 를 고치지 않는다.
"""
import argparse
import os
import sys

DASHBOARD = os.path.expanduser(
    "~/work-dashboard/.claude/worktrees/work-dashboard-impl"
)
sys.path.insert(0, DASHBOARD)

from app.db import connect  # noqa: E402
from app.repositories import categories as category_repo  # noqa: E402
from app.repositories import todos as todo_repo  # noqa: E402
from app.repositories import workspaces as workspace_repo  # noqa: E402
from app.services import session_link  # noqa: E402

DEFAULT_CATEGORY = "개발"


def cmd_get(args):
    print(session_link.scope_guard_block(connect(), args.jira))


def cmd_set_goal(args):
    """워크스페이스가 없으면 만들고, 있으면 배경·목표를 갱신"""
    con = connect()
    jira = args.jira.upper()
    workspace = workspace_repo.get_by_jira(con, jira)
    if workspace:
        workspace_repo.update(
            con, workspace["id"], background=args.background, goal=args.goal
        )
    else:
        category = category_repo.get_by_name(con, DEFAULT_CATEGORY)
        workspace_repo.create(
            con, category["id"], jira,
            background=args.background, goal=args.goal, jira_id=jira,
        )
    print(f"goal saved: {jira}")


def cmd_set_steps(args):
    """stdin 줄당 하나. 기존 할일을 지우고 새로 넣음"""
    con = connect()
    workspace = _require_workspace(con, args.jira)
    descriptions = [
        line.strip() for line in sys.stdin.read().splitlines() if line.strip()
    ]
    for todo in todo_repo.list_by_workspace(con, workspace["id"]):
        todo_repo.delete(con, todo["id"])
    for description in descriptions:
        todo_repo.create(con, description, workspace_id=workspace["id"])
    print(f"{len(descriptions)} steps saved: {workspace['jira_id']}")


def cmd_set_step_status(args):
    con = connect()
    workspace = _require_workspace(con, args.jira)
    todos = todo_repo.list_by_workspace(con, workspace["id"])
    target = next((t for t in todos if t["sort_order"] == args.seq), None)
    if not target:
        print(f"하위단계 {args.seq} 없음", file=sys.stderr)
        sys.exit(1)
    todo_repo.update(con, target["id"], status=args.status)
    print("updated 1 step(s)")


def cmd_list(args):
    for workspace in workspace_repo.list_all(connect()):
        if not workspace["jira_id"]:
            continue
        print(
            f"{workspace['jira_id']} [{workspace['status']}]"
            f" {(workspace['goal'] or '')[:60]}"
        )


def _require_workspace(con, jira):
    workspace = workspace_repo.get_by_jira(con, jira.upper())
    if not workspace:
        print(f"워크스페이스 없음: {jira}", file=sys.stderr)
        sys.exit(1)
    return workspace


def main():
    parser = argparse.ArgumentParser(description="scope-guard (dash.db 어댑터)")
    sub = parser.add_subparsers(dest="cmd")

    get = sub.add_parser("get")
    get.add_argument("jira")
    get.set_defaults(func=cmd_get)

    set_goal = sub.add_parser("set-goal")
    set_goal.add_argument("jira")
    set_goal.add_argument("--background", default="")
    set_goal.add_argument("--goal", default="")
    set_goal.add_argument("--status", default="active")
    set_goal.set_defaults(func=cmd_set_goal)

    set_steps = sub.add_parser("set-steps")
    set_steps.add_argument("jira")
    set_steps.set_defaults(func=cmd_set_steps)

    set_step_status = sub.add_parser("set-step-status")
    set_step_status.add_argument("jira")
    set_step_status.add_argument("seq", type=int)
    set_step_status.add_argument("status")
    set_step_status.set_defaults(func=cmd_set_step_status)

    listing = sub.add_parser("list")
    listing.set_defaults(func=cmd_list)

    args = parser.parse_args()
    if not getattr(args, "func", None):
        parser.print_help()
        sys.exit(1)
    args.func(args)


if __name__ == "__main__":
    main()
```

- [ ] **Step 7: 어댑터 수동 확인**

```bash
python3 ~/.claude/skills/scope-guard/scope_db.py get KT-1530
python3 ~/.claude/skills/scope-guard/scope_db.py list
```
Expected: `<scope-guard active="KT-1530" status="active">` 블록에 배경·목표와 할일 목록. `list` 에 `KT-1530` 한 줄.

- [ ] **Step 8: settings.json 훅 등록과 scope-guard 훅 제거**

`~/.claude/settings.json` 의 `hooks.SessionStart` 배열에서 `bash ~/.claude/skills/scope-guard/session-inject.sh` 항목을 **삭제**하고, 네 이벤트에 아래를 추가한다(마지막 인자만 이벤트명으로 바꿈).

```json
{"hooks": [{"type": "command", "command": "python3 /home/ujung/work-dashboard/.claude/worktrees/work-dashboard-impl/hooks/dash_hook.py SessionStart", "timeout": 2}]}
```

대상 이벤트: `SessionStart`, `UserPromptSubmit`, `Stop`, `SessionEnd`.

- [ ] **Step 9: 훅 실제 동작 확인**

새 터미널에서 Claude 세션을 열고 아무 질문을 한 뒤:
```bash
python3 dash.py sessions
```
Expected: 새 세션이 목록에 나타나고 `last_prompt` 에 첫 지시가 들어감. 세션 안에는 `<work-dashboard …>` 블록이 주입돼 있음.

- [ ] **Step 10: README 갱신과 커밋**

`README.md` 에 아래를 추가한다.

```markdown
## 세션 연동

Claude 세션이 열리면 훅이 자동 등록하고, 브랜치의 Jira ID가 워크스페이스와 맞으면 배경·목적을 주입한다.
아니면 세션이 스스로 카테고리를 정하고, 관련 워크스페이스가 있으면 확인을 받아 붙는다.

```bash
python3 dash.py sessions                              # 돌고 있는 세션
python3 dash.py classify <session> --category 개발 --workspace 1
python3 dash.py link-todo <session> 3
```

### 롤백

문제가 생기면 아래로 ② 이전 상태로 되돌린다.

1. `cp ~/.claude/settings.json.bak ~/.claude/settings.json`
2. `cp ~/.claude/skills/scope-guard/scope_db.py.bak ~/.claude/skills/scope-guard/scope_db.py`
3. `cp ~/.claude/scope-guard/scope.db.bak ~/.claude/scope-guard/scope.db`
```

```bash
python3 -m tests
git add README.md app/services/session_link.py tests/test_sessions.py
git commit -m "feat: scope-guard 를 dash.db 어댑터로 교체, 훅 등록 절차 문서화"
```

---

## Self-Review

**1. 스펙 커버리지**

| 스펙 요구 | 태스크 |
|-----------|--------|
| `sessions`·`session_todos` 테이블, 기존 4테이블 무변경 | 1 |
| 상수 전부 | 1 |
| 세션 등록·resume 시 분류 유지 | 2 |
| `working`/`idle`/`ended` 전이 | 2 |
| `last_prompt` 한 줄 저장·잘림 | 2 |
| 카테고리만/카테고리+워크스페이스 분류, 워크스페이스 우선 | 3 |
| `session_todos` 연결·중복 무시 | 3 |
| 활성 목록·분류 전 건수 | 3 |
| 정리 정책(24시간 idle, 7일 ended, 할일 있으면 유지) | 3 |
| 브랜치 Jira → 워크스페이스 자동 확정 | 4, 5 |
| 주입 블록 두 갈래(classified/unclassified) | 4 |
| 할일 생성 규칙을 지시문에 포함 | 4 (`UNCLASSIFIED_GUIDE`) |
| 훅 4개, 실패 시 exit 0 무출력 | 5 |
| 분류 전 재주입, 분류되면 멈춤 | 5 |
| CLI `sessions`/`classify`/`link-todo` | 6 |
| `GET /api/sessions`, `PATCH /api/sessions/<id>` | 7 |
| 세션 영역 UI, 2초 폴링, 세션 영역만 갱신 | 8 |
| 줄 클릭 → 워크스페이스 상세 이동 | 8 |
| scope-guard 어댑터, 블록 형식 유지 | 9 |
| `settings.json` 훅 등록·scope-guard 훅 제거 | 9 |
| 롤백 절차 문서화 | 9 |

빠진 항목 없음.

**2. 플레이스홀더 스캔**

TBD·TODO·"적절히 처리" 없음. 모든 코드 단계에 실제 코드가 들어 있다.

**3. 타입·이름 일관성**

- `session_repo.register(con, claude_session_id, cwd=None, git_branch=None)` — Task 2 정의, Task 5·6에서 동일 키워드
- `session_repo.classify(con, claude_session_id, category_name=None, workspace_id=None)` — Task 3 정의, Task 4·6에서 동일
- `session_repo.classify_by_ids(con, session_row_id, category_id=None, workspace_id=None)` — Task 3 정의, Task 7에서 동일
- `session_repo.set_state` / `set_last_prompt` — Task 2 정의, 없는 세션이면 `None` 규약. Task 5가 그 규약에 의존
- `session_link.render_context` / `attach_by_branch` / `active_payload` / `jira_from_branch` / `scope_guard_block` — Task 4·9 정의, Task 5·6·7·9에서 동일
- `api.getSessions()` — Task 8 Step 2에서 추가, 같은 태스크 `sessions.js` 가 사용
- `renderSessions(onPick)` / `startSessionPolling(onPick)` — Task 8 정의, `board.js` 가 `openWorkspace` 를 넘김
- `STATE_WORKING`/`STATE_IDLE`/`STATE_ENDED` — Task 1 정의. **Task 2의 import 목록에는 `STATE_WORKING` 이 없으므로 Task 3 Step 3에서 import 블록을 통째로 교체한다** (해당 단계에 명시)
- `POLL_INTERVAL_MS` 는 `app/constants.py` 와 `sessions.js` 양쪽에 `2000` 으로 중복 정의된다. 언어 경계라 공유 수단이 없고 값이 하나뿐이라 그대로 둔다
