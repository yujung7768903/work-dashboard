import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOK = os.path.join(ROOT, "hooks", "md_lint.py")

BAD_MD = "# Title\n\n## Title\n- item\n-  item2\n"
GOOD_MD = "# Title\n\nSome text.\n"
# 다른 규칙은 다 지키고 줄 길이(MD013)만 80 자를 넘는 문서.
# MD013 은 공백 없는 줄은 줄바꿈이 불가능하다고 보고 넘기므로 실제 문장이어야 한다
LONG_LINE_MD = (
    "# 메모\n\n오늘 논의한 내용은 인증 흐름을 어떻게 바꿀지, 그리고 그 변경이 기존 세션"
    " 관리 코드에 어떤 영향을 주는지에 대한 것이었고 결론은 다음 주에 다시 보기로 했다.\n"
)


class MdLintTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def _write(self, name, content):
        path = os.path.join(self.tmpdir, name)
        with open(path, "w") as f:
            f.write(content)
        return path

    def run_hook(self, tool_name, path, env=None):
        payload = {"tool_name": tool_name, "tool_input": {"file_path": path}}
        result = subprocess.run(
            [sys.executable, HOOK],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            env=env,
        )
        return result.returncode, result.stderr

    def test_lint_errors_block_and_report_stderr(self):
        """재현 테스트 핵심: 린트 에러가 있으면 exit 2 + stderr 에 에러 내용"""
        path = self._write("bad.md", BAD_MD)
        code, stderr = self.run_hook("Write", path)
        self.assertEqual(code, 2)
        self.assertIn("error", stderr)
        self.assertIn("다시 저장", stderr)

    def test_lint_pass_exits_zero(self):
        path = self._write("good.md", GOOD_MD)
        code, stderr = self.run_hook("Edit", path)
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")

    def test_non_md_file_skips_lint(self):
        path = self._write("bad.py", "x=1\n")
        code, stderr = self.run_hook("Write", path)
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")

    def test_non_lint_tool_skips(self):
        path = self._write("bad.md", BAD_MD)
        code, stderr = self.run_hook("Read", path)
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")

    def test_missing_binary_fails_open(self):
        """markdownlint-cli2 가 PATH 에 없는 상황 — fail-open 으로 exit 0"""
        path = self._write("bad.md", BAD_MD)
        env = dict(os.environ)
        env["PATH"] = "/nonexistent-bin-dir"
        code, stderr = self.run_hook("Write", path, env=env)
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")

    def test_broken_json_exits_zero(self):
        result = subprocess.run(
            [sys.executable, HOOK], input="{not json", capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0)

    def test_long_line_passes_in_a_project_without_config(self):
        """전역 훅이라 설정 없는 프로젝트에서도 돈다. 그때 이 저장소의 설정(MD013 off)을
        물려받지 않으면 긴 한글 문장마다 저장이 막힌다"""
        self._write("long.md", LONG_LINE_MD)
        payload = {
            "tool_name": "Write",
            "tool_input": {"file_path": "long.md"},
            "cwd": self.tmpdir,  # .markdownlint.json 이 없는 디렉토리
        }
        result = subprocess.run(
            [sys.executable, HOOK],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_project_config_wins_over_the_default(self):
        """프로젝트가 자기 설정을 갖고 있으면 그게 이긴다 — MD013 을 켠 프로젝트는 막혀야 한다"""
        self._write(".markdownlint.json", '{"default": true}')
        self._write("long.md", LONG_LINE_MD)
        payload = {
            "tool_name": "Write",
            "tool_input": {"file_path": "long.md"},
            "cwd": self.tmpdir,
        }
        result = subprocess.run(
            [sys.executable, HOOK],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("MD013", result.stderr)

    def test_relative_path_resolved_against_cwd(self):
        self._write("bad.md", BAD_MD)
        payload = {
            "tool_name": "Write",
            "tool_input": {"file_path": "bad.md"},
            "cwd": self.tmpdir,
        }
        result = subprocess.run(
            [sys.executable, HOOK],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 2)


if __name__ == "__main__":
    unittest.main()
