"""세션을 워크스페이스로 분류할 때 할일이 자동으로 생기는지."""
import json
import os
import tempfile
import unittest
from unittest import mock

import server
from app.constants import AUTO_TODO_MAX_SUBTASKS, AUTO_TODO_TITLE_CHARS
from app.repositories import categories as category_repo
from app.repositories import sessions as session_repo
from app.repositories import subtasks as subtask_repo
from app.repositories import todos as todo_repo
from app.repositories import workspaces as workspace_repo
from app.services import session_link, session_todo, transcript
from tests.support import temp_db

SID = "sess-auto-todo"


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
    def setUp(self):
        self.con = temp_db()
        dev = category_repo.get_by_name(self.con, "개발")["id"]
        self.workspace = workspace_repo.create(self.con, dev, "대시보드")["id"]
        self.session = session_repo.register(
            self.con, SID, cwd="/home/user/work", git_branch="master"
        )

    def classify(self, prompts, **fields):
        """transcript 를 깔고 분류한 뒤 만들어진 할일(또는 None)"""
        root = write_transcript(SID, prompts) if prompts else tempfile.mkdtemp()
        session_repo.classify_by_ids(
            self.con, self.session["id"], **(fields or {"workspace_id": self.workspace})
        )
        return session_todo.ensure_from_session(self.con, self.session["id"], root=root)

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

    def test_extracts_list_items_as_subtasks(self):
        todo = self.classify(["다음을 해줘\n- 탭 추가\n- 색 맞추기\n- 테스트"])
        self.assertEqual(
            [row["title"] for row in todo["subtasks"]], ["탭 추가", "색 맞추기", "테스트"]
        )
        self.assertEqual(todo["title"], "다음을 해줘")

    def test_extracts_numbered_items(self):
        todo = self.classify(["정리해줘\n1. 훅 등록\n2) 서버 종료"])
        self.assertEqual([row["title"] for row in todo["subtasks"]], ["훅 등록", "서버 종료"])

    def test_single_item_is_not_split(self):
        """항목이 하나면 할일과 같은 말이라 하위할일을 만들지 않는다"""
        todo = self.classify(["이것만 해줘\n- 탭 추가"])
        self.assertEqual(todo["subtasks"], [])

    def test_subtasks_are_capped(self):
        items = "\n".join(f"- 항목 {index}" for index in range(AUTO_TODO_MAX_SUBTASKS + 5))
        todo = self.classify([f"목록이다\n{items}"])
        self.assertEqual(len(todo["subtasks"]), AUTO_TODO_MAX_SUBTASKS)

    def test_duplicate_items_are_dropped(self):
        todo = self.classify(["해줘\n- 탭 추가\n- 탭 추가\n- 색 맞추기"])
        self.assertEqual([row["title"] for row in todo["subtasks"]], ["탭 추가", "색 맞추기"])

    def test_extracts_request_sentences_without_list_markers(self):
        """목록 표기 없이 요청을 이어 쓴 지시 — 실제로 가장 흔한 모양"""
        todo = self.classify(
            ["분류하면 할일을 만들어줘. 하위 할일도 추출해주고. note 도 채워주고"]
        )
        self.assertEqual(todo["title"], "분류하면 할일을 만들어줘.")
        self.assertEqual(
            [row["title"] for row in todo["subtasks"]], ["하위 할일도 추출해주고", "note 도 채워주고"]
        )

    def test_plain_sentences_are_not_subtasks(self):
        """설명·군더더기 문장은 하위할일이 아니다"""
        todo = self.classify(["이게 지금 이상해. 어제는 잘 됐었다. 로그도 남아 있다"])
        self.assertEqual(todo["subtasks"], [])

    def test_list_markers_win_over_sentences(self):
        todo = self.classify(["이렇게 해줘\n- 하나 해줘\n- 둘 해주고"])
        self.assertEqual([row["title"] for row in todo["subtasks"]], ["하나 해줘", "둘 해주고"])

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


class RouteTest(unittest.TestCase):
    """웹에서 분류하면(PATCH) 같은 일이 일어나는지"""

    def setUp(self):
        self.con = temp_db()
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
        self.assertEqual(payload["created_todo"]["title"], "세션 분류할 때 할일도 만들어줘")
        self.assertEqual(
            [row["title"] for row in payload["created_todo"]["subtasks"]], ["생성", "연결"]
        )

    def test_patch_with_category_only_creates_nothing(self):
        ops = category_repo.get_by_name(self.con, "운영")["id"]
        payload = self.patch({"category_id": ops})
        self.assertIsNone(payload["created_todo"])

    def test_popup_shows_the_created_todo_with_subtasks(self):
        """분류 직후 팝업 개요 탭이 하위할일까지 보여줄 수 있어야 한다"""
        created = self.patch({"workspace_id": self.workspace})["created_todo"]
        with mock.patch.object(transcript, "TRANSCRIPT_ROOT", "/nowhere"):
            detail = session_link.detail(self.con, self.row_id)
        self.assertEqual([row["id"] for row in detail["todos"]], [created["id"]])
        self.assertEqual(
            [row["title"] for row in detail["todos"][0]["subtasks"]],
            [row["title"] for row in subtask_repo.list_by_todo(self.con, created["id"])],
        )


if __name__ == "__main__":
    unittest.main()
