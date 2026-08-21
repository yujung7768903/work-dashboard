"""상태별 뷰가 카드를 세울 순서 — 보드 트리가 할일마다 마지막 세션 활동 시각을 실어야 한다"""
import unittest

from app.repositories import categories as category_repo
from app.repositories import sessions as session_repo
from app.repositories import todos as todo_repo
from app.services import board
from tests.support import temp_db


class BoardSessionOrderTest(unittest.TestCase):
    def setUp(self):
        self.con = temp_db()
        self.category = category_repo.list_all(self.con)[0]

    def _todo(self, title):
        return todo_repo.create(self.con, title, category_id=self.category["id"])

    def _worked(self, claude_session_id, todo_id):
        session_repo.register(self.con, claude_session_id)
        session_repo.link_todo(self.con, claude_session_id, todo_id, claim=False)

    def _by_title(self):
        groups = board.tree(self.con, board.GROUP_BY_WORKSPACE)["groups"]
        return {
            todo["title"]: todo["last_session_at"]
            for group in groups
            for todo in group["todos"]
        }

    def test_todo_a_session_worked_on_carries_that_session_time(self):
        todo = self._todo("세션이 잡은 것")
        self._worked("sess-1", todo["id"])
        self.assertIsNotNone(self._by_title()["세션이 잡은 것"])

    def test_todo_no_session_touched_has_no_time(self):
        self._todo("아무도 안 잡은 것")
        self.assertIsNone(self._by_title()["아무도 안 잡은 것"])

    def test_latest_session_wins_when_several_worked_on_it(self):
        todo = self._todo("여러 세션이 잡은 것")
        self._worked("sess-1", todo["id"])
        self._worked("sess-2", todo["id"])
        # 한쪽만 다시 살아 있다고 알린다 — 그 시각이 카드 순서를 정해야 한다
        session_repo.set_state(self.con, "sess-2", "working")
        seen = [
            session_repo.get(self.con, name)["last_seen_at"]
            for name in ("sess-1", "sess-2")
        ]
        self.assertEqual(self._by_title()["여러 세션이 잡은 것"], max(seen))


if __name__ == "__main__":
    unittest.main()
