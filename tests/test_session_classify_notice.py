"""세션 탭 분류 저장 뒤 팝업이 남아 완료 안내를 띄우는지. 렌더가 JS 안에 있어 node 로 돌리고 결과만 본다"""
import os
import shutil
import subprocess
import unittest

CHECK = os.path.join(os.path.dirname(__file__), "session_classify_notice_check.mjs")


class SessionClassifyNoticeTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "node 없음")
    def test_popup_stays_open_with_a_done_notice(self):
        done = subprocess.run(["node", CHECK], capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
