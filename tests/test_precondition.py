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
from app.services import precondition, session_link
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

    def test_todo_detail_carries_parsed_items(self):
        """팝업은 원문이 아니라 항목별 충족 여부를 그린다"""
        todo = todo_repo.create(
            self.con, "할일", workspace_id=self.workspace["id"], precondition=MULTILINE
        )
        items = session_link.todo_detail(self.con, todo["id"])["todo"][
            "precondition_items"
        ]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["kind"], precondition.KIND_COMMAND)
        self.assertIsNone(items[0]["met"])


class PreconditionParseTest(unittest.TestCase):
    """항목별로 쪼개고, 코드가 판정할 수 있는 것만 판정한다"""

    def setUp(self):
        self.con = temp_db()
        self.workspace = workspace_repo.create(self.con, 1, "테스트")

    def _todo(self, title, status="todo"):
        todo = todo_repo.create(self.con, title, workspace_id=self.workspace["id"])
        if status != "todo":
            todo_repo.update(self.con, todo["id"], status=status)
        return todo

    def test_each_line_is_one_item(self):
        items = precondition.parse("첫 조건\n둘째 조건")
        self.assertEqual([item["text"] for item in items], ["첫 조건", "둘째 조건"])

    def test_check_line_attaches_to_the_item_above(self):
        items = precondition.parse(MULTILINE)
        self.assertEqual(len(items), 1)
        self.assertEqual(
            items[0]["command"], "git -C ~/work/work-dashboard worktree list --porcelain"
        )

    def test_todo_reference_is_judged_by_status(self):
        done = self._todo("먼저 할 것", status="done")
        open_todo = self._todo("아직")
        met = precondition.items(self.con, f"#{done['id']} 이 done 일 것")
        unmet = precondition.items(self.con, f"#{open_todo['id']} 이 done 일 것")
        self.assertTrue(met[0]["met"])
        self.assertFalse(unmet[0]["met"])

    def test_missing_todo_is_not_met(self):
        """지워진 할일은 끝난 것과 구분되지 않는다 — 충족으로 보면 안 된다"""
        self.assertFalse(precondition.items(self.con, "#9999 이 done 일 것")[0]["met"])

    def test_free_sentence_is_not_judged(self):
        item = precondition.items(self.con, "기획이 확정될 것")[0]
        self.assertEqual(item["kind"], precondition.KIND_MANUAL)
        self.assertIsNone(item["met"])

    def test_todo_reference_with_a_command_stays_auto(self):
        """힌트의 표준 예시(#id + 확인 명령)가 자동 판정에서 빠지면 안 된다"""
        done = self._todo("먼저", status="done")
        text = f"#{done['id']} 이 done 일 것\n확인: true"
        self.assertEqual(
            precondition.items(self.con, text)[0]["kind"], precondition.KIND_TODO
        )
        self.assertTrue(precondition.all_met(self.con, text))

    def test_all_met_needs_every_item_auto_and_met(self):
        done = self._todo("먼저", status="done")
        self.assertTrue(precondition.all_met(self.con, f"#{done['id']} 끝났을 것"))
        self.assertFalse(
            precondition.all_met(self.con, f"#{done['id']} 끝났을 것\n기획 확정")
        )
        self.assertFalse(precondition.all_met(self.con, ""))

    def test_summary_counts_met_and_manual(self):
        done = self._todo("먼저", status="done")
        summary = precondition.summary(
            self.con, f"#{done['id']} 끝났을 것\n기획 확정\n확인: true"
        )
        self.assertEqual(summary, {"total": 2, "met": 1, "manual": 1})

    def test_command_of_reads_from_the_stored_text(self):
        """화면이 명령 문자열을 보내지 않는다 — 보내면 임의 실행 창구가 된다"""
        self.assertEqual(precondition.command_of(MULTILINE, 0), MULTILINE.split("확인: ")[1])
        self.assertEqual(precondition.command_of(MULTILINE, 5), "")


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
        # 예시는 placeholder 로 보여 준다 (개행은 &#10;). CLI 도움말과 같은 상수를
        # 그대로 쓰므로 이 자리만 한국어로 남는다
        self.assertIn(
            PRECONDITION_EXAMPLE.replace("\n", "&#10;"), INDEX.read_text(encoding="utf-8")
        )


if __name__ == "__main__":
    unittest.main()
