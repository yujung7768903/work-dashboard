"""할일 상세 결과물 탭. 렌더는 node 로 돌려 결과만 본다."""
import os
import shutil
import subprocess
import unittest

CHECK = os.path.join(os.path.dirname(__file__), "todo_result_tab_check.mjs")


class ResultTabRenderTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "node 없음")
    def test_single_result_opens_and_multiple_stay_collapsed(self):
        done = subprocess.run(["node", CHECK], capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)


if __name__ == "__main__":
    unittest.main()
