import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOK = os.path.join(ROOT, "hooks", "stale_base.py")


def _load_hook():
    """hooks/ 는 패키지가 아니라 경로로 직접 로드"""
    spec = importlib.util.spec_from_file_location("stale_base", HOOK)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _git(cwd, *args):
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
        cwd=cwd,
        capture_output=True,
        check=True,
    )


def _commit(repo, name):
    open(os.path.join(repo, name), "w").close()
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", name)


class StaleBaseTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load_hook()

    def setUp(self):
        # 캐시가 테스트 간 새지 않도록 매번 임시 디렉토리로 교체
        self.mod.CACHE_DIR = tempfile.mkdtemp()

    def _make_repo_with_worktree(self):
        """main 저장소 + .claude/worktrees/wt 아래 feat/x 워크트리 브랜치"""
        root = tempfile.mkdtemp()
        main = os.path.join(root, "main")
        os.makedirs(main)
        _git(main, "init", "-q", "-b", "master")
        _commit(main, "seed.txt")
        wt = os.path.join(main, ".claude", "worktrees", "wt")
        _git(main, "worktree", "add", "-q", "-b", "feat/x", wt)
        return main, wt

    # --- 핵심 재현: 워크트리 브랜치가 master 보다 뒤처진 상태 ---
    def test_branch_behind_base_branch_warns(self):
        main, wt = self._make_repo_with_worktree()
        _commit(main, "advance.txt")  # master 만 전진, feat/x 는 그대로

        message = self.mod._build_message(wt)

        self.assertIsNotNone(message)
        self.assertIn("master", message)
        self.assertIn("1 커밋 뒤처짐", message)

    def test_up_to_date_worktree_is_silent(self):
        _main, wt = self._make_repo_with_worktree()
        self.assertIsNone(self.mod._build_message(wt))

    def test_non_git_dir_is_silent(self):
        plain = tempfile.mkdtemp()
        self.assertIsNone(self.mod._build_message(plain))

    def test_subprocess_failure_fails_open(self):
        main, wt = self._make_repo_with_worktree()
        _commit(main, "advance.txt")
        with mock.patch.object(self.mod.subprocess, "run", side_effect=OSError("boom")):
            self.assertIsNone(self.mod._build_message(wt))

    # --- 브랜치가 upstream(@{u}) 보다 뒤처진 경우 ---
    def test_branch_behind_upstream_warns(self):
        origin = tempfile.mkdtemp()
        _git(origin, "init", "-q", "-b", "master")
        _commit(origin, "seed.txt")
        clone = tempfile.mkdtemp()
        subprocess.run(
            ["git", "clone", "-q", origin, os.path.join(clone, "repo")],
            capture_output=True,
            check=True,
        )
        repo = os.path.join(clone, "repo")
        _commit(origin, "advance.txt")  # origin 만 전진
        _git(repo, "fetch", "-q")  # 테스트 셋업용 fetch (훅은 fetch 하지 않음)

        message = self.mod._build_message(repo)

        self.assertIsNotNone(message)
        self.assertIn("1 커밋 뒤처짐", message)
        self.assertIn("git pull", message)

    # --- main() 프로세스 수준: exit code, 캐시(중복 억제) ---
    def test_main_exits_zero_and_prints_warning(self):
        main, wt = self._make_repo_with_worktree()
        _commit(main, "advance.txt")
        payload = json.dumps({"session_id": "s1", "cwd": wt})

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = self.mod.main(stdin=io.StringIO(payload))

        self.assertEqual(code, 0)
        self.assertIn("최신화", buf.getvalue())

    def test_repeat_prompt_same_session_suppressed(self):
        main, wt = self._make_repo_with_worktree()
        _commit(main, "advance.txt")
        payload = lambda: io.StringIO(json.dumps({"session_id": "dup", "cwd": wt}))

        first = io.StringIO()
        with contextlib.redirect_stdout(first):
            self.mod.main(stdin=payload())
        second = io.StringIO()
        with contextlib.redirect_stdout(second):
            self.mod.main(stdin=payload())

        self.assertIn("최신화", first.getvalue())
        self.assertEqual(second.getvalue().strip(), "")

    def test_broken_json_exits_zero_silently(self):
        code = self.mod.main(stdin=io.StringIO("{not json"))
        self.assertEqual(code, 0)

    def test_non_repo_dir_via_main_is_silent(self):
        plain = tempfile.mkdtemp()
        payload = json.dumps({"session_id": "s2", "cwd": plain})
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = self.mod.main(stdin=io.StringIO(payload))
        self.assertEqual(code, 0)
        self.assertEqual(buf.getvalue().strip(), "")

    # --- 실제 프로세스로도 한 번 확인 (실제 ~/.claude 를 건드리지 않게 HOME 격리) ---
    def test_real_process_warns_on_stale_worktree(self):
        main, wt = self._make_repo_with_worktree()
        _commit(main, "advance.txt")
        payload = json.dumps({"session_id": "s3", "cwd": wt})
        env = dict(os.environ, HOME=tempfile.mkdtemp())
        result = subprocess.run(
            [sys.executable, HOOK],
            input=payload,
            capture_output=True,
            text=True,
            env=env,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("최신화", result.stdout)


if __name__ == "__main__":
    unittest.main()
