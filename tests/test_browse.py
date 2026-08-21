"""로컬 폴더 탐색. 할일 케밥 "시작" 이 위치를 못 정했을 때 화면이 부르는 API"""
import os
import shutil
import tempfile
import unittest

from app.errors import Validation
from app.services import browse


class ListDirTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(_rmtree, self.root)

    def _mkdir(self, *parts):
        path = os.path.join(self.root, *parts)
        os.makedirs(path)
        return path

    def test_lists_only_directories(self):
        self._mkdir("repo")
        with open(os.path.join(self.root, "readme.txt"), "w", encoding="utf-8") as handle:
            handle.write("x")
        result = browse.list_dir(self.root)
        self.assertEqual([entry["name"] for entry in result["entries"]], ["repo"])

    def test_flags_git_repos(self):
        self._mkdir("repo", ".git")
        self._mkdir("plain")
        result = browse.list_dir(self.root)
        by_name = {entry["name"]: entry["is_git_repo"] for entry in result["entries"]}
        self.assertEqual(by_name, {"repo": True, "plain": False})

    def test_hides_dotfiles(self):
        self._mkdir(".hidden")
        self._mkdir("visible")
        result = browse.list_dir(self.root)
        self.assertEqual([entry["name"] for entry in result["entries"]], ["visible"])

    def test_marks_the_current_path_itself_as_a_git_repo(self):
        repo = self._mkdir("repo")
        os.makedirs(os.path.join(repo, ".git"))
        self.assertTrue(browse.list_dir(repo)["is_git_repo"])
        self.assertFalse(browse.list_dir(self.root)["is_git_repo"])

    def test_parent_climbs_up_one_level(self):
        child = self._mkdir("a", "b")
        result = browse.list_dir(child)
        self.assertEqual(result["parent"], os.path.join(self.root, "a"))

    def test_filesystem_root_has_no_parent(self):
        self.assertIsNone(browse.list_dir("/")["parent"])

    def test_defaults_to_home_when_no_path_given(self):
        self.assertEqual(browse.list_dir(None)["path"], browse.DEFAULT_ROOT)

    def test_rejects_a_path_that_is_not_a_directory(self):
        file_path = os.path.join(self.root, "file.txt")
        with open(file_path, "w", encoding="utf-8") as handle:
            handle.write("x")
        with self.assertRaises(Validation):
            browse.list_dir(file_path)


def _rmtree(path):
    shutil.rmtree(path, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
