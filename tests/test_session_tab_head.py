"""할일 상세의 세션 탭 머리글 검증. 렌더가 JS 안에 있어 node 로 돌리고 결과만 본다"""
import os
import shutil
import subprocess
import unittest

CHECK = os.path.join(os.path.dirname(__file__), "session_tab_head_check.mjs")


class SessionTabHeadTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "node 없음")
    def test_head_shows_todo_id_and_title(self):
        done = subprocess.run(["node", CHECK], capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
