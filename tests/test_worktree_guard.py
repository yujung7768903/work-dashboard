import importlib.util
import io
import json
import os
import subprocess
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOK = os.path.join(ROOT, "hooks", "worktree_guard.py")


def _load_hook():
    """hooks/ 는 패키지가 아니라 경로로 직접 로드"""
    spec = importlib.util.spec_from_file_location("worktree_guard", HOOK)
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


class WorktreeGuardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """WORK_ROOT 를 임시 디렉토리로 바꿔 실제 ~/work 를 건드리지 않음"""
        cls.guard = _load_hook()
        cls.root = tempfile.mkdtemp()
        cls.guard.WORK_ROOT = cls.root
        cls.main = os.path.join(cls.root, "repo")
        os.makedirs(cls.main)
        _git(cls.main, "init", "-q")
        open(os.path.join(cls.main, "seed.txt"), "w").close()
        _git(cls.main, "add", "-A")
        _git(cls.main, "commit", "-qm", "init")
        cls.wt = os.path.join(cls.main, ".claude", "worktrees", "wt")
        _git(cls.main, "worktree", "add", "-q", "-b", "feat/x", cls.wt)
        cls.loose = os.path.join(cls.root, "loose")
        os.makedirs(cls.loose, exist_ok=True)

    def setUp(self):
        os.environ.pop("ALLOW_MAIN_CHECKOUT", None)

    def test_block_decision_by_path(self):
        """메인 체크아웃의 소스만 막고 나머지는 다 통과해야 한다"""
        cases = (
            (os.path.join(self.main, "app.py"), True, "메인 체크아웃 소스"),
            (os.path.join(self.wt, "app.py"), False, "워크트리 안 소스"),
            (os.path.join(self.main, "README.md"), False, "문서 확장자"),
            (os.path.join(self.main, "docs", "note.py"), False, "docs/ 아래"),
            ("/tmp/somewhere/app.py", False, "~/work 밖"),
            (os.path.join(self.loose, "app.py"), False, "레포가 아님"),
        )
        for path, expected, why in cases:
            with self.subTest(why=why):
                self.assertEqual(self.guard.should_block(path), expected, why)

    def test_bypass_env_passes(self):
        os.environ["ALLOW_MAIN_CHECKOUT"] = "1"
        self.assertFalse(self.guard.should_block(os.path.join(self.main, "app.py")))

    def test_main_returns_block_exit_code(self):
        payload = {
            "tool_name": "Edit",
            "tool_input": {"file_path": os.path.join(self.main, "app.py")},
        }
        code = self.guard.main(stdin=io.StringIO(json.dumps(payload)))
        self.assertEqual(code, 2)

    def test_broken_json_exits_zero(self):
        self.assertEqual(self.guard.main(stdin=io.StringIO("{not json")), 0)

    def test_real_hook_process_matches_this_checkout(self):
        """실제 프로세스 확인 (WORK_ROOT 패치 없이). 워크트리면 0, 메인 체크아웃이면 2"""
        payload = {"tool_input": {"file_path": os.path.join(ROOT, "hooks", "x.py")}}
        result = subprocess.run(
            ["python3", HOOK], input=json.dumps(payload), capture_output=True, text=True
        )
        git_dir = subprocess.run(
            ["git", "-C", ROOT, "rev-parse", "--absolute-git-dir"],
            capture_output=True,
            text=True,
        ).stdout
        self.assertEqual(result.returncode, 0 if "/worktrees/" in git_dir else 2)
