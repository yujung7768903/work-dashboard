"""로컬 폴더 탐색. 할일 케밥 "시작" 이 위치를 못 정했을 때 화면이 부르는 API"""
import os
import shutil
import tempfile
import unittest

from app.errors import Validation
from app.services import browse


class ListDirTest(unittest.TestCase):
    def setUp(self):
        # macOS 의 /var 는 /private/var 심볼릭 링크다. list_dir 이 realpath 로 정규화하므로
        # 기대값도 같은 기준이어야 한다
        self.root = os.path.realpath(tempfile.mkdtemp())
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


class RevealTest(unittest.TestCase):
    """note 의 경로를 눌렀을 때 어떤 명령으로 탐색기를 띄우는지.

    reveal 자체는 창을 띄우므로 여기서 부르지 않는다 — 없는 경로(띄우기 전에 막히는
    갈래)만 실제로 부르고, 나머지는 명령 조립만 본다
    """

    def setUp(self):
        # macOS 의 /var 는 /private/var 심볼릭 링크다. list_dir 이 realpath 로 정규화하므로
        # 기대값도 같은 기준이어야 한다
        self.root = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(_rmtree, self.root)
        self.file = os.path.join(self.root, "note.md")
        with open(self.file, "w", encoding="utf-8") as handle:
            handle.write("x")

    def test_mac_reveals_the_file_itself(self):
        self.assertEqual(
            browse.reveal_command(self.file, browse.DARWIN), ["open", "-R", self.file]
        )

    def test_linux_opens_the_containing_folder_for_a_file(self):
        self.assertEqual(
            browse.reveal_command(self.file, browse.LINUX), ["xdg-open", self.root]
        )

    def test_linux_opens_a_folder_as_is(self):
        self.assertEqual(
            browse.reveal_command(self.root, browse.LINUX), ["xdg-open", self.root]
        )

    @unittest.skipUnless(shutil.which("wslpath"), "wslpath 없음 (WSL 아님)")
    def test_wsl_selects_a_file_and_opens_a_folder(self):
        file_command = browse.reveal_command(self.file, browse.WSL)
        self.assertEqual(file_command[0], "explorer.exe")
        self.assertTrue(file_command[1].startswith("/select,"), file_command)
        folder_command = browse.reveal_command(self.root, browse.WSL)
        self.assertEqual(folder_command[0], "explorer.exe")
        self.assertFalse(folder_command[1].startswith("/select,"), folder_command)

    def test_rejects_a_path_that_does_not_exist(self):
        with self.assertRaises(Validation):
            browse.reveal(os.path.join(self.root, "없는파일.md"))

    def test_rejects_an_empty_path(self):
        with self.assertRaises(Validation):
            browse.reveal(None)


def _rmtree(path):
    shutil.rmtree(path, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
