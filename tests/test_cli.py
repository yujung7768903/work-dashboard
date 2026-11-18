import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

import dash
from app.constants import DB_PATH_ENV, SESSION_ID_ENV
from app.db import connect
from app.repositories import categories as category_repo
from app.repositories import sessions as session_repo
from app.repositories import todos as todo_repo
from app.services import session_message
from tests.support import temp_db_path


class CliTest(unittest.TestCase):
    def setUp(self):
        os.environ[DB_PATH_ENV] = temp_db_path()
        # 테스트를 돌리는 세션의 실제 값이 새어 들어오면 결과가 실행 환경에 좌우된다
        os.environ.pop(SESSION_ID_ENV, None)
        # link-todo·edit-todo 가 세션 이름을 맞추러 `claude agents` 를 부른다 — 여기엔 살아 있는 세션이 없다
        patcher = mock.patch.object(session_message, "live_sessions", lambda claude_bin=None: {})
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        os.environ.pop(DB_PATH_ENV, None)
        os.environ.pop(SESSION_ID_ENV, None)

    def add_todo(self, title, category="운영", note=None):
        """할일 준비 — add-todo 명령은 없다(세션이 할일을 만들지 않는다. 매니저·화면이 만든다)"""
        con = connect()
        category_id = category_repo.get_by_name(con, category)["id"]
        return todo_repo.create(con, title, category_id=category_id, note=note)["id"]

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

    def test_edit_todo_updates_note(self):
        self.add_todo("락", "개발")
        code, out, _ = self.run_cli("edit-todo", "1", "--note", "새 컨텍스트")
        self.assertEqual(code, 0)
        self.assertIn("락", out)
        _, note_out, _ = self.run_cli("show-note", "1")
        self.assertIn("새 컨텍스트", note_out)

    def test_edit_todo_without_any_field_exits_one(self):
        self.add_todo("락", "개발")
        code, _, err = self.run_cli("edit-todo", "1")
        self.assertEqual(code, 1)
        self.assertIn("--title", err)

    def test_rm_category_conflict_exits_one(self):
        self.add_todo("문의", "운영")
        ops_id = 2
        code, _, err = self.run_cli("rm-category", str(ops_id))
        self.assertEqual(code, 1)
        self.assertIn("남아", err)

    def test_rm_category_with_sessions_demands_force(self):
        """세션이 붙어 있으면 무엇이 바뀌는지 알리고 --force 를 요구한다"""
        con = connect()  # 세션 등록은 훅의 일이라 CLI 에 없다
        session_repo.register(con, "sess-cli")
        session_repo.classify(con, "sess-cli", category_name="운영")
        code, _, err = self.run_cli("rm-category", "2")
        self.assertEqual(code, 1)
        self.assertIn("--force", err)
        code, out, _ = self.run_cli("rm-category", "2", "--force")
        self.assertEqual(code, 0)
        self.assertIn("삭제됨", out)

    def test_rm_category_without_occupants_succeeds(self):
        code, out, _ = self.run_cli("rm-category", "2")
        self.assertEqual(code, 0)
        self.assertIn("삭제됨", out)

    def test_unknown_command_exits_nonzero(self):
        with self.assertRaises(SystemExit):
            self.run_cli("nope")

    def test_autorun_request_uses_env_session_when_omitted(self):
        """자율 세션이 `autorun-request "<이유>"` 한 인자만 줘도 자기 세션으로 찾아야 한다"""
        from app.repositories import autorun as autorun_repo

        con = connect()
        self.add_todo("판단 필요한 일", "운영")
        autorun_repo.start_run(con, 1, "env-sess", "job1")
        os.environ[SESSION_ID_ENV] = "env-sess"
        code, out, _ = self.run_cli("autorun-request", "방향이 여러 개인데 note 에 없음")
        self.assertEqual(code, 0)
        self.assertIn("요청 등록", out)
        run = autorun_repo.recent(con, 1)[0]
        self.assertEqual(run["requested_note"], "방향이 여러 개인데 note 에 없음")

    def test_autorun_request_accepts_explicit_session(self):
        from app.repositories import autorun as autorun_repo

        con = connect()
        self.add_todo("판단 필요한 일", "운영")
        autorun_repo.start_run(con, 1, "다른세션", "job1")
        code, _, _ = self.run_cli("autorun-request", "다른세션", "토큰이 필요함")
        self.assertEqual(code, 0)
        self.assertEqual(
            autorun_repo.recent(con, 1)[0]["requested_note"], "토큰이 필요함"
        )

    def test_autorun_request_without_reason_exits_one(self):
        from app.repositories import autorun as autorun_repo

        con = connect()
        self.add_todo("판단 필요한 일", "운영")
        autorun_repo.start_run(con, 1, "다른세션", "job1")
        code, _, err = self.run_cli("autorun-request", "다른세션", "  ")
        self.assertEqual(code, 1)
        self.assertIn("이유", err)

    def test_sessions_empty(self):
        code, out, _ = self.run_cli("sessions")
        self.assertEqual(code, 0)
        self.assertIn("없", out)

    def test_link_todo_without_session_uses_env(self):
        from app.db import connect
        from app.repositories import sessions as session_repo

        session_repo.register(connect(), "env-sess")
        os.environ[SESSION_ID_ENV] = "env-sess"
        self.add_todo("문의", "운영")
        code, out, _ = self.run_cli("link-todo", "1")
        self.assertEqual(code, 0)
        self.assertIn("연결", out)

    def test_link_todo_defaults_to_doing(self):
        from app.db import connect
        from app.repositories import sessions as session_repo
        from app.repositories import todos as todo_repo

        session_repo.register(connect(), "env-sess")
        os.environ[SESSION_ID_ENV] = "env-sess"
        self.add_todo("진행할 일", "운영")
        self.run_cli("link-todo", "1")
        self.assertEqual(todo_repo.get(connect(), 1)["status"], "doing")

    def test_link_todo_with_status_done_closes_it(self):
        """이미 master 에 병합된 작업을 뒤늦게 연결하는 경우"""
        from app.db import connect
        from app.repositories import sessions as session_repo
        from app.repositories import todos as todo_repo

        session_repo.register(connect(), "env-sess")
        os.environ[SESSION_ID_ENV] = "env-sess"
        self.add_todo("이미 끝난 일", "운영")
        code, out, _ = self.run_cli("link-todo", "1", "--status", "done")
        self.assertEqual(code, 0)
        self.assertIn("done", out)
        todo = todo_repo.get(connect(), 1)
        self.assertEqual(todo["status"], "done")
        self.assertIsNotNone(todo["completed_at"])

    def test_link_todo_rejects_unknown_status(self):
        """todo 로 연결하는 것은 연결하지 않은 것과 같은 말이라 받지 않는다"""
        with self.assertRaises(SystemExit):
            self.run_cli("link-todo", "1", "--status", "todo")

    def test_link_todo_renames_the_live_session_after_the_todo(self):
        """이 세션이 할일을 잡으면 `claude agents` 목록의 이름도 `#id | 제목` 이 된다"""
        session_repo.register(connect(), "env-sess")
        os.environ[SESSION_ID_ENV] = "env-sess"
        self.add_todo("세션 이름 맞추기", "운영")
        sent = []
        live = {"env-sess": {"pid": 77, "name": "옛 이름"}}
        with mock.patch.object(
            session_message, "live_sessions", lambda claude_bin=None: live
        ), mock.patch.object(session_message, "deliver", lambda path, line: sent.append((path, line))):
            code, _, _ = self.run_cli("link-todo", "1")
        self.assertEqual(code, 0)
        ((path, line),) = sent
        self.assertTrue(path.endswith("/77.sock"))
        self.assertEqual(json.loads(line)["name"], "#1 | 세션 이름 맞추기")

    def test_edit_todo_title_renames_the_live_session(self):
        session_repo.register(connect(), "env-sess")
        os.environ[SESSION_ID_ENV] = "env-sess"
        self.add_todo("처음 제목", "운영")
        self.run_cli("link-todo", "1")
        sent = []
        live = {"env-sess": {"pid": 77, "name": "#1 | 처음 제목"}}
        with mock.patch.object(
            session_message, "live_sessions", lambda claude_bin=None: live
        ), mock.patch.object(session_message, "deliver", lambda path, line: sent.append(line)):
            self.run_cli("edit-todo", "1", "--title", "고친 제목")
            self.run_cli("edit-todo", "1", "--note", "메모만")  # 제목이 아니면 부르지 않는다
        self.assertEqual([json.loads(line)["name"] for line in sent], ["#1 | 고친 제목"])

    def test_link_todo_connects(self):
        from app.db import connect
        from app.repositories import sessions as session_repo

        session_repo.register(connect(), "cli-sess")
        self.add_todo("문의", "운영")
        code, out, _ = self.run_cli("link-todo", "cli-sess", "1")
        self.assertEqual(code, 0)
        self.assertIn("연결", out)

    def test_removed_commands_are_gone(self):
        """세션이 분류·할일 추가를 하지 않는다 — 분류는 대시보드가, 할일 연결은 매니저가 한다"""
        for command in ("classify", "add-todo", "next", "set-status", "done-today", "add-workspace", "show",
                        "move-todo", "reorder"):
            with self.assertRaises(SystemExit):
                self.run_cli(command)

    def test_show_todo_lists_this_sessions_linked_todos(self):
        session_repo.register(connect(), "env-sess")
        os.environ[SESSION_ID_ENV] = "env-sess"
        self.add_todo("잡은 할일", note="메모")
        self.add_todo("남의 할일")
        self.run_cli("link-todo", "1")
        for argv in (("show-todo",), ("show-todo", "--session"), ("show-todo", "--session", "env-sess")):
            code, out, _ = self.run_cli(*argv)
            self.assertEqual(code, 0)
            self.assertIn("1. [doing] 잡은 할일 (컨텍스트)", out)
            self.assertNotIn("남의 할일", out)

    def test_show_todo_without_linked_todo(self):
        session_repo.register(connect(), "bare-sess")
        code, out, _ = self.run_cli("show-todo", "--session", "bare-sess")
        self.assertEqual(code, 0)
        self.assertIn("없음", out)

    def test_show_note_without_note(self):
        self.add_todo("노트 없음", "운영")
        code, out, _ = self.run_cli("show-note", "1")
        self.assertEqual(code, 0)
        self.assertIn("(없음)", out)

    def test_show_note_missing_exits_one(self):
        code, _, err = self.run_cli("show-note", "9999")
        self.assertEqual(code, 1)
        self.assertIn("찾을 수 없습니다", err)

    def test_statusline_shows_the_linked_todo_and_its_status(self):
        session_repo.register(connect(), "sess-line", cwd="/tmp")
        self.add_todo("락 재설계", "개발")
        self.run_cli("link-todo", "sess-line", "1")
        code, out, _ = self.run_cli("statusline", "sess-line", "--cwd", "/tmp")
        self.assertEqual(code, 0)
        self.assertIn("[doing] 락 재설계", out)

    def test_statusline_clips_a_long_title_and_counts_the_rest(self):
        """한 줄에 다 못 담는다 — 제목은 자르고 나머지는 개수로"""
        session_repo.register(connect(), "sess-line", cwd="/tmp")
        self.add_todo("긴 제목을 가진 할일 하나 여기에 더 길게 붙여서 한 줄을 넘기게 만든 제목 끝", "개발")
        self.add_todo("두 번째", "개발")
        self.run_cli("link-todo", "sess-line", "1")
        self.run_cli("link-todo", "sess-line", "2")
        code, out, _ = self.run_cli("statusline", "sess-line", "--cwd", "/tmp")
        self.assertEqual(code, 0)
        self.assertIn("…", out)
        self.assertIn("+1", out)
        self.assertNotIn("제목 끝", out)

    def test_statusline_marks_read_status_place_port_in_that_order(self):
        session_repo.register(connect(), "sess-line", cwd="/tmp", git_branch="worktree-abc")
        self.add_todo("락 재설계", "개발")
        self.run_cli("link-todo", "sess-line", "1")
        code, out, _ = self.run_cli("statusline", "sess-line", "--cwd", "/tmp")
        self.assertEqual(code, 0)
        self.assertIn("[doing | worktree-abc] 락 재설계", out)

    def test_statusline_prefers_the_worktree_name_over_the_branch(self):
        """세션 DB 의 브랜치는 SessionStart 때 값이라 워크트리로 옮긴 뒤에는 메인 것이다"""
        root = os.path.join(tempfile.mkdtemp(), "repo", ".claude", "worktrees", "wt-a")
        os.makedirs(root)
        session_repo.register(connect(), "sess-line", cwd="/tmp", git_branch="master")
        code, out, _ = self.run_cli("statusline", "sess-line", "--cwd", root)
        self.assertEqual(code, 0)
        self.assertIn("[wt-a]", out)

    def test_statusline_is_silent_when_there_is_nothing_to_show(self):
        """등록 안 된 세션에서도 조용히 끝나야 한다 — 상태줄에 에러가 찍히면 안 된다"""
        code, out, err = self.run_cli("statusline", "sess-none", "--cwd", "/tmp")
        self.assertEqual(code, 0)
        self.assertEqual("", out.strip())
        self.assertEqual("", err.strip())

