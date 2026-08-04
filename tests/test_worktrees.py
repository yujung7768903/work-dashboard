"""워크트리 탭 데이터. 파싱은 단위로, 격차·커밋·요약은 진짜 git 저장소를 만들어 확인한다"""
import os
import shutil
import subprocess
import tempfile
import unittest

from app.constants import STATUS_DOING, STATUS_DONE
from app.errors import Conflict, NotFound, Validation
from app.repositories import categories as category_repo
from app.repositories import sessions as session_repo
from app.repositories import subtasks as subtask_repo
from app.repositories import todos as todo_repo
from app.repositories import workspaces as workspace_repo
from app.services import worktrees
from tests.support import temp_db

PORCELAIN = """worktree /repo
HEAD abc
branch refs/heads/master

worktree /repo/.claude/worktrees/feat
HEAD def
branch refs/heads/worktree-feat

worktree /repo/.claude/worktrees/loose
HEAD 999
detached
"""


class ParseTest(unittest.TestCase):
    def test_worktree_porcelain_maps_branch_to_path(self):
        found = {}
        path = None
        for line in PORCELAIN.splitlines():
            head, _, rest = line.partition(" ")
            if head == "worktree":
                path = rest.strip()
            elif head == "branch" and path:
                found[rest.strip().replace(worktrees.BRANCH_REF, "", 1)] = path
        self.assertEqual(found["master"], "/repo")
        self.assertEqual(found["worktree-feat"], "/repo/.claude/worktrees/feat")
        # 브랜치가 붙어 있지 않은(detached) 워크트리는 어느 브랜치로도 잡히지 않는다
        self.assertEqual(len(found), 2)

    def test_base_branch_goes_first(self):
        order = worktrees._base_first(["c", "master", "a"], "master")
        self.assertEqual(order, ["master", "c", "a"])

    def test_base_first_survives_missing_base(self):
        self.assertEqual(worktrees._base_first(["a", "b"], "main"), ["a", "b"])

    def test_summary_prefers_todo_title_over_commit(self):
        summary = worktrees._summary(
            "/w", {"/w": "탭 분리"}, [{"subject": "fix: 오타"}]
        )
        self.assertEqual(summary, "탭 분리")

    def test_summary_falls_back_to_latest_commit(self):
        self.assertEqual(worktrees._summary("/w", {}, [{"subject": "fix: 오타"}]), "fix: 오타")

    def test_summary_is_empty_without_todo_or_commit(self):
        self.assertEqual(worktrees._summary(None, {}, []), "")

    def test_command_is_shortened_to_basenames(self):
        self.assertEqual(
            worktrees._short("/usr/bin/python3 server.py --port 9080"), "python3 server.py"
        )


def git(root, *args):
    subprocess.run(["git", "-C", root, *args], check=True, capture_output=True)


def git_out(root, *args):
    return subprocess.run(
        ["git", "-C", root, *args], capture_output=True, text=True
    ).stdout


def write_commit(repo, name, content, message):
    with open(os.path.join(repo, name), "w") as handle:
        handle.write(content)
    git(repo, "add", name)
    git(repo, "commit", "-q", "-m", message)


class RepoTest(unittest.TestCase):
    """실제 저장소 하나에 워크트리 하나. git 호출 경로 전체를 지난다"""

    @classmethod
    def setUpClass(cls):
        cls.base = tempfile.mkdtemp()
        cls.repo = os.path.join(cls.base, "repo")
        os.makedirs(cls.repo)
        git(cls.repo, "init", "-q", "-b", "master")
        git(cls.repo, "config", "user.email", "t@t")
        git(cls.repo, "config", "user.name", "t")
        cls._commit("base.txt", "기준 커밋")
        cls.worktree = os.path.join(cls.repo, ".claude", "worktrees", "feat")
        git(cls.repo, "worktree", "add", "-q", "-b", "worktree-feat", cls.worktree)
        subprocess.run(
            ["git", "-C", cls.worktree, "commit", "-q", "--allow-empty", "-m", "feat: 새 기능"],
            check=True, capture_output=True,
        )

    @classmethod
    def _commit(cls, name, message):
        open(os.path.join(cls.repo, name), "w").close()
        git(cls.repo, "add", name)
        git(cls.repo, "commit", "-q", "-m", message)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.base, ignore_errors=True)

    def setUp(self):
        self.con = temp_db()
        category = category_repo.list_all(self.con)[0]
        self.workspace = workspace_repo.create(self.con, category["id"], "테스트")

    def _register(self, session_id, cwd, todo_title=None):
        """세션이 워크스페이스에 속한다는 것은 그 워크스페이스 할일을 잡았다는 뜻이다"""
        session_repo.register(self.con, session_id, cwd=cwd)
        todo = todo_repo.create(
            self.con, todo_title or f"작업 {session_id}", workspace_id=self.workspace["id"]
        )
        session_repo.link_todo(self.con, session_id, todo["id"])

    def _group(self):
        self._register("sess-1111", self.repo)
        groups = worktrees.overview(self.con)["groups"]
        return next(group for group in groups if group["id"] == self.workspace["id"])

    def test_repo_root_found_from_session_cwd(self):
        self.assertEqual(os.path.realpath(self._group()["repo"]), os.path.realpath(self.repo))

    def test_repo_root_climbs_out_of_a_worktree(self):
        """세션이 워크트리 안에서 돌았어도 본 저장소를 찾아야 브랜치가 다 보인다"""
        self._register("sess-2222", self.worktree)
        found = worktrees._repo_root([self.worktree])
        self.assertEqual(os.path.realpath(found), os.path.realpath(self.repo))

    def test_base_branch_and_row_order(self):
        group = self._group()
        self.assertEqual(group["base"], "master")
        self.assertEqual([row["branch"] for row in group["rows"]],
                         ["master", "worktree-feat"])

    def test_branch_ahead_of_base_reports_its_commits(self):
        row = next(r for r in self._group()["rows"] if r["branch"] == "worktree-feat")
        self.assertEqual((row["ahead"], row["behind"]), (1, 0))
        self.assertEqual([commit["subject"] for commit in row["commits"]], ["feat: 새 기능"])
        self.assertFalse(row["is_base"])
        self.assertEqual(os.path.realpath(row["path"]), os.path.realpath(self.worktree))

    def test_base_row_carries_no_commits(self):
        row = self._group()["rows"][0]
        self.assertTrue(row["is_base"])
        self.assertEqual(row["commits"], [])
        self.assertEqual((row["ahead"], row["behind"]), (0, 0))

    def test_summary_uses_the_todo_that_session_claimed(self):
        """워크트리에서 돈 세션이 할일을 잡고 있으면 커밋 제목 대신 그 제목이 보인다"""
        self._register("sess-3333", self.worktree, todo_title="탭 분리")
        row = next(r for r in self._group()["rows"] if r["branch"] == "worktree-feat")
        self.assertEqual(row["summary"], "탭 분리")

    def test_workspace_without_a_repo_is_left_out(self):
        """세션이 한 번도 안 돈 워크스페이스는 저장소를 모르므로 그리지 않는다"""
        groups = worktrees.overview(self.con)["groups"]
        self.assertEqual([group["id"] for group in groups], [])


class ApplyTest(unittest.TestCase):
    """워크트리 탭 케밥 메뉴의 "적용" — 병합·서버 종료·워크트리 및 브랜치 제거·할일 done.
    apply 는 상태를 바꾸므로 RepoTest 와 저장소를 나눠 각 테스트마다 새로 만든다"""

    def setUp(self):
        self.con = temp_db()
        self.base = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        self.repo = os.path.join(self.base, "repo")
        os.makedirs(self.repo)
        git(self.repo, "init", "-q", "-b", "master")
        git(self.repo, "config", "user.email", "t@t")
        git(self.repo, "config", "user.name", "t")
        # 실제 저장소처럼 .claude/ 를 무시해야 워크트리 디렉토리가 메인 체크아웃에서
        # 커밋되지 않은 변경사항으로 잡히지 않는다
        write_commit(self.repo, ".gitignore", ".claude/\n", "기준 커밋")
        write_commit(self.repo, "base.txt", "base\n", "base.txt 추가")
        self.worktree = os.path.join(self.repo, ".claude", "worktrees", "feat")
        git(self.repo, "worktree", "add", "-q", "-b", "worktree-feat", self.worktree)
        write_commit(self.worktree, "base.txt", "워크트리 변경\n", "feat: base.txt 수정")
        category = category_repo.list_all(self.con)[0]
        self.workspace = workspace_repo.create(self.con, category["id"], "테스트")

    def _link_todo(self, cwd, title="할일"):
        session_id = f"sess-{title}"
        session_repo.register(self.con, session_id, cwd=cwd)
        todo = todo_repo.create(self.con, title, workspace_id=self.workspace["id"])
        session_repo.link_todo(self.con, session_id, todo["id"])
        return todo["id"]

    def test_apply_merges_kills_removes_and_finishes_todo(self):
        todo_id = self._link_todo(self.worktree)
        result = worktrees.apply(self.con, self.repo, "worktree-feat")
        self.assertEqual("worktree-feat", result["branch"])
        self.assertEqual([todo_id], result["finished"])
        self.assertEqual(STATUS_DONE, todo_repo.get(self.con, todo_id)["status"])
        self.assertFalse(os.path.isdir(self.worktree))
        self.assertNotIn("worktree-feat", git_out(self.repo, "branch"))
        self.assertIn("수정", git_out(self.repo, "log", "--oneline"))

    def test_apply_rejects_the_base_branch(self):
        with self.assertRaises(Validation):
            worktrees.apply(self.con, self.repo, "master")

    def test_apply_rejects_an_unknown_branch(self):
        with self.assertRaises(NotFound):
            worktrees.apply(self.con, self.repo, "nope")

    def test_open_subtasks_block_apply_before_anything_is_touched(self):
        """워크트리를 지운 뒤 done 처리가 막히면 되돌릴 수 없다 — 미리 확인하고 멈춰야 한다"""
        todo_id = self._link_todo(self.worktree)
        subtask_repo.create(self.con, todo_id, "하위 할일")
        with self.assertRaises(Validation):
            worktrees.apply(self.con, self.repo, "worktree-feat")
        self.assertTrue(os.path.isdir(self.worktree))
        self.assertIn("worktree-feat", git_out(self.repo, "branch"))
        self.assertEqual(STATUS_DOING, todo_repo.get(self.con, todo_id)["status"])

    def test_merge_conflict_leaves_everything_in_place(self):
        write_commit(self.repo, "base.txt", "마스터 변경\n", "마스터도 수정")
        with self.assertRaises(Conflict):
            worktrees.apply(self.con, self.repo, "worktree-feat")
        self.assertTrue(os.path.isdir(self.worktree))
        self.assertIn("worktree-feat", git_out(self.repo, "branch"))
        self.assertEqual("", git_out(self.repo, "status", "--porcelain"))

    def test_dirty_main_checkout_blocks_apply(self):
        with open(os.path.join(self.repo, "untracked.txt"), "w") as handle:
            handle.write("x")
        with self.assertRaises(Validation):
            worktrees.apply(self.con, self.repo, "worktree-feat")
        self.assertTrue(os.path.isdir(self.worktree))

    def test_dirty_worktree_blocks_apply(self):
        with open(os.path.join(self.worktree, "untracked.txt"), "w") as handle:
            handle.write("x")
        with self.assertRaises(Validation):
            worktrees.apply(self.con, self.repo, "worktree-feat")
        self.assertTrue(os.path.isdir(self.worktree))

    def test_main_checkout_on_a_different_branch_blocks_apply(self):
        git(self.repo, "checkout", "-q", "-b", "other")
        with self.assertRaises(Validation):
            worktrees.apply(self.con, self.repo, "worktree-feat")
        self.assertTrue(os.path.isdir(self.worktree))


class DiscardTest(unittest.TestCase):
    """케밥 메뉴의 "삭제" — 병합하지 않고 서버 종료·워크트리·브랜치만 강제로 버린다.
    ApplyTest 와 같은 저장소 구성을 쓰되 병합 게이트가 없어 검사 항목이 다르다"""

    def setUp(self):
        self.con = temp_db()
        self.base = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        self.repo = os.path.join(self.base, "repo")
        os.makedirs(self.repo)
        git(self.repo, "init", "-q", "-b", "master")
        git(self.repo, "config", "user.email", "t@t")
        git(self.repo, "config", "user.name", "t")
        write_commit(self.repo, ".gitignore", ".claude/\n", "기준 커밋")
        write_commit(self.repo, "base.txt", "base\n", "base.txt 추가")
        self.worktree = os.path.join(self.repo, ".claude", "worktrees", "feat")
        git(self.repo, "worktree", "add", "-q", "-b", "worktree-feat", self.worktree)
        write_commit(self.worktree, "base.txt", "워크트리 변경\n", "feat: base.txt 수정")
        category = category_repo.list_all(self.con)[0]
        self.workspace = workspace_repo.create(self.con, category["id"], "테스트")

    def test_discard_removes_worktree_and_branch_without_merging(self):
        result = worktrees.discard(self.con, self.repo, "worktree-feat")
        self.assertEqual("worktree-feat", result["branch"])
        self.assertFalse(os.path.isdir(self.worktree))
        self.assertNotIn("worktree-feat", git_out(self.repo, "branch"))
        # 병합이 아니므로 그 커밋은 master 이력에 없어야 한다
        self.assertNotIn("수정", git_out(self.repo, "log", "--oneline"))

    def test_discard_ignores_open_subtasks(self):
        """적용과 달리 완료 처리를 하지 않으므로 하위할일 여부를 보지 않는다"""
        session_repo.register(self.con, "sess-1", cwd=self.worktree)
        todo = todo_repo.create(self.con, "할일", workspace_id=self.workspace["id"])
        session_repo.link_todo(self.con, "sess-1", todo["id"])
        subtask_repo.create(self.con, todo["id"], "하위 할일")
        worktrees.discard(self.con, self.repo, "worktree-feat")
        self.assertFalse(os.path.isdir(self.worktree))
        self.assertEqual(STATUS_DOING, todo_repo.get(self.con, todo["id"])["status"])

    def test_discard_removes_a_dirty_worktree_without_complaint(self):
        with open(os.path.join(self.worktree, "untracked.txt"), "w") as handle:
            handle.write("x")
        worktrees.discard(self.con, self.repo, "worktree-feat")
        self.assertFalse(os.path.isdir(self.worktree))

    def test_discard_rejects_the_base_branch(self):
        with self.assertRaises(Validation):
            worktrees.discard(self.con, self.repo, "master")

    def test_discard_rejects_an_unknown_branch(self):
        with self.assertRaises(NotFound):
            worktrees.discard(self.con, self.repo, "nope")


if __name__ == "__main__":
    unittest.main()
