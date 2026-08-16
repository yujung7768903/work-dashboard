"""보드 열 수·레일 접힘 취향 검증. 로직이 JS 안에 있어 node 로 돌리고 결과만 여기서 본다"""
import os
import shutil
import subprocess
import unittest

CHECK = os.path.join(os.path.dirname(__file__), "layout_prefs_check.mjs")
VISITS = ("first", "again")


class LayoutPrefsTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "node 없음")
    def test_saved_choice_survives_and_click_updates_it(self):
        for visit in VISITS:
            with self.subTest(visit=visit):
                done = subprocess.run(
                    ["node", CHECK, visit], capture_output=True, text=True
                )
                self.assertEqual(done.returncode, 0, done.stderr)
