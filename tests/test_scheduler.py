"""④ 자율 실행 스케줄러 등록. 실제 launchctl 은 부르지 않는다"""
import os
import unittest

import dash
from app.constants import (
    AUTORUN_AGENT_LABEL,
    AUTORUN_AGENT_PYTHON,
    AUTORUN_TICK_INTERVAL_SEC,
)
from app.services import release, scheduler

REPO = "/Users/u/work/work-dashboard"
WORKTREE = f"{REPO}/.claude/worktrees/some-branch"

# 경로 → 되돌아갈 본 저장소. 워크트리는 일이 끝나면 지워지므로 plist 에 박히면 안 된다
MAIN_CHECKOUT_CASES = (
    (REPO, REPO, "메인 체크아웃은 그대로 둔다"),
    (WORKTREE, REPO, "워크트리는 본 저장소로 되돌린다"),
    (f"{WORKTREE}/app/services", REPO, "워크트리 하위 경로도 본 저장소로 되돌린다"),
    ("/nope/.claude/worktrees/gone", "/nope", "지워진 워크트리도 경로만 보고 되돌린다"),
    ("", "", "빈 경로는 빈 채로"),
    (None, "", "None 은 빈 문자열로"),
)

# 스케줄러 상태 → 사람이 읽는 줄에 반드시 들어 있어야 하는 말
LINE_CASES = (
    ({"written": False, "loaded": False}, "미등록", "등록 안 된 사실이 드러나야 한다"),
    ({"written": True, "loaded": False}, "로드 안 됨", "파일만 있고 안 도는 상태"),
    ({"written": True, "loaded": True}, "등록됨", "정상 등록"),
    ({"written": True, "loaded": True, "error": "boom"}, "등록 실패", "오류가 우선한다"),
)


class MainCheckout(unittest.TestCase):
    def test_worktree_paths_fall_back_to_the_repository(self):
        for path, expected, why in MAIN_CHECKOUT_CASES:
            with self.subTest(path=path):
                self.assertEqual(release.main_checkout(path), expected, why)


class Plist(unittest.TestCase):
    def test_registering_from_a_worktree_still_points_at_the_repository(self):
        """워크트리에서 install 을 불러도 plist 에는 본 저장소가 박혀야 한다 —
        워크트리는 병합 뒤 지워지고, 그러면 다음 tick 이 dash.py 를 못 찾는다"""
        body = scheduler._plist(release.main_checkout(WORKTREE))
        self.assertEqual(body["WorkingDirectory"], REPO)
        self.assertIn(os.path.join(REPO, "dash.py"), body["ProgramArguments"])
        self.assertNotIn("worktrees", str(body["ProgramArguments"]))

    def test_plist_runs_the_tick_on_the_five_minute_interval(self):
        body = scheduler._plist(REPO)
        self.assertEqual(body["Label"], AUTORUN_AGENT_LABEL)
        self.assertEqual(body["StartInterval"], AUTORUN_TICK_INTERVAL_SEC)
        self.assertEqual(body["ProgramArguments"][0], AUTORUN_AGENT_PYTHON)
        self.assertEqual(body["ProgramArguments"][-1], "autorun-tick")
        self.assertTrue(body["RunAtLoad"], "등록 직후 한 번 돌아야 5분을 안 기다린다")

    def test_system_python_is_used_so_a_pyenv_change_cannot_kill_it(self):
        """pyenv 경로를 박으면 그 버전을 지우는 순간 스케줄러가 조용히 죽는다"""
        self.assertTrue(os.path.exists(AUTORUN_AGENT_PYTHON), AUTORUN_AGENT_PYTHON)
        self.assertNotIn("pyenv", scheduler._plist(REPO)["ProgramArguments"][0])


class StatusLine(unittest.TestCase):
    def test_line_tells_whether_anything_will_actually_run(self):
        """on 과 '실제로 도는가' 는 다른 축이라, 갈라진 것이 이 줄에서 보여야 한다"""
        for overrides, expected, why in LINE_CASES:
            with self.subTest(overrides=overrides):
                agent = dict(
                    {"plist": "/tmp/x.plist", "interval_sec": AUTORUN_TICK_INTERVAL_SEC},
                    **overrides,
                )
                self.assertIn(expected, dash._scheduler_line(agent), why)


if __name__ == "__main__":
    unittest.main()
