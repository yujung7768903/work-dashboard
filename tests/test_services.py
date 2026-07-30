import unittest

from app.constants import STATUS_DOING, STATUS_DONE, UNASSIGNED_LABEL
from app.errors import Validation
from app.repositories import categories as category_repo
from app.repositories import subtasks as subtask_repo
from app.repositories import todos as todo_repo
from app.repositories import workspaces as workspace_repo
from app.services import board, planning
from tests.support import temp_db

PAUSED = "paused"


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
        self.assertNotIn(self.empty["name"], self._names(board.GROUP_BY_WORKSPACE))

    def test_workspace_grouping_includes_unassigned_last(self):
        self.assertEqual(self._names(board.GROUP_BY_WORKSPACE)[-1], UNASSIGNED_LABEL)

    def test_unassigned_group_shown_even_when_empty(self):
        con = temp_db()
        groups = board.tree(con, board.GROUP_BY_WORKSPACE)["groups"]
        self.assertEqual([group["name"] for group in groups], [UNASSIGNED_LABEL])

    def test_workspace_group_carries_category_name(self):
        group = board.tree(self.con, board.GROUP_BY_WORKSPACE)["groups"][0]
        self.assertEqual(group["category_name"], "개발")

    def test_workspace_group_carries_category_id_color_emoji(self):
        """보드가 카드 상단 색과 카테고리 라벨 필터에 쓰는 값들"""
        group = board.tree(self.con, board.GROUP_BY_WORKSPACE)["groups"][0]
        dev = category_repo.get_by_name(self.con, "개발")
        self.assertEqual(group["category_id"], dev["id"])
        self.assertEqual(group["category_color"], dev["color"])
        self.assertEqual(group["category_emoji"], dev["emoji"])

    def test_unassigned_group_has_no_category_color(self):
        """미분류는 색을 받지 않고 화면에서 옅은 회색 기본값으로 그려짐"""
        group = board.tree(self.con, board.GROUP_BY_WORKSPACE)["groups"][-1]
        self.assertEqual(group["kind"], board.KIND_UNASSIGNED)
        self.assertIsNone(group.get("category_color"))

    def test_todos_carry_subtasks(self):
        group = board.tree(self.con, board.GROUP_BY_WORKSPACE)["groups"][0]
        self.assertEqual(group["todos"][0]["subtasks"][0]["title"], "k6 시나리오")

    def test_counts_reflect_done_state(self):
        todo_repo.update(self.con, self.todo["id"], status=STATUS_DONE)
        group = board.tree(self.con, board.GROUP_BY_WORKSPACE)["groups"][0]
        self.assertEqual((group["done_count"], group["total_count"]), (1, 1))

    def test_category_grouping_includes_unassigned_todos(self):
        titles = [
            todo["title"]
            for group in board.tree(self.con, board.GROUP_BY_CATEGORY)["groups"]
            for todo in group["todos"]
        ]
        self.assertIn("문의 회신", titles)

    def test_category_grouping_hides_empty_categories(self):
        self.assertEqual(sorted(self._names(board.GROUP_BY_CATEGORY)), ["개발", "운영"])


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
        workspace_repo.update(self.con, self.first["id"], status=PAUSED)
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
