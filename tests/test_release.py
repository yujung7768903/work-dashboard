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


def _serve(root, case, *flags):
    """워크트리를 cwd 로 도는 서버 프로세스. 탐지될 때까지 기다려 돌려준다"""
    with open(os.path.join(root, "server.py"), "w") as handle:
        handle.write("import time\ntime.sleep(30)\n")
    proc = subprocess.Popen([sys.executable, *flags, "server.py"], cwd=root)
    case.addCleanup(_stop, proc)
    deadline = time.time() + 5
    while time.time() < deadline:
        if release.serving_processes(root):
            return proc
        time.sleep(0.2)
    case.fail(f"워크트리에서 도는 서버를 찾지 못함: {flags}")


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

    def test_main_checkout_cwd_is_reported_but_never_used(self):
        """메인 체크아웃은 탐색 대상이 아니고, 어디를 봤는지는 남아야 한다"""
        result = release.finish(self.con, SID)
        self.assertEqual("", result["worktree"])
        self.assertIn("/tmp", result["looked"])


class WorktreeLookupTest(unittest.TestCase):
    """세션 cwd 는 SessionStart 때 값이라 메인 체크아웃이다 — 실제 작업 위치는 transcript 에 있다"""

    def setUp(self):
        self.con = temp_db()
        session_repo.register(self.con, SID, cwd="/tmp")
        self.root = tempfile.mkdtemp()

    def _transcript(self, *cwds):
        project = os.path.join(self.root, "-Users-me-repo")
        os.makedirs(project, exist_ok=True)
        with open(os.path.join(project, f"{SID}.jsonl"), "w") as handle:
            for cwd in cwds:
                handle.write(json.dumps({"type": "user", "cwd": cwd}) + "\n")

    def test_last_worktree_cwd_wins(self):
        self._transcript("/w/repo", "/w/repo/.claude/worktrees/a", "/w/repo/.claude/worktrees/b")
        self.assertEqual(
            "/w/repo/.claude/worktrees/b", release.last_worktree_cwd(SID, root=self.root)
        )

    def test_no_worktree_in_transcript_is_empty(self):
        self._transcript("/w/repo", "/w/repo")
        self.assertEqual("", release.last_worktree_cwd(SID, root=self.root))

    def test_missing_transcript_is_empty(self):
        self.assertEqual("", release.last_worktree_cwd(SID, root=self.root))

    def test_finish_kills_the_server_of_the_worktree_from_the_transcript(self):
        """--worktree 없이도 EnterWorktree 로 옮겨간 워크트리의 서버를 정리해야 한다"""
        worktree = _worktree_dir()
        self._patch_transcript(worktree)
        proc = _serve(worktree, self)
        result = release.finish(self.con, SID)
        self.assertEqual(worktree, result["worktree"])
        self.assertEqual([proc.pid], [pid for pid, _ in result["killed"]])
        self.assertIsNotNone(proc.wait(timeout=5))

    def test_explicit_worktree_still_wins(self):
        given = _worktree_dir()
        self._patch_transcript(_worktree_dir())
        self.assertEqual(given, release.finish(self.con, SID, worktree=given)["worktree"])

    def _patch_transcript(self, worktree):
        original = release.last_worktree_cwd
        release.last_worktree_cwd = lambda session_id, root=None: worktree
        self.addCleanup(setattr, release, "last_worktree_cwd", original)


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

    def test_flags_do_not_hide_the_server(self):
        """어떻게 띄웠는지에 판정이 흔들리면 안 된다 — 플래그가 스크립트 이름을 밀어낸다"""
        self.assertTrue(release._is_server("python3 -u server.py --port 9092"))
        self.assertTrue(release._is_server("/opt/homebrew/bin/python3 -B server.py"))

    def test_wrappers_do_not_hide_the_server(self):
        """nohup·env 로 감싸 띄우면 래퍼가 앞 두 토큰을 다 차지한다"""
        self.assertTrue(release._is_server("env WORK_DASHBOARD_DB=/tmp/x.db python3 server.py"))
        self.assertTrue(release._is_server("nohup python3 server.py --port 9092"))
        # 래퍼를 걷어내도 셸은 여전히 서버가 아니어야 한다
        self.assertFalse(release._is_server("nohup /bin/zsh -c 'python3 server.py'"))

    def test_running_server_in_worktree_is_found_and_killed(self):
        root = _worktree_dir()
        proc = _serve(root, self)
        self.assertEqual([proc.pid], [pid for pid, _ in release.kill_serving(root)])
        self.assertIsNotNone(proc.wait(timeout=5))

    def test_server_started_with_a_flag_is_found(self):
        """`python3 -u server.py` 처럼 띄운 프로세스도 실제로 찾아야 한다"""
        root = _worktree_dir()
        proc = _serve(root, self, "-u")
        self.assertIn(proc.pid, [pid for pid, _ in release.serving_processes(root)])


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

    def test_finish_says_where_it_looked_when_it_found_nothing(self):
        """(없음) 만 찍으면 서버가 남은 것을 아무도 모른다"""
        path = temp_db_path()
        session_repo.register(temp_db(path), SID, cwd="/tmp")
        out = self._dash(path, "finish", SID)
        self.assertIn("워크트리를 찾지 못함", out)
        self.assertIn("/tmp", out)

    def test_finish_says_the_worktree_had_no_server(self):
        path = temp_db_path()
        session_repo.register(temp_db(path), SID, cwd="/tmp")
        empty = _worktree_dir()
        out = self._dash(path, "finish", SID, "--worktree", empty)
        self.assertIn(f"{empty} 를 cwd 로 쓰는 서버가 없음", out)
        self.assertIn(f"ExitWorktree 로 워크트리 제거 — {empty}", out)

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
