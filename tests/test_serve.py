"""워크트리 서버 실행·재실행·중지.

포트 판정은 실제로 소켓을 잡아 확인하고, 서버 기동은 여기서 하지 않는다 —
테스트가 공유 대역(9080~9139) 을 물면 다른 워크트리가 못 뜬다.
"""
import os
import pathlib
import re
import shutil
import socket
import subprocess
import tempfile
import unittest

from app.errors import Validation
from app.services import serve, worktrees

HERE = pathlib.Path(__file__).resolve().parent
WORKTREES_JS = HERE.parent / "static" / "js" / "worktrees.js"
MENU_CHECK = HERE / "worktree_serve_menu_check.mjs"
# serveItems 가 메뉴 항목을 만드는 모양: item("실행", "start", ...)
MENU_ITEM = re.compile(r'item\("[^"]+",\s*"(\w+)"')


class PortTest(unittest.TestCase):
    def _held(self):
        """실제로 듣고 있는 포트 하나. 테스트가 끝나면 닫힌다"""
        held = socket.socket()
        self.addCleanup(held.close)
        held.bind(("127.0.0.1", 0))
        held.listen()
        return held.getsockname()[1]

    def test_free_port_comes_from_the_shared_range(self):
        self.assertIn(serve.free_port(), serve.PORT_RANGE)

    def test_taken_port_is_neither_free_nor_offered(self):
        port = self._held()
        self.assertFalse(serve._is_free(port))
        original = serve.PORT_RANGE
        # 잡아 둔 포트를 범위 맨 앞에 놓아도 건너뛰어야 한다
        serve.PORT_RANGE = range(port, port + 2)
        self.addCleanup(setattr, serve, "PORT_RANGE", original)
        self.assertNotEqual(serve.free_port(), port)

    def test_listening_is_judged_by_connecting_not_binding(self):
        """기동·종료 확인은 bind 가 아니라 연결로 본다 — 남이 물고 있는 포트를
        내 서버가 떴다고 읽으면 안 된다"""
        port = self._held()
        self.assertTrue(serve._is_listening(port))
        self.assertFalse(serve._is_listening(serve.free_port()))


class StartTest(unittest.TestCase):
    def test_start_without_run_script_is_refused(self):
        """진입점을 추측하지 않는다 — run.sh 가 없으면 그 사실을 그대로 알린다"""
        with tempfile.TemporaryDirectory() as path:
            with self.assertRaises(Validation) as caught:
                serve.start(path)
        self.assertIn(serve.RUN_SCRIPT, str(caught.exception))

    def test_own_worktree_is_refused(self):
        """자기를 서비스하는 서버는 자기를 못 중지한다 — 죽이면 응답할 주체가 없다.
        그 워크트리의 대시보드를 보면서 그 줄을 재실행하려 할 때 걸린다"""
        for action in (serve.restart, serve.stop):
            with self.assertRaises(Validation):
                action(os.getcwd())

    def test_stop_without_a_server_is_not_an_error(self):
        """재실행이 같은 길을 지나가고, 안 떠 있는 줄에서도 중지를 누를 수 있다 —
        떠 있는 게 없어도 오류로 끝나면 안 된다. 다만 "종료했습니다" 로 끝나면
        안 죽인 것을 죽였다고 오해하므로 문장이 갈린다"""
        with tempfile.TemporaryDirectory() as path:
            result = serve.stop(path)
        self.assertEqual(result["stopped"], [])
        self.assertEqual(result["message"], "종료할 서버가 없었습니다")


class ControlTest(unittest.TestCase):
    def test_unknown_action_is_refused(self):
        with self.assertRaises(Validation):
            worktrees.control("/repo", "feat", "nope")

    def test_menu_actions_all_exist_on_the_server(self):
        """화면이 보내는 동작 이름과 서버가 아는 이름이 갈리면 메뉴만 조용히 실패한다"""
        actions = set(MENU_ITEM.findall(WORKTREES_JS.read_text(encoding="utf-8")))
        self.assertEqual(actions, set(worktrees.CONTROLS))

    @unittest.skipUnless(shutil.which("node"), "node 없음")
    def test_menu_shows_and_sends_the_right_action(self):
        """어느 항목이 보이고 무엇을 보내는지는 JS 안에 있어 node 로 돌리고 결과만 본다"""
        done = subprocess.run(["node", str(MENU_CHECK)], capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)


if __name__ == "__main__":
    unittest.main()
