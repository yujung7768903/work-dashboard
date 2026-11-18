"""매니저 탭 회고 — 매니저 CLI(retro list|show · feedback add)만 부르는지, 글을 셸 없이 --text=<글> 한 덩어리로
넘기는지, 빈 글을 먼저 막는지, POST 를 이 PC 에서만 받는지, 개선 후보가 결정 대기 칸에서 빠지는지.
가짜 manager.py 는 받은 argv 를 적어 두고 정해 둔 JSON 을 낸다"""
import json
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime

import server
from app.errors import Validation
from app.services import manager_panel, retro_panel
from tests.support import temp_db

FAKE_MANAGER = r'''
import json, os, sys
here = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(here, "calls.jsonl"), "a", encoding="utf-8") as handle:
    handle.write(json.dumps(sys.argv[1:], ensure_ascii=False) + "\n")
args = sys.argv[1:]
if args[0] == "retro" and args[1] == "list":
    print(json.dumps({"feedback": [{"id": 1, "text": "짧게", "status": "pending", "label": "대기"}],
                      "retros": [{"id": 3, "day": "2026-11-17", "summary": "요약"}]}, ensure_ascii=False))
elif args[0] == "retro" and args[1] == "show":
    print(json.dumps({"id": int(args[2]), "detail": {"items": []}}))
elif args[0] == "feedback":
    print(json.dumps({"id": 7}))
'''


class RetroPanelTest(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        with open(os.path.join(self.home, "manager.py"), "w", encoding="utf-8") as handle:
            handle.write(FAKE_MANAGER)
        os.environ["WORK_DASHBOARD_MANAGER_HOME"] = self.home
        self.addCleanup(os.environ.pop, "WORK_DASHBOARD_MANAGER_HOME", None)
        self.con = temp_db()

    def calls(self):
        with open(os.path.join(self.home, "calls.jsonl"), encoding="utf-8") as handle:
            return [json.loads(line) for line in handle]

    def test_listing_and_detail_routes(self):
        found = server.route(self.con, "GET", "/api/manager-retro", {}, None)
        self.assertEqual(found["retros"][0]["day"], "2026-11-17")
        detail = server.route(self.con, "GET", "/api/manager-retro/3", {}, None)
        self.assertEqual(detail["id"], 3)
        self.assertEqual(self.calls(), [["retro", "list", "--json"], ["retro", "show", "3", "--json"]])

    def test_feedback_goes_as_one_text_argument(self):
        text = "--help; rm -rf ~ 처럼 보이는 글"
        out = server.route(self.con, "POST", "/api/retro-feedback", {}, {"text": f"  {text}  "})
        self.assertEqual(out, {"id": 7})
        self.assertEqual(self.calls()[-1], ["feedback", "add", "--source", "ui", "--json", f"--text={text}"])

    def test_empty_feedback_rejected_before_running(self):
        with self.assertRaises(Validation):
            retro_panel.add("   ", home=self.home)
        self.assertFalse(os.path.exists(os.path.join(self.home, "calls.jsonl")))

    def test_feedback_only_from_this_pc(self):
        with self.assertRaises(Validation):
            server.guard_origin("POST", "/api/retro-feedback", "192.168.0.7")
        server.guard_origin("POST", "/api/retro-feedback", "127.0.0.1")


class ImprovementExcludedTest(unittest.TestCase):
    def test_improvement_candidate_not_in_decisions(self):
        home = tempfile.mkdtemp()
        os.makedirs(os.path.join(home, "state"))
        con = sqlite3.connect(os.path.join(home, "state", "manager.db"))
        con.execute("CREATE TABLE tasks (id INTEGER PRIMARY KEY, title TEXT, kind TEXT, status TEXT, priority INTEGER, "
                    "created_at TEXT, updated_at TEXT, session_id TEXT)")
        con.executemany("INSERT INTO tasks VALUES (?,?,?,?,?,?,?,?)", [
            (1, "개선 후보: 로그 정리", "decision", "open", 1, "2026-11-18T09:00:00", "2026-11-18T09:00:00", None),
            (2, "배포할까?", "decision", "open", 2, "2026-11-18T09:00:00", "2026-11-18T09:00:00", None),
        ])
        con.commit()
        con.close()
        now = datetime.now().astimezone()
        rows = manager_panel.decisions(now, manager_home=home)
        self.assertEqual([row["id"] for row in rows], [2])
        self.assertEqual(manager_panel.task_item(1, now, manager_home=home)["id"], 1)


if __name__ == "__main__":
    unittest.main()
