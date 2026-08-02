"""라벨 CRUD 와 할일 붙이기.

카테고리와 달리 한 할일에 여러 개 붙고, 라벨을 지우면 붙어 있던 할일에서 조용히
떨어진다 — 그 확인 흐름과 보드가 라벨을 실어 내주는지를 본다.
"""
import unittest

from app.errors import Conflict, NeedsConfirm, NotFound, Validation
from app.repositories import categories as category_repo
from app.repositories import labels as label_repo
from app.repositories import todos as todo_repo
from app.services import board
from tests.support import temp_db


class LabelRepoTest(unittest.TestCase):
    def setUp(self):
        self.con = temp_db()
        self.category = category_repo.list_all(self.con)[0]

    def _todo(self, title="할일"):
        return todo_repo.create(self.con, title, category_id=self.category["id"])

    def test_create_assigns_palette_color_and_order(self):
        first = label_repo.create(self.con, "버그")
        second = label_repo.create(self.con, "기능")
        self.assertEqual(first["sort_order"], 1)
        self.assertEqual(second["sort_order"], 2)
        self.assertRegex(first["color"], r"^#[0-9a-f]{6}$")
        self.assertNotEqual(first["color"], second["color"])

    def test_rejects_blank_and_duplicate_name(self):
        label_repo.create(self.con, "버그")
        with self.assertRaises(Validation):
            label_repo.create(self.con, "  ")
        with self.assertRaises(Conflict):
            label_repo.create(self.con, "버그")

    def test_update_changes_name_and_color(self):
        label = label_repo.create(self.con, "버그")
        updated = label_repo.update(self.con, label["id"], name="장애", color="#AABBCC")
        self.assertEqual(updated["name"], "장애")
        self.assertEqual(updated["color"], "#aabbcc")
        with self.assertRaises(Validation):
            label_repo.update(self.con, label["id"], color="red")

    def test_todo_carries_many_labels_in_given_order(self):
        todo = self._todo()
        bug = label_repo.create(self.con, "버그")
        feature = label_repo.create(self.con, "기능")
        todo_repo.update(self.con, todo["id"], label_ids=[feature["id"], bug["id"]])
        names = [row["name"] for row in label_repo.list_by_todo(self.con, todo["id"])]
        self.assertEqual(names, ["버그", "기능"])  # 정렬은 라벨 순서를 따름

    def test_set_replaces_previous_labels(self):
        todo = self._todo()
        bug = label_repo.create(self.con, "버그")
        feature = label_repo.create(self.con, "기능")
        todo_repo.update(self.con, todo["id"], label_ids=[bug["id"]])
        todo_repo.update(self.con, todo["id"], label_ids=[feature["id"]])
        names = [row["name"] for row in label_repo.list_by_todo(self.con, todo["id"])]
        self.assertEqual(names, ["기능"])

    def test_unknown_label_id_is_rejected_without_partial_write(self):
        todo = self._todo()
        bug = label_repo.create(self.con, "버그")
        todo_repo.update(self.con, todo["id"], label_ids=[bug["id"]])
        with self.assertRaises(NotFound):
            todo_repo.update(self.con, todo["id"], label_ids=[bug["id"], 999])
        self.assertEqual(len(label_repo.list_by_todo(self.con, todo["id"])), 1)

    def test_delete_asks_before_detaching_from_todos(self):
        todo = self._todo()
        label = label_repo.create(self.con, "버그")
        todo_repo.update(self.con, todo["id"], label_ids=[label["id"]])
        with self.assertRaises(NeedsConfirm):
            label_repo.delete(self.con, label["id"])
        label_repo.delete(self.con, label["id"], force=True)
        self.assertEqual(label_repo.list_by_todo(self.con, todo["id"]), [])

    def test_delete_without_attachments_does_not_ask(self):
        label = label_repo.create(self.con, "버그")
        label_repo.delete(self.con, label["id"])
        self.assertEqual(label_repo.list_all(self.con), [])

    def test_deleting_todo_releases_labels_but_keeps_them(self):
        todo = self._todo()
        label = label_repo.create(self.con, "버그")
        todo_repo.update(self.con, todo["id"], label_ids=[label["id"]])
        todo_repo.delete(self.con, todo["id"])
        self.assertEqual(len(label_repo.list_all(self.con)), 1)
        self.assertEqual(label_repo.map_by_todo(self.con), {})

    def test_board_tree_carries_labels(self):
        todo = self._todo()
        label = label_repo.create(self.con, "버그")
        todo_repo.update(self.con, todo["id"], label_ids=[label["id"]])
        groups = board.tree(self.con, board.GROUP_BY_CATEGORY)["groups"]
        shown = [item for group in groups for item in group["todos"]]
        self.assertEqual([row["name"] for row in shown[0]["labels"]], ["버그"])

    def test_board_tree_gives_empty_list_when_no_labels(self):
        self._todo()
        groups = board.tree(self.con, board.GROUP_BY_CATEGORY)["groups"]
        self.assertEqual(groups[0]["todos"][0]["labels"], [])


if __name__ == "__main__":
    unittest.main()
