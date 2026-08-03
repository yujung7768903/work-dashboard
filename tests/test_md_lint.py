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

    def test_missing_npx_fails_open(self):
        """markdownlint-cli2(npx) 를 못 찾는 상황 — fail-open 으로 exit 0"""
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
