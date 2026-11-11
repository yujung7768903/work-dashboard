"""할일 우선순위 숫자와 그것으로 정하는 워크스페이스 카드 순서"""
import unittest

from app.errors import Validation
from app.repositories import categories as category_repo
from app.repositories import todos as todo_repo
from app.repositories import workspaces as workspace_repo
from app.services import board
from tests.support import temp_db


class TodoPriorityTest(unittest.TestCase):
    def setUp(self):
        self.con = temp_db()
        self.category = category_repo.list_all(self.con)[0]
        self.todo = todo_repo.create(self.con, "할일", category_id=self.category["id"])

    def test_new_todo_has_no_priority(self):
        self.assertIsNone(self.todo["priority"])

    def test_priority_is_stored_as_integer(self):
        updated = todo_repo.update(self.con, self.todo["id"], priority="3")
        self.assertEqual(updated["priority"], 3)

    def test_blank_or_dash_clears_priority(self):
        todo_repo.update(self.con, self.todo["id"], priority=5)
        for blank in ("", "-", None):
            with self.subTest(blank=blank):
                todo_repo.update(self.con, self.todo["id"], priority=5)
                cleared = todo_repo.update(self.con, self.todo["id"], priority=blank)
                self.assertIsNone(cleared["priority"])

    def test_rejects_non_positive_or_non_integer(self):
        for bad in (0, -1, "높음", "1.5", True):
            with self.subTest(bad=bad):
                with self.assertRaises(Validation):
                    todo_repo.update(self.con, self.todo["id"], priority=bad)


class WorkspaceOrderTest(unittest.TestCase):
    def setUp(self):
        self.con = temp_db()
        self.category = category_repo.list_all(self.con)[0]["id"]

    def _workspace(self, name, *todos):
        """todos: (우선순위, 상태) 묶음. 우선순위 None 은 정하지 않음"""
        workspace = workspace_repo.create(self.con, self.category, name)
        for index, (priority, status) in enumerate(todos):
            todo = todo_repo.create(
                self.con, f"{name}-{index}", workspace_id=workspace["id"]
            )
            todo_repo.update(self.con, todo["id"], priority=priority, status=status)
        return workspace

    def _order(self):
        groups = board.tree(self.con, board.GROUP_BY_WORKSPACE)["groups"]
        return [group["name"] for group in groups if group["kind"] == "workspace"]

    def test_highest_open_priority_comes_first(self):
        self._workspace("낮음", (2, "todo"))
        self._workspace("높음", (9, "todo"))
        self._workspace("중간", (5, "doing"))
        self.assertEqual(self._order(), ["높음", "중간", "낮음"])

    def test_done_todos_do_not_count(self):
        self._workspace("완료로만 높음", (10, "done"), (1, "todo"))
        self._workspace("열린 것이 높음", (4, "todo"))
        self.assertEqual(self._order(), ["열린 것이 높음", "완료로만 높음"])

    def test_tie_goes_to_more_open_todos(self):
        self._workspace("하나", (3, "todo"))
        self._workspace("셋", (3, "todo"), (None, "todo"), (1, "doing"))
        self.assertEqual(self._order(), ["셋", "하나"])

    def test_workspaces_without_priority_follow_by_open_count(self):
        self._workspace("우선순위 없음 둘", (None, "todo"), (None, "todo"))
        self._workspace("우선순위 있음", (1, "todo"))
        self._workspace("우선순위 없음 하나", (None, "todo"))
        self.assertEqual(
            self._order(), ["우선순위 있음", "우선순위 없음 둘", "우선순위 없음 하나"]
        )

    def test_unassigned_group_stays_last(self):
        self._workspace("워크스페이스", (1, "todo"))
        todo = todo_repo.create(self.con, "미분류", category_id=self.category)
        todo_repo.update(self.con, todo["id"], priority=99)
        groups = board.tree(self.con, board.GROUP_BY_WORKSPACE)["groups"]
        self.assertEqual(groups[-1]["kind"], board.KIND_UNASSIGNED)

    def test_priority_max_is_over_all_open_todos(self):
        self._workspace("가", (4, "todo"), (12, "done"))
        self._workspace("나", (7, "doing"))
        tree = board.tree(self.con, board.GROUP_BY_WORKSPACE)
        self.assertEqual(tree["priority_max"], 7)

    def test_priority_max_is_none_without_any_priority(self):
        self._workspace("가", (None, "todo"))
        tree = board.tree(self.con, board.GROUP_BY_WORKSPACE)
        self.assertIsNone(tree["priority_max"])


if __name__ == "__main__":
    unittest.main()
