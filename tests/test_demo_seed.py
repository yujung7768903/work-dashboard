"""데모 한 벌이 실제로 화면에 그려질 모양으로 나오는지.

데모는 실 데이터를 대신하는 것이라 세 축이 다 채워져야 한다 — 보드(영어 데이터),
사용량(HOME 아래 파일), 워크트리(진짜 git 저장소). 하나라도 비면 녹화할 화면이 빈다.
"""
import json
import pathlib
import re
import subprocess
import sys
import tempfile
import unittest

from app.db import connect
from app.services import board, usage, worktrees

ROOT = pathlib.Path(__file__).resolve().parent.parent
SEED = ROOT / "demo" / "seed.py"
HANGUL = re.compile(r"[가-힣]")
# 사람이 읽는 데이터. 이 값들이 한국어면 영어 데모가 아니다
DATA_FIELDS = ("name", "title", "note", "precondition", "last_prompt", "goal", "purpose",
               "background", "considerations")


def built_once():
    root = pathlib.Path(tempfile.mkdtemp())
    subprocess.run([sys.executable, str(SEED), "--root", str(root)],
                   check=True, capture_output=True)
    return root


class DemoSeedTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = built_once()
        cls.home = cls.root / "home"
        cls.con = connect(str(cls.home / ".claude/work-dashboard/dash.db"))

    def test_board_is_english(self):
        tree = board.tree(self.con, "workspace")
        names = [group["name"] for group in tree["groups"]]
        self.assertIn("Usage-based billing", names)
        self.assertTrue(any(group["todos"] for group in tree["groups"]))
        for group in tree["groups"]:
            for todo in group["todos"]:
                for field in DATA_FIELDS:
                    self.assertIsNone(HANGUL.search(str(todo.get(field) or "")), todo)

    def test_sessions_carry_english_prompts(self):
        rows = self.con.execute("SELECT last_prompt, cwd FROM sessions").fetchall()
        self.assertTrue(rows)
        for row in rows:
            self.assertIsNone(HANGUL.search(row["last_prompt"]))

    def test_usage_reads_the_demo_files(self):
        snapshot = usage.snapshot(
            self.con,
            limits_path=str(self.home / ".claude/token-optimizer/rate-limits.json"),
            cost_path=str(self.home / ".claude/metrics/costs.jsonl"),
            config_path=str(self.home / ".claude.json"),
        )
        self.assertEqual(len(snapshot["windows"]), 2)
        self.assertTrue(snapshot["pct_samples"])
        self.assertTrue(snapshot["tokens"]["available"])
        self.assertEqual(snapshot["weekly"]["tracks"][0]["plan"], "Max 20x")
        # 플랜 이름은 인자가 아니라 HOME 아래 설정에서 오므로 파일 쪽을 본다
        config = json.loads((self.home / ".claude.json").read_text())
        self.assertEqual(config["oauthAccount"]["userRateLimitTier"], "default_claude_max_20x")

    def test_worktrees_come_from_real_repos(self):
        groups = worktrees.overview(self.con, "workspace")
        self.assertTrue(groups["groups"])
        for group in groups["groups"]:
            branches = [row["branch"] for row in group["rows"]]
            self.assertIn("master", branches)
            self.assertTrue([name for name in branches if name.startswith("worktree-")])

    def test_google_tasks_looks_connected(self):
        state = self.con.execute("SELECT * FROM gtasks_state WHERE id=1").fetchone()
        self.assertEqual(state["enabled"], 1)
        self.assertTrue(state["last_sync_at"])
        self.assertIsNone(state["last_error"])
        linked = self.con.execute(
            "SELECT name, gtasks_enabled FROM categories WHERE google_list_id IS NOT NULL"
        ).fetchall()
        # 켠 것과 끈 것이 섞여 있어야 카테고리별 스위치가 무엇인지 화면에서 읽힌다
        self.assertTrue([row for row in linked if row["gtasks_enabled"]])
        self.assertTrue([row for row in linked if not row["gtasks_enabled"]])

    def test_google_credentials_and_schedule_are_where_the_panel_looks(self):
        path = self.home / ".claude/work-dashboard/gtasks.json"
        self.assertTrue(json.loads(path.read_text())["refresh_token"])
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        agents = list((self.home / "Library/LaunchAgents").glob("*.plist"))
        self.assertTrue(agents)
        plist = agents[0].read_text()
        self.assertIn("gtasks-sync", plist)
        self.assertIn("<integer>600</integer>", plist)

    def test_launcher_points_at_the_demo_home(self):
        script = (self.root / "serve.sh").read_text()
        self.assertIn(f'export HOME="{self.home}"', script)
        self.assertIn("server.py --port", script)

    def test_transcripts_are_readable(self):
        found = list((self.home / ".claude/projects").glob("*/*.jsonl"))
        self.assertTrue(found)
        for path in found:
            for line in path.read_text().splitlines():
                entry = json.loads(line)
                self.assertIn(entry["type"], ("user", "assistant"))


if __name__ == "__main__":
    unittest.main()
