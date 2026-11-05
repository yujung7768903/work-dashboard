"""⑥ 방치된 doing 판정 — 후보 선별·근거 수집·적용. 실제 `claude -p` 는 부르지 않는다"""
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from app.constants import (
    STALE_JUDGE_IDLE_DAYS,
    STALE_JUDGE_MIN_CONFIDENCE,
    STALE_JUDGE_NOTE_MARK,
    STATE_ENDED,
    STATUS_DOING,
    STATUS_DONE,
    STATUS_TODO,
    VERDICT_DONE,
    VERDICT_INVALID,
    VERDICT_KEEP,
    VERDICT_TODO,
)
from app.repositories import autorun as autorun_repo
from app.repositories import categories as category_repo
from app.repositories import sessions as session_repo
from app.repositories import stale_judgments as judgment_repo
from app.repositories import todos as todo_repo
from app.repositories import workspaces as workspace_repo
from app.repositories import worktrees as worktree_repo
from app.services import stale_judge
from tests.support import temp_db

SID = "sess-stale"
OLD_DAYS = STALE_JUDGE_IDLE_DAYS + 5


def verdict(kind, confidence=0.9, reason="근거 있음"):
    return {"verdict": kind, "confidence": confidence, "reason": reason}


def fixed(kind, **extra):
    """모델 대신 쓰는 판정 함수. 받은 근거를 기록해 둬서 프롬프트 내용도 검사한다"""
    seen = []

    def judge(facts):
        seen.append(facts)
        return verdict(kind, **extra)

    judge.seen = seen
    return judge


class StaleCase(unittest.TestCase):
    def setUp(self):
        self.con = temp_db()
        category = category_repo.create(self.con, "방치 판정")
        self.workspace = workspace_repo.create(self.con, category["id"], "워크스페이스")
        self.todo = self._doing("오래 붙잡은 일", days=OLD_DAYS, note="처음 적은 맥락")

    def _doing(self, title, days, note=None):
        todo = todo_repo.create(self.con, title, workspace_id=self.workspace["id"], note=note)
        todo_repo.update(self.con, todo["id"], status=STATUS_DOING)
        self._age(todo["id"], days)
        return todo_repo.get(self.con, todo["id"])

    def _age(self, todo_id, days):
        stamp = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
        self.con.execute("UPDATE todos SET updated_at=? WHERE id=?", (stamp, todo_id))
        self.con.commit()


class Candidates(StaleCase):
    def test_only_old_doing(self):
        self._doing("방금 잡은 일", days=1)
        waiting = todo_repo.create(self.con, "대기", workspace_id=self.workspace["id"])
        self._age(waiting["id"], OLD_DAYS)
        ids = [todo["id"] for todo in stale_judge.candidates(self.con)]
        self.assertEqual(ids, [self.todo["id"]])

    def test_claimed_by_live_session_is_skipped(self):
        session_repo.register(self.con, SID)
        session_repo.link_todo(self.con, SID, self.todo["id"])
        self.assertEqual(stale_judge.candidates(self.con), [])
        session_repo.set_state(self.con, SID, STATE_ENDED)
        self.assertEqual(len(stale_judge.candidates(self.con)), 1)

    def test_open_autorun_run_is_skipped(self):
        autorun_repo.start_run(self.con, self.todo["id"])
        self.assertEqual(stale_judge.candidates(self.con), [])

    def test_recent_keep_judgment_is_not_asked_again(self):
        judgment_repo.record(self.con, self.todo["id"], VERDICT_KEEP, 0.4, "모름", False)
        self.assertEqual(stale_judge.candidates(self.con), [])


class Applying(StaleCase):
    def test_done_closes_and_notes_reason(self):
        report = stale_judge.run(self.con, judge=fixed(VERDICT_DONE, reason="워크트리 병합됨"))
        todo = todo_repo.get(self.con, self.todo["id"])
        self.assertEqual(todo["status"], STATUS_DONE)
        self.assertIsNotNone(todo["completed_at"])
        self.assertIn("처음 적은 맥락", todo["note"])
        self.assertIn(f"{STALE_JUDGE_NOTE_MARK} ", todo["note"])
        self.assertIn("완료로 닫음 — 워크트리 병합됨", todo["note"])
        self.assertTrue(report["results"][0]["applied"])
        self.assertEqual(judgment_repo.recent(self.con)[0]["applied"], 1)

    def test_invalid_closes_with_invalid_label(self):
        stale_judge.run(self.con, judge=fixed(VERDICT_INVALID, reason="다른 할일이 대신 끝냄"))
        todo = todo_repo.get(self.con, self.todo["id"])
        self.assertEqual(todo["status"], STATUS_DONE)
        self.assertIn("무효로 닫음", todo["note"])

    def test_todo_demotes(self):
        stale_judge.run(self.con, judge=fixed(VERDICT_TODO))
        todo = todo_repo.get(self.con, self.todo["id"])
        self.assertEqual(todo["status"], STATUS_TODO)
        self.assertIsNone(todo["completed_at"])
        self.assertIn("대기로 되돌림", todo["note"])

    def test_low_confidence_changes_nothing_but_is_recorded(self):
        low = STALE_JUDGE_MIN_CONFIDENCE - 0.1
        report = stale_judge.run(self.con, judge=fixed(VERDICT_DONE, confidence=low))
        todo = todo_repo.get(self.con, self.todo["id"])
        self.assertEqual(todo["status"], STATUS_DOING)
        self.assertEqual(todo["note"], "처음 적은 맥락")
        self.assertFalse(report["results"][0]["applied"])
        self.assertEqual(judgment_repo.recent(self.con)[0]["verdict"], VERDICT_DONE)

    def test_keep_records_only(self):
        stale_judge.run(self.con, judge=fixed(VERDICT_KEEP, confidence=0.95))
        self.assertEqual(todo_repo.get(self.con, self.todo["id"])["status"], STATUS_DOING)
        self.assertEqual(len(judgment_repo.recent(self.con)), 1)

    def test_dry_run_writes_nothing(self):
        report = stale_judge.run(self.con, dry_run=True, judge=fixed(VERDICT_DONE))
        self.assertEqual(report["results"][0]["status"], STATUS_DONE)
        self.assertEqual(todo_repo.get(self.con, self.todo["id"])["status"], STATUS_DOING)
        self.assertEqual(judgment_repo.recent(self.con), [])

    def test_limit_caps_model_calls(self):
        self._doing("둘째", days=OLD_DAYS)
        judge = fixed(VERDICT_KEEP)
        stale_judge.run(self.con, limit=1, judge=judge)
        self.assertEqual(len(judge.seen), 1)


class Evidence(StaleCase):
    def test_collects_sessions_transcript_and_worktrees(self):
        root = tempfile.mkdtemp()
        os.makedirs(os.path.join(root, "proj"))
        with open(os.path.join(root, "proj", f"{SID}.jsonl"), "w") as handle:
            for role, text in (("user", "병합해줘"), ("assistant", "병합 끝났어")):
                handle.write(json.dumps({
                    "type": role, "message": {"role": role, "content": text},
                }) + "\n")
        session_repo.register(self.con, SID, cwd="/tmp/x")
        session_repo.link_todo(self.con, SID, self.todo["id"])
        session_repo.set_last_prompt(self.con, SID, "병합해줘")
        session_repo.set_state(self.con, SID, STATE_ENDED)
        branch = f"worktree-todo-{self.todo['id']}-x"
        worktree_repo.remember(self.con, "/tmp/wt", "/tmp/x", branch, "2026-01-01T00:00:00+00:00")
        worktree_repo.mark_merged(self.con, "/tmp/wt", "2026-01-02T00:00:00+00:00", "abc", branch)
        other = todo_repo.create(self.con, "이웃 할일", workspace_id=self.workspace["id"])

        judge = fixed(VERDICT_KEEP)
        stale_judge.run(self.con, judge=judge, root=root)
        facts = judge.seen[0]
        self.assertEqual(facts["sessions"][0]["last_prompt"], "병합해줘")
        self.assertEqual([m["text"] for m in facts["tail"]], ["병합해줘", "병합 끝났어"])
        self.assertEqual(facts["worktrees"][0]["merged_at"], "2026-01-02T00:00:00+00:00")
        self.assertEqual(facts["siblings"][0]["id"], other["id"])
        self.assertEqual(facts["workspace"]["name"], "워크스페이스")
        text = stale_judge.prompt(facts)
        self.assertIn("병합 끝났어", text)
        self.assertIn(branch, text)

    def test_long_note_is_clipped(self):
        todo = dict(self.todo, note="가" * 5000)
        facts = stale_judge.evidence(self.con, todo)
        self.assertLess(len(facts["todo"]["note"]), 5000)


class Parsing(unittest.TestCase):
    def test_reads_object_inside_chatter(self):
        out = stale_judge.parse('판정할게.\n{"verdict": "Done", "confidence": "0.85", "reason": "병합됨"}\n끝')
        self.assertEqual(out, {"verdict": VERDICT_DONE, "confidence": 0.85, "reason": "병합됨"})

    def test_unknown_verdict_or_garbage_becomes_keep(self):
        for text in ("", "그냥 말", '{"verdict": "maybe", "confidence": 1}', "{broken"):
            self.assertEqual(stale_judge.parse(text)["verdict"], VERDICT_KEEP)

    def test_confidence_is_clamped(self):
        self.assertEqual(stale_judge.parse('{"verdict": "todo", "confidence": 7}')["confidence"], 1.0)

    def test_failed_call_is_keep(self):
        out = stale_judge.ask({"todo": {}, "workspace": None, "siblings": [], "sessions": [],
                               "tail": [], "worktrees": []}, claude_bin="/nonexistent/claude")
        self.assertEqual(out["verdict"], VERDICT_KEEP)
        self.assertIn("모델 호출 실패", out["reason"])


if __name__ == "__main__":
    unittest.main()
