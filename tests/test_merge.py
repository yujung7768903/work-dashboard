"""병합 파이프라인. 진짜 저장소와 워크트리를 만들어 git 경로 전체를 지난다"""
import os
import subprocess
import tempfile
import unittest
from unittest import mock

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


class MergeRepoCase(unittest.TestCase):
    """진짜 저장소 + 워크트리. 테스트 메서드는 하위 클래스에 둔다"""

    def setUp(self):
        self.con = temp_db()
        self.category = category_repo.get_by_name(self.con, "개발")["id"]
        # 워크트리 경로에 /.claude/worktrees/ 가 있어야 서버 종료 안전장치를 지난다
        self.base = tempfile.mkdtemp()
        self.repo = os.path.join(self.base, "repo")
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


class MergeTest(MergeRepoCase):
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

    def _conflict(self):
        """양쪽이 같은 파일을 고쳐 병합이 멈춘 상태를 만든다"""
        commit(self.worktree, "same.txt", "feat: 내 쪽", body="mine\n")
        commit(self.repo, "same.txt", "fix: master 쪽", body="theirs\n")
        return self._merge(no_test=True)

    def test_conflict_reports_the_files_to_resolve(self):
        """사람에게 넘기지 않고 해결할 수 있게 파일 목록과 방침을 준다"""
        result = self._conflict()
        self.assertIn("same.txt", result["aborted"])
        self.assertIn("양쪽 기능이 모두 살아 있게", result["aborted"])
        self.assertEqual(["fix: master 쪽", "chore: 초기"], self._master_subjects())

    def test_resolved_conflict_is_resumed_on_the_next_run(self):
        self._conflict()
        with open(os.path.join(self.worktree, "same.txt"), "w") as handle:
            handle.write("mine\ntheirs\n")  # 양쪽 다 살린 해결
        git(self.worktree, "add", "same.txt")
        result = self._merge(no_test=True)
        self.assertEqual("", result["aborted"])
        self.assertIn(("master 들이기", "충돌 해결분 커밋"), result["steps"])
        self.assertEqual("merge: 내 쪽", self._master_subjects()[0])

    def test_still_unresolved_conflict_aborts_again_with_the_file_list(self):
        self._conflict()
        result = self._merge(no_test=True)
        self.assertIn("same.txt", result["aborted"])
        self.assertEqual(["fix: master 쪽", "chore: 초기"], self._master_subjects())

    def test_staged_conflict_markers_abort(self):
        """`<<<<<<<` 를 그대로 두고 add 한 경우. 테스트가 못 잡는 실수라 기계로 막는다"""
        self._conflict()
        git(self.worktree, "add", "same.txt")
        result = self._merge(no_test=True)
        self.assertIn("충돌 표시", result["aborted"])
        self.assertEqual(["fix: master 쪽", "chore: 초기"], self._master_subjects())

    def test_resumed_merge_still_runs_the_test_before_master(self):
        self._conflict()
        with open(os.path.join(self.worktree, "same.txt"), "w") as handle:
            handle.write("mine\ntheirs\n")
        git(self.worktree, "add", "same.txt")
        result = self._merge(test="exit 1")
        self.assertIn("테스트가 실패해", result["aborted"])
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


class MasterMovesDuringMergeTest(MergeRepoCase):
    """테스트를 도는 사이 다른 세션이 master 에 병합한 경우 (11-16 매니저 레포).

    메인 체크아웃은 여러 세션이 같이 쓰고, 워크트리에 갇힌 세션은 거기서 git 을 못 한다.
    병합 중 상태로 남기면 사람이 merge --abort 를 해야 한다
    """

    def _runs(self):
        path = os.path.join(self.base, "runs")
        if not os.path.exists(path):
            return 0
        with open(path) as handle:
            return len(handle.read().splitlines())

    def _test_that_commits_to_master(self, name, body, every_run=False):
        """테스트 명령인 척 master 에 커밋한다. 테스트를 도는 사이 다른 세션이 병합한 상황"""
        payload = os.path.join(self.base, "payload")
        with open(payload, "w") as handle:
            handle.write(body)
        runs = os.path.join(self.base, "runs")
        target = f"{name}$n" if every_run else name
        condition = "true" if every_run else '[ "$n" -eq 1 ]'
        script = os.path.join(self.base, "fake_test.sh")
        with open(script, "w") as handle:
            handle.write(
                "set -e\n"
                f"echo run >> {runs}\n"
                f"n=$(wc -l < {runs})\n"
                f"if {condition}; then\n"
                f"  cp {payload} {self.repo}/{target}\n"
                f"  git -C {self.repo} add {target}\n"
                f'  git -C {self.repo} commit -q -m "fix: 다른 세션 병합 $n"\n'
                "fi\n"
            )
        return f"sh {script}"

    def _assert_main_checkout_clean(self):
        merge_head = os.path.join(self.repo, ".git", "MERGE_HEAD")
        self.assertFalse(os.path.exists(merge_head), "메인 체크아웃이 병합 중 상태로 남음")
        status = subprocess.run(
            ["git", "-C", self.repo, "status", "--porcelain", "--untracked-files=no"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        self.assertEqual("", status)
        same = os.path.join(self.repo, "same.txt")
        if os.path.exists(same):
            with open(same) as handle:
                self.assertNotIn("<<<<<<<", handle.read())

    def test_master_change_during_test_is_pulled_in_and_tested_again(self):
        """테스트한 트리가 병합할 트리여야 한다 — 바뀐 master 를 들인 뒤 다시 테스트"""
        commit(self.worktree, "a.txt", "feat: 기능")
        result = self._merge(test=self._test_that_commits_to_master("b.txt", "m"))
        self.assertEqual("", result["aborted"])
        self.assertEqual(2, self._runs())
        self.assertIn(("master 다시 들이기", "테스트하는 사이 바뀐 1개 커밋"), result["steps"])
        self.assertEqual("merge: 기능", self._master_subjects()[0])

    def test_conflicting_master_change_during_test_leaves_main_checkout_clean(self):
        """충돌은 워크트리에서 낸다 — 해결은 그 세션 몫이고 메인 체크아웃은 건드리지 않는다"""
        commit(self.worktree, "same.txt", "feat: 내 쪽", body="mine\n")
        result = self._merge(test=self._test_that_commits_to_master("same.txt", "theirs\n"))
        self.assertIn("same.txt", result["aborted"])
        self.assertIn("양쪽 기능이 모두 살아 있게", result["aborted"])
        self.assertEqual(["fix: 다른 세션 병합 1", "chore: 초기"], self._master_subjects())
        self._assert_main_checkout_clean()
        self.assertTrue(merge._merge_in_progress(self.worktree))  # 해결하고 다시 실행하면 이어받는다

    def test_master_that_keeps_moving_gives_up_without_touching_master(self):
        commit(self.worktree, "a.txt", "feat: 기능")
        command = self._test_that_commits_to_master("m", "m", every_run=True)
        result = self._merge(test=command)
        self.assertIn("계속 바뀌어", result["aborted"])
        self.assertEqual(1 + merge.MERGE_CATCH_UP_LIMIT, self._runs())
        self.assertNotIn("merge: 기능", self._master_subjects())
        self._assert_main_checkout_clean()

    def test_main_checkout_dirtied_during_test_aborts_before_merging(self):
        """커밋 안 된 변경 위에서 병합이 충돌하면 merge --abort 가 그 변경을 못 살릴 수 있다"""
        commit(self.worktree, "a.txt", "feat: 기능")
        seed = os.path.join(self.repo, "seed.txt")
        result = self._merge(test=f"printf 'editing' > {seed}")
        self.assertIn("메인 체크아웃 — 커밋 안 된 변경", result["aborted"])
        self.assertEqual(["chore: 초기"], self._master_subjects())
        with open(seed) as handle:
            self.assertEqual("editing", handle.read())

    def _race_before_final_merge(self, abort_fails=False):
        """마지막 병합 직전에 master 가 바뀌는 경합. 테스트 뒤 확인과 병합 사이의 틈이다"""
        real = merge._git

        def fake(root, *args):
            if args[:2] == ("merge", "--no-ff"):
                commit(self.repo, "same.txt", "fix: 끼어든 병합", body="theirs\n")
            if abort_fails and args == ("merge", "--abort"):
                return False, "fatal: 되돌리기 흉내 실패"
            return real(root, *args)

        commit(self.worktree, "same.txt", "feat: 내 쪽", body="mine\n")
        with mock.patch.object(merge, "_git", side_effect=fake):
            return self._merge(no_test=True)

    def test_conflict_on_the_final_merge_is_reverted(self):
        result = self._race_before_final_merge()
        self.assertIn("되돌림", result["aborted"])
        self.assertIn("same.txt", result["aborted"])
        self.assertIn(("병합", "충돌 — 메인 체크아웃 되돌림"), result["steps"])
        self.assertEqual(["fix: 끼어든 병합", "chore: 초기"], self._master_subjects())
        self._assert_main_checkout_clean()
        with open(os.path.join(self.repo, "same.txt")) as handle:
            self.assertEqual("theirs\n", handle.read())

    def test_failed_revert_is_reported_plainly(self):
        result = self._race_before_final_merge(abort_fails=True)
        self.assertIn("되돌리기(git merge --abort)도 실패", result["aborted"])
        self.assertIn(self.repo, result["aborted"])
        self.assertIn("되돌리기 흉내 실패", result["aborted"])
        self.assertIn(("병합", "충돌 — 되돌리기 실패"), result["steps"])

    def test_merge_that_never_started_is_not_reverted(self):
        """잠금 등으로 시작도 못 한 병합. 그때 남은 병합 상태는 남의 것이라 건드리지 않는다"""
        commit(self.worktree, "a.txt", "feat: 기능")
        real = merge._git
        calls = []

        def fake(root, *args):
            calls.append(args)
            if args[:2] == ("merge", "--no-ff"):
                return False, "fatal: Unable to create '.git/index.lock': File exists."
            return real(root, *args)

        with mock.patch.object(merge, "_git", side_effect=fake):
            result = self._merge(no_test=True)
        self.assertIn("index.lock", result["aborted"])
        self.assertIn("건드리지 않음", result["aborted"])
        self.assertIn(("병합", "실패"), result["steps"])
        self.assertNotIn(("merge", "--abort"), calls)


if __name__ == "__main__":
    unittest.main()
