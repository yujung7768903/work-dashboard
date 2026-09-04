import json
import os
import socket
import stat
import tempfile
import threading
import unittest
from unittest import mock

from app.errors import NotFound, Validation
from app.repositories import sessions as session_repo
from app.services import autorun, session_message, transcript
from tests.support import temp_db
from tests.test_transcript import QUESTIONS, ask, write_transcript

SID = "sess-msg"
PID = 4242


class Deliver:
    def __init__(self):
        self.calls = []

    def __call__(self, path, line):
        self.calls.append((path, line))


class Resume:
    def __init__(self, job_id="793abbd8", error=""):
        self.calls = []
        self.result = {"job_id": job_id, "error": error}

    def __call__(self, session_id, text, cwd):
        self.calls.append((session_id, text, cwd))
        return self.result


class SendTest(unittest.TestCase):
    def setUp(self):
        self.con = temp_db()
        self.cwd = tempfile.mkdtemp()
        self.row = session_repo.register(self.con, SID, cwd=self.cwd)["id"]

    def test_empty_text_is_rejected_before_lookup(self):
        """거절 테스트는 빈 DB 에서도 돈다 — 없는 세션보다 빈 문장을 먼저 본다"""
        with self.assertRaises(Validation):
            session_message.send(self.con, 999, "   ")

    def test_unknown_session_raises(self):
        with self.assertRaises(NotFound):
            session_message.send(self.con, 999, "안녕")

    def test_live_session_gets_one_json_line_over_its_socket(self):
        deliver = Deliver()
        with mock.patch.object(transcript, "TRANSCRIPT_ROOT", "/nowhere"):
            result = session_message.send(
                self.con, self.row, " 테스트 돌려줘 ", agents=lambda sid: PID, deliver=deliver
            )
        self.assertEqual(result, {"delivered": "socket", "priority": "next"})
        ((path, line),) = deliver.calls
        self.assertTrue(path.endswith(f"/{PID}.sock"), path)
        self.assertTrue(line.endswith("\n"))
        self.assertEqual(
            json.loads(line),
            {"type": "user", "message": {"content": "테스트 돌려줘"}, "session_id": SID,
             "priority": "next", "from": "work-dashboard"},
        )

    def test_pending_question_makes_it_urgent(self):
        """선택창이 열려 있으면 now — 진행 중인 턴을 끊고 이 문장이 다음 입력이 된다"""
        deliver = Deliver()
        root = write_transcript(SID, [ask("toolu_1", QUESTIONS)])
        with mock.patch.object(transcript, "TRANSCRIPT_ROOT", root):
            result = session_message.send(
                self.con, self.row, "제목 - 질문형", agents=lambda sid: PID, deliver=deliver
            )
        self.assertEqual(result["priority"], "now")
        self.assertEqual(json.loads(deliver.calls[0][1])["priority"], "now")

    def test_dead_session_is_resumed_with_the_text(self):
        resume = Resume()
        with mock.patch.object(transcript, "TRANSCRIPT_ROOT", "/nowhere"):
            result = session_message.send(
                self.con, self.row, "이어서 해줘", agents=lambda sid: None, resume=resume
            )
        self.assertEqual(
            result, {"delivered": "resumed", "priority": "next", "job_id": "793abbd8"}
        )
        self.assertEqual(resume.calls, [(SID, "이어서 해줘", self.cwd)])

    def test_resume_failure_and_missing_cwd_are_reported(self):
        with mock.patch.object(transcript, "TRANSCRIPT_ROOT", "/nowhere"):
            with self.assertRaises(Validation):
                session_message.send(
                    self.con, self.row, "x",
                    agents=lambda sid: None, resume=Resume(job_id="", error="boom"),
                )
            gone = session_repo.register(self.con, "sess-gone", cwd="/nowhere/worktree")["id"]
            with self.assertRaises(Validation):
                session_message.send(self.con, gone, "x", agents=lambda sid: None, resume=Resume())


class SocketTest(unittest.TestCase):
    def test_socket_path_prefers_runtime_dir_then_tmp(self):
        runtime = tempfile.mkdtemp()
        with mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": runtime}):
            self.assertEqual(
                session_message.socket_path(PID),
                os.path.join("/tmp", f"cc-socks-{os.getuid()}", f"{PID}.sock"),
            )
            os.makedirs(os.path.join(runtime, "cc-socks"))
            open(os.path.join(runtime, "cc-socks", f"{PID}.sock"), "w").close()
            self.assertEqual(
                session_message.socket_path(PID), os.path.join(runtime, "cc-socks", f"{PID}.sock")
            )

    def test_deliver_writes_the_line_to_a_unix_socket(self):
        path = os.path.join(tempfile.mkdtemp(), "s.sock")
        received = []
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(path)
        server.listen(1)

        def accept():
            conn, _ = server.accept()
            with conn:
                received.append(conn.recv(4096))

        thread = threading.Thread(target=accept)
        thread.start()
        session_message._deliver(path, '{"type":"user"}\n')
        thread.join(timeout=3)
        server.close()
        self.assertEqual(received, [b'{"type":"user"}\n'])

    def test_deliver_reports_a_missing_socket(self):
        with self.assertRaises(Validation):
            session_message._deliver(os.path.join(tempfile.mkdtemp(), "none.sock"), "x\n")


def stub_claude(script_body):
    """claude 대신 돌릴 셸 스텁. 받은 인자를 옆의 args.txt 에 한 줄씩 남긴다"""
    folder = tempfile.mkdtemp()
    path = os.path.join(folder, "claude")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("#!/bin/sh\n" + f'printf "%s\\n" "$@" > "{folder}/args.txt"\n' + script_body)
    os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)
    return path, os.path.join(folder, "args.txt")


class ProcessTest(unittest.TestCase):
    def test_live_pid_reads_claude_agents_json(self):
        rows = json.dumps(
            [{"sessionId": "other", "pid": 1}, {"sessionId": SID, "pid": PID, "kind": "interactive"}]
        )
        stub, _ = stub_claude(f"echo '{rows}'\n")
        self.assertEqual(session_message.live_pid(SID, claude_bin=stub), PID)
        self.assertIsNone(session_message.live_pid("nobody", claude_bin=stub))

    def test_live_pid_is_none_when_claude_is_missing(self):
        self.assertIsNone(session_message.live_pid(SID, claude_bin="/nonexistent/claude"))

    def test_resume_session_passes_resume_and_text_without_forcing_a_model(self):
        stub, args = stub_claude('echo "backgrounded (20 words) … 793abbd8"\n')
        result = autorun.resume_session(SID, "이어서", tempfile.mkdtemp(), claude_bin=stub)
        self.assertEqual(result, {"job_id": "793abbd8", "error": ""})
        with open(args, encoding="utf-8") as handle:
            argv = handle.read().split("\n")
        self.assertEqual(argv[:4], ["--bg", "--resume", SID, "이어서"])
        self.assertNotIn("--model", argv)

    def test_resume_session_reports_launch_failure(self):
        stub, _ = stub_claude('echo "no daemon" >&2; exit 1\n')
        result = autorun.resume_session(SID, "x", tempfile.mkdtemp(), claude_bin=stub)
        self.assertEqual(result["job_id"], "")
        self.assertIn("no daemon", result["error"])


if __name__ == "__main__":
    unittest.main()
