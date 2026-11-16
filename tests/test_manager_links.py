"""매니저 탭 줄 → 트리 카드 연결, 그 일을 시작한 사용자 요청(transcript 첫 지시)"""
import json
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from unittest import mock

from app.repositories import categories as category_repo
from app.repositories import sessions as session_repo
from app.repositories import todos as todo_repo
from app.repositories import workspaces as workspace_repo
from app.services import manager_links, manager_panel, transcript
from tests.support import temp_db

NOW = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)
# 매니저 spawn.py 와 같은 모양의 상수. 문단은 \n\n 으로 시작하고 끝에 차례로 붙는다
SPAWN_PY = '''
PROGRESS = ("\\n\\n큰 단계가 바뀔 때마다 전체 대비 몇 퍼센트 왔는지 스스로 판단해 "
            "`manager.py progress` 로 남긴다.")
OPEN_RESULT = "\\n\\n일의 실제 산출물이 있으면 --open 으로 위치를 남긴다."
DECISION = "\\n\\n사용자 결정이 필요하면 결정 문서(md)를 만들지 말고 ask 로 넘긴다."
BLOCKED = "\\n\\n권한·접근 문제로 막히면 우회하지 말고 ask --blocked 로 남긴다."
SELF_STOP = ("\\n\\n맡은 일을 끝냈으면, 마지막 동작으로 완료 보고를 넣어 "
             "퇴근-보조 를 실행해 이 세션을 끈다.")
MANAGER_WORK = "\\n\\n이 세션은 매니저 자체 작업이라 작업 대시보드 분류를 하지 않는다."
'''
DIRECTIVE = "목표: 트리 메뉴를 만든다.\n\n화면:\n- List | Map\n- 맡은 일을 끝냈으면 알려 준다는 말은 본문이다"
SUFFIX = (
    "\n\n큰 단계가 바뀔 때마다 전체 대비 몇 퍼센트 왔는지 스스로 판단해 `manager.py progress` 로 남긴다."
    "\n\n일의 실제 산출물이 있으면 --open 으로 위치를 남긴다."
    "\n\n사용자 결정이 필요하면 결정 문서(md)를 만들지 말고 ask 로 넘긴다."
    "\n\n권한·접근 문제로 막히면 우회하지 말고 ask --blocked 로 남긴다."
    "\n\n맡은 일을 끝냈으면, 마지막 동작으로 완료 보고를 넣어 퇴근-보조 를 실행해 이 세션을 끈다."
)


def write_transcript(root, session_id, entries):
    os.makedirs(os.path.join(root, "proj"), exist_ok=True)
    path = os.path.join(root, "proj", f"{session_id}.jsonl")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(json.dumps(entry, ensure_ascii=False) for entry in entries) + "\n")
    return path


class LinkFixture(unittest.TestCase):
    def setUp(self):
        manager_links._request_cache.clear()
        self.home = tempfile.mkdtemp()
        with open(os.path.join(self.home, "spawn.py"), "w", encoding="utf-8") as handle:
            handle.write(SPAWN_PY)
        self.root = tempfile.mkdtemp()
        original = transcript.find_path
        patcher = mock.patch.object(
            transcript, "find_path", lambda sid, root=None: original(sid, self.root)
        )
        patcher.start()
        self.addCleanup(patcher.stop)


class FirstRequestTest(LinkFixture):
    def test_spawn_suffix_is_stripped_but_directive_kept_whole(self):
        write_transcript(self.root, "helper", [
            {"type": "attachment", "attachment": {"content": "SessionStart hook 주입"}},
            {"type": "user", "message": {"content": DIRECTIVE + SUFFIX}},
        ])
        found = manager_links.first_request("helper", self.home)
        self.assertEqual(found, {"status": "ok", "text": DIRECTIVE})

    def test_hook_and_reminder_text_is_not_the_request(self):
        write_transcript(self.root, "own", [
            {"type": "user", "isMeta": True, "message": {"content": "Caveat: 메타"}},
            {"type": "user", "message": {"content": "<command-name>/model</command-name>"}},
            {"type": "user", "message": {"content": [
                {"type": "text", "text": "<system-reminder>\n지침 전문\n</system-reminder>"},
                {"type": "text", "text": "첫 줄\n둘째 줄<system-reminder>훅</system-reminder>"},
            ]}},
            {"type": "user", "message": {"content": "두 번째 지시"}},
        ])
        found = manager_links.first_request("own", self.home)
        self.assertEqual(found["text"], "첫 줄\n둘째 줄")

    def test_statuses_without_session_or_transcript(self):
        self.assertEqual(manager_links.first_request(None, self.home)["status"], "no_session")
        self.assertEqual(manager_links.first_request("ghost", self.home)["status"], "not_found")
        write_transcript(self.root, "silent", [{"type": "assistant", "message": {"content": "혼잣말"}}])
        self.assertEqual(manager_links.first_request("silent", self.home)["status"], "empty")

    def test_without_manager_repo_nothing_is_stripped(self):
        self.assertEqual(manager_links.spawn_heads(tempfile.mkdtemp()), ())
        self.assertEqual(manager_links.strip_spawn_suffix(DIRECTIVE + SUFFIX, ()), DIRECTIVE + SUFFIX)


class CardTest(LinkFixture):
    def setUp(self):
        super().setUp()
        self.con = temp_db()
        category = category_repo.list_all(self.con)[0]
        self.space = workspace_repo.create(self.con, category["id"], "작업 대시보드")
        self.old = todo_repo.create(self.con, "지난 일", workspace_id=self.space["id"])
        self.todo = todo_repo.create(self.con, "트리 메뉴", workspace_id=self.space["id"])
        session_repo.register(self.con, "helper", cwd="/tmp")
        session_repo.link_todo(self.con, "helper", self.old["id"])
        session_repo.link_todo(self.con, "helper", self.todo["id"])
        session_repo.register(self.con, "loose", cwd="/tmp")

    def test_card_is_the_sessions_current_todo_and_its_tree(self):
        found = manager_links.cards(self.con, ["helper", "loose", None])
        self.assertEqual(set(found), {"helper"})
        card = found["helper"]
        self.assertEqual((card["todo_id"], card["title"]), (self.todo["id"], "트리 메뉴"))
        self.assertEqual((card["workspace_id"], card["workspace_name"]), (self.space["id"], "작업 대시보드"))

    def test_waiting_is_the_sessions_dashboard_signal(self):
        # 트리 카드의 대기 표시와 같은 신호(sessions.waiting). 끝난 세션·대기 아닌 세션은 빠진다
        session_repo.set_waiting(self.con, "helper", "permission")
        session_repo.set_waiting(self.con, "loose", "input")
        session_repo.register(self.con, "gone", cwd="/tmp")
        session_repo.set_waiting(self.con, "gone", "input")
        session_repo.set_state(self.con, "gone", session_repo.STATE_ENDED)
        session_repo.register(self.con, "busy", cwd="/tmp")
        found = manager_links.waiting(self.con, ["helper", "loose", "gone", "busy", "ghost", None])
        self.assertEqual(found, {"helper": "permission", "loose": "input"})
        self.assertEqual(manager_links.waiting(None, ["helper"]), {})
        self.assertEqual(manager_links.waiting(self.con, []), {})

    def test_rows_carry_waiting_even_without_card(self):
        # 카드 없는 줄도 트리 탭에 카드 한 장으로 그리므로 대기 신호가 실려야 한다
        session_repo.set_waiting(self.con, "loose", "input")
        rows = [
            {"session_id": "loose", "name": "보조3 | 결정", "status": "결정 대기"},
            {"session_id": "helper", "name": "보조2 | 트리", "status": "작업 중"},
        ]
        helpers = manager_panel.snapshot(
            "helpers", now=NOW, con=self.con, manager_home=self.home, helpers_fn=lambda _home: rows
        )["helpers"]["items"]
        self.assertEqual([(item["card"], item["waiting"]) for item in helpers][0], (None, "input"))
        self.assertIsNone(helpers[1]["waiting"])

        os.makedirs(os.path.join(self.home, "state"))
        db = sqlite3.connect(os.path.join(self.home, "state", "manager.db"))
        db.execute(
            "CREATE TABLE tasks (id INTEGER PRIMARY KEY, title TEXT, kind TEXT, status TEXT, priority INTEGER,"
            " created_at TEXT, updated_at TEXT, session_id TEXT)"
        )
        db.executemany(
            "INSERT INTO tasks VALUES (?,?,?,?,?,?,?,?)",
            [
                (1, "결정", "decision", "open", 1, "2026-11-16T01:00:00Z", "2026-11-16T01:00:00Z", "loose"),
                (2, "세션 없는 결정", "decision", "open", 1, "2026-11-16T01:00:00Z", "2026-11-16T01:00:00Z", None),
            ],
        )
        db.commit()
        db.close()
        items = {item["id"]: item for item in manager_panel.decisions(NOW, manager_home=self.home, con=self.con)}
        self.assertEqual(items[1]["waiting"], "input")
        self.assertIsNone(items[2]["waiting"])

    def test_helpers_and_tasks_carry_card_and_request(self):
        write_transcript(self.root, "helper", [{"type": "user", "message": {"content": DIRECTIVE + SUFFIX}}])
        rows = [{"session_id": "helper", "name": "보조2 | 트리", "status": "작업 중", "percent": 65,
                 "doing": "화면", "moved_at": None, "percent_at": None}]
        helpers = manager_panel.snapshot(
            "helpers", now=NOW, con=self.con, manager_home=self.home, helpers_fn=lambda _home: rows
        )["helpers"]["items"]
        self.assertEqual(helpers[0]["card"]["todo_id"], self.todo["id"])
        self.assertEqual(helpers[0]["request"], {"status": "ok", "text": DIRECTIVE})

        os.makedirs(os.path.join(self.home, "state"))
        db = sqlite3.connect(os.path.join(self.home, "state", "manager.db"))
        db.execute(
            "CREATE TABLE tasks (id INTEGER PRIMARY KEY, title TEXT, kind TEXT, status TEXT, priority INTEGER,"
            " created_at TEXT, updated_at TEXT, session_id TEXT, source TEXT, source_ref TEXT)"
        )
        db.executemany(
            "INSERT INTO tasks VALUES (?,?,?,?,?,?,?,?,?,?)",
            [
                (1, "A·B 중 고르기", "decision", "open", 2, "2026-11-16T01:00:00Z", "2026-11-16T01:00:00Z",
                 "helper", "session", None),
                (2, "PFD-6350 확인", "decision", "open", 1, "2026-11-16T01:00:00Z", "2026-11-16T01:00:00Z",
                 None, "jira", "PFD-6350"),
            ],
        )
        db.commit()
        db.close()
        items = {item["id"]: item for item in manager_panel.decisions(NOW, manager_home=self.home, con=self.con)}
        self.assertEqual(items[1]["card"]["title"], "트리 메뉴")
        self.assertEqual(items[1]["popup"]["request"]["text"], DIRECTIVE)
        # 세션 없이 들어온 일 — 카드도 요청도 없고, 출처를 화면이 보인다
        self.assertIsNone(items[2]["card"])
        self.assertEqual(items[2]["popup"]["request"], {"status": "no_session"})
        self.assertEqual((items[2]["popup"]["source"], items[2]["popup"]["source_ref"]), ("jira", "PFD-6350"))


if __name__ == "__main__":
    unittest.main()
