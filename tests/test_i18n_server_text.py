"""서버 문구 되짚기 검증. 동작이 JS 안에 있어 node 로 돌리고 결과만 여기서 본다"""
import os
import shutil
import subprocess
import unittest

CHECK = os.path.join(os.path.dirname(__file__), "i18n_server_text_check.mjs")


class ServerTextTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "node 없음")
    def test_korean_server_text_follows_the_screen_language(self):
        done = subprocess.run(["node", CHECK], capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)


if __name__ == "__main__":
    unittest.main()
