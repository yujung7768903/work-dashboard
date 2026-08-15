"""상단 우측 언어 메뉴 검증. 동작이 JS 안에 있어 node 로 돌리고 결과만 여기서 본다"""
import os
import shutil
import subprocess
import unittest

CHECK = os.path.join(os.path.dirname(__file__), "language_menu_check.mjs")


class LanguageMenuTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "node 없음")
    def test_icon_opens_list_and_choice_is_saved(self):
        done = subprocess.run(["node", CHECK], capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)


if __name__ == "__main__":
    unittest.main()
