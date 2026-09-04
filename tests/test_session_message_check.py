"""세션 탭 입력칸·선택지 검증. 그리는 일이 JS 안에 있어 node 로 돌리고 결과만 여기서 본다"""
import os
import shutil
import subprocess
import unittest

CHECK = os.path.join(os.path.dirname(__file__), "session_message_check.mjs")


class SessionMessageCheckTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "node 없음")
    def test_choices_fill_the_input_and_send_posts_the_text(self):
        # 타이머가 남으면 node 가 안 끝난다 — 그리는 시점에 폴링을 걸었다는 뜻이므로 실패로 본다
        done = subprocess.run(["node", CHECK], capture_output=True, text=True, timeout=30)
        self.assertEqual(done.returncode, 0, done.stderr)
