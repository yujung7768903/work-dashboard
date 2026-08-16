"""착수 가능 조건(precondition) 저장·표시·주입."""
import json
import pathlib
import sqlite3
import unittest

import dash
import server
from app.constants import PRECONDITION_EXAMPLE, PRECONDITION_HINT
from app.repositories import todos as todo_repo
from app.repositories import sessions as session_repo
from app.repositories import workspaces as workspace_repo
from app.services import session_link
from tests.support import temp_db, temp_db_path

STATIC = pathlib.Path(__file__).resolve().parent.parent / "static"
INDEX = STATIC / "index.html"
CONDITION = "#30 사용량 대시보드가 done 일 것"
MULTILINE = (
    "work-dashboard 에 미커밋 변경이 남은 워크트리가 없을 것\n"
    "확인: git -C ~/work/work-dashboard worktree list --porcelain"
)


class PreconditionStorageTest(unittest.TestCase):
    def setUp(self):
        self.con = temp_db()
        self.workspace = workspace_repo.create(self.con, 1, "테스트")

    def test_todo_keeps_precondition(self):
        todo = todo_repo.create(
            self.con, "할일", workspace_id=self.workspace["id"], precondition=CONDITION
        )
        self.assertEqual(todo_repo.get(self.con, todo["id"])["precondition"], CONDITION)

    def test_defaults_to_none(self):
        todo = todo_repo.create(self.con, "조건 없음", workspace_id=self.workspace["id"])
        self.assertIsNone(todo["precondition"])

    def test_update_can_set_precondition(self):
        todo = todo_repo.create(self.con, "할일", workspace_id=self.workspace["id"])
        updated = todo_repo.update(self.con, todo["id"], precondition=CONDITION)
        self.assertEqual(updated["precondition"], CONDITION)


class PreconditionMigrationTest(unittest.TestCase):
    def test_existing_db_without_column_is_upgraded(self):
        """컬럼이 없던 시절 DB 도 그냥 열려야 한다. 열리면서 값은 NULL.

        하위할일을 쓰던 DB 로 만든다 — 그 테이블은 열리면서 사라져야 한다
        """
        path = temp_db_path()
        legacy = sqlite3.connect(path)
        legacy.executescript(
            "CREATE TABLE todos(id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " category_id INTEGER, workspace_id INTEGER, title TEXT NOT NULL,"
            " note TEXT, status TEXT NOT NULL DEFAULT 'todo',"
            " sort_order INTEGER NOT NULL, completed_at TEXT,"
            " created_at TEXT NOT NULL, updated_at TEXT NOT NULL);"
            "CREATE TABLE subtasks(id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " todo_id INTEGER NOT NULL, title TEXT NOT NULL,"
            " status TEXT NOT NULL DEFAULT 'todo', sort_order INTEGER NOT NULL,"
            " created_at TEXT NOT NULL);"
            "INSERT INTO todos(category_id, title, status, sort_order,"
            " created_at, updated_at) VALUES(1,'옛 할일','todo',1,'x','x');"
        )
        legacy.commit()
        legacy.close()

        con = temp_db(path)
        columns = {row["name"] for row in con.execute("PRAGMA table_info(todos)")}
        self.assertIn("precondition", columns)
        self.assertIsNone(todo_repo.get(con, 1)["precondition"])
        tables = {
            row["name"]
            for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        self.assertNotIn("subtasks", tables)


class PreconditionInjectionTest(unittest.TestCase):
    def setUp(self):
        self.con = temp_db()
        # 세션에 워크스페이스가 저장되지 않으므로 브랜치 Jira 로 컨텍스트를 되찾는 경로를 씀
        self.workspace = workspace_repo.create(self.con, 1, "테스트", jira_id="AB-1")
        session_repo.register(self.con, "sess-1", cwd="/tmp", git_branch="AB-1")
        session_repo.classify(self.con, "sess-1", workspace_id=self.workspace["id"])

    def test_condition_appears_in_injected_block(self):
        todo_repo.create(
            self.con, "할일", workspace_id=self.workspace["id"], precondition=CONDITION
        )
        block = session_link.render_context(self.con, "sess-1")
        self.assertIn(f"조건: {CONDITION}", block)

    def test_only_first_line_is_injected(self):
        """'확인:' 명령줄까지 넣으면 할일이 많을 때 블록이 불어난다"""
        todo_repo.create(
            self.con, "할일", workspace_id=self.workspace["id"], precondition=MULTILINE
        )
        block = session_link.render_context(self.con, "sess-1")
        self.assertIn("조건: work-dashboard 에 미커밋", block)
        self.assertNotIn("확인: git -C", block)

    def test_no_condition_line_when_absent(self):
        """지침 문구에도 '조건:' 이 들어 있으므로 들여쓴 할일 줄만 본다"""
        todo_repo.create(self.con, "조건 없음", workspace_id=self.workspace["id"])
        block = session_link.render_context(self.con, "sess-1")
        self.assertNotIn("     조건:", block)


class PreconditionPopupTest(unittest.TestCase):
    """팝업 개요 탭이 조건을 그리려면 API 응답에 값이 실려 있어야 한다"""

    def setUp(self):
        self.con = temp_db()
        self.workspace = workspace_repo.create(self.con, 1, "테스트")

    def test_todo_detail_carries_condition(self):
        todo = todo_repo.create(
            self.con, "할일", workspace_id=self.workspace["id"], precondition=MULTILINE
        )
        payload = session_link.todo_detail(self.con, todo["id"])
        self.assertEqual(payload["todo"]["precondition"], MULTILINE)


class PreconditionAddFormTest(unittest.TestCase):
    """화면(할일 추가 폼)에서 넣은 조건·note 가 저장까지 가야 한다.

    서버가 body 의 값을 버리면, 저장 계층 테스트는 전부 통과하면서
    브라우저에서만 값이 사라진다 — 실제로 그랬다.
    """

    def setUp(self):
        self.con = temp_db()

    def test_post_carries_condition_and_note(self):
        created = server.route(
            self.con,
            "POST",
            "/api/todos",
            {},
            {
                "title": "할일",
                "category_id": 1,
                "precondition": CONDITION,
                "note": "컨텍스트",
            },
        )
        stored = todo_repo.get(self.con, created["id"])
        self.assertEqual(stored["precondition"], CONDITION)
        self.assertEqual(stored["note"], "컨텍스트")

    def test_popup_hint_matches_cli_help(self):
        """안내 문구는 CLI 도움말과 같아야 한다.

        두 곳에서 다르게 설명하면 어느 규약이 맞는지 알 수 없다. 화면 쪽 문구는
        static/lang/ko.json 에 있고(index.html 은 키만 갖는다) 상수를 끼워 넣을 수
        없으므로 같은 문장인지 여기서 대조한다
        """
        korean = json.loads((STATIC / "lang" / "ko.json").read_text(encoding="utf-8"))
        self.assertEqual(korean["common.preconditionHint"], PRECONDITION_HINT)
        self.assertIn("common.preconditionHint", INDEX.read_text(encoding="utf-8"))
        self.assertIn(PRECONDITION_HINT, dash.PRECONDITION_HELP)
        # 예시는 placeholder 로 보여 준다. 안내 문구와 같이 사전에서 꺼내 쓰므로
        # 화면 언어를 따라가고, 한국어 값은 CLI 도움말과 같은 상수여야 한다
        self.assertEqual(korean["common.preconditionExample"], PRECONDITION_EXAMPLE)
        self.assertIn(
            'data-i18n-placeholder="common.preconditionExample"',
            INDEX.read_text(encoding="utf-8"),
        )


if __name__ == "__main__":
    unittest.main()
