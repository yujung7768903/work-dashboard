import json
import os
import subprocess
import sys
import unittest

from app.constants import DB_PATH_ENV, STATE_ENDED, STATE_IDLE, STATE_WORKING
from app.db import connect
from app.repositories import categories as category_repo
from app.repositories import sessions as session_repo
from app.repositories import workspaces as workspace_repo
from app.services import session_link
from tests.support import temp_db_path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOK = os.path.join(ROOT, "hooks", "dash_hook.py")
SID = "hook-sess"


class HookTest(unittest.TestCase):
    def setUp(self):
        self.path = temp_db_path()
        self.env = dict(os.environ, **{DB_PATH_ENV: self.path})
        self.con = connect(self.path)

    def run_hook(self, event, payload, raw=None):
        result = subprocess.run(
            [sys.executable, HOOK, event],
            input=raw if raw is not None else json.dumps(payload),
            capture_output=True,
            text=True,
            env=self.env,
        )
        return result.returncode, result.stdout

    def seed_workspace(self):
        """워크스페이스가 하나라도 있어야 온보딩 대신 분류 블록이 나온다"""
        dev = category_repo.get_by_name(self.con, "개발")["id"]
        workspace_repo.create(self.con, dev, "기존 작업")

    def test_session_start_registers_and_injects_catalog(self):
        self.seed_workspace()
        code, out = self.run_hook("SessionStart", {"session_id": SID, "cwd": "/tmp"})
        self.assertEqual(code, 0)
        self.assertIn('state="unclassified"', out)
        self.assertIsNotNone(session_repo.find(self.con, SID))

    def test_session_start_injects_onboarding_when_no_workspace_exists(self):
        """빈 DB 는 분류가 아니라 초기 설정이 먼저다"""
        code, out = self.run_hook("SessionStart", {"session_id": SID, "cwd": "/tmp"})
        self.assertEqual(code, 0)
        self.assertIn('state="onboarding"', out)
        self.assertIn("scan-history", out)

    def test_onboarding_stops_after_user_declines(self):
        session_link.decline(self.con)
        _, out = self.run_hook("SessionStart", {"session_id": SID, "cwd": "/tmp"})
        self.assertIn('state="unclassified"', out)

    def test_prompt_submit_sets_working_and_prompt(self):
        self.run_hook("SessionStart", {"session_id": SID, "cwd": "/tmp"})
        code, _ = self.run_hook(
            "UserPromptSubmit", {"session_id": SID, "prompt": "락 확인해줘"}
        )
        self.assertEqual(code, 0)
        session = session_repo.get(self.con, SID)
        self.assertEqual(session["state"], STATE_WORKING)
        self.assertEqual(session["last_prompt"], "락 확인해줘")

    def test_prompt_submit_reinjects_while_unclassified(self):
        self.seed_workspace()
        self.run_hook("SessionStart", {"session_id": SID, "cwd": "/tmp"})
        _, out = self.run_hook("UserPromptSubmit", {"session_id": SID, "prompt": "x"})
        self.assertIn('state="unclassified"', out)

    def test_prompt_submit_silent_after_classified(self):
        self.run_hook("SessionStart", {"session_id": SID, "cwd": "/tmp"})
        session_repo.classify(self.con, SID, category_name="운영")
        _, out = self.run_hook("UserPromptSubmit", {"session_id": SID, "prompt": "x"})
        self.assertEqual(out.strip(), "")

    def test_stop_sets_idle(self):
        self.run_hook("SessionStart", {"session_id": SID, "cwd": "/tmp"})
        self.run_hook("UserPromptSubmit", {"session_id": SID, "prompt": "x"})
        self.run_hook("Stop", {"session_id": SID})
        self.assertEqual(session_repo.get(self.con, SID)["state"], STATE_IDLE)

    def test_stop_moves_cwd_into_the_worktree(self):
        """세션이 시작 뒤에 EnterWorktree 하면 위치가 따라와야 한다 — 안 따라오면
        워크트리 뷰가 할일을 워크트리 줄이 아니라 base 줄에 붙인다"""
        self.run_hook("SessionStart", {"session_id": SID, "cwd": "/tmp"})
        worktree = "/tmp/repo/.claude/worktrees/feat"
        self.run_hook("Stop", {"session_id": SID, "cwd": worktree})
        self.assertEqual(session_repo.get(self.con, SID)["cwd"], worktree)

    def test_stop_without_cwd_keeps_the_known_one(self):
        """위치를 안 알려주는 페이로드에 기존 위치를 지우면 그 줄을 잃는다"""
        self.run_hook("SessionStart", {"session_id": SID, "cwd": "/tmp"})
        self.run_hook("Stop", {"session_id": SID})
        self.assertEqual(session_repo.get(self.con, SID)["cwd"], "/tmp")

    def test_session_end_sets_ended(self):
        self.run_hook("SessionStart", {"session_id": SID, "cwd": "/tmp"})
        self.run_hook("SessionEnd", {"session_id": SID})
        self.assertEqual(session_repo.get(self.con, SID)["state"], STATE_ENDED)

    def test_broken_json_exits_zero_silently(self):
        code, out = self.run_hook("SessionStart", None, raw="{not json")
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "")

    def test_unknown_event_exits_zero_silently(self):
        code, out = self.run_hook("Nope", {"session_id": SID})
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "")

    def test_missing_session_id_exits_zero(self):
        code, out = self.run_hook("SessionStart", {"cwd": "/tmp"})
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "")

    def test_branch_jira_attaches_workspace(self):
        dev = category_repo.get_by_name(self.con, "개발")["id"]
        workspace_repo.create(
            self.con, dev, "KT 동시성", jira_id="KT-1530", background="엑셀 충돌"
        )
        repo_dir = os.path.join(os.path.dirname(self.path), "repo")
        os.makedirs(repo_dir, exist_ok=True)
        subprocess.run(["git", "init", "-q"], cwd=repo_dir, capture_output=True)
        subprocess.run(
            ["git", "checkout", "-q", "-b", "KT-1530-lock"],
            cwd=repo_dir,
            capture_output=True,
        )
        code, out = self.run_hook("SessionStart", {"session_id": SID, "cwd": repo_dir})
        self.assertEqual(code, 0)
        self.assertIn('state="classified"', out)
        self.assertIn("엑셀 충돌", out)
