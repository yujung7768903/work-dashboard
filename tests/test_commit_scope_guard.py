import importlib.util
import io
import json
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOK = os.path.join(ROOT, "hooks", "commit_scope_guard.py")


def _load_hook():
    """hooks/ 는 패키지가 아니라 경로로 직접 로드"""
    spec = importlib.util.spec_from_file_location("commit_scope_guard", HOOK)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(guard, command, tool_name="Bash"):
    payload = {"tool_name": tool_name, "tool_input": {"command": command}}
    return guard.main(stdin=io.StringIO(json.dumps(payload)))


class CommitScopeGuardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.guard = _load_hook()

    def setUp(self):
        os.environ.pop("ALLOW_BROAD_COMMIT", None)

    def test_git_add_dash_a_blocked(self):
        """문제 재현: 전체 스테이징이 그대로 통과되던 사고 케이스"""
        self.assertEqual(_run(self.guard, "git add -A"), 2)

    def test_git_add_all_long_flag_blocked(self):
        self.assertEqual(_run(self.guard, "git add --all"), 2)

    def test_git_add_dot_blocked(self):
        self.assertEqual(_run(self.guard, "git add ."), 2)

    def test_git_add_dash_u_blocked(self):
        self.assertEqual(_run(self.guard, "git add -u"), 2)

    def test_git_commit_am_blocked(self):
        self.assertEqual(_run(self.guard, 'git commit -am "x"'), 2)

    def test_git_commit_dash_a_blocked(self):
        self.assertEqual(_run(self.guard, "git commit -a -m 'x'"), 2)

    def test_git_commit_all_long_flag_blocked(self):
        self.assertEqual(_run(self.guard, 'git commit --all -m "x"'), 2)

    def test_compound_command_with_and_operator_blocked(self):
        self.assertEqual(_run(self.guard, "cd foo && git add ."), 2)

    def test_compound_command_with_semicolon_blocked(self):
        self.assertEqual(_run(self.guard, "git status; git add -A"), 2)

    def test_compound_command_with_pipe_blocked(self):
        self.assertEqual(_run(self.guard, "echo hi | cat && git add -A"), 2)

    def test_git_add_specific_path_passes(self):
        self.assertEqual(_run(self.guard, "git add docs/a.md"), 0)

    def test_git_add_dash_a_with_explicit_pathspec_passes(self):
        self.assertEqual(_run(self.guard, "git add -A -- docs/"), 0)

    def test_git_status_passes(self):
        self.assertEqual(_run(self.guard, "git status"), 0)

    def test_git_commit_with_message_only_passes(self):
        self.assertEqual(_run(self.guard, 'git commit -m "x"'), 0)

    def test_non_bash_tool_passes(self):
        self.assertEqual(
            _run(self.guard, "git add -A", tool_name="Edit"), 0
        )

    def test_bypass_env_passes(self):
        os.environ["ALLOW_BROAD_COMMIT"] = "1"
        self.assertEqual(_run(self.guard, "git add -A"), 0)

    def test_broken_json_exits_zero(self):
        self.assertEqual(self.guard.main(stdin=io.StringIO("{not json")), 0)

    def test_empty_command_passes(self):
        self.assertEqual(_run(self.guard, ""), 0)


if __name__ == "__main__":
    unittest.main()
