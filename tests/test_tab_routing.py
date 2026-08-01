"""탭 경로 라우팅 검증. 로직이 JS 안에 있어 node 로 돌리고 결과만 여기서 본다"""
import os
import shutil
import subprocess
import unittest

CHECK = os.path.join(os.path.dirname(__file__), "tab_routing_check.mjs")
ENTRY_PATHS = ("/", "/board", "/nope")


class TabRoutingTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "node 없음")
    def test_path_drives_tab_and_tab_drives_path(self):
        for path in ENTRY_PATHS:
            with self.subTest(path=path):
                done = subprocess.run(
                    ["node", CHECK, path], capture_output=True, text=True
                )
                self.assertEqual(done.returncode, 0, done.stderr)
