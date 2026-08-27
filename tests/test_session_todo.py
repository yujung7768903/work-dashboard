"""세션을 워크스페이스로 분류할 때 할일이 자동으로 생기는지."""
import json
import os
import tempfile
import threading
import unittest
from unittest import mock

import server
from app.constants import (
    AUTO_TODO_NOTE_RAW_TITLE,
    AUTO_TODO_TITLE_CHARS,
    SUMMARY_MAX_CHARS,
)
from app.repositories import categories as category_repo
from app.repositories import sessions as session_repo
from app.repositories import todos as todo_repo
from app.repositories import workspaces as workspace_repo
from app.services import session_link, session_todo, summary, transcript
from tests.support import temp_db

SID = "sess-auto-todo"


def run_inline(case):
    """제목 요약은 뒷일(스레드)이다. 테스트는 스레드를 기다리지 않게 그 자리에서 돌린다"""
    patcher = mock.patch.object(session_todo, "schedule", lambda work: work())
    patcher.start()
    case.addCleanup(patcher.stop)


def _db_path(con):
    return con.execute("PRAGMA database_list").fetchone()["file"]


def write_transcript(session_id, prompts):
    """사람 지시만 담긴 transcript 흉내. root 를 돌려줌"""
    root = tempfile.mkdtemp()
    project = os.path.join(root, "-home-user-work")
    os.makedirs(project)
    with open(os.path.join(project, f"{session_id}.jsonl"), "w", encoding="utf-8") as handle:
        for prompt in prompts:
            handle.write(
                json.dumps({"type": "user", "message": {"content": prompt}}, ensure_ascii=False)
                + "\n"
            )
    return root


class AutoTodoTest(unittest.TestCase):
    """요약을 끈 상태 — 요약이 실패했을 때의 규칙 기반 제목을 확인한다"""

    def setUp(self):
        self.con = temp_db()
        patcher = mock.patch.object(summary, "one_line", return_value=None)
        patcher.start()
        self.addCleanup(patcher.stop)
        run_inline(self)
        dev = category_repo.get_by_name(self.con, "개발")["id"]
        self.workspace = workspace_repo.create(self.con, dev, "대시보드")["id"]
        self.session = session_repo.register(
            self.con, SID, cwd="/home/user/work", git_branch="master"
        )

    def classify(self, prompts, **fields):
        """transcript 를 깔고 분류한 뒤 만들어진 할일(또는 None)"""
        root = write_transcript(SID, prompts) if prompts else tempfile.mkdtemp()
        fields = fields or {"workspace_id": self.workspace}
        session_repo.classify_by_ids(self.con, self.session["id"], **fields)
        return session_todo.ensure_from_session(
            self.con, self.session["id"], fields.get("workspace_id"), root=root
        )

    def test_creates_todo_in_the_workspace(self):
        todo = self.classify(["세션 팝업에 탭을 추가해줘"])
        self.assertEqual(todo["title"], "세션 팝업에 탭을 추가해줘")
        self.assertEqual(todo["workspace_id"], self.workspace)

    def test_links_todo_to_the_session(self):
        todo = self.classify(["탭을 추가해줘"])
        self.assertEqual(session_repo.linked_todo_ids(self.con, SID), [todo["id"]])

    def test_linked_todo_is_doing(self):
        """연결은 착수 선언이므로 보드에서 진행 중으로 보여야 한다"""
        todo = self.classify(["탭을 추가해줘"])
        self.assertEqual(todo_repo.get(self.con, todo["id"])["status"], "doing")

    def test_note_carries_prompts_and_place(self):
        todo = self.classify(["첫 지시", "둘째 지시"])
        self.assertIn("1) 첫 지시", todo["note"])
        self.assertIn("2) 둘째 지시", todo["note"])
        self.assertIn("/home/user/work", todo["note"])
        self.assertIn("master", todo["note"])

    def test_list_marked_lines_do_not_become_the_title(self):
        """목록으로 적은 지시 — 제목은 항목이 아니라 그 앞 문장이다"""
        todo = self.classify(["다음을 해줘\n- 탭 추가\n- 색 맞추기\n- 테스트"])
        self.assertEqual(todo["title"], "다음을 해줘")

    def test_first_sentence_becomes_the_title(self):
        todo = self.classify(
            ["분류하면 할일을 만들어줘. note 도 채워주고. 라벨도 붙여주고"]
        )
        self.assertEqual(todo["title"], "분류하면 할일을 만들어줘.")

    def test_long_title_is_truncated(self):
        todo = self.classify(["가" * 200])
        self.assertEqual(len(todo["title"]), AUTO_TODO_TITLE_CHARS)

    def test_category_only_classification_creates_nothing(self):
        ops = category_repo.get_by_name(self.con, "운영")["id"]
        self.assertIsNone(self.classify(["뭐 좀 알려줘"], category_id=ops))
        self.assertEqual(session_repo.linked_todo_ids(self.con, SID), [])

    def test_session_with_a_todo_is_left_alone(self):
        """이미 잡은 할일이 있으면 그게 이 세션의 작업이다 — 두 줄이 되면 안 된다"""
        existing = todo_repo.create(self.con, "이미 있는 일", workspace_id=self.workspace)
        session_repo.link_todo(self.con, SID, existing["id"])
        self.assertIsNone(self.classify(["새 지시"]))
        self.assertEqual(session_repo.linked_todo_ids(self.con, SID), [existing["id"]])

    def test_reclassifying_moves_the_linked_todo(self):
        """세션의 소속은 연결된 할일에서 파생된다 — 할일을 안 옮기면 저장이 조용히 무시된다"""
        existing = todo_repo.create(self.con, "이미 있는 일", workspace_id=self.workspace)
        session_repo.link_todo(self.con, SID, existing["id"])
        ops = category_repo.get_by_name(self.con, "운영")["id"]
        other = workspace_repo.create(self.con, ops, "다른 방")["id"]
        self.assertIsNone(self.classify(["새 지시"], workspace_id=other))
        moved = todo_repo.get(self.con, existing["id"])
        self.assertEqual((moved["workspace_id"], moved["category_id"]), (other, ops))
        self.assertEqual(
            session_repo.get_by_row_id(self.con, self.session["id"])["workspace_id"], other
        )

    def test_reclassifying_to_the_same_workspace_keeps_the_order(self):
        """같은 곳으로 다시 저장해도 할일이 목록 끝으로 밀리면 안 된다"""
        first = todo_repo.create(self.con, "먼저", workspace_id=self.workspace)
        todo_repo.create(self.con, "나중", workspace_id=self.workspace)
        session_repo.link_todo(self.con, SID, first["id"])
        self.classify(["새 지시"])
        self.assertEqual(todo_repo.get(self.con, first["id"])["sort_order"], first["sort_order"])

    def test_no_prompt_anywhere_creates_nothing(self):
        """transcript 도 없고 지시도 없으면 제목을 지어낼 근거가 없다"""
        self.assertIsNone(self.classify([]))

    def test_falls_back_to_last_prompt_without_transcript(self):
        session_repo.set_last_prompt(self.con, SID, "훅이 남긴 마지막 지시")
        todo = self.classify([])
        self.assertEqual(todo["title"], "훅이 남긴 마지막 지시")

    def test_slash_command_line_is_not_the_title(self):
        todo = self.classify(["<command-name>/model</command-name>", "진짜 지시"])
        self.assertEqual(todo["title"], "진짜 지시")


class SummaryTitleTest(unittest.TestCase):
    """제목은 요약으로 짧게. 다만 요약을 기다리면 분류 저장이 7~8초 멈추므로 뒷일로 돌린다"""

    def setUp(self):
        self.con = temp_db()
        dev = category_repo.get_by_name(self.con, "개발")["id"]
        self.workspace = workspace_repo.create(self.con, dev, "대시보드")["id"]
        self.row_id = session_repo.register(self.con, SID, cwd="/tmp")["id"]
        session_repo.classify_by_ids(self.con, self.row_id, workspace_id=self.workspace)
        self.prompt = "워크스페이스 카드가 완료된 것까지 다 보이는데, 너무 길어져서 접어줘"
        self.root = write_transcript(SID, [self.prompt])

    def create(self, one_line):
        """뒷일을 동기로 돌린 뒤의 (응답에 실린 할일, 요약 반영 후 DB 의 할일)"""
        run_inline(self)
        with mock.patch.object(summary, "one_line", side_effect=one_line) as call:
            created = session_todo.ensure_from_session(
                self.con, self.row_id, self.workspace, root=self.root
            )
        return created, todo_repo.get(self.con, created["id"]), call

    def test_response_does_not_wait_for_summary(self):
        """분류 응답은 요약을 부르기 전에 끝난다 — 화면이 멈추면 안 된다"""
        jobs = []
        with mock.patch.object(session_todo, "schedule", jobs.append), mock.patch.object(
            summary, "one_line", return_value="완료 워크스페이스 접힘 토글"
        ) as call:
            created = session_todo.ensure_from_session(
                self.con, self.row_id, self.workspace, root=self.root
            )
            call.assert_not_called()  # 응답을 만들 때까지 요약은 부르지 않는다
            self.assertEqual(created["title"], self.prompt)
            self.assertTrue(created["needs_title"])
            jobs[0]()  # 뒷일이 돌면 제목이 요약으로 바뀐다
        self.assertEqual(todo_repo.get(self.con, created["id"])["title"], "완료 워크스페이스 접힘 토글")

    def test_background_job_works_from_another_thread(self):
        """뒷일은 다른 스레드에서 돈다 — 요청 스레드의 sqlite 연결을 만지면 거부당한다"""
        jobs = []
        with mock.patch.object(session_todo, "schedule", jobs.append), mock.patch.object(
            summary, "one_line", return_value="요약된 제목"
        ):
            created = session_todo.ensure_from_session(
                self.con, self.row_id, self.workspace, root=self.root
            )
            thread = threading.Thread(target=jobs[0])
            thread.start()
            thread.join(timeout=5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(todo_repo.get(self.con, created["id"])["title"], "요약된 제목")

    def test_summary_becomes_the_title(self):
        created, stored, call = self.create(lambda text: "완료 워크스페이스 접힘 토글")
        self.assertEqual(stored["title"], "완료 워크스페이스 접힘 토글")
        self.assertFalse(stored["needs_title"])
        call.assert_called_once_with(self.prompt)
        self.assertEqual(created["title"], self.prompt)

    def test_note_keeps_the_original_prompt(self):
        """제목이 요약이라 원문은 note 에만 남는다 — 여기서 잃으면 근거가 사라진다"""
        _, stored, _ = self.create(lambda text: "완료 워크스페이스 접힘 토글")
        self.assertIn(self.prompt, stored["note"])
        self.assertNotIn("첫 문장을 그대로", stored["note"])

    def test_failed_summary_leaves_the_mark(self):
        """요약을 못 만든 할일은 보드·팝업에서 구분돼야 한다 (needs_title)"""
        _, stored, _ = self.create(lambda text: None)
        self.assertEqual(stored["title"], self.prompt)
        self.assertTrue(stored["needs_title"])
        self.assertIn(AUTO_TODO_NOTE_RAW_TITLE, stored["note"])

    def test_summary_does_not_overwrite_a_user_edit(self):
        """요약이 도착하기 전에 사용자가 제목을 고쳤으면 그 제목이 이긴다"""
        jobs = []
        with mock.patch.object(session_todo, "schedule", jobs.append):
            created = session_todo.ensure_from_session(
                self.con, self.row_id, self.workspace, root=self.root
            )
        todo_repo.update(self.con, created["id"], title="내가 고친 제목")
        with mock.patch.object(summary, "one_line", return_value="요약된 제목"):
            jobs[0]()
        self.assertEqual(todo_repo.get(self.con, created["id"])["title"], "내가 고친 제목")

    def test_retitle_survives_a_missing_todo(self):
        """뒷일은 응답을 이미 보낸 뒤라 예외가 서버로 올라가면 안 된다"""
        with mock.patch.object(summary, "one_line", return_value="요약된 제목"):
            session_todo.retitle(_db_path(self.con), 9999, "무언가 해줘", "첫 문장")

    def test_retitle_without_db_path_touches_nothing(self):
        """경로가 비면 connect() 가 사용자의 실제 DB 로 떨어진다 — 열지도 말아야 한다"""
        with mock.patch.object(summary, "one_line", return_value="요약된 제목"), mock.patch.object(
            session_todo, "connect"
        ) as opened:
            session_todo.retitle("", 1, "무언가 해줘", "첫 문장")
        opened.assert_not_called()


class SummaryCallTest(unittest.TestCase):
    """요약 호출 자체. 실제 CLI 는 부르지 않는다"""

    def test_clean_keeps_only_a_real_one_line_summary(self):
        for why, raw, expected in (
            ("첫 줄만 남기고 따옴표·마침표 제거", '"할일 자동 생성".\n남는 말\n', "할일 자동 생성"),
            ("설명을 늘어놓으면 요약이 아니다", "가" * (SUMMARY_MAX_CHARS + 1), None),
            ("빈 텍스트", "  \n ", None),
        ):
            with self.subTest(why=why):
                self.assertEqual(summary.clean(raw), expected)

    def test_no_cli_returns_none(self):
        with mock.patch.object(summary.shutil, "which", return_value=None):
            self.assertIsNone(summary.one_line("무언가 해줘"))

    def test_blank_text_is_not_sent(self):
        with mock.patch.object(summary.subprocess, "run") as run:
            self.assertIsNone(summary.one_line("   "))
        run.assert_not_called()

    def test_timeout_returns_none(self):
        with mock.patch.object(summary.shutil, "which", return_value="/bin/claude"), mock.patch.object(
            summary.subprocess, "run", side_effect=summary.subprocess.TimeoutExpired("claude", 1)
        ):
            self.assertIsNone(summary.one_line("무언가 해줘"))

    def test_failed_exit_returns_none_and_says_why(self):
        """실패를 조용히 넘기면 배지만 뜨고 이유를 알 방법이 없다"""
        result = mock.Mock(returncode=1, stdout="제목", stderr="로그인이 필요합니다")
        with mock.patch.object(summary.shutil, "which", return_value="/bin/claude"), mock.patch.object(
            summary.subprocess, "run", return_value=result
        ), mock.patch("builtins.print") as printed:
            self.assertIsNone(summary.one_line("무언가 해줘"))
        self.assertIn("로그인이 필요합니다", printed.call_args[0][0])

    def test_harness_is_disabled_in_the_call(self):
        """도구·MCP·설정을 끄지 않으면 1분이 넘고 지시를 작업으로 착각해 파일을 고친다"""
        result = mock.Mock(returncode=0, stdout="제목\n")
        with mock.patch.object(summary.shutil, "which", return_value="/bin/claude"), mock.patch.object(
            summary.subprocess, "run", return_value=result
        ) as run:
            self.assertEqual(summary.one_line("무언가 해줘"), "제목")
        argv = run.call_args[0][0]
        self.assertIn("--tools", argv)
        self.assertIn("--strict-mcp-config", argv)
        self.assertIn("--setting-sources", argv)
        self.assertEqual(argv[-1], "무언가 해줘")


class RouteTest(unittest.TestCase):
    """웹에서 분류하면(PATCH) 같은 일이 일어나는지"""

    def setUp(self):
        self.con = temp_db()
        patcher = mock.patch.object(summary, "one_line", return_value="요약된 제목")
        patcher.start()
        self.addCleanup(patcher.stop)
        run_inline(self)
        dev = category_repo.get_by_name(self.con, "개발")["id"]
        self.workspace = workspace_repo.create(self.con, dev, "대시보드")["id"]
        self.row_id = session_repo.register(self.con, SID, cwd="/tmp")["id"]

    def patch(self, body):
        root = write_transcript(SID, ["세션 분류할 때 할일도 만들어줘\n- 생성\n- 연결"])
        with mock.patch.object(transcript, "TRANSCRIPT_ROOT", root):
            return server.route(self.con, "PATCH", f"/api/sessions/{self.row_id}", {}, body)

    def test_patch_with_workspace_returns_created_todo(self):
        payload = self.patch({"workspace_id": self.workspace})
        self.assertEqual(payload["workspace_id"], self.workspace)
        # 응답은 요약을 기다리지 않으므로 첫 문장 제목. 요약은 뒷일이 갈아 끼운다
        self.assertEqual(payload["created_todo"]["title"], "세션 분류할 때 할일도 만들어줘")
        created_id = payload["created_todo"]["id"]
        self.assertEqual(todo_repo.get(self.con, created_id)["title"], "요약된 제목")

    def test_patch_with_category_only_creates_nothing(self):
        ops = category_repo.get_by_name(self.con, "운영")["id"]
        payload = self.patch({"category_id": ops})
        self.assertIsNone(payload["created_todo"])

    def test_popup_shows_the_created_todo(self):
        """분류 직후 팝업 개요 탭이 만들어진 할일을 바로 보여줄 수 있어야 한다"""
        created = self.patch({"workspace_id": self.workspace})["created_todo"]
        with mock.patch.object(transcript, "TRANSCRIPT_ROOT", "/nowhere"):
            detail = session_link.detail(self.con, self.row_id)
        self.assertEqual([row["id"] for row in detail["todos"]], [created["id"]])


if __name__ == "__main__":
    unittest.main()
