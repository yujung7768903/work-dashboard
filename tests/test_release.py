import json
import os
import subprocess
import sys
import tempfile
import time
import unittest

from app.constants import STATUS_DONE, STATUS_TODO
from app.repositories import categories as category_repo
from app.repositories import sessions as session_repo
from app.repositories import todos as todo_repo
from app.repositories import workspaces as workspace_repo
from app.services import release, session_link
from tests.support import temp_db, temp_db_path

SID = "sess-release"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _stop(proc):
    """kill 만 하면 좀비가 남아 ResourceWarning 이 뜬다"""
    proc.kill()
    proc.wait(timeout=5)


def _worktree_dir():
    """WORKTREE_MARK 를 포함한 임시 경로. 안전장치가 경로 모양으로 판단하므로 모양을 맞춘다"""
    base = tempfile.mkdtemp()
    path = os.path.join(base, "repo", ".claude", "worktrees", "wt")
    os.makedirs(path)
    return path


class FinishTest(unittest.TestCase):
    def setUp(self):
        self.con = temp_db()
        self.category = category_repo.get_by_name(self.con, "개발")["id"]
        session_repo.register(self.con, SID, cwd="/tmp")

    def _linked_todo(self):
        todo = todo_repo.create(self.con, "할일", category_id=self.category)
        session_repo.link_todo(self.con, SID, todo["id"])
        return todo["id"]

    def test_linked_todos_become_done(self):
        todo_id = self._linked_todo()
        result = release.finish(self.con, SID)
        self.assertEqual([todo_id], result["todos"])
        self.assertEqual(STATUS_DONE, todo_repo.get(self.con, todo_id)["status"])

    def test_already_done_todo_is_not_reported_again(self):
        todo_id = self._linked_todo()
        todo_repo.update(self.con, todo_id, status=STATUS_DONE)
        self.assertEqual([], release.finish(self.con, SID)["todos"])

    def test_unlinked_todo_is_untouched(self):
        other = todo_repo.create(self.con, "남의 할일", category_id=self.category)
        release.finish(self.con, SID)
        self.assertEqual(STATUS_TODO, todo_repo.get(self.con, other["id"])["status"])


class ServingProcessTest(unittest.TestCase):
    def test_server_outside_a_worktree_is_never_touched(self):
        """메인 체크아웃까지 종료 대상이 되면 사용자가 보던 대시보드가 꺼진다"""
        plain = tempfile.mkdtemp()
        with open(os.path.join(plain, "server.py"), "w") as handle:
            handle.write("import time\ntime.sleep(30)\n")
        proc = subprocess.Popen([sys.executable, "server.py"], cwd=plain)
        self.addCleanup(_stop, proc)
        time.sleep(0.5)
        self.assertEqual([], release.serving_processes(plain))
        self.assertEqual([], release.kill_serving(plain))
        self.assertIsNone(proc.poll())

    def test_missing_directory_is_empty(self):
        self.assertEqual([], release.serving_processes("/nope/.claude/worktrees/gone"))

    def test_shell_command_mentioning_server_is_not_a_server(self):
        """셸 명령줄 어딘가에 server.py 가 있다고 서버는 아니다 — 자기 셸을 죽인다"""
        self.assertFalse(release._is_server("/bin/zsh -c 'python3 server.py --port 1'"))

    def test_server_command_is_detected(self):
        self.assertTrue(release._is_server("/usr/bin/python3 server.py --port 9092"))
        self.assertTrue(release._is_server("node /opt/npm/bin/npm-cli.js run dev"))

    def test_running_server_in_worktree_is_found_and_killed(self):
        root = _worktree_dir()
        script = os.path.join(root, "server.py")
        with open(script, "w") as handle:
            handle.write("import time\ntime.sleep(30)\n")
        proc = subprocess.Popen([sys.executable, "server.py"], cwd=root)
        try:
            self.addCleanup(proc.kill)
            found = self._wait_for_detection(root)
            self.assertIn(proc.pid, [pid for pid, _ in found])
            self.assertEqual([proc.pid], [pid for pid, _ in release.kill_serving(root)])
            self.assertIsNotNone(proc.wait(timeout=5))
        finally:
            proc.poll()

    def _wait_for_detection(self, root, timeout=5):
        deadline = time.time() + timeout
        while time.time() < deadline:
            found = release.serving_processes(root)
            if found:
                return found
            time.sleep(0.2)
        self.fail("워크트리에서 도는 서버를 찾지 못함")


class ReleasedContextTest(unittest.TestCase):
    def setUp(self):
        self.con = temp_db()
        self.category = category_repo.get_by_name(self.con, "개발")["id"]
        session_repo.register(self.con, SID, cwd="/tmp")
        session_repo.classify(self.con, SID, category_name="개발")

    def test_no_linked_todo_stays_quiet(self):
        self.assertEqual("", session_link.released_context(self.con, SID))

    def test_unfinished_todo_stays_quiet(self):
        todo = todo_repo.create(self.con, "진행 중", category_id=self.category)
        session_repo.link_todo(self.con, SID, todo["id"])
        self.assertEqual("", session_link.released_context(self.con, SID))

    def test_all_done_asks_for_a_new_todo(self):
        todo = todo_repo.create(self.con, "끝난 것", category_id=self.category)
        session_repo.link_todo(self.con, SID, todo["id"])
        release.finish(self.con, SID)
        block = session_link.released_context(self.con, SID)
        self.assertIn(session_link.STATE_RELEASED, block)
        self.assertIn("새 할일", block)

    def test_new_linked_todo_makes_it_quiet_again(self):
        done = todo_repo.create(self.con, "끝난 것", category_id=self.category)
        session_repo.link_todo(self.con, SID, done["id"])
        release.finish(self.con, SID)
        fresh = todo_repo.create(self.con, "새 요청", category_id=self.category)
        session_repo.link_todo(self.con, SID, fresh["id"])
        self.assertEqual("", session_link.released_context(self.con, SID))


class PromptHookTest(unittest.TestCase):
    """UserPromptSubmit 이 해제된 세션에만 새 할일 지침을 다시 주입하는지"""

    def setUp(self):
        self.path = temp_db_path()
        self.con = temp_db(self.path)
        self.category = category_repo.get_by_name(self.con, "개발")["id"]
        session_repo.register(self.con, SID, cwd="/tmp")
        session_repo.classify(self.con, SID, category_name="개발")

    def _run_hook(self):
        env = dict(os.environ, WORK_DASHBOARD_DB=self.path)
        payload = json.dumps({"session_id": SID, "prompt": "다음 요청"})
        result = subprocess.run(
            [sys.executable, os.path.join(ROOT, "hooks", "dash_hook.py"), "UserPromptSubmit"],
            input=payload,
            capture_output=True,
            text=True,
            env=env,
        )
        return result.stdout

    def test_classified_session_with_open_todo_is_silent(self):
        todo = todo_repo.create(self.con, "진행 중", category_id=self.category)
        session_repo.link_todo(self.con, SID, todo["id"])
        self.assertEqual("", self._run_hook().strip())

    def test_released_session_gets_new_todo_guide(self):
        todo = todo_repo.create(self.con, "끝난 것", category_id=self.category)
        session_repo.link_todo(self.con, SID, todo["id"])
        release.finish(self.con, SID)
        self.assertIn("새 할일", self._run_hook())


class GuideTest(unittest.TestCase):
    """해제 절차는 분류 전후 어느 블록에도 있어야 한다 — 병합은 둘 다에서 일어난다"""

    def setUp(self):
        self.con = temp_db()
        category = category_repo.get_by_name(self.con, "개발")["id"]
        self.workspace = workspace_repo.create(self.con, category, "작업")["id"]
        session_repo.register(self.con, SID, cwd="/tmp")

    def test_unclassified_block_carries_release_steps(self):
        block = session_link.render_context(self.con, SID)
        self.assertIn(session_link.STATE_UNCLASSIFIED, block)
        self.assertIn("dash.py finish", block)
        self.assertIn("ExitWorktree", block)

    def test_classified_block_carries_release_steps(self):
        session_repo.classify(self.con, SID, workspace_id=self.workspace)
        block = session_link.render_context(self.con, SID)
        self.assertIn(session_link.STATE_CLASSIFIED, block)
        self.assertIn("dash.py finish", block)


class CliTest(unittest.TestCase):
    def test_finish_reports_what_it_released(self):
        path = temp_db_path()
        con = temp_db(path)
        session_repo.register(con, SID, cwd="/tmp")
        todo = todo_repo.create(con, "할일", category_id=category_repo.get_by_name(con, "개발")["id"])
        session_repo.link_todo(con, SID, todo["id"])
        out = self._dash(path, "finish", SID)
        self.assertIn(f"완료한 할일: {todo['id']}", out)
        self.assertIn("종료한 프로세스: (없음)", out)
        self.assertEqual(STATUS_DONE, todo_repo.get(con, todo["id"])["status"])

    def _dash(self, path, *argv):
        result = subprocess.run(
            [sys.executable, os.path.join(ROOT, "dash.py"), *argv],
            capture_output=True,
            text=True,
            env=dict(os.environ, WORK_DASHBOARD_DB=path),
        )
        self.assertEqual(0, result.returncode, result.stderr)
        return result.stdout


if __name__ == "__main__":
    unittest.main()
