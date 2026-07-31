import json
import os
import tempfile
import unittest
from unittest import mock

from app.constants import TRANSCRIPT_MAX_CHARS, TRANSCRIPT_MAX_MESSAGES
from app.errors import NotFound
from app.repositories import sessions as session_repo
from app.services import session_link, transcript
from tests.support import temp_db

SID = "sess-transcript"


def write_transcript(session_id, entries):
    """~/.claude/projects/<프로젝트>/<세션id>.jsonl 흉내. root 를 돌려줌"""
    root = tempfile.mkdtemp()
    project = os.path.join(root, "-home-user-work")
    os.makedirs(project)
    with open(os.path.join(project, f"{session_id}.jsonl"), "w", encoding="utf-8") as handle:
        for entry in entries:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return root


class ParseLineTest(unittest.TestCase):
    def test_reads_plain_user_text(self):
        line = json.dumps({"type": "user", "message": {"content": "할일  추가해줘"}})
        self.assertEqual(
            transcript.parse_line(line), {"role": "user", "text": "할일 추가해줘"}
        )

    def test_reads_assistant_text_blocks_only(self):
        line = json.dumps(
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "thinking", "thinking": "속마음"},
                        {"type": "text", "text": "네 추가했습니다"},
                        {"type": "tool_use", "name": "Bash"},
                    ]
                },
            }
        )
        self.assertEqual(
            transcript.parse_line(line), {"role": "assistant", "text": "네 추가했습니다"}
        )

    def test_skips_non_conversation_lines(self):
        skipped = [
            {"type": "user", "message": {"content": [{"type": "tool_result"}]}},
            {"type": "user", "isMeta": True, "message": {"content": "주입된 컨텍스트"}},
            {"type": "assistant", "isSidechain": True, "message": {"content": "서브에이전트"}},
            {"type": "system", "message": {"content": "훅 출력"}},
            {"type": "user", "message": {"content": "<system-reminder> 어쩌구"}},
            "깨진 줄",
        ]
        for entry in skipped:
            line = entry if isinstance(entry, str) else json.dumps(entry)
            self.assertIsNone(transcript.parse_line(line), line)

    def test_truncates_long_text(self):
        line = json.dumps({"type": "user", "message": {"content": "가" * 1000}})
        self.assertEqual(len(transcript.parse_line(line)["text"]), TRANSCRIPT_MAX_CHARS)


class RecentTest(unittest.TestCase):
    def test_returns_last_messages_in_order(self):
        entries = [
            {"type": "user", "message": {"content": f"질문 {index}"}}
            for index in range(TRANSCRIPT_MAX_MESSAGES + 5)
        ]
        root = write_transcript(SID, entries)
        messages = transcript.recent(SID, root=root)
        self.assertEqual(len(messages), TRANSCRIPT_MAX_MESSAGES)
        self.assertEqual(messages[-1]["text"], f"질문 {TRANSCRIPT_MAX_MESSAGES + 4}")

    def test_missing_transcript_is_empty(self):
        self.assertEqual(transcript.recent(SID, root=tempfile.mkdtemp()), [])

    def test_tail_drops_partial_first_line(self):
        root = write_transcript(SID, [{"type": "user", "message": {"content": "x"}}] * 3)
        path = transcript.find_path(SID, root)
        self.assertEqual(transcript.tail(path, max_bytes=10), [])


class DetailTest(unittest.TestCase):
    def test_detail_carries_session_id_and_messages(self):
        con = temp_db()
        session = session_repo.register(con, SID, cwd="/home/user/work")
        root = write_transcript(SID, [{"type": "user", "message": {"content": "안녕"}}])
        with mock.patch.object(transcript, "TRANSCRIPT_ROOT", root):
            payload = session_link.detail(con, session["id"])
        self.assertEqual(payload["session"]["claude_session_id"], SID)
        self.assertEqual(payload["messages"], [{"role": "user", "text": "안녕"}])

    def test_unknown_session_raises(self):
        con = temp_db()
        with self.assertRaises(NotFound):
            session_link.detail(con, 999)


if __name__ == "__main__":
    unittest.main()
