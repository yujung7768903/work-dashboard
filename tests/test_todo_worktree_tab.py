"""할일 상세 워크트리 탭. 상태 판정은 파이썬에서, 렌더는 node 로 돌려 결과만 본다"""
import os
import shutil
import subprocess
import unittest

from app.db import connect, now
from app.repositories import sessions as session_repo
from app.repositories import worktrees as worktree_repo
from app.services import worktrees
from tests.support import temp_db

CHECK = os.path.join(os.path.dirname(__file__), "todo_worktree_tab_check.mjs")


class WorktreeTabRenderTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "node 없음")
    def test_merged_worktree_shows_merge_time_not_delete_time(self):
        done = subprocess.run(["node", CHECK], capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)


class MergeEventsTest(unittest.TestCase):
    """지워진 브랜치의 병합 사실은 기준 브랜치 reflog 에만 남는다"""

    def test_parses_branch_time_and_range_from_reflog(self):
        root = _repo(self)
        _run(root, "checkout", "-b", "worktree-thing")
        _write(root, "b.txt", "b")
        _run(root, "add", ".")
        _run(root, "commit", "-m", "feat: 작업")
        _run(root, "checkout", "master")
        _run(root, "merge", "--no-ff", "worktree-thing", "-m", "merge: 작업")
        _run(root, "branch", "-d", "worktree-thing")

        events = worktrees.merge_events(root, "master")
        self.assertIn("worktree-thing", events)
        event = events["worktree-thing"]
        self.assertTrue(event["at"].endswith("+00:00"), event["at"])
        # 브랜치가 사라진 뒤에도 병합 전후 해시로 그 작업 커밋을 되짚을 수 있어야 한다
        subjects = [
            commit["subject"]
            for commit in worktrees._log(root, f"{event['from']}..{event['hash']}", "--no-merges")
        ]
        self.assertEqual(subjects, ["feat: 작업"])

    def test_no_merge_entry_for_plain_commits(self):
        root = _repo(self)
        self.assertEqual(worktrees.merge_events(root, "master"), {})


class HistoryStateTest(unittest.TestCase):
    def setUp(self):
        self.con = temp_db()

    def test_states_cover_create_working_merged_deleted(self):
        row = {"path": "/x", "merged_at": None, "deleted_at": None}
        merged = {"path": "/x", "merged_at": now(), "deleted_at": None}
        # 살아 있는데 커밋이 없으면 만들어만 둔 것
        self.assertEqual(worktrees._state(row, True, 0), worktrees.STATE_CREATE)
        self.assertEqual(worktrees._state(row, True, 3), worktrees.STATE_WORKING)
        self.assertEqual(worktrees._state(merged, False, 0), worktrees.STATE_MERGED)
        # 병합 뒤에 커밋이 더 쌓였으면 다시 작업 중이다 — 그 커밋은 아직 기준 브랜치에 없다
        self.assertEqual(worktrees._state(merged, True, 2), worktrees.STATE_WORKING)
        self.assertEqual(worktrees._state(row, False, 0), worktrees.STATE_DELETED)

    def test_gone_worktree_keeps_name_and_stamps_deleted_once(self):
        """병합 없이 사라진 워크트리도 이름·상태로 남고, 삭제 시각은 처음 확인한 때로 고정된다"""
        todo_id = _todo_with_worktree_session(self.con, "/repo/.claude/worktrees/gone")
        first = worktrees.history(self.con, [todo_id])
        self.assertEqual([row["name"] for row in first], ["gone"])
        self.assertEqual(first[0]["state"], worktrees.STATE_DELETED)
        self.assertTrue(first[0]["deleted_at"])
        self.assertEqual(worktrees.history(self.con, [todo_id])[0]["deleted_at"],
                         first[0]["deleted_at"])

    def test_recreated_path_drops_the_previous_worktree_marks(self):
        """같은 이름을 다시 만들면 앞 워크트리의 병합·삭제 자국은 이 워크트리의 것이 아니다"""
        path = "/repo/.claude/worktrees/again"
        worktree_repo.remember(self.con, path, "/repo", "worktree-again", "2026-08-01T00:00:00+00:00")
        worktree_repo.mark_deleted(self.con, path, "2026-08-02T00:00:00+00:00")
        row = worktree_repo.remember(
            self.con, path, "/repo", "worktree-again", "2026-08-03T00:00:00+00:00"
        )
        self.assertIsNone(row["deleted_at"])
        self.assertEqual(row["created_at"], "2026-08-03T00:00:00+00:00")


def _todo_with_worktree_session(con, path):
    todo = con.execute(
        "INSERT INTO todos(category_id, title, status, sort_order, created_at, updated_at)"
        " VALUES(1,'워크트리 탭','todo',1,?,?) RETURNING id", (now(), now())
    ).fetchone()["id"]
    session_repo.register(con, "sess-1", cwd=path, git_branch="worktree-gone")
    session_repo.link_todo(con, "sess-1", todo)
    return todo


def _repo(case):
    import tempfile

    root = tempfile.mkdtemp()
    case.addCleanup(shutil.rmtree, root, True)
    _run(root, "init", "-b", "master")
    _run(root, "config", "user.email", "t@t")
    _run(root, "config", "user.name", "t")
    _write(root, "a.txt", "a")
    _run(root, "add", ".")
    _run(root, "commit", "-m", "chore: 처음")
    return root


def _write(root, name, text):
    with open(os.path.join(root, name), "w", encoding="utf-8") as handle:
        handle.write(text)


def _run(root, *args):
    subprocess.run(["git", "-C", root, *args], capture_output=True, text=True, check=True)


if __name__ == "__main__":
    unittest.main()
