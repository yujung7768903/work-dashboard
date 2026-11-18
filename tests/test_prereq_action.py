"""선행 대기 사전 조건 케밥 — 사전 조건 하나만 빼기(task update --after 남은 목록·마지막이면 none),
사전 조건 할일 완료 처리(직접 할 일·확인 대기는 화면 완료와 같은 task-ui --done, 열린 결정은 task done --by-user),
잘못된 요청은 매니저를 부르기 전에 막는지, POST 를 이 PC 에서만 받는지.
가짜 manager.py 는 받은 argv 를 적고 update·done·task-ui 를 tasks.json 에 반영한다"""
import json
import os

import server
from app.errors import Validation
from app.services import manager_panel, prereq_action
from tests.test_decision_answer import Fixture, task

FAKE_MANAGER = r'''
import json, os, sys
here = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(here, "calls.jsonl"), "a", encoding="utf-8") as handle:
    handle.write(json.dumps(sys.argv[1:], ensure_ascii=False) + "\n")
path = os.path.join(here, "tasks.json")
with open(path, encoding="utf-8") as handle:
    tasks = json.load(handle)
by_id = {row["id"]: row for row in tasks}
args = sys.argv[1:]

def save():
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(tasks, handle, ensure_ascii=False)

def view(row):
    ids = [int(x) for x in (row.get("after_ids") or "").split(",") if x]
    after = [{"id": i, "title": by_id[i]["title"], "status": by_id[i]["status"],
              "finished": by_id[i]["status"] in ("done", "invalid")} for i in ids]
    return {**row, "after": after}

if args[:2] == ["task", "show"]:
    row = by_id.get(int(args[2]))
    print(json.dumps(view(row) if row else None, ensure_ascii=False))
elif args[:2] == ["task", "update"]:
    after = args[args.index("--after") + 1]
    by_id[int(args[2])]["after_ids"] = None if after == "none" else after
    save()
    print(json.dumps(by_id[int(args[2])], ensure_ascii=False))
elif args[:2] == ["task", "done"]:
    by_id[int(args[2])]["status"] = "done"
    save()
elif args[0] == "task-ui":
    by_id[int(args[1])]["status"] = "done"
    save()
    print(json.dumps({"id": int(args[1]), "exit": 3}))
    sys.exit(3)
'''


class Base(Fixture):
    def setUp(self):
        super().setUp()
        with open(os.path.join(self.home, "manager.py"), "w", encoding="utf-8") as handle:
            handle.write(FAKE_MANAGER)
        # 매니저 탭 줄 모양은 매니저 DB 를 읽는다 — 여기서는 매니저 CLI 가 보는 선행만 확인한다
        original = manager_panel.task_item
        manager_panel.task_item = lambda task_id, **_: {"id": task_id, "after_ids": self.row(task_id).get("after_ids")}
        self.addCleanup(setattr, manager_panel, "task_item", original)
        self.tasks([
            task(1, title="선행을 가진 결정", after_ids="2,3,4"),
            task(2, kind="action", title="직접 할 일"),
            task(3, title="열린 결정"),
            task(4, status="confirm", title="확인 대기"),
            task(5, status="done", title="끝난 할일"),
            task(6, title="선행 하나", after_ids="5"),
        ])

    def row(self, task_id):
        with open(os.path.join(self.home, "tasks.json"), encoding="utf-8") as handle:
            return next(row for row in json.load(handle) if row["id"] == task_id)

    def changes(self):
        return [call for call in self.calls() if call[:2] != ["task", "show"]]


class RemoveTest(Base):
    def test_removes_only_that_prereq(self):
        result = prereq_action.remove(1, 3, home=self.home)
        self.assertEqual(self.changes(), [["task", "update", "1", "--after", "2,4"]])
        self.assertEqual(result["task"]["after_ids"], "2,4")

    def test_last_prereq_becomes_none(self):
        prereq_action.remove(6, 5, home=self.home)
        self.assertEqual(self.changes(), [["task", "update", "6", "--after", "none"]])
        self.assertIsNone(self.row(6)["after_ids"])

    def test_not_a_prereq_is_refused_before_writing(self):
        with self.assertRaises(Validation):
            prereq_action.remove(1, 5, home=self.home)
        self.assertEqual(self.changes(), [])


class FinishTest(Base):
    def test_action_goes_through_task_ui_done(self):
        prereq_action.finish(1, 2, home=self.home)
        self.wait_job(2)
        self.assertEqual(self.changes(), [["task-ui", "2", "--done", f"--feedback={prereq_action.FINISH_TEXT}"]])
        self.assertEqual(self.row(2)["status"], "done")

    def test_confirm_goes_through_task_ui_done(self):
        prereq_action.finish(1, 4, home=self.home)
        self.wait_job(4)
        self.assertEqual(self.changes(), [["task-ui", "4", "--done", f"--feedback={prereq_action.FINISH_TEXT}"]])

    def test_open_decision_closes_by_user(self):
        # task-ui 는 열린 결정을 받지 않는다 — 사용자 말을 근거로 바로 닫는 task done --by-user
        prereq_action.finish(1, 3, home=self.home)
        self.assertEqual(self.changes(), [["task", "done", "3", f"--by-user={prereq_action.FINISH_TEXT}"]])
        self.assertEqual(self.row(3)["status"], "done")

    def test_refuses_closed_or_foreign(self):
        for owner, prereq in ((6, 5), (1, 5), (6, 2)):
            with self.subTest(owner=owner, prereq=prereq):
                with self.assertRaises(Validation):
                    prereq_action.finish(owner, prereq, home=self.home)
        self.assertEqual(self.changes(), [])


class RouteTest(Base):
    def setUp(self):
        super().setUp()
        os.environ["WORK_DASHBOARD_MANAGER_HOME"] = self.home
        self.addCleanup(os.environ.pop, "WORK_DASHBOARD_MANAGER_HOME", None)

    def test_routes(self):
        body = {"task_id": 1, "prereq_id": 2, "action": "remove"}
        self.assertEqual(server.route(self.con, "POST", "/api/prereq-action", {}, body)["task"]["after_ids"], "3,4")
        for bad in ({"task_id": 1, "prereq_id": 3}, {"task_id": 1, "prereq_id": 3, "action": "delete"}, {"action": "remove"}):
            with self.subTest(body=bad):
                with self.assertRaises(Validation):
                    server.route(self.con, "POST", "/api/prereq-action", {}, bad)

    def test_only_from_this_pc(self):
        with self.assertRaises(Validation):
            server.guard_origin("POST", "/api/prereq-action", "192.168.0.7")
        server.guard_origin("POST", "/api/prereq-action", "127.0.0.1")
