"""할일 우선순위 숫자"""
import unittest

from app.errors import Validation
from app.repositories import categories as category_repo
from app.repositories import todos as todo_repo
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


if __name__ == "__main__":
    unittest.main()
