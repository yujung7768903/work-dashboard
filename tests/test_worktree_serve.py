import importlib.util
import io
import json
import os
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOK = os.path.join(ROOT, "hooks", "worktree_serve.py")


def _load_hook():
    """hooks/ 는 패키지가 아니라 경로로 직접 로드"""
    spec = importlib.util.spec_from_file_location("worktree_serve", HOOK)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class WorktreeServeTest(unittest.TestCase):
    def setUp(self):
        self.hook = _load_hook()
        self.base = tempfile.mkdtemp()
        # 웹 프로젝트 워크트리 (server.py 있음) 와 라이브러리 워크트리 (없음)
        self.web = os.path.join(self.base, "repo", ".claude", "worktrees", "web")
        self.lib = os.path.join(self.base, "repo", ".claude", "worktrees", "lib")
        os.makedirs(os.path.join(self.web, "static"))
        os.makedirs(self.lib)
        open(os.path.join(self.web, "server.py"), "w").close()

    def _transcript(self, *paths):
        handle = tempfile.NamedTemporaryFile(
            "w", suffix=".jsonl", delete=False, dir=self.base
        )
        for path in paths:
            handle.write(json.dumps({"tool_input": {"file_path": path}}) + "\n")
        handle.close()
        return handle.name

    def _run(self, payload):
        return self.hook.main(stdin=io.StringIO(json.dumps(payload)))

    def test_web_worktree_without_server_blocks(self):
        transcript = self._transcript(os.path.join(self.web, "static/app.css"))
        self.assertEqual(
            self.hook.EXIT_BLOCK, self._run({"transcript_path": transcript})
        )

    def test_block_message_names_worktree_and_url(self):
        port = self.hook.free_port()
        message = self.hook.MESSAGE.format(root=self.web, port=port)
        self.assertIn(self.web, message)
        self.assertIn(f"url: http://127.0.0.1:{port}/", message)

    def test_non_web_worktree_passes(self):
        transcript = self._transcript(os.path.join(self.lib, "util.py"))
        self.assertEqual(self.hook.EXIT_OK, self._run({"transcript_path": transcript}))

    def test_edit_outside_worktree_passes(self):
        transcript = self._transcript(os.path.join(self.base, "repo", "server.py"))
        self.assertEqual(self.hook.EXIT_OK, self._run({"transcript_path": transcript}))

    def test_second_pass_does_not_block_again(self):
        """stop_hook_active 면 통과 — 훅이 종료를 무한히 막지 않게"""
        transcript = self._transcript(os.path.join(self.web, "static/app.css"))
        payload = {"transcript_path": transcript, "stop_hook_active": True}
        self.assertEqual(self.hook.EXIT_OK, self._run(payload))

    def test_served_worktree_passes(self):
        """cwd 가 그 워크트리인 서버 프로세스가 있으면 관여하지 않음"""
        self.hook._is_served = lambda root: True
        transcript = self._transcript(os.path.join(self.web, "static/app.css"))
        self.assertEqual(self.hook.EXIT_OK, self._run({"transcript_path": transcript}))

    def test_broken_payload_passes(self):
        self.assertEqual(self.hook.EXIT_OK, self.hook.main(stdin=io.StringIO("nope")))

    def test_worktree_root_trims_inner_path(self):
        deep = os.path.join(self.web, "app", "services", "board.py")
        self.assertEqual(self.web, self.hook._worktree_root(deep))
