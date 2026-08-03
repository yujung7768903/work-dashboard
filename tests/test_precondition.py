"""착수 가능 조건(precondition) 저장·표시·주입."""
import sqlite3
import unittest

from app.repositories import subtasks as subtask_repo
from app.repositories import todos as todo_repo
from app.repositories import sessions as session_repo
from app.repositories import workspaces as workspace_repo
from app.services import session_link
from tests.support import temp_db, temp_db_path

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

    def test_subtask_keeps_precondition(self):
        todo = todo_repo.create(self.con, "할일", workspace_id=self.workspace["id"])
        subtask = subtask_repo.create(
            self.con, todo["id"], "하위", precondition=MULTILINE
        )
        self.assertEqual(
            subtask_repo.get(self.con, subtask["id"])["precondition"], MULTILINE
        )

    def test_defaults_to_none(self):
        todo = todo_repo.create(self.con, "조건 없음", workspace_id=self.workspace["id"])
        self.assertIsNone(todo["precondition"])
        subtask = subtask_repo.create(self.con, todo["id"], "하위")
        self.assertIsNone(subtask["precondition"])

    def test_update_can_set_precondition(self):
        todo = todo_repo.create(self.con, "할일", workspace_id=self.workspace["id"])
        updated = todo_repo.update(self.con, todo["id"], precondition=CONDITION)
        self.assertEqual(updated["precondition"], CONDITION)
        subtask = subtask_repo.create(self.con, todo["id"], "하위")
        self.assertEqual(
            subtask_repo.update(self.con, subtask["id"], precondition=CONDITION)[
                "precondition"
            ],
            CONDITION,
        )


class PreconditionMigrationTest(unittest.TestCase):
    def test_existing_db_without_column_is_upgraded(self):
        """컬럼이 없던 시절 DB 도 그냥 열려야 한다. 열리면서 값은 NULL"""
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
        for table in ("todos", "subtasks"):
            columns = {row["name"] for row in con.execute(f"PRAGMA table_info({table})")}
            self.assertIn("precondition", columns, table)
        self.assertIsNone(todo_repo.get(con, 1)["precondition"])


class PreconditionInjectionTest(unittest.TestCase):
    def setUp(self):
        self.con = temp_db()
        self.workspace = workspace_repo.create(self.con, 1, "테스트")
        session_repo.register(self.con, "sess-1", cwd="/tmp")
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

    def test_todo_detail_carries_subtask_conditions(self):
        todo = todo_repo.create(
            self.con, "할일", workspace_id=self.workspace["id"], precondition=CONDITION
        )
        subtask_repo.create(self.con, todo["id"], "하위", precondition=MULTILINE)
        payload = session_link.todo_detail(self.con, todo["id"])
        self.assertEqual(payload["todo"]["precondition"], CONDITION)
        self.assertEqual(payload["todo"]["subtasks"][0]["precondition"], MULTILINE)


if __name__ == "__main__":
    unittest.main()
