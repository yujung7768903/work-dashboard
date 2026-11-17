"""결정 답하기 — 매니저 CLI(task list --json·task show·answer-ui)만 부르는지, 할일에 붙은 결정을 고르는 규칙,
answer-ui 를 셸 없이 리스트 인자로 뒤에서 돌리는지, 고칠 수 있는 입력 오류를 먼저 막는지.

매니저는 가짜 manager.py 로 갈음한다 — 받은 argv 를 그대로 적어 두므로, 의견 글이 셸·argparse 를 거치며
바뀌지 않고 그대로 도착했는지를 실제 프로세스 경계에서 본다
"""
import json
import os
import sys
import tempfile
import threading
import time
import unittest

import server
from app.errors import Conflict, NotFound, Validation
from app.repositories import categories as category_repo
from app.repositories import sessions as session_repo
from app.repositories import todos as todo_repo
from app.repositories import workspaces as workspace_repo
from app.services import decision_answer
from tests.support import temp_db

FAKE_MANAGER = r'''
import json, os, sys
here = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(here, "calls.jsonl"), "a", encoding="utf-8") as handle:
    handle.write(json.dumps(sys.argv[1:], ensure_ascii=False) + "\n")
with open(os.path.join(here, "tasks.json"), encoding="utf-8") as handle:
    tasks = json.load(handle)
args = sys.argv[1:]
if args[:2] == ["task", "list"]:
    rows = tasks if "--all" in args else [row for row in tasks if row["status"] in ("open", "confirm")]
    print(json.dumps(rows, ensure_ascii=False))
elif args[:2] == ["task", "show"]:
    print(json.dumps(next((row for row in tasks if row["id"] == int(args[2])), None), ensure_ascii=False))
elif args[0] in ("answer-ui", "task-ui"):
    with open(os.path.join(here, "answer.json"), encoding="utf-8") as handle:
        out = json.load(handle)
    print(json.dumps(out, ensure_ascii=False))
    sys.exit(out["exit"])
'''


def task(task_id, **fields):
    row = {
        "id": task_id, "title": f"결정 {task_id}", "kind": "decision", "status": "open", "priority": 1,
        "detail": "배경", "next_step": None, "open_target": None, "session_id": "", "options": [],
        "recommend": None, "answer": None, "answer_choice": None, "answer_feedback": None,
        "answered_at": None, "created_at": f"2026-11-16T10:{task_id:02d}:00", "answer_state": "unanswered",
        "session": None, "hold_until": None,
    }
    row.update(fields)
    return row


OPTIONS = [
    {"key": "A", "label": "고친다", "desc": "inbox 로 매니저를 깨운다"},
    {"key": "B", "label": "그대로 둔다", "desc": "화면 표시만"},
]


class Fixture(unittest.TestCase):
    def setUp(self):
        decision_answer._jobs.clear()
        self.home = tempfile.mkdtemp()
        with open(os.path.join(self.home, "manager.py"), "w", encoding="utf-8") as handle:
            handle.write(FAKE_MANAGER)
        self.answer({"id": 0, "exit": 0, "answer_state": "delivered"})
        self.con = temp_db()
        category = category_repo.list_all(self.con)[0]
        space = workspace_repo.create(self.con, category["id"], "작업 대시보드")
        self.todo = todo_repo.create(self.con, "결정 버튼", workspace_id=space["id"])
        self.other = todo_repo.create(self.con, "다른 할일", workspace_id=space["id"])
        # 예전엔 이 할일을 잡았다가 다른 할일로 옮겨 간 세션 — 그 세션의 결정은 지금 할일에 붙는다
        session_repo.register(self.con, "mine", cwd="/tmp")
        session_repo.link_todo(self.con, "mine", self.todo["id"])
        session_repo.register(self.con, "moved", cwd="/tmp")
        session_repo.link_todo(self.con, "moved", self.todo["id"])
        session_repo.link_todo(self.con, "moved", self.other["id"])

    def tasks(self, rows):
        with open(os.path.join(self.home, "tasks.json"), "w", encoding="utf-8") as handle:
            json.dump(rows, handle, ensure_ascii=False)

    def answer(self, out):
        with open(os.path.join(self.home, "answer.json"), "w", encoding="utf-8") as handle:
            json.dump(out, handle, ensure_ascii=False)

    def calls(self):
        path = os.path.join(self.home, "calls.jsonl")
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8") as handle:
            return [json.loads(line) for line in handle]

    def wait_job(self, task_id):
        for _ in range(200):
            job = decision_answer._jobs.get(task_id)
            if job and not job["running"]:
                return job
            time.sleep(0.05)
        self.fail("answer-ui 가 끝나지 않았다")


class ForTodoTest(Fixture):
    def test_open_then_answered_decisions_of_the_sessions_current_todo(self):
        self.tasks([
            task(1, session_id="mine", priority=1),
            task(2, session_id="mine", priority=3, options=OPTIONS, recommend="A"),
            task(3, session_id="mine", status="done", answer="B(그대로 둔다)", answered_at="2026-11-16T11:00:00",
                 answer_state="delivered"),
            task(4, session_id="mine", status="done", answer="A(고친다)", answered_at="2026-11-16T12:00:00",
                 answer_state="failed"),
            # 답 없이 닫힌 결정은 답할 수 없어 안 올린다
            task(5, session_id="mine", status="invalid"),
            # 결정이 아닌 직접 할 일
            task(6, session_id="mine", kind="action"),
            # 다른 할일로 옮겨 간 세션·연결 세션 없는 결정은 매니저 탭 몫
            task(7, session_id="moved"),
            task(8, session_id=""),
        ])
        found = decision_answer.for_todo(self.con, self.todo["id"], home=self.home)
        self.assertTrue(found["available"])
        # 답 대기(우선순위 높은 것 먼저) → 답한 것(최근 답 먼저)
        self.assertEqual([item["id"] for item in found["items"]], [2, 1, 4, 3])
        first = found["items"][0]
        self.assertEqual(first["options"], OPTIONS)
        self.assertEqual(first["recommend"], "A")
        self.assertEqual(first["answer_state"], "unanswered")
        self.assertIsNone(first["job"])
        # 화면이 쓰는 칸만 — 매니저 내부 칸(보류 시각 등)은 옮기지 않는다
        self.assertNotIn("hold_until", first)
        self.assertEqual(self.calls(), [["task", "list", "--json", "--all"]])

    def test_moved_session_decision_follows_its_current_todo(self):
        self.tasks([task(7, session_id="moved")])
        self.assertEqual(decision_answer.for_todo(self.con, self.todo["id"], home=self.home)["items"], [])
        found = decision_answer.for_todo(self.con, self.other["id"], home=self.home)
        self.assertEqual([item["id"] for item in found["items"]], [7])

    def test_without_manager_nothing_to_show(self):
        found = decision_answer.for_todo(self.con, self.todo["id"], home=tempfile.mkdtemp())
        self.assertEqual(found, {"available": False, "items": [], "reports": []})


class ShowTest(Fixture):
    def test_one_decision_with_its_job(self):
        self.tasks([task(9, options=OPTIONS, answer_state="sending")])
        found = decision_answer.show(9, home=self.home)
        self.assertEqual((found["id"], found["answer_state"], found["job"]), (9, "sending", None))
        self.assertEqual(self.calls(), [["task", "show", "9"]])

    def test_missing_task_is_not_found(self):
        self.tasks([])
        with self.assertRaises(NotFound):
            decision_answer.show(404, home=self.home)


class StartTest(Fixture):
    def test_args_go_as_a_list_and_feedback_arrives_untouched(self):
        self.tasks([task(11, options=OPTIONS)])
        self.answer({"id": 11, "exit": 0, "answer_state": "delivered"})
        # 셸이라면 명령 치환·연결로, argparse 라면 옵션으로 읽힐 글
        feedback = "--choice=B; $(touch /tmp/pwned) `id` && echo '끝'\n둘째 줄"
        started = decision_answer.start(11, "a", feedback, home=self.home)
        self.assertTrue(started["job"]["running"])
        job = self.wait_job(11)
        self.assertEqual((job["exit"], job["error"]), (0, None))
        self.assertEqual(
            self.calls()[-1], ["answer-ui", "11", "--choice=a", f"--feedback={feedback.strip()}"]
        )
        self.assertFalse(os.path.exists("/tmp/pwned"))

    def test_feedback_only_and_choice_only(self):
        self.tasks([task(12), task(13, options=OPTIONS)])
        decision_answer.start(12, None, "  의견만  ", home=self.home)
        self.wait_job(12)
        decision_answer.start(13, "B", "   ", home=self.home)
        self.wait_job(13)
        answers = [call for call in self.calls() if call[0] == "answer-ui"]
        self.assertEqual(answers, [["answer-ui", "12", "--feedback=의견만"], ["answer-ui", "13", "--choice=B"]])

    def test_saved_outcomes_are_not_errors_but_usage_error_is(self):
        self.tasks([task(14, options=OPTIONS)])
        for code in (1, 3, 4):
            self.answer({"id": 14, "exit": code, "answer_state": "failed"})
            decision_answer.start(14, "A", None, home=self.home)
            self.assertEqual((self.wait_job(14)["exit"], self.wait_job(14)["error"]), (code, None))
        self.answer({"id": 14, "exit": 2, "error": "할일 14 은 답 없이 닫혔다(done)"})
        decision_answer.start(14, "A", None, home=self.home)
        self.assertEqual(self.wait_job(14)["error"], "할일 14 은 답 없이 닫혔다(done)")
        # 다시 읽으면 job 이 실려 화면이 사유를 보인다
        self.assertEqual(decision_answer.show(14, home=self.home)["job"]["exit"], 2)

    def test_input_errors_are_caught_before_running(self):
        self.tasks([
            task(21, options=OPTIONS),
            task(22, kind="action"),
            task(23, status="invalid"),
            task(24, status="done", answer="A(고친다)", options=OPTIONS),
        ])
        cases = [
            (21, None, "  "),  # 고른 것도 쓴 것도 없다
            (21, "C", None),  # 없는 선택지
            (22, None, "글"),  # 결정이 아니다
            (23, None, "글"),  # 답 없이 닫혔다
        ]
        for task_id, choice, feedback in cases:
            with self.subTest(task_id=task_id, choice=choice):
                with self.assertRaises(Validation):
                    decision_answer.start(task_id, choice, feedback, home=self.home)
        self.assertEqual([call for call in self.calls() if call[0] == "answer-ui"], [])
        # 이미 답한 결정은 다시 답할 수 있다
        decision_answer.start(24, "B", None, home=self.home)
        self.wait_job(24)

    def test_second_answer_while_delivering_conflicts(self):
        self.tasks([task(31, options=OPTIONS)])
        release = threading.Event()

        class SlowProc:
            returncode = 0

            def communicate(self, timeout=None):
                release.wait(5)
                return '{"exit": 0}', ""

        decision_answer.start(31, "A", None, home=self.home, popen=lambda *args, **kwargs: SlowProc())
        with self.assertRaises(Conflict):
            decision_answer.start(31, "B", None, home=self.home)
        release.set()
        self.wait_job(31)

    def test_runs_without_shell_in_its_own_session(self):
        self.tasks([task(41, options=OPTIONS)])
        seen = {}

        class Done:
            returncode = 0

            def communicate(self, timeout=None):
                return "{}", ""

        def popen(args, **kwargs):
            seen.update(args=args, **kwargs)
            return Done()

        decision_answer.start(41, "A", "글", home=self.home, popen=popen)
        self.wait_job(41)
        self.assertIsInstance(seen["args"], list)
        self.assertEqual(seen["args"][0], sys.executable)
        self.assertNotIn("shell", seen)
        # 대시보드 서버가 다시 떠도 전달이 끊기지 않게
        self.assertTrue(seen["start_new_session"])


class RouteTest(Fixture):
    def setUp(self):
        super().setUp()
        os.environ["WORK_DASHBOARD_MANAGER_HOME"] = self.home
        self.addCleanup(os.environ.pop, "WORK_DASHBOARD_MANAGER_HOME", None)

    def test_routes(self):
        self.tasks([task(51, session_id="mine", options=OPTIONS)])
        found = server.route(self.con, "GET", "/api/decisions", {"todo_id": [str(self.todo["id"])]}, None)
        self.assertEqual([item["id"] for item in found["items"]], [51])
        self.assertEqual(server.route(self.con, "GET", "/api/decisions/51", {}, None)["id"], 51)
        with self.assertRaises(Validation):
            server.route(self.con, "GET", "/api/decisions", {}, None)
        started = server.route(self.con, "POST", "/api/decision-answer", {}, {"id": 51, "choice": "A"})
        self.assertTrue(started["job"]["running"])
        self.wait_job(51)

    def test_answer_only_from_this_pc(self):
        # 의견은 도구가 달린 에이전트 세션에 들어간다 — --lan 화면에서 남이 넣지 못하게
        with self.assertRaises(Validation):
            server.guard_origin("POST", "/api/decision-answer", "192.168.0.7")
        server.guard_origin("POST", "/api/decision-answer", "127.0.0.1")


if __name__ == "__main__":
    unittest.main()
