"""권한 요청 칸 — 무엇을 기다리는지(transcript 의 미응답 호출)를 찾는 규칙, 화면에서 답할 수 있는 요청(매니저
permission_gate 가 기다리는 요청)과 그렇지 않은 요청(터미널 프롬프트·꺼진 세션)을 가르는 규칙, 허용이 사람이 본
그 호출에만 가는지.

매니저는 가짜 manager.py 로 갈음한다 — 받은 argv 를 그대로 적어 두므로 셸 없이 리스트 인자로 perm-answer 를
부르는지를 실제 프로세스 경계에서 본다. 살아 있는 세션 목록(claude agents --json)은 주입한다
"""
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta

import server
from app.errors import Conflict, NotFound, Validation
from app.repositories import categories as category_repo
from app.repositories import sessions as session_repo
from app.repositories import todos as todo_repo
from app.repositories import workspaces as workspace_repo
from app.services import permission_answer as pa
from app.services import transcript
from tests.support import temp_db

FAKE_MANAGER = r'''
import json, os, sys
here = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(here, "calls.jsonl"), "a", encoding="utf-8") as handle:
    handle.write(json.dumps(sys.argv[1:], ensure_ascii=False) + "\n")
with open(os.path.join(here, "exit.txt"), encoding="utf-8") as handle:
    sys.exit(int(handle.read().strip()))
'''

COMMAND = "cd /repo && git push -u origin fix/cors && gh pr create --title 'CORS' --body-file pr.md"
NOW = datetime(2026, 11, 17, 10, 0, 0).astimezone()


def stamp(seconds_ago):
    """요청 파일의 created_at 모양 — 지역 시각, 시간대 없음"""
    return (NOW - timedelta(seconds=seconds_ago)).strftime("%Y-%m-%dT%H:%M:%S")


def assistant_tool(tool_id, name, data, at="2026-11-17T00:59:00.000Z"):
    return {"type": "assistant", "timestamp": at,
            "message": {"content": [{"type": "tool_use", "id": tool_id, "name": name, "input": data}]}}


def tool_result(tool_id):
    return {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": tool_id, "content": "ok"}]}}


def prompt(text):
    return {"type": "user", "message": {"content": text}}


def preview_of(data, size=200):
    """매니저 훅과 같은 미리보기 — JSON 을 200자에서 자른다(가림은 테스트마다 손으로 넣는다)"""
    return json.dumps(data, ensure_ascii=False)[:size]


class Fixture(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        with open(os.path.join(self.home, "manager.py"), "w", encoding="utf-8") as handle:
            handle.write(FAKE_MANAGER)
        self.exit_code(0)
        os.makedirs(os.path.join(self.home, "state", "perm"))
        self.root = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.root, "proj"))
        self.con = temp_db()
        category = category_repo.list_all(self.con)[0]
        space = workspace_repo.create(self.con, category["id"], "작업 대시보드")
        self.todo = todo_repo.create(self.con, "CORS 제한", workspace_id=space["id"])
        self.other = todo_repo.create(self.con, "다른 할일", workspace_id=space["id"])
        self.live = {}

    def session(self, sid, todo=None, waiting="permission"):
        session_repo.register(self.con, sid, cwd="/repo")
        session_repo.link_todo(self.con, sid, (todo or self.todo)["id"])
        if waiting:
            session_repo.set_waiting(self.con, sid, waiting)

    def write_transcript(self, sid, entries):
        with open(os.path.join(self.root, "proj", f"{sid}.jsonl"), "w", encoding="utf-8") as handle:
            for entry in entries:
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def request(self, req_id, sid, preview, seconds_ago=30, tool="Bash", deliver="terminal"):
        body = {"id": req_id, "session_id": sid, "cwd": "/repo", "tool_name": tool, "preview": preview,
                "created_at": stamp(seconds_ago), "deliver": deliver}
        with open(os.path.join(self.home, "state", "perm", f"{req_id}.json"), "w", encoding="utf-8") as handle:
            json.dump(body, handle, ensure_ascii=False)
        return body

    def exit_code(self, code):
        with open(os.path.join(self.home, "exit.txt"), "w", encoding="utf-8") as handle:
            handle.write(str(code))

    def calls(self):
        path = os.path.join(self.home, "calls.jsonl")
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8") as handle:
            return [json.loads(line) for line in handle]

    def items(self, todo=None):
        payload = pa.for_todo(self.con, (todo or self.todo)["id"], home=self.home, live=lambda: self.live,
                              root=self.root, now=NOW)
        return payload["items"]


class PendingToolUsesTest(Fixture):
    def test_unanswered_calls_after_the_last_prompt(self):
        self.write_transcript("s1", [
            # 세션이 죽었다 재개돼 결과 없이 남은 예전 호출 — 다음 지시 앞이라 버린다
            assistant_tool("old", "Bash", {"command": "ls"}),
            prompt("이어서 해"),
            assistant_tool("done", "Bash", {"command": "pwd"}),
            tool_result("done"),
            # 질문은 권한이 아니다 — 세션 탭 몫
            assistant_tool("ask", "AskUserQuestion", {"questions": []}),
            assistant_tool("wait", "Bash", {"command": COMMAND, "description": "PR 열기"}),
            # 훅이 넣은 줄(isMeta)·도구 결과는 사람이 친 지시가 아니다
            {"type": "user", "isMeta": True, "message": {"content": "<system-reminder>x</system-reminder>"}},
        ])
        calls = transcript.pending_tool_uses("s1", self.root)
        self.assertEqual([call["tool_use_id"] for call in calls], ["wait"])
        self.assertEqual(calls[0]["input"]["command"], COMMAND, "명령 전문 그대로")

    def test_no_transcript(self):
        self.assertEqual(transcript.pending_tool_uses("nope", self.root), [])


class MatchTest(unittest.TestCase):
    def test_redacted_and_cut_preview_matches_the_full_call(self):
        data = {"command": COMMAND + " && echo " + "x" * 300, "description": "PR 열기"}
        # 매니저 가림 규칙(-u <값>)과 200자 자름. 끝이 가림 표지 중간에서 잘려도 맞춘다
        preview = preview_of(data).replace("-u origin", "-u [REDACTED]")
        call = {"tool_use_id": "t1", "name": "Bash", "input": data}
        self.assertIs(pa.match_call({"tool_name": "Bash", "preview": preview}, [call]), call)
        cut = preview_of(data, 30) + "[REDAC"
        self.assertIs(pa.match_call({"tool_name": "Bash", "preview": cut}, [call]), call)

    def test_other_command_or_tool_does_not_match(self):
        data = {"command": COMMAND}
        call = {"tool_use_id": "t1", "name": "Bash", "input": data}
        self.assertIsNone(pa.match_call({"tool_name": "Bash", "preview": preview_of({"command": "rm -rf /"})}, [call]))
        self.assertIsNone(pa.match_call({"tool_name": "Write", "preview": preview_of(data)}, [call]))
        # 앞부분은 같아도 미리보기는 JSON 맨 앞부터다 — 중간에서 찾은 조각으로 맞추지 않는다
        self.assertIsNone(pa.match_call({"tool_name": "Bash", "preview": '"git push'}, [call]))


class PendingRequestsTest(Fixture):
    def test_fresh_requests_latest_per_session(self):
        self.request("0001", "s1", "{}", seconds_ago=100)
        self.request("0002", "s1", "{}", seconds_ago=10)
        # 훅 timeout(600초)보다 오래 남은 파일은 기다리던 훅이 이미 없다
        self.request("0003", "s2", "{}", seconds_ago=700)
        with open(os.path.join(self.home, "state", "perm", "proactive_denied.jsonl"), "w") as handle:
            handle.write("{}\n")
        found = pa.pending_requests(self.home, NOW)
        self.assertEqual(sorted(found), ["s1"])
        self.assertEqual(found["s1"]["id"], "0002")

    def test_missing_manager_folder(self):
        self.assertEqual(pa.pending_requests(os.path.join(self.home, "nope"), NOW), {})


class ForTodoTest(Fixture):
    def test_gate_request_shows_full_command_and_is_answerable(self):
        self.session("s1")
        data = {"command": COMMAND, "description": "PR 열기"}
        self.write_transcript("s1", [prompt("CORS 고쳐"), assistant_tool("t1", "Bash", data)])
        self.request("0411", "s1", preview_of(data).replace("-u origin", "-u [REDACTED]"), seconds_ago=60)
        self.live = {"s1": {"id": "s1short", "name": "보조1 | CORS", "waitingFor": PROMPT}}
        [item] = self.items()
        self.assertEqual(item["mode"], pa.MODE_GATE)
        self.assertTrue(item["verified"])
        self.assertEqual(item["request"]["id"], "0411")
        self.assertEqual(item["calls"][0]["text"], COMMAND, "가린 미리보기가 아니라 전문")
        self.assertEqual(item["calls"][0]["description"], "PR 열기")
        self.assertTrue(item["calls"][0]["is_command"])
        self.assertEqual(item["waited_sec"], 60)
        self.assertEqual(item["session"]["name"], "보조1 | CORS")
        self.assertIsNotNone(item["deadline_at"])
        self.assertIsNone(item["attach"])

    def test_gate_request_without_matching_call_shows_nothing_to_allow(self):
        self.session("s1")
        self.write_transcript("s1", [assistant_tool("t1", "Bash", {"command": "ls"})])
        self.request("0412", "s1", preview_of({"command": "rm -rf /tmp/x"}))
        [item] = self.items()
        self.assertEqual(item["mode"], pa.MODE_GATE)
        self.assertFalse(item["verified"])
        self.assertEqual(item["calls"], [], "다른 호출을 이 요청의 명령처럼 보이지 않는다")
        self.assertEqual(item["request"]["preview"], '{"command": "rm -rf /tmp/x"}')

    def test_terminal_prompt_of_a_live_session(self):
        self.session("s1")
        self.write_transcript("s1", [assistant_tool("t1", "Edit", {"file_path": "/repo/a.py", "old_string": "a",
                                                                    "new_string": "b"})])
        self.live = {"s1": {"id": "abcd1234", "name": "보조", "waitingFor": PROMPT}}
        [item] = self.items()
        self.assertEqual(item["mode"], pa.MODE_TERMINAL)
        self.assertEqual(item["attach"], "claude attach abcd1234")
        self.assertEqual(item["calls"][0]["target"], "/repo/a.py")
        self.assertFalse(item["calls"][0]["is_command"])
        self.assertIn('"new_string": "b"', item["calls"][0]["text"], "명령이 아닌 도구는 입력 전체")
        self.assertIsNone(item["request"])

    def test_ended_session_left_waiting(self):
        self.session("s1")
        self.write_transcript("s1", [assistant_tool("t1", "Bash", {"command": COMMAND},
                                                    at="2026-11-13T07:19:58.407Z")])
        [item] = self.items()
        self.assertEqual(item["mode"], pa.MODE_ENDED)
        self.assertEqual(item["requested_at"], datetime(2026, 11, 13, 7, 19, 58).replace(
            tzinfo=__import__("datetime").timezone.utc).astimezone().isoformat(timespec="seconds"))

    def test_skips_what_is_not_waiting(self):
        # 살아 있고 권한 창이 없는 세션 — DB 표시가 낡았다
        self.session("busy")
        self.write_transcript("busy", [assistant_tool("t1", "Bash", {"command": "sleep 60"})])
        self.live = {"busy": {"id": "busy", "waitingFor": None}}
        self.assertEqual(self.items(), [])

    def test_ended_session_only_when_it_is_the_latest_on_the_todo(self):
        self.session("old")
        self.write_transcript("old", [assistant_tool("t1", "Bash", {"command": COMMAND})])
        self.session("new", waiting=None)
        self.con.execute("UPDATE sessions SET last_seen_at='2999-01-01T00:00:00+00:00' WHERE claude_session_id='new'")
        self.assertEqual(self.items(), [], "예전 세션의 흔적이 지금 일을 가리지 않는다")

    def test_does_not_list_live_sessions_without_a_waiting_mark(self):
        """권한 대기 표시도 요청 파일도 없으면 claude agents(1~2초)를 부르지 않는다"""
        self.session("s1", waiting=None)

        def boom():
            raise AssertionError("claude agents 를 불렀다")

        payload = pa.for_todo(self.con, self.todo["id"], home=self.home, live=boom, root=self.root, now=NOW)
        self.assertEqual(payload, {"items": []})

    def test_session_moved_to_another_todo(self):
        self.session("s1")
        session_repo.link_todo(self.con, "s1", self.other["id"])
        data = {"command": COMMAND}
        self.write_transcript("s1", [assistant_tool("t1", "Bash", data)])
        self.request("0411", "s1", preview_of(data))
        self.assertEqual(self.items(), [])
        self.assertEqual(len(self.items(self.other)), 1)


PROMPT = pa.PROMPT_WAITING


class AnswerTest(Fixture):
    def setUp(self):
        super().setUp()
        self.data = {"command": COMMAND}
        self.write_transcript("s1", [assistant_tool("t1", "Bash", self.data)])
        self.req = self.request("0411", "s1", preview_of(self.data))

    def answer(self, reply="yes", **overrides):
        args = {"request_id": "0411", "reply": reply, "session_id": "s1", "created_at": self.req["created_at"],
                "tool_use_id": "t1"}
        args.update(overrides)
        return pa.answer(home=self.home, root=self.root, now=NOW, **args)

    def test_allow_and_deny_go_through_perm_answer_as_list_args(self):
        self.assertEqual(self.answer("yes")["decision"], "allow")
        self.assertEqual(self.answer("no", tool_use_id=None)["decision"], "deny")
        self.assertEqual(self.calls(), [["perm-answer", "0411", "yes"], ["perm-answer", "0411", "no"]])

    def test_rejects_bad_input_before_calling_manager(self):
        for kwargs in ({"request_id": "41"}, {"request_id": "0411; rm -rf /"}, {"reply": "always"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(Validation):
                self.answer(**kwargs)
        self.assertEqual(self.calls(), [])

    def test_request_replaced_by_a_new_one_with_the_same_id(self):
        """4자리 id 는 다시 쓰인다 — 화면이 본 요청이 아니면 넘기지 않는다"""
        with self.assertRaises(Conflict):
            self.answer(created_at="2026-11-17T09:00:00")
        with self.assertRaises(Conflict):
            self.answer(session_id="other")
        self.assertEqual(self.calls(), [])

    def test_allow_only_the_call_that_was_shown(self):
        with self.assertRaises(Validation):
            self.answer("yes", tool_use_id="different")
        # 미리보기와 맞는 호출을 transcript 에서 못 찾으면 허용은 막고 거부는 받는다
        self.write_transcript("s1", [assistant_tool("t2", "Bash", {"command": "rm -rf /"})])
        with self.assertRaises(Validation):
            self.answer("yes", tool_use_id="t2")
        self.assertEqual(self.answer("no", tool_use_id=None)["decision"], "deny")
        self.assertEqual(self.calls(), [["perm-answer", "0411", "no"]])

    def test_gate_closed_in_between(self):
        self.exit_code(1)
        with self.assertRaises(Conflict):
            self.answer("no")

    def test_stale_request_file(self):
        self.req = self.request("0411", "s1", preview_of(self.data), seconds_ago=900)
        with self.assertRaises(Conflict):
            self.answer("no")

    def test_missing_manager(self):
        os.remove(os.path.join(self.home, "manager.py"))
        with self.assertRaises(NotFound):
            self.answer("no")


class RouteTest(unittest.TestCase):
    def test_answer_only_from_this_pc(self):
        """--lan 화면에는 인증이 없다 — 권한 허용은 이 PC 에서만"""
        with self.assertRaises(Validation):
            server.guard_origin("POST", "/api/permission-answer", "192.168.0.10")
        server.guard_origin("POST", "/api/permission-answer", "127.0.0.1")
        server.guard_origin("GET", "/api/permissions", "192.168.0.10")

    def test_get_needs_todo_id(self):
        with self.assertRaises(Validation):
            server.route(temp_db(), "GET", "/api/permissions", {}, {})


if __name__ == "__main__":
    unittest.main()
