"""결과물 메뉴 카드 그리드. 렌더는 node 로 돌려 결과만 본다."""
import os
import shutil
import subprocess
import unittest

CHECK = os.path.join(os.path.dirname(__file__), "results_tab_check.mjs")


class ResultsTabRenderTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "node 없음")
    def test_cards_show_inline_fields_and_link_to_the_todo(self):
        done = subprocess.run(["node", CHECK], capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)


if __name__ == "__main__":
    unittest.main()
