"""트리 Map 루트(워크스페이스) 카드 클릭 검증. 카드 그리기가 JS 안에 있어 node 로 돌리고 결과만 여기서 본다"""
import os
import shutil
import subprocess
import unittest

CHECK = os.path.join(os.path.dirname(__file__), "tree_root_card_check.mjs")


class TreeRootCardTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "node 없음")
    def test_root_card_opens_waiting_todo(self):
        done = subprocess.run(["node", CHECK], capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)


if __name__ == "__main__":
    unittest.main()
