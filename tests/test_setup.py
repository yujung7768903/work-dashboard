"""setup.sh 의 훅 등록 검사.

사용자의 진짜 ~/.claude/settings.json 을 건드리면 안 되므로 HOME 을 임시
디렉토리로 바꿔 실행한다. 보는 것은 세 가지 — 새로 깔았을 때, 두 번 돌렸을 때,
이미 다른 훅이 들어 있는 파일에 얹었을 때.
"""
import json
import os
import subprocess
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SETUP = os.path.join(ROOT, "setup.sh")
HOOK_COUNT = 8


def run_setup(home):
    result = subprocess.run(
        [SETUP], cwd=ROOT, capture_output=True, text=True, env=dict(os.environ, HOME=home)
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def read_settings(home):
    with open(os.path.join(home, ".claude", "settings.json")) as handle:
        return json.load(handle)


def commands(settings):
    """(이벤트, matcher, 명령) 목록으로 펼친다"""
    return [
        (event, group.get("matcher", ""), hook["command"])
        for event, groups in settings["hooks"].items()
        for group in groups
        for hook in group.get("hooks", [])
    ]


class SetupTest(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()

    def test_registers_every_hook_with_absolute_path(self):
        run_setup(self.home)
        entries = commands(read_settings(self.home))
        self.assertEqual(HOOK_COUNT, len(entries))
        for event, _, command in entries:
            self.assertTrue(command.startswith("python3 /"), f"{event}: 절대경로가 아니다")
            script = command.split()[1]
            self.assertTrue(os.path.isfile(script), f"{script} 없음")
            # 워크트리는 병합 뒤 지워진다 — 그 경로가 등록되면 훅이 통째로 죽는다
            self.assertNotIn("/.claude/worktrees/", script)

    def test_matchers(self):
        run_setup(self.home)
        entries = commands(read_settings(self.home))
        by_script = {command.split("/hooks/")[1]: (event, matcher) for event, matcher, command in entries}
        self.assertEqual(("PreToolUse", "Bash"), by_script["commit_scope_guard.py"])
        self.assertEqual(("PreToolUse", "Write|Edit|NotebookEdit"), by_script["worktree_guard.py"])
        self.assertEqual(("PostToolUse", "Write|Edit|NotebookEdit"), by_script["md_lint.py"])
        self.assertEqual(("Stop", ""), by_script["dash_hook.py Stop"])

    def test_second_run_changes_nothing(self):
        run_setup(self.home)
        first = read_settings(self.home)
        output = run_setup(self.home)
        self.assertIn("바뀐 것 없음", output)
        self.assertEqual(first, read_settings(self.home))

    def test_keeps_other_hooks_and_moves_stale_path(self):
        """저장소를 옮긴 뒤 다시 돌리면 경로만 갱신된다. 남의 훅은 그대로 둔다"""
        os.makedirs(os.path.join(self.home, ".claude"))
        seeded = {
            "statusLine": {"type": "command", "command": "node statusline.js"},
            "hooks": {
                "SessionStart": [
                    {
                        "matcher": "",
                        "hooks": [
                            {"type": "command", "command": "python3 /old/place/hooks/dash_hook.py SessionStart"},
                            {"type": "command", "command": "say hello"},
                        ],
                    }
                ]
            },
        }
        with open(os.path.join(self.home, ".claude", "settings.json"), "w") as handle:
            json.dump(seeded, handle)

        run_setup(self.home)
        settings = read_settings(self.home)
        entries = commands(settings)

        self.assertEqual(seeded["statusLine"], settings["statusLine"])
        self.assertIn(("SessionStart", "", "say hello"), entries)
        starts = [c for _, _, c in entries if c.endswith("dash_hook.py SessionStart")]
        self.assertEqual(1, len(starts), "옛 경로 옆에 새 훅이 하나 더 붙었다")
        self.assertNotIn("/old/place/", starts[0])
        self.assertTrue(os.path.exists(os.path.join(self.home, ".claude", "settings.json.bak")))

    def test_broken_settings_is_not_overwritten(self):
        os.makedirs(os.path.join(self.home, ".claude"))
        path = os.path.join(self.home, ".claude", "settings.json")
        with open(path, "w") as handle:
            handle.write("{ this is not json")
        result = subprocess.run(
            [SETUP], cwd=ROOT, capture_output=True, text=True, env=dict(os.environ, HOME=self.home)
        )
        self.assertNotEqual(0, result.returncode)
        with open(path) as handle:
            self.assertEqual("{ this is not json", handle.read())


if __name__ == "__main__":
    unittest.main()
