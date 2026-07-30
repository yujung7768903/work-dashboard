import io
import json
import os
import unittest
from contextlib import redirect_stderr, redirect_stdout

import dash
from app.constants import DB_PATH_ENV
from tests.support import temp_db_path


class CliTest(unittest.TestCase):
    def setUp(self):
        os.environ[DB_PATH_ENV] = temp_db_path()

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

    def test_show_unknown_jira_exits_one(self):
        code, _, err = self.run_cli("show", "KT-9999")
        self.assertEqual(code, 1)
        self.assertIn("없음", err)

    def test_rm_category_conflict_exits_one(self):
        self.run_cli("add-todo", "문의", "--category", "운영")
        ops_id = 2
        code, _, err = self.run_cli("rm-category", str(ops_id))
        self.assertEqual(code, 1)
        self.assertIn("남아", err)

    def test_unknown_command_exits_nonzero(self):
        with self.assertRaises(SystemExit):
            self.run_cli("nope")

    def test_done_today_json_is_list(self):
        code, out, _ = self.run_cli("done-today", "--json")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out), [])

    def test_set_status_todo_to_done(self):
        self.run_cli("add-todo", "문의", "--category", "운영")
        code, out, _ = self.run_cli("set-status", "todo", "1", "done")
        self.assertEqual(code, 0)
        self.assertIn("done", out)

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

    def test_add_todo_with_session_uses_its_workspace(self):
        from app.db import connect
        from app.repositories import sessions as session_repo

        self.run_cli("add-workspace", "개발", "KT")
        con = connect()
        session_repo.register(con, "todo-sess")
        session_repo.classify(con, "todo-sess", workspace_id=1)
        code, out, _ = self.run_cli(
            "add-todo", "세션 할일", "--session", "todo-sess", "--note", "파일 경계 메모"
        )
        self.assertEqual(code, 0)
        self.assertIn("세션 할일", out)
        code, out, _ = self.run_cli("show-todo", "1")
        self.assertIn("파일 경계 메모", out)

    def test_add_todo_with_unclassified_session_exits_one(self):
        from app.db import connect
        from app.repositories import sessions as session_repo

        session_repo.register(connect(), "bare-sess")
        code, _, err = self.run_cli("add-todo", "안 됨", "--session", "bare-sess")
        self.assertEqual(code, 1)
        self.assertIn("분류", err)

    def test_show_todo_without_note(self):
        self.run_cli("add-todo", "노트 없음", "--category", "운영")
        code, out, _ = self.run_cli("show-todo", "1")
        self.assertEqual(code, 0)
        self.assertIn("(없음)", out)

    def test_show_todo_missing_exits_one(self):
        code, _, err = self.run_cli("show-todo", "9999")
        self.assertEqual(code, 1)
        self.assertIn("없음", err)

    def test_add_subtask_under_todo(self):
        self.run_cli("add-todo", "문의", "--category", "운영")
        code, out, _ = self.run_cli("add-subtask", "1", "회신 초안")
        self.assertEqual(code, 0)
        self.assertIn("회신 초안", out)
