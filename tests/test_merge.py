"""병합 파이프라인. 진짜 저장소와 워크트리를 만들어 git 경로 전체를 지난다"""
import os
import subprocess
import tempfile
import unittest

from app.constants import STATUS_DONE
from app.repositories import categories as category_repo
from app.repositories import sessions as session_repo
from app.repositories import todos as todo_repo
from app.services import merge
from tests.support import temp_db

SID = "sess-merge"


def git(root, *args):
    subprocess.run(["git", "-C", root, *args], check=True, capture_output=True)


def commit(root, name, message, body="x"):
    with open(os.path.join(root, name), "w") as handle:
        handle.write(body)
    git(root, "add", name)
    git(root, "commit", "-q", "-m", message)


class MergeTest(unittest.TestCase):
    def setUp(self):
        self.con = temp_db()
        self.category = category_repo.get_by_name(self.con, "개발")["id"]
        # 워크트리 경로에 /.claude/worktrees/ 가 있어야 서버 종료 안전장치를 지난다
        base = tempfile.mkdtemp()
        self.repo = os.path.join(base, "repo")
        os.makedirs(self.repo)
        git(self.repo, "init", "-q", "-b", "master")
        git(self.repo, "config", "user.email", "t@t")
        git(self.repo, "config", "user.name", "t")
        commit(self.repo, "seed.txt", "chore: 초기")
        self.worktree = os.path.join(self.repo, ".claude", "worktrees", "wt")
        git(self.repo, "worktree", "add", "-q", "-b", "worktree-feat", self.worktree)
        session_repo.register(self.con, SID, cwd=self.repo)

    def _merge(self, **kwargs):
        return merge.merge(self.con, SID, worktree=self.worktree, **kwargs)

    def _linked_todo(self):
        todo = todo_repo.create(self.con, "할일", category_id=self.category)
        session_repo.link_todo(self.con, SID, todo["id"])
        return todo["id"]

    def _master_subjects(self):
        out = subprocess.run(
            ["git", "-C", self.repo, "log", "--format=%s"],
            capture_output=True,
            text=True,
            check=True,
        )
        return out.stdout.splitlines()

    def test_branch_lands_on_master_with_merge_commit(self):
        commit(self.worktree, "a.txt", "feat: 기능 하나")
        result = self._merge(no_test=True)
        self.assertEqual("", result["aborted"])
        subjects = self._master_subjects()
        self.assertEqual("merge: 기능 하나", subjects[0])  # --no-ff 로 병합 커밋이 남는다
        self.assertEqual({"merge: 기능 하나", "feat: 기능 하나", "chore: 초기"}, set(subjects))

    def test_linked_todo_becomes_done(self):
        todo_id = self._linked_todo()
        commit(self.worktree, "a.txt", "feat: 기능")
        self._merge(no_test=True)
        self.assertEqual(STATUS_DONE, todo_repo.get(self.con, todo_id)["status"])

    def test_master_is_merged_in_before_the_test_runs(self):
        """대상 브랜치를 먼저 들이므로 병합 뒤 다시 테스트할 필요가 없다"""
        commit(self.worktree, "a.txt", "feat: 기능")
        commit(self.repo, "b.txt", "fix: master 쪽 변경")
        result = self._merge(test=f"test -f {os.path.join(self.worktree, 'b.txt')}")
        self.assertEqual("", result["aborted"])
        self.assertIn(("master 들이기", "1개 커밋"), result["steps"])

    def test_failing_test_stops_before_master_is_touched(self):
        commit(self.worktree, "a.txt", "feat: 기능")
        result = self._merge(test="exit 1")
        self.assertIn("테스트가 실패해", result["aborted"])
        self.assertEqual(["chore: 초기"], self._master_subjects())

    def test_test_count_is_reported(self):
        commit(self.worktree, "a.txt", "feat: 기능")
        result = self._merge(test="echo 'Ran 12 tests in 0.1s'")
        self.assertIn(("테스트", "echo 'Ran 12 tests in 0.1s' — 12개 통과"), result["steps"])

    def test_dirty_worktree_aborts(self):
        commit(self.worktree, "a.txt", "feat: 기능")
        with open(os.path.join(self.worktree, "a.txt"), "w") as handle:
            handle.write("고치는 중")
        result = self._merge(no_test=True)
        self.assertIn("워크트리 — 커밋 안 된 변경", result["aborted"])
        self.assertEqual(["chore: 초기"], self._master_subjects())

    def test_dirty_main_checkout_aborts(self):
        commit(self.worktree, "a.txt", "feat: 기능")
        with open(os.path.join(self.repo, "seed.txt"), "w") as handle:
            handle.write("다른 세션이 고치는 중")
        result = self._merge(no_test=True)
        self.assertIn("메인 체크아웃 — 커밋 안 된 변경", result["aborted"])
        self.assertEqual(["chore: 초기"], self._master_subjects())

    def test_untracked_file_does_not_block(self):
        """워크트리 디렉토리·잔여 sqlite 같은 미추적 파일로 병합이 막히면 안 된다"""
        commit(self.worktree, "a.txt", "feat: 기능")
        with open(os.path.join(self.repo, "leftover.db"), "w") as handle:
            handle.write("")
        self.assertEqual("", self._merge(no_test=True)["aborted"])

    def test_nothing_to_merge_aborts(self):
        result = self._merge(no_test=True)
        self.assertIn("없는 커밋이 없음", result["aborted"])

    def test_conflict_leaves_the_worktree_for_a_human(self):
        commit(self.worktree, "same.txt", "feat: 내 쪽", body="mine")
        commit(self.repo, "same.txt", "fix: master 쪽", body="theirs")
        result = self._merge(no_test=True)
        self.assertIn("충돌", result["aborted"])
        self.assertEqual(["fix: master 쪽", "chore: 초기"], self._master_subjects())

    def test_given_message_wins(self):
        commit(self.worktree, "a.txt", "feat: 기능")
        self._merge(no_test=True, message="직접 쓴 제목")
        self.assertEqual("merge: 직접 쓴 제목", self._master_subjects()[0])

    def test_default_message_uses_the_oldest_commit_of_the_branch(self):
        commit(self.worktree, "a.txt", "feat: 먼저 한 것")
        commit(self.worktree, "b.txt", "fix: 나중에 고친 것")
        self._merge(no_test=True)
        self.assertEqual("merge: 먼저 한 것", self._master_subjects()[0])

    def test_skip_reason_is_reported_when_no_test_entry(self):
        commit(self.worktree, "a.txt", "feat: 기능")
        result = self._merge()
        self.assertIn(("테스트", merge._skip_reason(False)), result["steps"])

    def test_missing_worktree_aborts_without_touching_git(self):
        result = merge.merge(self.con, SID, worktree="/does/not/exist")
        self.assertIn("워크트리를 찾지 못함", result["aborted"])


if __name__ == "__main__":
    unittest.main()
