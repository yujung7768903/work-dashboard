"""직접 할 일·확인 대기 응답 — 매니저 CLI(task list --json·task show·task-ui)만 부르는지, 할일에 붙은 것을 고르는 규칙,
task-ui 를 셸 없이 리스트 인자로 뒤에서 돌리는지, 고칠 수 있는 입력 오류를 먼저 막는지, POST 를 이 PC 에서만 받는지.
가짜 manager.py 는 결정 답하기 테스트의 것을 쓴다 — 받은 argv 를 그대로 적어 둔다"""
import os
import tempfile

import server
from app.errors import Conflict, Validation
from app.services import decision_answer, task_report
from tests.test_decision_answer import Fixture, task


def action(task_id, **fields):
    return task(task_id, kind="action", title=f"직접 할 일 {task_id}", **fields)


class ForTodoTest(Fixture):
    def test_reports_ride_with_decisions_in_one_manager_call(self):
        self.tasks([
            task(1, session_id="mine"),
            action(2, session_id="mine", priority=1),
            action(3, session_id="mine", priority=3),
            # 확인 대기는 종류를 가리지 않는다
            task(4, session_id="mine", status="confirm", reason="끝냄"),
            # 화면에서 알려 닫힌 것은 최근 순으로 뒤에
            action(5, session_id="mine", status="done", answer="했어", answer_via="ui:done",
                   answered_at="2026-11-17T10:00:00"),
            task(6, session_id="mine", status="done", answer="좋아", answer_via="ui:confirm",
                 answered_at="2026-11-17T11:00:00"),
            # 화면을 거치지 않고 닫힌 직접 할 일·무효는 올리지 않는다
            action(7, session_id="mine", status="done"),
            action(8, session_id="mine", status="invalid"),
            # 다른 할일로 옮겨 간 세션·연결 세션 없는 것은 이 할일 몫이 아니다
            action(9, session_id="moved"),
            action(10, session_id=""),
        ])
        found = decision_answer.for_todo(self.con, self.todo["id"], home=self.home)
        self.assertEqual([item["id"] for item in found["items"]], [1], "결정 칸은 그대로 — 화면에서 확인한 결정은 빠진다")
        self.assertEqual([item["id"] for item in found["reports"]], [3, 2, 4, 6, 5])
        kinds = {item["id"]: item["report_kind"] for item in found["reports"]}
        self.assertEqual(kinds, {3: "action", 2: "action", 4: "confirm", 6: "confirm", 5: "action"})
        self.assertNotIn("hold_until", found["reports"][0])
        self.assertEqual(self.calls(), [["task", "list", "--json", "--all"]])

    def test_reopened_by_fix_is_an_open_task_again(self):
        self.tasks([action(11, session_id="mine", answer="표 하나 더", answer_via="ui:fix")])
        [item] = decision_answer.for_todo(self.con, self.todo["id"], home=self.home)["reports"]
        self.assertEqual(item["report_kind"], "action", "task-ui 는 열린 직접 할 일로 받는다")

    def test_without_manager(self):
        found = decision_answer.for_todo(self.con, self.todo["id"], home=tempfile.mkdtemp())
        self.assertEqual(found["reports"], [])


class StartTest(Fixture):
    def test_args_go_as_a_list_and_feedback_arrives_untouched(self):
        self.tasks([action(21), task(22, status="confirm")])
        feedback = "--done; $(touch /tmp/pwned-report) `id` && echo '끝'\n둘째 줄"
        started = task_report.start(21, False, feedback, home=self.home)
        self.assertTrue(started["job"]["running"])
        self.assertEqual(started["report_kind"], "action")
        self.wait_job(21)
        self.assertEqual(self.calls()[-1], ["task-ui", "21", f"--feedback={feedback.strip()}"])
        self.assertFalse(os.path.exists("/tmp/pwned-report"))
        task_report.start(22, True, "  ", home=self.home)
        self.wait_job(22)
        self.assertEqual(self.calls()[-1], ["task-ui", "22", "--done"])

    def test_parked_exit_is_not_an_error(self):
        self.tasks([action(23)])
        self.answer({"id": 23, "exit": 5, "answer_state": "parked"})
        task_report.start(23, True, None, home=self.home)
        self.assertEqual((self.wait_job(23)["exit"], self.wait_job(23)["error"]), (5, None))
        self.answer({"id": 23, "exit": 2, "error": "할일 23 은 이미 닫혔다(done)"})
        task_report.start(23, True, None, home=self.home)
        self.assertEqual(self.wait_job(23)["error"], "할일 23 은 이미 닫혔다(done)")
        self.assertEqual(task_report.show(23, home=self.home)["job"]["exit"], 2)

    def test_input_errors_are_caught_before_running(self):
        self.tasks([action(31), task(32), action(33, status="done"), action(34, status="invalid")])
        for task_id, done, feedback in ((31, False, "  "), (32, True, None), (33, True, None), (34, False, "글")):
            with self.subTest(task_id=task_id):
                with self.assertRaises(Validation):
                    task_report.start(task_id, done, feedback, home=self.home)
        self.assertEqual([call for call in self.calls() if call[0] == "task-ui"], [])

    def test_second_report_while_delivering_conflicts(self):
        self.tasks([action(41)])

        class Slow:
            returncode = 0

            def communicate(self, timeout=None):
                import time
                time.sleep(0.3)
                return "{}", ""

        task_report.start(41, True, None, home=self.home, popen=lambda *args, **kwargs: Slow())
        with self.assertRaises(Conflict):
            task_report.start(41, False, "또", home=self.home)
        self.wait_job(41)


class RouteTest(Fixture):
    def setUp(self):
        super().setUp()
        os.environ["WORK_DASHBOARD_MANAGER_HOME"] = self.home
        self.addCleanup(os.environ.pop, "WORK_DASHBOARD_MANAGER_HOME", None)

    def test_routes(self):
        self.tasks([action(51, session_id="mine")])
        found = server.route(self.con, "GET", "/api/decisions", {"todo_id": [str(self.todo["id"])]}, None)
        self.assertEqual([item["id"] for item in found["reports"]], [51])
        self.assertEqual(server.route(self.con, "GET", "/api/task-reports/51", {}, None)["id"], 51)
        with self.assertRaises(Validation):
            server.route(self.con, "GET", "/api/task-reports", {}, None)
        started = server.route(self.con, "POST", "/api/task-report", {}, {"id": 51, "done": True})
        self.assertTrue(started["job"]["running"])
        self.wait_job(51)
        self.assertEqual(self.calls()[-1], ["task-ui", "51", "--done"])
        with self.assertRaises(Validation):
            server.route(self.con, "POST", "/api/task-report", {}, {"done": True})

    def test_report_only_from_this_pc(self):
        # 완료·확인은 매니저 할일을 닫고 원 세션에 글을 넣는다 — --lan 화면에서 남이 하지 못하게
        with self.assertRaises(Validation):
            server.guard_origin("POST", "/api/task-report", "192.168.0.7")
        server.guard_origin("POST", "/api/task-report", "127.0.0.1")
