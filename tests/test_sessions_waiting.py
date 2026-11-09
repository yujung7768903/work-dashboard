"""매니저 알림용 세션 대기 상태·마지막 답변 기록"""
import unittest

from app.repositories import sessions as session_repo
from tests.support import temp_db


class SessionsWaitingTest(unittest.TestCase):
    def setUp(self):
        self.con = temp_db()
        session_repo.register(self.con, "sess-a", cwd="/tmp/a")
        session_repo.register(self.con, "sess-b", cwd="/tmp/b")

    def test_waiting_session_is_listed(self):
        session_repo.set_waiting(self.con, "sess-a", "permission")
        rows = session_repo.list_waiting(self.con)
        self.assertEqual([r["claude_session_id"] for r in rows], ["sess-a"])
        self.assertEqual(rows[0]["waiting"], "permission")

    def test_clearing_waiting_removes_from_list(self):
        session_repo.set_waiting(self.con, "sess-a", "input")
        session_repo.set_waiting(self.con, "sess-a", None)
        self.assertEqual(session_repo.list_waiting(self.con), [])

    def test_ended_session_not_listed(self):
        session_repo.set_waiting(self.con, "sess-b", "permission")
        session_repo.set_state(self.con, "sess-b", "ended")
        self.assertEqual(session_repo.list_waiting(self.con), [])

    def test_last_reply_is_one_line_and_capped(self):
        text = ("첫 줄\n둘째 줄 " + "가" * 400)
        session_repo.set_last_reply(self.con, "sess-a", text)
        row = session_repo.find(self.con, "sess-a")
        self.assertNotIn("\n", row["last_reply"])
        self.assertLessEqual(len(row["last_reply"]), 300)
        self.assertTrue(row["last_reply"].startswith("첫 줄 둘째 줄"))

    def test_unknown_session_is_ignored(self):
        self.assertIsNone(session_repo.set_waiting(self.con, "nope", "input"))
        self.assertIsNone(session_repo.set_last_reply(self.con, "nope", "x"))


if __name__ == "__main__":
    unittest.main()
