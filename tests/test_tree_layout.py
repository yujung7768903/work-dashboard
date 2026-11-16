"""트리 Map 배치 검증. 배치가 JS 안에 있어 node 로 돌리고 결과만 여기서 본다"""
import os
import shutil
import subprocess
import unittest

CHECK = os.path.join(os.path.dirname(__file__), "tree_layout_check.mjs")


class TreeLayoutTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "node 없음")
    def test_roots_left_children_right_and_done_hiding(self):
        done = subprocess.run(["node", CHECK], capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
