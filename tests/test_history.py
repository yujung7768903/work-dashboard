import json
import os
import tempfile
import time
import unittest

from app.constants import HISTORY_FIRST_PROMPT_CHARS, HISTORY_HEAD_BYTES
from app.services import history, transcript

DAY = 86400


def write_session(root, project, session_id, entries, age_days=0):
    """~/.claude/projects/<프로젝트>/<세션id>.jsonl 흉내. mtime 을 age_days 만큼 과거로"""
    folder = os.path.join(root, project)
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"{session_id}.jsonl")
    with open(path, "w", encoding="utf-8") as handle:
        for entry in entries:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    stamp = time.time() - age_days * DAY
    os.utime(path, (stamp, stamp))
    return path


def prompt(text, cwd="/home/user/work", stamp="2026-07-30T01:00:00.000Z"):
    return {"type": "user", "cwd": cwd, "timestamp": stamp, "message": {"content": text}}


class HeadTest(unittest.TestCase):
    def test_reads_only_the_front(self):
        root = tempfile.mkdtemp()
        path = write_session(root, "proj", "s1", [prompt(f"질문 {i}") for i in range(500)])
        self.assertLess(len(transcript.head(path, 200)), 500)

    def test_drops_partial_last_line(self):
        """상한에 걸려 잘렸으면 마지막 줄은 반쪽이라 버린다"""
        root = tempfile.mkdtemp()
        path = write_session(root, "proj", "s1", [prompt("가" * 100)] * 5)
        for line in transcript.head(path, 150):
            json.loads(line)  # 깨진 줄이 섞여 나오면 여기서 실패


class ScanTest(unittest.TestCase):
    def test_groups_by_cwd_and_keeps_first_prompt(self):
        root = tempfile.mkdtemp()
        write_session(root, "a", "s1", [prompt("훅을 만들어줘", cwd="/work/dash")])
        write_session(root, "a", "s2", [prompt("차트를 고쳐줘", cwd="/work/dash")])
        write_session(root, "b", "s3", [prompt("항공권 검색", cwd="/work/routex")])
        groups = history.scan(days=7, root=root)
        self.assertEqual([group["cwd"] for group in groups], ["/work/dash", "/work/routex"])
        self.assertEqual(
            [row["first_prompt"] for row in groups[0]["sessions"]],
            ["훅을 만들어줘", "차트를 고쳐줘"],
        )

    def test_filters_by_mtime(self):
        root = tempfile.mkdtemp()
        write_session(root, "a", "recent", [prompt("최근")], age_days=2)
        write_session(root, "a", "old", [prompt("오래됨")], age_days=30)
        groups = history.scan(days=7, root=root)
        self.assertEqual(
            [row["first_prompt"] for group in groups for row in group["sessions"]], ["최근"]
        )

    def test_skips_slash_commands_and_compaction_prompts(self):
        """이것들이 첫 발화로 잡히면 세션의 주제를 가린다"""
        root = tempfile.mkdtemp()
        write_session(
            root,
            "a",
            "s1",
            [
                prompt("<command-name>/model</command-name>"),
                prompt("Below is a conversation log from a Claude Code coding session."),
                prompt("진짜 지시"),
            ],
        )
        groups = history.scan(days=7, root=root)
        self.assertEqual(groups[0]["sessions"][0]["first_prompt"], "진짜 지시")

    def test_skips_sessions_without_human_speech(self):
        root = tempfile.mkdtemp()
        write_session(root, "a", "s1", [prompt("<command-name>/model</command-name>")])
        write_session(root, "a", "s2", [{"type": "system", "message": {"content": "훅"}}])
        self.assertEqual(history.scan(days=7, root=root), [])

    def test_truncates_long_first_prompt(self):
        root = tempfile.mkdtemp()
        write_session(root, "a", "s1", [prompt("가" * 500)])
        groups = history.scan(days=7, root=root)
        self.assertEqual(
            len(groups[0]["sessions"][0]["first_prompt"]), HISTORY_FIRST_PROMPT_CHARS
        )

    def test_reads_only_head_of_huge_file(self):
        """수백 MB 를 통째로 읽지 않는다 — 앞 조각을 넘어선 발화는 안 잡혀야 한다"""
        root = tempfile.mkdtemp()
        filler = [prompt("가" * 2000) for _ in range(HISTORY_HEAD_BYTES // 1000)]
        write_session(root, "a", "s1", [prompt("맨 앞")] + filler + [prompt("꼬리 발화")])
        groups = history.scan(days=7, root=root)
        texts = [row["first_prompt"] for row in groups[0]["sessions"]]
        self.assertEqual(texts, ["맨 앞"])


class RenderTest(unittest.TestCase):
    def test_one_line_per_session_under_a_project_header(self):
        root = tempfile.mkdtemp()
        write_session(root, "a", "s1", [prompt("훅을 만들어줘", cwd="/work/dash")])
        text = history.render(history.scan(days=7, root=root), days=7)
        self.assertIn("최근 7일 세션 1건 / 작업 위치 1곳", text)
        self.assertIn("== /work/dash (세션 1건) ==", text)
        self.assertIn("훅을 만들어줘", text)

    def test_empty_history_still_renders_a_header(self):
        text = history.render(history.scan(days=7, root=tempfile.mkdtemp()), days=7)
        self.assertIn("세션 0건", text)


if __name__ == "__main__":
    unittest.main()
