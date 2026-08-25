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
    AUTORUN_CANDIDATE_LIMIT,
    AUTORUN_LABEL,
    OUTCOME_BLOCKED,
    OUTCOME_DONE,
    OUTCOME_FAILED,
    OUTCOME_REQUESTED,
    OUTCOME_REVIEW,
    STATE_ENDED,
    STATUS_DOING,
    STATUS_DONE,
    STATUS_TODO,
    USAGE_CRITICAL_PCT,
)
from app.errors import NotFound, Validation
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
    """작업 위치 후보로 쓸 빈 저장소"""
    path = tempfile.mkdtemp()
    subprocess.run(["git", "init", "-q", path], check=True, timeout=30)
    return path


def _commit(path, *files):
    """임시 저장소라 전역 git 신원에 기대지 않는다"""
    subprocess.run(["git", "-C", path, "add", *files], check=True, timeout=30)
    subprocess.run(
        ["git", "-C", path, "-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "-q", "-m", "t"],
        check=True, timeout=30,
    )


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

    def test_skips_todo_with_a_condition_code_cannot_judge(self):
        """자유 문장은 코드가 충족을 판정할 수 없다 — 사람이 풀어야 후보가 된다"""
        label_repo.set_for_todo(self.con, self.todo["id"], [])
        self._todo("조건 붙은 일", labeled=True, precondition="다른 게 먼저 끝날 것")
        self.assertIsNone(autorun.pick(self.con))

    def test_skips_todo_whose_referenced_todo_is_open(self):
        label_repo.set_for_todo(self.con, self.todo["id"], [])
        blocker = self._todo("먼저 할 일")
        self._todo("뒤에 할 일", labeled=True, precondition=f"#{blocker['id']} 이 done 일 것")
        self.assertIsNone(autorun.pick(self.con))

    def test_takes_todo_once_every_referenced_todo_is_done(self):
        """#id 조건은 코드가 판정할 수 있다 — 그 할일이 끝나면 저절로 후보가 된다"""
        label_repo.set_for_todo(self.con, self.todo["id"], [])
        blocker = self._todo("먼저 할 일")
        waiting = self._todo(
            "뒤에 할 일", labeled=True, precondition=f"#{blocker['id']} 이 done 일 것"
        )
        todo_repo.update(self.con, blocker["id"], status=STATUS_DONE)
        self.assertEqual(autorun.pick(self.con)["todo"]["id"], waiting["id"])

    def test_skips_blocked_todo(self):
        run = autorun_repo.start_run(self.con, self.todo["id"], CHILD, JOB)
        autorun_repo.close_run(self.con, run["id"], OUTCOME_BLOCKED)
        self.assertIsNone(autorun.pick(self.con))

    def test_skips_requested_todo(self):
        """판단 보류로 멈춘 할일도 blocked 와 같이 후보에서 빠진다"""
        run = autorun_repo.start_run(self.con, self.todo["id"], CHILD, JOB)
        autorun_repo.close_run(self.con, run["id"], OUTCOME_REQUESTED)
        self.assertIsNone(autorun.pick(self.con))

    def test_skips_review_locked_todo(self):
        """검토 대기인 할일에 새 잡을 또 띄우면 사람이 확인하기 전에 diff 가 두 벌 생긴다"""
        run = autorun_repo.start_run(self.con, self.todo["id"], CHILD, JOB)
        autorun_repo.close_run(self.con, run["id"], OUTCOME_REVIEW)
        self.assertIsNone(autorun.pick(self.con))

    def test_skips_done_todo(self):
        todo_repo.update(self.con, self.todo["id"], status=STATUS_DONE)
        self.assertIsNone(autorun.pick(self.con))


class CandidatePanel(AutorunCase):
    """자율 수행 화면의 후보 목록. 못 도는 것도 싣고 왜 못 도는지를 같이 준다"""

    def test_lists_labeled_todo_as_ready(self):
        rows = autorun.candidates(self.con)
        self.assertEqual([row["todo_id"] for row in rows], [self.todo["id"]])
        self.assertEqual(rows[0]["blocker"], autorun.BLOCKER_READY)
        self.assertEqual(rows[0]["workspace_name"], self.workspace["name"])

    def test_leaves_out_unlabeled_todo(self):
        self._todo("라벨 없는 일")
        self.assertEqual(len(autorun.candidates(self.con)), 1)

    def test_leaves_out_what_already_ran(self):
        """한 번 돈 것은 아래 실행 목록이 제 구획으로 보여준다 — 후보에 또 실으면
        limit 줄을 다 차지해서 정작 다음에 돌 할일이 화면 밖으로 밀린다"""
        for outcome in (OUTCOME_BLOCKED, OUTCOME_REQUESTED, OUTCOME_REVIEW):
            run = autorun_repo.start_run(self.con, self.todo["id"], CHILD, JOB)
            autorun_repo.close_run(self.con, run["id"], outcome)
            self.assertEqual(autorun.candidates(self.con), [], outcome)
            self.con.execute("DELETE FROM autorun_runs")

    def test_leaves_out_todo_another_session_holds(self):
        """남이 잡고 있는 동안은 자율 수행이 건드릴 것이 아니다 — 그 세션 목록에 이미 있다"""
        session_repo.register(self.con, "다른-세션")
        session_repo.link_todo(self.con, "다른-세션", self.todo["id"])
        self.assertEqual(autorun.candidates(self.con), [])

    def test_marks_unknown_cwd(self):
        """위치를 못 정하면 tick 이 건너뛴다 — 목록이 "시작 가능" 이라 적으면 거짓말이 된다"""
        label_repo.set_for_todo(self.con, self.todo["id"], [])
        blind = workspace_repo.create(
            self.con, self.workspace["category_id"], "아무도 안 가본 곳"
        )
        orphan = todo_repo.create(self.con, "위치 모르는 일", workspace_id=blind["id"])
        label_repo.set_for_todo(self.con, orphan["id"], [self.label["id"]])
        row = autorun.candidates(self.con)[0]
        self.assertEqual(row["blocker"], autorun.BLOCKER_CWD)
        # 화면이 위치를 지정할 워크스페이스를 알아야 그 자리에서 풀 수 있다
        self.assertEqual(row["workspace_id"], blind["id"])

    def test_designated_cwd_clears_the_blocker(self):
        """사람이 위치를 지정하면 그 워크스페이스의 후보가 바로 돌 수 있게 된다"""
        label_repo.set_for_todo(self.con, self.todo["id"], [])
        blind = workspace_repo.create(
            self.con, self.workspace["category_id"], "아무도 안 가본 곳"
        )
        orphan = todo_repo.create(self.con, "위치 모르는 일", workspace_id=blind["id"])
        label_repo.set_for_todo(self.con, orphan["id"], [self.label["id"]])
        workspace_repo.update(self.con, blind["id"], cwd=tempfile.mkdtemp())
        self.assertEqual(autorun.candidates(self.con)[0]["blocker"], autorun.BLOCKER_READY)

    def test_counts_unmet_conditions(self):
        label_repo.set_for_todo(self.con, self.todo["id"], [])
        blocker = self._todo("먼저 할 일")
        self._todo(
            "조건 걸린 일",
            labeled=True,
            precondition=f"#{blocker['id']} 이 done 일 것\n기획 확정",
        )
        row = autorun.candidates(self.con)[0]
        self.assertEqual(row["blocker"], autorun.BLOCKER_PRECONDITION)
        self.assertEqual(row["precondition"], {"total": 2, "met": 0, "manual": 1})

    def test_drag_order_wins_over_board_order(self):
        """사람이 끌어 정한 순서가 먼저다. 안 정한 것은 그 뒤에 원래 순위대로 남는다"""
        second = self._todo("둘째", labeled=True)
        third = self._todo("셋째", labeled=True)
        todo_repo.set_autorun_order(self.con, [third["id"], self.todo["id"]])
        self.assertEqual(
            [row["todo_id"] for row in autorun.candidates(self.con)],
            [third["id"], self.todo["id"], second["id"]],
        )

    def test_pick_follows_the_dragged_order(self):
        """목록 맨 위와 실제로 돌 할일이 다르면 그 조작이 거짓말이 된다"""
        later = self._todo("나중 것", labeled=True)
        todo_repo.set_autorun_order(self.con, [later["id"], self.todo["id"]])
        self.assertEqual(autorun.pick(self.con)["todo"]["id"], later["id"])

    def test_reorder_route_saves_candidate_order(self):
        second = self._todo("둘째", labeled=True)
        server.route(
            self.con,
            "POST",
            "/api/reorder",
            {},
            {"kind": "autorun", "ids": [second["id"], self.todo["id"]]},
        )
        self.assertEqual(
            [row["todo_id"] for row in autorun.candidates(self.con)],
            [second["id"], self.todo["id"]],
        )

    def test_caps_the_list(self):
        for index in range(AUTORUN_CANDIDATE_LIMIT + 2):
            self._todo(f"자동 {index}", labeled=True)
        self.assertEqual(len(autorun.candidates(self.con)), AUTORUN_CANDIDATE_LIMIT)


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

    def test_designated_cwd_wins_over_session_history(self):
        """사람이 지정한 위치가 있으면 세션 이력을 추론하지 않는다 — 지정이 곧 답이다.

        저장소가 아닌 곳도 받는다: 자료·문서만 다루는 워크스페이스는 .git 이 없다
        """
        chosen = tempfile.mkdtemp()
        workspace_repo.update(self.con, self.workspace["id"], cwd=chosen)
        workspace = workspace_repo.get(self.con, self.workspace["id"])
        self.assertEqual(autorun.target_cwd(self.con, workspace), chosen)

    def test_designated_cwd_that_is_gone_falls_back_to_history(self):
        """지운 경로를 물고 멈추면 안 된다 — 추론으로 내려가고, 그것도 없으면 위치 미정"""
        missing = tempfile.mkdtemp()
        os.rmdir(missing)
        workspace_repo.update(self.con, self.workspace["id"], cwd=missing)
        workspace = workspace_repo.get(self.con, self.workspace["id"])
        self.assertEqual(autorun.target_cwd(self.con, workspace), self.repo)

    def test_unknown_cwd_blocks_start(self):
        """그 워크스페이스에서 돈 세션이 없으면 어디서 작업할지 알 수 없다"""
        label_repo.set_for_todo(self.con, self.todo["id"], [])
        other = workspace_repo.create(
            self.con, self.workspace["category_id"], "아무도 안 가본 곳"
        )
        orphan = todo_repo.create(self.con, "위치 모르는 일", workspace_id=other["id"])
        label_repo.set_for_todo(self.con, orphan["id"], [self.label["id"]])
        self.assertEqual(autorun.judge(self.con)["reason"], autorun.REASON_NO_CWD)

    def test_unknown_cwd_candidate_is_skipped_for_the_next_one(self):
        """위치 없는 워크스페이스가 순위상 앞이어도 위치가 있는 다음 후보가 뜬다 —

        한 워크스페이스가 위치를 못 정했다고 tick 전체가 멈추면 안 된다
        """
        blind = workspace_repo.create(
            self.con, self.workspace["category_id"], "아무도 안 가본 곳"
        )
        orphan = todo_repo.create(self.con, "위치 모르는 일", workspace_id=blind["id"])
        label_repo.set_for_todo(self.con, orphan["id"], [self.label["id"]])
        workspace_repo.reorder(self.con, [blind["id"], self.workspace["id"]])
        decision = autorun.judge(self.con)
        self.assertEqual(decision["reason"], autorun.REASON_READY)
        self.assertEqual(decision["todo"]["id"], self.todo["id"])
        self.assertEqual(decision["cwd"], self.repo)

    def test_uncommitted_changes_do_not_block_start(self):
        """자율 세션은 워크트리를 새로 파서 일하므로 본 체크아웃의 미커밋 변경과 겹치지 않는다"""
        tracked = os.path.join(self.repo, "kept.txt")
        with open(tracked, "w", encoding="utf-8") as handle:
            handle.write("처음\n")
        _commit(self.repo, "kept.txt")
        with open(tracked, "w", encoding="utf-8") as handle:
            handle.write("고치는 중\n")
        with open(os.path.join(self.repo, "잔여물.tmp"), "w", encoding="utf-8") as handle:
            handle.write("")
        self.assertEqual(autorun.judge(self.con)["reason"], autorun.REASON_READY)


class Prompt(AutorunCase):
    def setUp(self):
        super().setUp()
        workspace_repo.update(self.con, self.workspace["id"], goal="끝까지 돌리기")
        self.workspace = workspace_repo.get(self.con, self.workspace["id"])

    def _text(self, cwd=None, **fields):
        todo = (
            todo_repo.update(self.con, self.todo["id"], **fields)
            if fields
            else self.todo
        )
        return autorun.build_prompt(todo, self.workspace, cwd or _git_repo())

    def test_carries_workspace_and_todo(self):
        text = self._text()
        self.assertIn("끝까지 돌리기", text)
        self.assertIn(self.todo["title"], text)

    def test_cancels_harness_push_pr_instruction(self):
        """--bg 하네스는 '끝나면 커밋·푸시·draft PR' 을 넣는다. 푸시·PR 은 프롬프트가 취소해야 한다"""
        text = self._text()
        self.assertIn("푸시·PR 을 하지 않는다", text)
        self.assertIn("EnterWorktree", text)

    def test_tells_how_to_finish(self):
        """할일 상태는 안 건드린다 — autorun-finish 는 검토 대기 표시만 남긴다"""
        self.assertIn("autorun-finish", self._text())

    def test_commits_only_when_fully_done(self):
        """확인할 것도 불분명한 것도 없을 때만 커밋 — 안 그러면 dash.py merge 가

        '커밋 안 된 변경' 으로 막혀 워크트리의 결과물을 사람이 손으로 커밋해야 한다
        """
        text = self._text()
        self.assertIn("커밋한 뒤", text)
        self.assertIn("커밋하지 않고 `autorun-finish` 도 부르지 않는다", text)

    def test_tells_how_to_request_when_judgment_is_missing(self):
        self.assertIn("autorun-request", self._text())

    def test_carries_precondition_and_recheck(self):
        text = self._text(precondition="포트 9080 이 비어 있을 것")
        self.assertIn("포트 9080 이 비어 있을 것", text)
        self.assertIn("코드를 고치기 전에", text)

    def test_non_git_cwd_skips_worktree_and_commit_instructions(self):
        """할일 케밥의 "시작"이 고른 폴더는 git 저장소가 아닐 수 있다 — 그때는
        워크트리·커밋을 요구하면 안 끝낼 방법이 없어진다"""
        plain = tempfile.mkdtemp()
        text = self._text(cwd=plain)
        self.assertNotIn("EnterWorktree", text)
        self.assertNotIn("diff 로 확인해 커밋한 뒤", text)
        self.assertIn("autorun-finish", text)
        self.assertIn(plain, text)

    def test_this_repo_gets_the_concrete_test_command(self):
        """cwd 가 work-dashboard 자기 자신이면 이미 아는 실행법(python3 -m tests)을 그대로 알려준다"""
        this_repo = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(autorun.__file__)))
        )
        text = self._text(cwd=this_repo)
        self.assertIn("python3 -m tests", text)

    def test_other_project_gets_a_generic_test_instruction(self):
        """cwd 가 다른 프로젝트면 python3 -m tests 는 틀린 명령이다 — 일반 안내로 대신한다"""
        text = self._text()  # 기본 cwd 는 _git_repo() — work-dashboard 가 아닌 임시 저장소
        self.assertNotIn("python3 -m tests", text)
        self.assertIn("README·CLAUDE.md", text)


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

    def test_job_name_carries_the_todo_id(self):
        launcher = Recorder()
        autorun.tick(self.con, launcher=launcher)
        self.assertEqual(
            launcher.calls[0]["name"],
            f"#{self.todo['id']} | {self.todo['title']}",
        )

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


class ManualStart(AutorunCase):
    """할일 케밥의 "시작". 사람이 직접 고른 할일이라 eligible() 의 자동 후보 판정을 거치지 않는다"""

    def test_starts_unlabeled_todo(self):
        """auto 라벨은 자율 실행의 자동 후보 판정 조건이다 — 사람이 직접 고른 시작에는 안 붙는다"""
        unlabeled = self._todo("라벨 없는 일")
        launcher = Recorder()
        result = autorun.start_todo(self.con, unlabeled["id"], launcher=launcher)
        self.assertEqual(result["session_id"], CHILD)
        self.assertEqual(launcher.calls[0]["cwd"], self.repo)

    def test_starts_todo_with_precondition(self):
        """조건 문장이 있어도 시작은 막지 않는다 — 판단은 프롬프트가 세션에 넘긴다"""
        todo = self._todo("조건 붙은 일", precondition="다른 게 먼저 끝날 것")
        launcher = Recorder()
        autorun.start_todo(self.con, todo["id"], launcher=launcher)
        self.assertIn("다른 게 먼저 끝날 것", launcher.calls[0]["prompt"])

    def test_job_name_carries_the_todo_id(self):
        launcher = Recorder()
        autorun.start_todo(self.con, self.todo["id"], launcher=launcher)
        self.assertEqual(
            launcher.calls[0]["name"], f"#{self.todo['id']} | {self.todo['title']}"
        )

    def test_links_child_session_and_marks_doing(self):
        autorun.start_todo(self.con, self.todo["id"], launcher=Recorder())
        self.assertEqual(
            session_repo.linked_todo_ids(self.con, CHILD), [self.todo["id"]]
        )
        self.assertEqual(
            todo_repo.get(self.con, self.todo["id"])["status"], STATUS_DOING
        )

    def test_blocks_review_locked_todo(self):
        """검토 대기 중에 또 띄우면 확인 전에 같은 할일의 diff 가 두 벌 생긴다"""
        run = autorun_repo.start_run(self.con, self.todo["id"], CHILD, JOB)
        autorun_repo.close_run(self.con, run["id"], OUTCOME_REVIEW)
        with self.assertRaises(Validation):
            autorun.start_todo(self.con, self.todo["id"], launcher=Recorder())

    def test_blocks_when_cwd_is_unknown(self):
        workspace = workspace_repo.create(
            self.con, self.workspace["category_id"], "위치 모름"
        )
        todo = todo_repo.create(self.con, "위치 모르는 일", workspace_id=workspace["id"])
        with self.assertRaises(Validation):
            autorun.start_todo(self.con, todo["id"], launcher=Recorder())

    def test_explicit_cwd_is_used_when_workspace_has_no_history(self):
        """위치를 모르는 워크스페이스도, 화면이 물어 받은 경로가 있으면 그걸 쓴다.

        git 저장소로 제한하지 않는다 — 워크트리를 안 만들어도 되는 작업도 있다
        """
        workspace = workspace_repo.create(
            self.con, self.workspace["category_id"], "위치 모름"
        )
        todo = todo_repo.create(self.con, "위치 모르는 일", workspace_id=workspace["id"])
        chosen = tempfile.mkdtemp()
        launcher = Recorder()
        autorun.start_todo(self.con, todo["id"], launcher=launcher, cwd=chosen)
        self.assertEqual(launcher.calls[0]["cwd"], chosen)

    def test_explicit_cwd_must_be_an_existing_directory(self):
        missing = os.path.join(tempfile.mkdtemp(), "없음")
        with self.assertRaises(Validation):
            autorun.start_todo(
                self.con, self.todo["id"], launcher=Recorder(), cwd=missing
            )

    def test_launch_failure_raises(self):
        launcher = Recorder(job_id="", session_id="", error="claude 없음")
        with self.assertRaises(Validation):
            autorun.start_todo(self.con, self.todo["id"], launcher=launcher)


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

    def test_finished_job_waits_for_review(self):
        """성공한 잡은 완료가 아니라 검토 대기다 — 변경이 워크트리에 남아 있다.

        완료 신호는 todo.status 가 아니라 세션이 직접 남긴 mark_finished 다 —
        status 는 사람이 확인하기 전까지 doing 그대로여야 한다(done 은 더 안 봐도
        된다는 뜻이라, 확인 전에 done 이면 그 뜻이 깨진다)
        """
        autorun_repo.start_run(self.con, self.todo["id"], CHILD, JOB)
        autorun_repo.mark_finished(self.con, CHILD)
        self._job(JOB, "done")
        run = autorun.reconcile(self.con)[0]
        self.assertEqual(run["outcome"], OUTCOME_REVIEW)
        self.assertEqual(todo_repo.get(self.con, self.todo["id"])["status"], STATUS_DOING)

    def test_silent_finish_without_signal_counts_as_failure(self):
        """아무 신호도 안 남기고 조용히 멈추면 낙관적으로 review 로 보지 않는다 —

        review 로 잘못 보면 미완성 작업이 검토 대상으로 둔갑한다. 안전한 기본값은 실패다
        """
        autorun_repo.start_run(self.con, self.todo["id"], CHILD, JOB)
        self._job(JOB, "done")
        self.assertEqual(autorun.reconcile(self.con)[0]["outcome"], OUTCOME_FAILED)

    def test_confirm_promotes_todo_to_done(self):
        """확인해야 비로소 done — 그 전엔 doing 이라 next·완료 집계에 그대로 잡힌다"""
        run = autorun_repo.start_run(self.con, self.todo["id"], CHILD, JOB)
        autorun_repo.close_run(self.con, run["id"], OUTCOME_REVIEW)
        autorun.confirm_run(self.con, run["id"])
        self.assertEqual(todo_repo.get(self.con, self.todo["id"])["status"], STATUS_DONE)

    def test_reopen_reverts_todo_to_doing(self):
        """확인을 취소하면(reopen) 할일도 doing 으로 되돌아간다 — confirm_run 의 역"""
        run = autorun_repo.start_run(self.con, self.todo["id"], CHILD, JOB)
        autorun_repo.close_run(self.con, run["id"], OUTCOME_REVIEW)
        autorun.confirm_run(self.con, run["id"])
        autorun.reopen_run(self.con, run["id"])
        self.assertEqual(todo_repo.get(self.con, self.todo["id"])["status"], STATUS_DOING)

    def test_confirm_rejects_anything_but_review(self):
        run = autorun_repo.start_run(self.con, self.todo["id"], CHILD, JOB)
        with self.assertRaises(Validation):  # 진행 중
            autorun_repo.confirm_run(self.con, run["id"])
        autorun_repo.close_run(self.con, run["id"], OUTCOME_FAILED)
        with self.assertRaises(Validation):
            autorun_repo.confirm_run(self.con, run["id"])

    def test_status_change_blocked_while_review_pending(self):
        """검토 대기인 동안은 사람이 상태를 직접 못 바꾼다 — 확인 버튼으로만 넘어간다"""
        run = autorun_repo.start_run(self.con, self.todo["id"], CHILD, JOB)
        autorun_repo.close_run(self.con, run["id"], OUTCOME_REVIEW)
        with self.assertRaises(Validation):
            todo_repo.update(self.con, self.todo["id"], status=STATUS_TODO)

    def test_confirm_unlocks_status_change(self):
        run = autorun_repo.start_run(self.con, self.todo["id"], CHILD, JOB)
        autorun_repo.close_run(self.con, run["id"], OUTCOME_REVIEW)
        autorun_repo.confirm_run(self.con, run["id"])
        updated = todo_repo.update(self.con, self.todo["id"], status=STATUS_TODO)
        self.assertEqual(updated["status"], STATUS_TODO)

    def test_open_run_does_not_block_the_job_s_own_completion(self):
        """실행이 아직 열려 있는 동안(outcome 없음)은 그 할일의 상태 변경이 안 잠긴다"""
        autorun_repo.start_run(self.con, self.todo["id"], CHILD, JOB)
        updated = todo_repo.update(self.con, self.todo["id"], status=STATUS_DONE)
        self.assertEqual(updated["status"], STATUS_DONE)

    def test_reopen_reverts_confirm_and_relocks_status(self):
        run = autorun_repo.start_run(self.con, self.todo["id"], CHILD, JOB)
        autorun_repo.close_run(self.con, run["id"], OUTCOME_REVIEW)
        autorun_repo.confirm_run(self.con, run["id"])
        reopened = autorun_repo.reopen_run(self.con, run["id"])
        self.assertEqual(reopened["outcome"], OUTCOME_REVIEW)
        with self.assertRaises(Validation):
            todo_repo.update(self.con, self.todo["id"], status=STATUS_TODO)

    def test_reopen_rejects_anything_but_done(self):
        run = autorun_repo.start_run(self.con, self.todo["id"], CHILD, JOB)
        with self.assertRaises(Validation):  # 진행 중
            autorun_repo.reopen_run(self.con, run["id"])
        autorun_repo.close_run(self.con, run["id"], OUTCOME_REVIEW)
        with self.assertRaises(Validation):  # 아직 확인 전
            autorun_repo.reopen_run(self.con, run["id"])

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

    def test_requested_note_closes_as_requested_not_failed(self):
        """세션이 판단을 요청하고 멈추면 실패가 아니라 요청으로 닫혀야 한다"""
        autorun_repo.start_run(self.con, self.todo["id"], CHILD, JOB)
        autorun_repo.mark_requested(self.con, CHILD, "이 방향으로 갈지 저 방향으로 갈지 note 에 없음")
        self._job(JOB, "stopped")
        run = autorun.reconcile(self.con)[0]
        self.assertEqual(run["outcome"], OUTCOME_REQUESTED)
        self.assertIn(self.todo["id"], autorun_repo.requested_todo_ids(self.con))

    def test_requested_does_not_count_as_failure(self):
        """요청 뒤에 다시 잡히더라도 실패 스트릭에 안 섞여야 blocked 로 잘못 안 넘어간다"""
        first = autorun_repo.start_run(self.con, self.todo["id"], CHILD, "job1")
        autorun_repo.close_run(self.con, first["id"], OUTCOME_REQUESTED)
        self.assertEqual(autorun_repo.consecutive_failures(self.con, self.todo["id"]), 0)

    def test_mark_requested_needs_a_reason(self):
        autorun_repo.start_run(self.con, self.todo["id"], CHILD, JOB)
        with self.assertRaises(Validation):
            autorun_repo.mark_requested(self.con, CHILD, "   ")

    def test_mark_requested_needs_an_open_run(self):
        with self.assertRaises(NotFound):
            autorun_repo.mark_requested(self.con, "아무도 안 도는 세션", "이유")


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

    def test_review_feedback_leaves_autorun_on(self):
        """검토 대기 잡에 주는 피드백은 인계가 아니다 — 다른 할일까지 멈출 이유가 없다"""
        autorun.tick(self.con, launcher=Recorder())
        run = autorun_repo.find_by_session(self.con, CHILD)
        autorun_repo.close_run(self.con, run["id"], OUTCOME_REVIEW)
        session_repo.set_last_prompt(self.con, CHILD, "이거 브라우저 검증은 한거야?")
        self.assertFalse(autorun.handover_if_human(self.con, CHILD))
        self.assertTrue(autorun_repo.state(self.con)["enabled"])

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

    def test_carries_the_session_cwd(self):
        """그 세션이 어디서 돌았는지 — 패널의 워크트리 칸이 여기서 나온다"""
        path = os.path.join(self.repo, ".claude", "worktrees", "고침")
        session_repo.register(self.con, CHILD, cwd=path)
        autorun_repo.start_run(self.con, self.todo["id"], CHILD, JOB)
        self.assertEqual(autorun_repo.recent_with_todos(self.con)[0]["cwd"], path)

    def test_most_recent_run_comes_first(self):
        first = autorun_repo.start_run(self.con, self.todo["id"], CHILD, "job1")
        autorun_repo.close_run(self.con, first["id"], OUTCOME_DONE)
        second = autorun_repo.start_run(self.con, self.todo["id"], CHILD, "job2")
        self.assertEqual(autorun_repo.recent_with_todos(self.con)[0]["id"], second["id"])


class PanelRuns(AutorunCase):
    """패널이 받는 목록 — 실행 기록에 워크트리 이름과 그 위치의 포트가 붙어야 한다"""

    def setUp(self):
        super().setUp()
        self.calls = []
        autorun._WORKTREE_CACHE.clear()
        self.addCleanup(autorun._WORKTREE_CACHE.clear)
        original = autorun.worktrees.processes_by_path
        self.addCleanup(setattr, autorun.worktrees, "processes_by_path", original)
        # lsof 를 부르지 않는다 — 무엇을 물었는지와 붙는 결과만 본다
        autorun.worktrees.processes_by_path = self._lookup

    def _lookup(self, paths):
        self.calls.append(list(paths))
        # 진짜 조회는 lsof 가 푼 경로로 돌려준다 — 키도 그렇게 맞춰 둔다
        return {os.path.realpath(path):
                [{"pid": 1, "command": "python3 server.py", "ports": [9081]}]
                for path in paths}

    def _run_at(self, cwd):
        session_repo.register(self.con, CHILD, cwd=cwd)
        return autorun_repo.start_run(self.con, self.todo["id"], CHILD, JOB)

    def _worktree_dir(self, name):
        path = os.path.join(self.repo, ".claude", "worktrees", name)
        os.makedirs(path)
        return path

    def test_worktree_name_and_ports_are_attached(self):
        self._run_at(self._worktree_dir("고침"))
        row = autorun.panel_runs(self.con)[0]
        self.assertEqual(row["worktree"], "고침")
        self.assertEqual(row["ports"], [9081])

    def test_main_checkout_has_no_worktree_and_is_not_looked_up(self):
        """메인 체크아웃에서 돈 실행은 워크트리가 없다 — lsof 도 부르지 않는다"""
        self._run_at(self.repo)
        row = autorun.panel_runs(self.con)[0]
        self.assertEqual(row["worktree"], "")
        self.assertEqual(row["ports"], [])
        self.assertEqual(self.calls, [[]])

    def test_finished_run_is_looked_up_once(self):
        """끝난 실행의 워크트리는 안 바뀐다 — 5초 폴링이 transcript 를 다시 읽으면 안 된다"""
        run = self._run_at(self._worktree_dir("끝난것"))
        autorun_repo.close_run(self.con, run["id"], OUTCOME_DONE)
        reads = []
        original = autorun.release.worktree_of
        self.addCleanup(setattr, autorun.release, "worktree_of", original)
        autorun.release.worktree_of = lambda *args: (reads.append(args), original(*args))[1]
        autorun.panel_runs(self.con)
        autorun.panel_runs(self.con)
        self.assertEqual(len(reads), 1)


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


class TitleRename(AutorunCase):
    """제목을 고치면 그 할일을 잡았던 잡 이름도 따라가야 한다.

    안 따라가면 `claude agents` 목록과 대시보드가 서로 다른 제목을 보여준다
    """

    def setUp(self):
        super().setUp()
        self.jobs = tempfile.mkdtemp()

    def _job(self, job_id, session_id, name, flags=None):
        directory = os.path.join(self.jobs, job_id)
        os.makedirs(directory, exist_ok=True)
        state = {"sessionId": session_id, "name": name, "nameSource": "user"}
        if flags is not None:
            state["respawnFlags"] = flags
        with open(self._path(job_id), "w", encoding="utf-8") as handle:
            json.dump(state, handle)

    def _path(self, job_id):
        return os.path.join(self.jobs, job_id, "state.json")

    def _state(self, job_id):
        with open(self._path(job_id), encoding="utf-8") as handle:
            return json.load(handle)

    def _rename(self, title):
        updated = todo_repo.update(self.con, self.todo["id"], title=title)
        return autorun.rename_todo_sessions(self.con, updated, jobs_root=self.jobs)

    def test_renames_job_of_the_linked_session(self):
        old = f"#{self.todo['id']} | {self.todo['title']}"
        self._job(SID[:8], SID, old, ["--name", old])
        self.assertEqual(self._rename("고친 제목"), [SID[:8]])
        state = self._state(SID[:8])
        new = f"#{self.todo['id']} | 고친 제목"
        self.assertEqual(state["name"], new)
        # 리밋 재개가 예전 이름으로 되돌리지 않아야 한다
        self.assertEqual(state["respawnFlags"], ["--name", new])

    def test_skips_job_of_another_session(self):
        """잡 디렉터리 이름이 겹쳐도 sessionId 가 다르면 남의 잡이다"""
        self._job(SID[:8], "다른-세션", "남의 잡")
        self.assertEqual(self._rename("고친 제목"), [])
        self.assertEqual(self._state(SID[:8])["name"], "남의 잡")

    def test_no_job_file_is_not_an_error(self):
        """사람이 터미널에서 직접 연 세션은 고칠 파일이 없다"""
        self.assertEqual(self._rename("고친 제목"), [])

    def test_patch_renames_only_when_title_changes(self):
        calls = []
        original = autorun.rename_todo_sessions
        autorun.rename_todo_sessions = lambda con, todo: calls.append(todo["title"])
        self.addCleanup(setattr, autorun, "rename_todo_sessions", original)
        path = f"/api/todos/{self.todo['id']}"
        server.route(self.con, "PATCH", path, {}, {"note": "메모만"})
        self.assertEqual(calls, [])
        server.route(self.con, "PATCH", path, {}, {"title": "고친 제목"})
        self.assertEqual(calls, ["고친 제목"])


if __name__ == "__main__":
    unittest.main()
