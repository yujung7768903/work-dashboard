"""워크트리 탭 데이터. 파싱은 단위로, 격차·커밋·요약은 진짜 git 저장소를 만들어 확인한다"""
import os
import shutil
import subprocess
import tempfile
import unittest

from app.repositories import categories as category_repo
from app.repositories import sessions as session_repo
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

    def _register(self, session_id, cwd):
        session_repo.register(self.con, session_id, cwd=cwd)
        session_repo.classify_by_ids(
            self.con,
            session_repo.get(self.con, session_id)["id"],
            workspace_id=self.workspace["id"],
        )

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
        todo = todo_repo.create(self.con, "탭 분리", workspace_id=self.workspace["id"])
        self._register("sess-3333", self.worktree)
        session_repo.link_todo(self.con, "sess-3333", todo["id"])
        row = next(r for r in self._group()["rows"] if r["branch"] == "worktree-feat")
        self.assertEqual(row["summary"], "탭 분리")

    def test_workspace_without_a_repo_is_left_out(self):
        """세션이 한 번도 안 돈 워크스페이스는 저장소를 모르므로 그리지 않는다"""
        groups = worktrees.overview(self.con)["groups"]
        self.assertEqual([group["id"] for group in groups], [])


if __name__ == "__main__":
    unittest.main()
