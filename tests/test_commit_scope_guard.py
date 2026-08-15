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


# 차단해야 하는 명령. 새 우회 수법이 나오면 여기에 한 줄 추가한다
BLOCKED = (
    ("git add -A", "문제 재현: 전체 스테이징이 그대로 통과되던 사고 케이스"),
    ("git add --all", "긴 플래그"),
    ("git add .", "현재 디렉토리 전체"),
    ("git add -u", "추적 중 파일 전체"),
    ('git commit -am "x"', "스테이징 건너뛰기"),
    ("git commit -a -m 'x'", "분리된 -a"),
    ('git commit --all -m "x"', "긴 플래그"),
    ("cd foo && git add .", "복합 명령 - && 로 이어붙임"),
    ("git status; git add -A", "복합 명령 - 세미콜론"),
    ("echo hi | cat && git add -A", "복합 명령 - 파이프 뒤"),
)

# 통과해야 하는 명령. 하나라도 막히면 정상 작업이 멈춘다
ALLOWED = (
    ("git add docs/a.md", "개별 경로"),
    ("git add -A -- docs/", "pathspec 을 명시한 -A"),
    ("git status", "스테이징과 무관"),
    ('git commit -m "x"', "이미 스테이징된 것만"),
    ("", "빈 명령"),
)


class CommitScopeGuardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.guard = _load_hook()

    def setUp(self):
        os.environ.pop("ALLOW_BROAD_COMMIT", None)

    def test_broad_staging_commands_are_blocked(self):
        for command, why in BLOCKED:
            with self.subTest(command=command):
                self.assertEqual(_run(self.guard, command), 2, why)

    def test_scoped_commands_pass(self):
        for command, why in ALLOWED:
            with self.subTest(command=command):
                self.assertEqual(_run(self.guard, command), 0, why)

    def test_non_bash_tool_passes(self):
        self.assertEqual(_run(self.guard, "git add -A", tool_name="Edit"), 0)

    def test_bypass_env_passes(self):
        os.environ["ALLOW_BROAD_COMMIT"] = "1"
        self.assertEqual(_run(self.guard, "git add -A"), 0)

    def test_broken_json_exits_zero(self):
        self.assertEqual(self.guard.main(stdin=io.StringIO("{not json")), 0)


if __name__ == "__main__":
    unittest.main()
