"""④ 자율 실행 — tick 판정과 실행 기록. 실제 `claude --bg` 는 띄우지 않는다"""
import json
import os
import subprocess
import tempfile
import time
import unittest

import server
from app.constants import (
    AUTORUN_BLOCKED_STREAK_LIMIT,
    AUTORUN_LABEL,
    OUTCOME_BLOCKED,
    OUTCOME_DONE,
    OUTCOME_FAILED,
    OUTCOME_REVIEW,
    STATE_ENDED,
    STATUS_DOING,
    STATUS_DONE,
    USAGE_CRITICAL_PCT,
)
from app.errors import Validation
from app.repositories import autorun as autorun_repo
from app.repositories import categories as category_repo
from app.repositories import labels as label_repo
from app.repositories import sessions as session_repo
from app.repositories import todos as todo_repo
from app.repositories import workspaces as workspace_repo
from app.services import autorun
from tests.support import temp_db

SID = "sess-autorun"
JOB = "abcd1234"
CHILD = "child-session-id"


class Recorder:
    """주입되는 런처. 실제 잡을 띄우지 않고 무엇을 받았는지만 기록한다"""

    def __init__(self, job_id=JOB, session_id=CHILD, error=""):
        self.calls = []
        self.result = {"job_id": job_id, "session_id": session_id, "error": error}

    def __call__(self, prompt, cwd, name=""):
        self.calls.append({"prompt": prompt, "cwd": cwd, "name": name})
        return self.result


def _git_repo():
    """작업 위치 후보로 쓸 빈 저장소. 깨끗해야 tick 이 시작 판정을 낸다"""
    path = tempfile.mkdtemp()
    subprocess.run(["git", "init", "-q", path], check=True, timeout=30)
    return path


def _limits_file(pct, age_seconds=0, resets_in=3600):
    """사이드카 한 장. resets_in 이 음수면 그 5시간 창은 이미 리셋된 것"""
    path = os.path.join(tempfile.mkdtemp(), "rate-limits.json")
    stamp = int((time.time() - age_seconds) * 1000)
    window = {
        "used_percentage": pct,
        "resets_at": int(time.time() + resets_in),
    }
    with open(path, "w", encoding="utf-8") as handle:
        json.dump({"five_hour": window, "timestamp": stamp}, handle)
    return path


class AutorunCase(unittest.TestCase):
    """워크스페이스 하나 + auto 라벨이 붙은 할일 하나. 작업 위치는 이 저장소로 둔다"""

    def setUp(self):
        self.con = temp_db()
        self.repo = _git_repo()
        self._usage_original = autorun.usage_gate
        self.addCleanup(setattr, autorun, "usage_gate", self._usage_original)
        category = category_repo.create(self.con, "자율")
        self.workspace = workspace_repo.create(self.con, category["id"], "워크스페이스")
        self.label = label_repo.create(self.con, AUTORUN_LABEL)
        self.todo = self._todo("자동으로 돌릴 일", labeled=True)
        session_repo.register(self.con, SID, cwd=self.repo)
        session_repo.link_todo(self.con, SID, self.todo["id"])
        # 이 세션이 잡고 있으면 후보에서 빠지므로, 위치만 남기고 끝난 것으로 둔다
        session_repo.set_state(self.con, SID, STATE_ENDED)
        autorun_repo.set_enabled(self.con, True)
        self._use_limits(_limits_file(10))

    def _todo(self, title, labeled=False, precondition=None):
        todo = todo_repo.create(
            self.con,
            title,
            workspace_id=self.workspace["id"],
            precondition=precondition,
        )
        if labeled:
            label_repo.set_for_todo(self.con, todo["id"], [self.label["id"]])
        return todo

    def _use_limits(self, path):
        """usage 게이트가 볼 사이드카를 임시 파일로 고정. 늘 진짜 원본에서 다시 감싼다"""
        autorun.usage_gate = lambda *_, **__: self._usage_original(path)


class Candidates(AutorunCase):
    def test_picks_labeled_todo(self):
        self.assertEqual(autorun.pick(self.con)["todo"]["id"], self.todo["id"])

    def test_skips_unlabeled_todo(self):
        label_repo.set_for_todo(self.con, self.todo["id"], [])
        self._todo("라벨 없는 일")
        self.assertIsNone(autorun.pick(self.con))

    def test_skips_todo_with_precondition(self):
        """조건은 자연어라 코드가 충족을 판정할 수 없다 — 사람이 풀어야 후보가 된다"""
        label_repo.set_for_todo(self.con, self.todo["id"], [])
        self._todo("조건 붙은 일", labeled=True, precondition="다른 게 먼저 끝날 것")
        self.assertIsNone(autorun.pick(self.con))

    def test_skips_blocked_todo(self):
        run = autorun_repo.start_run(self.con, self.todo["id"], CHILD, JOB)
        autorun_repo.close_run(self.con, run["id"], OUTCOME_BLOCKED)
        self.assertIsNone(autorun.pick(self.con))

    def test_skips_done_todo(self):
        todo_repo.update(self.con, self.todo["id"], status=STATUS_DONE)
        self.assertIsNone(autorun.pick(self.con))


class Gates(AutorunCase):
    def test_off_does_nothing(self):
        autorun_repo.set_enabled(self.con, False)
        launcher = Recorder()
        result = autorun.tick(self.con, launcher=launcher)
        self.assertEqual(result["reason"], autorun.REASON_OFF)
        self.assertEqual(launcher.calls, [])

    def test_open_run_blocks_start(self):
        autorun_repo.start_run(self.con, self.todo["id"], CHILD, JOB)
        self.assertEqual(autorun.judge(self.con)["reason"], autorun.REASON_RUNNING)

    def test_usage_at_limit_blocks_start(self):
        self._use_limits(_limits_file(USAGE_CRITICAL_PCT))
        self.assertEqual(autorun.judge(self.con)["reason"], autorun.REASON_USAGE)

    def test_stale_usage_still_judges_by_last_value(self):
        """낡음으로 막으면 사람 없는 시간에 영구히 안 돈다 — 마지막 값으로 판단한다"""
        self._use_limits(_limits_file(10, age_seconds=3600))
        self.assertEqual(autorun.judge(self.con)["reason"], autorun.REASON_READY)

    def test_stale_usage_at_limit_still_blocks(self):
        """창이 아직 안 리셋됐으면 낡은 값이라도 한도는 한도다"""
        self._use_limits(_limits_file(USAGE_CRITICAL_PCT, age_seconds=3600))
        self.assertEqual(autorun.judge(self.con)["reason"], autorun.REASON_USAGE)

    def test_reset_window_clears_stale_limit(self):
        """한도에 닿은 채 찍힌 사진 한 장으로 밤새 막히면 안 된다"""
        self._use_limits(
            _limits_file(USAGE_CRITICAL_PCT, age_seconds=6 * 3600, resets_in=-3600)
        )
        self.assertEqual(autorun.judge(self.con)["reason"], autorun.REASON_READY)

    def test_missing_usage_file_blocks_start(self):
        self._use_limits(os.path.join(tempfile.mkdtemp(), "없음.json"))
        self.assertEqual(autorun.judge(self.con)["reason"], autorun.REASON_NO_USAGE)

    def test_no_candidate_only_skips_start(self):
        """후보가 비는 것은 일시적이다 — 다른 세션이 잡고 있기만 해도 그렇다. 끄면 안 된다"""
        label_repo.set_for_todo(self.con, self.todo["id"], [])
        launcher = Recorder()
        result = autorun.tick(self.con, launcher=launcher)
        self.assertEqual(result["reason"], autorun.REASON_NO_TODO)
        self.assertEqual(launcher.calls, [])
        self.assertTrue(autorun_repo.state(self.con)["enabled"])

    def test_tick_records_its_reason(self):
        """켜져 있는데 안 도는 이유를 화면에서 보려면 사유가 남아야 한다"""
        label_repo.set_for_todo(self.con, self.todo["id"], [])
        autorun.tick(self.con, launcher=Recorder())
        state = autorun_repo.state(self.con)
        self.assertEqual(state["last_tick_reason"], autorun.REASON_NO_TODO)
        self.assertTrue(state["last_tick_at"])

    def test_busiest_repo_wins_over_the_most_recent(self):
        """다른 저장소에서 이 워크스페이스 할일을 하나 잡았다고 위치가 넘어가면 안 된다"""
        session_repo.register(self.con, "sess-worktree", cwd=os.path.join(
            self.repo, ".claude", "worktrees", "wt"
        ))
        session_repo.link_todo(self.con, "sess-worktree", self.todo["id"])
        session_repo.set_state(self.con, "sess-worktree", STATE_ENDED)
        stranger = _git_repo()
        session_repo.register(self.con, "sess-stranger", cwd=stranger)
        session_repo.link_todo(self.con, "sess-stranger", self.todo["id"])
        session_repo.set_state(self.con, "sess-stranger", STATE_ENDED)
        self.assertEqual(autorun.target_cwd(self.con, self.workspace), self.repo)

    def test_unknown_cwd_blocks_start(self):
        """그 워크스페이스에서 돈 세션이 없으면 어디서 작업할지 알 수 없다"""
        label_repo.set_for_todo(self.con, self.todo["id"], [])
        other = workspace_repo.create(
            self.con, self.workspace["category_id"], "아무도 안 가본 곳"
        )
        orphan = todo_repo.create(self.con, "위치 모르는 일", workspace_id=other["id"])
        label_repo.set_for_todo(self.con, orphan["id"], [self.label["id"]])
        self.assertEqual(autorun.judge(self.con)["reason"], autorun.REASON_NO_CWD)


class Prompt(AutorunCase):
    def setUp(self):
        super().setUp()
        workspace_repo.update(self.con, self.workspace["id"], goal="끝까지 돌리기")
        self.workspace = workspace_repo.get(self.con, self.workspace["id"])

    def _text(self, **fields):
        todo = (
            todo_repo.update(self.con, self.todo["id"], **fields)
            if fields
            else self.todo
        )
        return autorun.build_prompt(todo, self.workspace, "/repo")

    def test_carries_workspace_and_todo(self):
        text = self._text()
        self.assertIn("끝까지 돌리기", text)
        self.assertIn(self.todo["title"], text)

    def test_cancels_harness_commit_instruction(self):
        """--bg 하네스는 '끝나면 커밋·푸시·draft PR' 을 넣는다. 프롬프트가 취소해야 한다"""
        text = self._text()
        self.assertIn("커밋·푸시·PR 을 하지 않는다", text)
        self.assertIn("EnterWorktree", text)

    def test_tells_how_to_finish(self):
        self.assertIn(f"set-status todo {self.todo['id']} done", self._text())

    def test_carries_precondition_and_recheck(self):
        text = self._text(precondition="포트 9080 이 비어 있을 것")
        self.assertIn("포트 9080 이 비어 있을 것", text)
        self.assertIn("코드를 고치기 전에", text)


class Launching(AutorunCase):
    def test_links_child_session_to_the_todo(self):
        """세션을 안 붙이면 보드는 그 작업을 모른다 — 붙고 doing 으로 올라가야 한다"""
        launcher = Recorder()
        result = autorun.tick(self.con, launcher=launcher)
        self.assertEqual(result["reason"], autorun.REASON_READY)
        self.assertEqual(len(launcher.calls), 1)
        self.assertEqual(launcher.calls[0]["cwd"], self.repo)
        self.assertEqual(
            session_repo.linked_todo_ids(self.con, CHILD), [self.todo["id"]]
        )
        self.assertEqual(
            todo_repo.get(self.con, self.todo["id"])["status"], STATUS_DOING
        )
        self.assertEqual(result["run"]["job_id"], JOB)

    def test_child_session_differs_from_launcher(self):
        autorun.tick(self.con, launcher=Recorder())
        self.assertNotEqual(
            autorun_repo.recent(self.con, 1)[0]["claude_session_id"], SID
        )

    def test_dry_run_does_not_launch(self):
        launcher = Recorder()
        result = autorun.tick(self.con, dry_run=True, launcher=launcher)
        self.assertEqual(result["reason"], autorun.REASON_READY)
        self.assertEqual(launcher.calls, [])
        self.assertEqual(autorun_repo.open_runs(self.con), [])

    def test_launch_failure_leaves_no_run(self):
        result = autorun.tick(
            self.con, launcher=Recorder(job_id="", session_id="", error="claude 없음")
        )
        self.assertEqual(result["error"], "claude 없음")
        self.assertEqual(autorun_repo.open_runs(self.con), [])


class Outcomes(AutorunCase):
    """잡이 끝났을 때 실행 기록을 어떻게 닫는가. 잡 상태 파일은 임시 디렉토리에 만든다"""

    def setUp(self):
        super().setUp()
        self.jobs = tempfile.mkdtemp()
        original = autorun._job_finished
        autorun._job_finished = lambda job_id: original(job_id, jobs_root=self.jobs)
        self.addCleanup(setattr, autorun, "_job_finished", original)

    def _job(self, job_id, state):
        directory = os.path.join(self.jobs, job_id)
        os.makedirs(directory, exist_ok=True)
        with open(os.path.join(directory, "state.json"), "w", encoding="utf-8") as f:
            json.dump({"state": state}, f)

    def test_working_job_stays_open(self):
        autorun_repo.start_run(self.con, self.todo["id"], CHILD, JOB)
        self._job(JOB, "working")
        self.assertEqual(autorun.reconcile(self.con), [])

    def test_limited_job_stays_open(self):
        """리밋으로 막힌 잡은 resume-limited-jobs.py 가 다시 민다"""
        autorun_repo.start_run(self.con, self.todo["id"], CHILD, JOB)
        self._job(JOB, "blocked")
        self.assertEqual(autorun.reconcile(self.con), [])

    def test_done_job_with_done_todo_waits_for_review(self):
        """성공한 잡은 완료가 아니라 확인 필요다 — 변경이 워크트리에 남아 있다"""
        autorun_repo.start_run(self.con, self.todo["id"], CHILD, JOB)
        self._job(JOB, "done")
        todo_repo.update(self.con, self.todo["id"], status=STATUS_DONE)
        run = autorun.reconcile(self.con)[0]
        self.assertEqual(run["outcome"], OUTCOME_REVIEW)
        self.assertEqual(
            autorun_repo.confirm_run(self.con, run["id"])["outcome"], OUTCOME_DONE
        )

    def test_confirm_rejects_anything_but_review(self):
        run = autorun_repo.start_run(self.con, self.todo["id"], CHILD, JOB)
        with self.assertRaises(Validation):  # 진행 중
            autorun_repo.confirm_run(self.con, run["id"])
        autorun_repo.close_run(self.con, run["id"], OUTCOME_FAILED)
        with self.assertRaises(Validation):
            autorun_repo.confirm_run(self.con, run["id"])

    def test_review_does_not_count_as_failure(self):
        """확인이 밀린 동안 그 할일이 blocked 로 올라가면 다음 tick 후보에서 빠진다"""
        first = autorun_repo.start_run(self.con, self.todo["id"], CHILD, "job1")
        autorun_repo.close_run(self.con, first["id"], OUTCOME_REVIEW)
        self.assertEqual(autorun_repo.consecutive_failures(self.con, self.todo["id"]), 0)
        autorun_repo.start_run(self.con, self.todo["id"], CHILD, JOB)
        self._job(JOB, "stopped")
        self.assertEqual(autorun.reconcile(self.con)[0]["outcome"], OUTCOME_FAILED)

    def test_finished_job_with_unfinished_todo_fails(self):
        autorun_repo.start_run(self.con, self.todo["id"], CHILD, JOB)
        self._job(JOB, "stopped")
        self.assertEqual(autorun.reconcile(self.con)[0]["outcome"], OUTCOME_FAILED)

    def test_second_failure_blocks_the_todo(self):
        outcome = None
        for state in ("stopped", "failed"):
            autorun_repo.start_run(self.con, self.todo["id"], CHILD, JOB)
            self._job(JOB, state)
            outcome = autorun.reconcile(self.con)[0]["outcome"]
        self.assertEqual(outcome, OUTCOME_BLOCKED)
        self.assertIn(self.todo["id"], autorun_repo.blocked_todo_ids(self.con))

    def test_blocked_streak_turns_autorun_off(self):
        for index in range(AUTORUN_BLOCKED_STREAK_LIMIT):
            run = autorun_repo.start_run(
                self.con, self.todo["id"], CHILD, f"job{index}"
            )
            autorun_repo.close_run(self.con, run["id"], OUTCOME_BLOCKED)
            autorun._apply_streak(self.con, OUTCOME_BLOCKED)
        self.assertFalse(autorun_repo.state(self.con)["enabled"])

    def test_missing_job_dir_closes_the_run(self):
        autorun_repo.start_run(self.con, self.todo["id"], CHILD, "사라진잡")
        self.assertEqual(len(autorun.reconcile(self.con)), 1)


class Handover(AutorunCase):
    def test_human_prompt_turns_autorun_off(self):
        autorun_repo.start_run(self.con, self.todo["id"], CHILD, JOB)
        self.assertTrue(autorun.disable_for_session(self.con, CHILD))
        self.assertFalse(autorun_repo.state(self.con)["enabled"])

    def test_other_session_is_left_alone(self):
        self.assertFalse(autorun.disable_for_session(self.con, "남의 세션"))
        self.assertTrue(autorun_repo.state(self.con)["enabled"])

    def test_the_jobs_own_first_prompt_is_not_a_human(self):
        """런처가 last_prompt 를 미리 심으면 자율 세션 자신의 첫 프롬프트가 사람으로
        오판돼 autorun 이 뜨자마자 꺼진다 — 실제로 job cfe5d3f4 가 그렇게 꺼졌다"""
        autorun.tick(self.con, launcher=Recorder())
        self.assertFalse(autorun.handover_if_human(self.con, CHILD))
        self.assertTrue(autorun_repo.state(self.con)["enabled"])

    def test_second_prompt_is_a_human_and_hands_over(self):
        autorun.tick(self.con, launcher=Recorder())
        # 자율 세션의 첫 프롬프트는 훅이 그때 기록한다
        session_repo.set_last_prompt(self.con, CHILD, "자율 실행 지시 전문")
        self.assertTrue(autorun.handover_if_human(self.con, CHILD))
        self.assertFalse(autorun_repo.state(self.con)["enabled"])

    def test_handover_ignores_sessions_without_a_run(self):
        session_repo.register(self.con, "손세션", cwd=self.repo)
        session_repo.set_last_prompt(self.con, "손세션", "사람이 친 지시")
        self.assertFalse(autorun.handover_if_human(self.con, "손세션"))
        self.assertTrue(autorun_repo.state(self.con)["enabled"])


class RecentWithTodos(AutorunCase):
    """자율 수행 패널이 그대로 뿌리는 조회. 할일 제목·워크스페이스 이름이 붙어야 한다"""

    def test_carries_todo_title_and_workspace_name(self):
        autorun_repo.start_run(self.con, self.todo["id"], CHILD, JOB)
        row = autorun_repo.recent_with_todos(self.con)[0]
        self.assertEqual(row["todo_title"], self.todo["title"])
        self.assertEqual(row["workspace_name"], self.workspace["name"])

    def test_unassigned_todo_has_no_workspace_name(self):
        orphan = todo_repo.create(
            self.con, "미분류 할일", category_id=self.workspace["category_id"]
        )
        autorun_repo.start_run(self.con, orphan["id"], CHILD, JOB)
        row = autorun_repo.recent_with_todos(self.con)[0]
        self.assertIsNone(row["workspace_name"])

    def test_most_recent_run_comes_first(self):
        first = autorun_repo.start_run(self.con, self.todo["id"], CHILD, "job1")
        autorun_repo.close_run(self.con, first["id"], OUTCOME_DONE)
        second = autorun_repo.start_run(self.con, self.todo["id"], CHILD, "job2")
        self.assertEqual(autorun_repo.recent_with_todos(self.con)[0]["id"], second["id"])


class WebToggle(AutorunCase):
    """화면의 on/off 스위치. CLI 의 dash.py autorun on|off 와 같은 상태를 건드린다"""

    def test_patch_turns_autorun_off_and_on(self):
        payload = server.route(self.con, "PATCH", "/api/autorun", {}, {"enabled": False})
        self.assertEqual(payload["state"]["enabled"], 0)
        self.assertEqual(autorun_repo.state(self.con)["enabled"], 0)

        payload = server.route(self.con, "PATCH", "/api/autorun", {}, {"enabled": True})
        self.assertEqual(payload["state"]["enabled"], 1)
        self.assertEqual(autorun_repo.state(self.con)["enabled"], 1)

    def test_response_carries_runs_so_the_panel_repaints(self):
        autorun_repo.start_run(self.con, self.todo["id"], CHILD, JOB)
        payload = server.route(self.con, "PATCH", "/api/autorun", {}, {"enabled": True})
        self.assertEqual(payload["runs"][0]["todo_title"], self.todo["title"])


if __name__ == "__main__":
    unittest.main()
