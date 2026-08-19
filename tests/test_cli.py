import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

import dash
from app.constants import DB_PATH_ENV, SESSION_ID_ENV
from app.db import connect
from app.repositories import sessions as session_repo
from tests.support import temp_db_path


class CliTest(unittest.TestCase):
    def setUp(self):
        os.environ[DB_PATH_ENV] = temp_db_path()
        # 테스트를 돌리는 세션의 실제 값이 새어 들어오면 결과가 실행 환경에 좌우된다
        os.environ.pop(SESSION_ID_ENV, None)

    def tearDown(self):
        os.environ.pop(DB_PATH_ENV, None)
        os.environ.pop(SESSION_ID_ENV, None)

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

    def test_add_todo_tells_when_not_to_link(self):
        self.run_cli("add-workspace", "개발", "KT 동시성", "--goal", "락 재설계")
        _, out, _ = self.run_cli("add-todo", "나중에 할 일", "--workspace", "1")
        self.assertIn("link-todo 1", out)
        self.assertIn("연결하지 않는다", out)

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

    def test_done_today_json_is_list(self):
        code, out, _ = self.run_cli("done-today", "--json")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out), [])

    def test_set_status_todo_to_done(self):
        self.run_cli("add-todo", "문의", "--category", "운영")
        code, out, _ = self.run_cli("set-status", "todo", "1", "done")
        self.assertEqual(code, 0)
        self.assertIn("done", out)

    def test_autorun_request_uses_env_session_when_omitted(self):
        """자율 세션이 `autorun-request "<이유>"` 한 인자만 줘도 자기 세션으로 찾아야 한다"""
        from app.repositories import autorun as autorun_repo

        con = connect()
        self.run_cli("add-todo", "판단 필요한 일", "--category", "운영")
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
        self.run_cli("add-todo", "판단 필요한 일", "--category", "운영")
        autorun_repo.start_run(con, 1, "다른세션", "job1")
        code, _, _ = self.run_cli("autorun-request", "다른세션", "토큰이 필요함")
        self.assertEqual(code, 0)
        self.assertEqual(
            autorun_repo.recent(con, 1)[0]["requested_note"], "토큰이 필요함"
        )

    def test_autorun_request_without_reason_exits_one(self):
        from app.repositories import autorun as autorun_repo

        con = connect()
        self.run_cli("add-todo", "판단 필요한 일", "--category", "운영")
        autorun_repo.start_run(con, 1, "다른세션", "job1")
        code, _, err = self.run_cli("autorun-request", "다른세션", "  ")
        self.assertEqual(code, 1)
        self.assertIn("이유", err)

    def test_sessions_empty(self):
        code, out, _ = self.run_cli("sessions")
        self.assertEqual(code, 0)
        self.assertIn("없", out)

    def test_classify_and_list(self):
        from app.db import connect
        from app.repositories import sessions as session_repo

        con = connect()
        session_repo.register(con, "cli-sess", cwd="/tmp")
        session_repo.set_last_prompt(con, "cli-sess", "무엇을 하나")
        code, _, _ = self.run_cli("classify", "cli-sess", "--category", "운영")
        self.assertEqual(code, 0)
        code, out, _ = self.run_cli("sessions", "--json")
        payload = json.loads(out)
        self.assertEqual(payload["sessions"][0]["category_name"], "운영")
        self.assertEqual(payload["unclassified_count"], 0)

    def test_classify_unknown_session_exits_one(self):
        code, _, err = self.run_cli("classify", "nope", "--category", "운영")
        self.assertEqual(code, 1)
        self.assertIn("찾을 수 없습니다", err)

    def test_classify_without_session_uses_env(self):
        from app.db import connect
        from app.repositories import sessions as session_repo

        con = connect()
        session_repo.register(con, "env-sess", cwd="/tmp")
        session_repo.set_last_prompt(con, "env-sess", "무엇을 하나")  # 목록은 프롬프트가 있어야 뜬다
        os.environ[SESSION_ID_ENV] = "env-sess"
        code, _, _ = self.run_cli("classify", "--category", "운영")
        self.assertEqual(code, 0)
        code, out, _ = self.run_cli("sessions", "--json")
        self.assertEqual(json.loads(out)["sessions"][0]["category_name"], "운영")

    def test_classify_without_session_or_env_exits_one(self):
        os.environ.pop(SESSION_ID_ENV, None)
        code, _, err = self.run_cli("classify", "--category", "운영")
        self.assertEqual(code, 1)
        self.assertIn(SESSION_ID_ENV, err)

    def test_link_todo_without_session_uses_env(self):
        from app.db import connect
        from app.repositories import sessions as session_repo

        session_repo.register(connect(), "env-sess")
        os.environ[SESSION_ID_ENV] = "env-sess"
        self.run_cli("add-todo", "문의", "--category", "운영")
        code, out, _ = self.run_cli("link-todo", "1")
        self.assertEqual(code, 0)
        self.assertIn("연결", out)

    def test_link_todo_defaults_to_doing(self):
        from app.db import connect
        from app.repositories import sessions as session_repo
        from app.repositories import todos as todo_repo

        session_repo.register(connect(), "env-sess")
        os.environ[SESSION_ID_ENV] = "env-sess"
        self.run_cli("add-todo", "진행할 일", "--category", "운영")
        self.run_cli("link-todo", "1")
        self.assertEqual(todo_repo.get(connect(), 1)["status"], "doing")

    def test_link_todo_with_status_done_closes_it(self):
        """이미 master 에 병합된 작업을 뒤늦게 연결하는 경우"""
        from app.db import connect
        from app.repositories import sessions as session_repo
        from app.repositories import todos as todo_repo

        session_repo.register(connect(), "env-sess")
        os.environ[SESSION_ID_ENV] = "env-sess"
        self.run_cli("add-todo", "이미 끝난 일", "--category", "운영")
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

    def test_bare_session_flag_scopes_to_env_session(self):
        from app.db import connect
        from app.repositories import sessions as session_repo

        self.run_cli("add-workspace", "개발", "KT")
        con = connect()
        session_repo.register(con, "env-sess")
        session_repo.classify(con, "env-sess", workspace_id=1)
        self.run_cli("add-todo", "워크스페이스 할일", "--workspace", "1")
        self.run_cli("add-todo", "남의 할일", "--category", "운영")
        os.environ[SESSION_ID_ENV] = "env-sess"
        code, out, _ = self.run_cli("show-todo", "--session")
        self.assertEqual(code, 0)
        self.assertIn("워크스페이스 할일", out)
        self.assertNotIn("남의 할일", out)

    def test_session_flag_absent_still_lists_everything(self):
        """--session 자체를 빼면 예전대로 전체. 환경변수가 있어도 범위를 좁히지 않는다"""
        self.run_cli("add-todo", "남의 할일", "--category", "운영")
        os.environ[SESSION_ID_ENV] = "env-sess"
        code, out, _ = self.run_cli("show-todo")
        self.assertEqual(code, 0)
        self.assertIn("남의 할일", out)

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
        code, out, _ = self.run_cli("show-note", "1")
        self.assertIn("파일 경계 메모", out)

    def test_add_todo_with_unclassified_session_exits_one(self):
        from app.db import connect
        from app.repositories import sessions as session_repo

        session_repo.register(connect(), "bare-sess")
        code, _, err = self.run_cli("add-todo", "안 됨", "--session", "bare-sess")
        self.assertEqual(code, 1)
        self.assertIn("분류", err)

    def test_show_note_without_note(self):
        self.run_cli("add-todo", "노트 없음", "--category", "운영")
        code, out, _ = self.run_cli("show-note", "1")
        self.assertEqual(code, 0)
        self.assertIn("(없음)", out)

    def test_show_note_missing_exits_one(self):
        code, _, err = self.run_cli("show-note", "9999")
        self.assertEqual(code, 1)
        self.assertIn("찾을 수 없습니다", err)

    def test_show_todo_lists_ids_and_context_marker(self):
        self.run_cli("add-workspace", "개발", "KT")
        self.run_cli("add-todo", "노트 있음", "--workspace", "1", "--note", "메모")
        self.run_cli("add-todo", "노트 없음", "--workspace", "1")
        code, out, _ = self.run_cli("show-todo", "--workspace", "1")
        self.assertEqual(code, 0)
        self.assertIn("1. [todo] 노트 있음 (컨텍스트)", out)
        self.assertIn("2. [todo] 노트 없음", out)
        self.assertNotIn("2. [todo] 노트 없음 (컨텍스트)", out)

    def test_show_todo_empty_scope(self):
        self.run_cli("add-workspace", "개발", "KT")
        code, out, _ = self.run_cli("show-todo", "--workspace", "1")
        self.assertEqual(code, 0)
        self.assertIn("없음", out)

    def test_statusline_shows_the_linked_todo_and_its_status(self):
        session_repo.register(connect(), "sess-line", cwd="/tmp")
        self.run_cli("add-todo", "락 재설계", "--category", "개발")
        self.run_cli("link-todo", "sess-line", "1")
        code, out, _ = self.run_cli("statusline", "sess-line", "--cwd", "/tmp")
        self.assertEqual(code, 0)
        self.assertIn("[doing] 락 재설계", out)

    def test_statusline_clips_a_long_title_and_counts_the_rest(self):
        """한 줄에 다 못 담는다 — 제목은 자르고 나머지는 개수로"""
        session_repo.register(connect(), "sess-line", cwd="/tmp")
        self.run_cli(
            "add-todo",
            "긴 제목을 가진 할일 하나 여기에 더 길게 붙여서 한 줄을 넘기게 만든 제목 끝",
            "--category",
            "개발",
        )
        self.run_cli("add-todo", "두 번째", "--category", "개발")
        self.run_cli("link-todo", "sess-line", "1")
        self.run_cli("link-todo", "sess-line", "2")
        code, out, _ = self.run_cli("statusline", "sess-line", "--cwd", "/tmp")
        self.assertEqual(code, 0)
        self.assertIn("…", out)
        self.assertIn("+1", out)
        self.assertNotIn("제목 끝", out)

    def test_statusline_marks_read_status_place_port_in_that_order(self):
        session_repo.register(connect(), "sess-line", cwd="/tmp", git_branch="worktree-abc")
        self.run_cli("add-todo", "락 재설계", "--category", "개발")
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

