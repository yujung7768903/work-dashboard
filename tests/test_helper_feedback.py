"""보조 세션 피드백 — 매니저 CLI(helper-ui)만 부르는지, 글을 셸 없이 리스트 인자로 뒤에서 넘기는지, 고칠 수 있는
입력 오류를 먼저 막는지, 같은 세션에 보내는 중이면 겹쳐 보내지 않는지, POST 를 이 PC 에서만 받는지.
가짜 manager.py 는 받은 argv 를 그대로 적어 두고 helper.json(보기)·answer.json(보내기 결과)을 낸다"""
import json
import os
import tempfile
import time
import unittest

import server
from app.errors import Conflict, Validation
from app.services import decision_answer, helper_feedback
from tests.support import temp_db

FAKE_MANAGER = r'''
import json, os, sys
here = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(here, "calls.jsonl"), "a", encoding="utf-8") as handle:
    handle.write(json.dumps(sys.argv[1:], ensure_ascii=False) + "\n")
args = sys.argv[1:]
if args[0] == "helper-ui":
    name = "answer.json" if any(a.startswith("--feedback=") for a in args) else "helper.json"
    with open(os.path.join(here, name), encoding="utf-8") as handle:
        out = json.load(handle)
    print(json.dumps(out, ensure_ascii=False))
    sys.exit(out.get("exit", 0))
'''
SID = "cccccccc-1111-2222-3333-444444444444"
ITEMS = [
    {"id": 12, "answer": "표는 빼 줘", "answered_at": "2026-11-17T12:00:00", "answer_state": "relayed"},
    {"id": 9, "answer": "로그도 봐 줘", "answered_at": "2026-11-17T11:00:00", "answer_state": "delivered"},
]


class Fixture(unittest.TestCase):
    def setUp(self):
        decision_answer._jobs.clear()
        self.home = tempfile.mkdtemp()
        with open(os.path.join(self.home, "manager.py"), "w", encoding="utf-8") as handle:
            handle.write(FAKE_MANAGER)
        self.helper({"session": {"id": SID, "name": "보조3 | 피드백", "alive": True}, "items": ITEMS})
        self.answer({"id": 13, "exit": 4, "answer_state": "relayed"})
        self.con = temp_db()

    def write(self, name, value):
        with open(os.path.join(self.home, name), "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False)

    def helper(self, value):
        self.write("helper.json", value)

    def answer(self, value):
        self.write("answer.json", value)

    def calls(self):
        path = os.path.join(self.home, "calls.jsonl")
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8") as handle:
            return [json.loads(line) for line in handle]

    def wait_job(self):
        key = helper_feedback._job_key(SID)
        for _ in range(200):
            job = decision_answer._jobs.get(key)
            if job and not job["running"]:
                return job
            time.sleep(0.05)
        self.fail("helper-ui 가 끝나지 않았다")


class ShowTest(Fixture):
    def test_session_and_items_come_from_one_manager_call(self):
        found = helper_feedback.show(f"  {SID} ", home=self.home)
        self.assertEqual(found["session"]["alive"], True)
        self.assertEqual([item["id"] for item in found["items"]], [12, 9])
        self.assertIsNone(found["job"])
        self.assertEqual(self.calls(), [["helper-ui", SID]])

    def test_empty_session_id(self):
        with self.assertRaises(Validation):
            helper_feedback.show("  ", home=self.home)
        self.assertEqual(self.calls(), [])


class StartTest(Fixture):
    def test_args_go_as_a_list_and_feedback_arrives_untouched(self):
        feedback = "--done; $(touch /tmp/pwned-helper) `id` && echo '끝'\n둘째 줄"
        started = helper_feedback.start(SID, feedback, home=self.home)
        self.assertTrue(started["job"]["running"])
        job = self.wait_job()
        self.assertEqual((job["exit"], job["error"]), (4, None), "매니저에 넘김은 오류가 아니다")
        self.assertEqual(self.calls()[-1], ["helper-ui", SID, f"--feedback={feedback.strip()}"])
        self.assertFalse(os.path.exists("/tmp/pwned-helper"))
        self.assertEqual(helper_feedback.show(SID, home=self.home)["job"]["exit"], 4)

    def test_ended_session_is_not_an_error(self):
        # 매니저가 끝난 세션이라 남기지 않았다(exit 3) — 화면은 show() 의 session.alive 로 보인다
        self.answer({"session": {"id": SID, "alive": False}, "exit": 3, "ended": True})
        helper_feedback.start(SID, "이것도", home=self.home)
        self.assertEqual((self.wait_job()["exit"], self.wait_job()["error"]), (3, None))

    def test_usage_error_is_shown(self):
        self.answer({"session_id": SID, "exit": 2, "error": "--feedback 이 비어 있다"})
        helper_feedback.start(SID, "글", home=self.home)
        self.assertEqual(self.wait_job()["error"], "--feedback 이 비어 있다")

    def test_input_errors_are_caught_before_running(self):
        for session_id, feedback in ((SID, "  "), (SID, None), ("  ", "글")):
            with self.subTest(session_id=session_id, feedback=feedback):
                with self.assertRaises(Validation):
                    helper_feedback.start(session_id, feedback, home=self.home)
        self.assertEqual(self.calls(), [])

    def test_second_feedback_while_delivering_conflicts(self):
        class Slow:
            returncode = 0

            def communicate(self, timeout=None):
                time.sleep(0.3)
                return "{}", ""

        helper_feedback.start(SID, "하나", home=self.home, popen=lambda *args, **kwargs: Slow())
        with self.assertRaises(Conflict):
            helper_feedback.start(SID, "둘", home=self.home)
        self.wait_job()

    def test_job_key_does_not_collide_with_task_ids(self):
        decision_answer._jobs[13] = {"running": True}
        helper_feedback.start(SID, "겹치지 않는다", home=self.home)
        self.wait_job()


class RouteTest(Fixture):
    def setUp(self):
        super().setUp()
        os.environ["WORK_DASHBOARD_MANAGER_HOME"] = self.home
        self.addCleanup(os.environ.pop, "WORK_DASHBOARD_MANAGER_HOME", None)

    def test_routes(self):
        found = server.route(self.con, "GET", "/api/helper-feedback", {"session_id": [SID]}, None)
        self.assertEqual(found["items"][0]["answer"], "표는 빼 줘")
        with self.assertRaises(Validation):
            server.route(self.con, "GET", "/api/helper-feedback", {}, None)
        started = server.route(self.con, "POST", "/api/helper-feedback", {}, {"session_id": SID, "feedback": "짧게"})
        self.assertTrue(started["job"]["running"])
        self.wait_job()
        self.assertEqual(self.calls()[-1], ["helper-ui", SID, "--feedback=짧게"])
        with self.assertRaises(Validation):
            server.route(self.con, "POST", "/api/helper-feedback", {}, {"feedback": "짧게"})

    def test_feedback_only_from_this_pc(self):
        # 돌고 있는 보조 세션에 글을 넣는다 — --lan 화면에서 남이 하지 못하게
        with self.assertRaises(Validation):
            server.guard_origin("POST", "/api/helper-feedback", "192.168.0.7")
        server.guard_origin("POST", "/api/helper-feedback", "127.0.0.1")


if __name__ == "__main__":
    unittest.main()
