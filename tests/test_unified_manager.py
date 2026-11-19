"""할일 통합 뒤(meta unified_todos) — 매니저 탭·할일 상세가 대시보드 todos(뷰 manager_tasks)를 읽고,
단계 행(role='step')을 할일의 진행 단계로 보이며, 후보 할일은 기다리는 할일을 빼고 고른다"""
import tempfile
import unittest
from datetime import datetime, timezone
from unittest import mock

from app.constants import EDGE_CONFIRMED, NODE_TODO, REL_PRECEDES
from app.db import ROLE_STEP, UNIFIED_FLAG, meta_set
from app.repositories import categories as category_repo
from app.repositories import graph as graph_repo
from app.repositories import sessions as session_repo
from app.repositories import todos as todo_repo
from app.services import candidates, decision_answer, manager_links, manager_panel, task_steps
from tests.support import temp_db

NOW = datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc)
STAMP = "2026-11-18T10:00:00"


class Fixture(unittest.TestCase):
    def setUp(self):
        self.con = temp_db()
        meta_set(self.con, UNIFIED_FLAG)
        self.category = category_repo.list_all(self.con)[0]
        # 매니저 DB 가 없는 매니저 레포 — 통합 뒤에는 읽지 않아야 한다
        self.home = tempfile.mkdtemp()

    def todo(self, title, priority=None, status="todo", **mgr):
        row = todo_repo.create(self.con, title, category_id=self.category["id"])
        sets = {"status": status, "priority": priority}
        for key, value in mgr.items():
            sets[key if key in ("role", "parent_id", "step_by", "step_result", "step_unblock", "completed_at")
                 else f"mgr_{key}"] = value
        if mgr and "kind" in mgr:
            sets.setdefault("mgr_created_at", STAMP)
            sets.setdefault("mgr_updated_at", STAMP)
        assignments = ", ".join(f"{key}=?" for key in sets)
        self.con.execute(f"UPDATE todos SET {assignments} WHERE id=?", (*sets.values(), row["id"]))
        self.con.commit()
        return row["id"]

    def step(self, task_id, title, status="todo", **mgr):
        return self.todo(title, status=status, role=ROLE_STEP, parent_id=task_id, **mgr)


class UnifiedPanelTest(Fixture):
    def test_manager_tab_reads_dashboard_view_not_manager_db(self):
        decision = self.todo("락 방식", 3, kind="decision")
        self.con.execute("UPDATE todos SET mgr_status='open' WHERE id=?", (decision,))
        blocked = self.todo("로그인", 2, kind="action", blocked="permission", session_id="s-perm")
        self.con.execute("UPDATE todos SET mgr_status='open' WHERE id=?", (blocked,))
        prereq = self.todo("선행 남음", 2, kind="action", after_ids=str(decision))
        self.con.execute("UPDATE todos SET mgr_status='open' WHERE id=?", (prereq,))
        confirm = self.todo("확인 대기", 2, kind="action")
        self.con.execute("UPDATE todos SET mgr_status='confirm' WHERE id=?", (confirm,))
        self.con.commit()
        ids = lambda items: [item["id"] for item in items]  # noqa: E731
        self.assertEqual(ids(manager_panel.decisions(NOW, manager_home=self.home, con=self.con)), [decision])
        # 권한 대기 목록은 매니저(권한대기 --json)가 고른다 — 그 할일 줄은 통합 테이블에서 읽는다
        waits = lambda _home: [{"source": "task", "task_id": blocked, "session_id": "s-perm"}]  # noqa: E731
        self.assertEqual(ids(manager_panel.permissions(NOW, manager_home=self.home, con=self.con, waits_fn=waits)),
                         [blocked])
        self.assertEqual(ids(manager_panel.waits(NOW, manager_home=self.home, con=self.con)), [prereq])
        self.assertEqual(ids(manager_panel.confirms(NOW, manager_home=self.home, con=self.con)), [confirm])
        item = manager_panel.task_item(prereq, NOW, manager_home=self.home, con=self.con)
        self.assertEqual(item["prereqs"], [{"id": decision, "title": "락 방식", "status": "open", "finished": False}])
        self.assertEqual(manager_links.permission_sessions(self.home, self.con), frozenset({"s-perm"}))

    def test_without_flag_keeps_legacy_manager_db(self):
        con = temp_db()
        with self.assertRaises(FileNotFoundError):
            manager_panel.decisions(NOW, manager_home=self.home, con=con)
        self.assertFalse(manager_links.unified(con))
        self.assertFalse(manager_links.unified(None))

    def test_step_decision_shows_task_title_and_task_steps(self):
        task = self.todo("KT 락", 3)
        done = self.step(task, "조사", status="done", step_by="보조1", step_result="후보 2개",
                         completed_at="2026-11-18T01:00:00Z")
        ask = self.step(task, "방식 결정", status="doing", kind="decision", step_unblock="A·B 고르기")
        self.con.execute("UPDATE todos SET mgr_status='open' WHERE id=?", (ask,))
        self.con.commit()
        [item] = manager_panel.decisions(NOW, manager_home=self.home, con=self.con)
        self.assertEqual(item["title"], "KT 락 › 방식 결정")
        self.assertEqual([(s["id"], s["status"]) for s in item["steps"]], [(done, "done"), (ask, "current")])
        self.assertEqual((item["steps"][0]["by"], item["steps"][0]["result"]), ("보조1", "후보 2개"))
        self.assertEqual(item["steps"][1]["unblock"], "A·B 고르기")


class TaskStepsTest(Fixture):
    def test_timeline_marks_one_current_preferring_the_asking_step(self):
        task = self.todo("일")
        doing = self.step(task, "구현", status="doing")
        asking = self.step(task, "확인", kind="action")
        self.con.execute("UPDATE todos SET mgr_status='confirm' WHERE id=?", (asking,))
        self.con.commit()
        steps = task_steps.timeline(self.con, task)
        self.assertEqual([(s["id"], s["status"], s["ask"]) for s in steps],
                         [(doing, "todo", None), (asking, "current", "confirm")])

    def test_timeline_follows_the_shown_dates(self):
        """끝난 단계는 보이는 날짜(끝난 시각) 순, 안 끝난 단계는 그 아래 생긴 시각 순(사용자 지적 11-19).
        11-16 에 생겨 11-18 에 끝난 단계가 11-16 줄 사이에 끼지 않고, 멈춘 단계가 가운데 남지 않는다. sort_order 는 믿지 않는다"""
        task = self.todo("분석")
        late = self.step(task, "결론 문서", status="done", completed_at="2026-11-18T03:00:00+00:00")
        # 먼저 생겼지만 늦게 끝난 단계 — 끝난 날짜 자리(11-17)로 간다
        slow = self.step(task, "오래 걸린 조회", status="done", completed_at="2026-11-17T12:00:00+09:00")
        asking = self.step(task, "수정 범위 결정", status="doing", kind="decision")
        early = self.step(task, "조회", status="done", completed_at="2026-11-16T02:00:00+00:00")
        tie = self.step(task, "조회 결과 정리", status="done", completed_at="2026-11-16T01:30:00+00:00")
        no_time = self.step(task, "시각 없음")
        for ident, created, order in ((late, "2026-11-18T01:00:00+00:00", 1), (asking, "2026-11-16T09:00:00+00:00", 2),
                                      (early, "2026-11-16T01:00:00+00:00", 3), (tie, "2026-11-16T01:00:00+00:00", 4),
                                      (no_time, "", 5), (slow, "2026-11-15T00:00:00Z", 6)):
            self.con.execute("UPDATE todos SET created_at=?, sort_order=? WHERE id=?", (created, order, ident))
        self.con.execute("UPDATE todos SET mgr_status='open' WHERE id=?", (asking,))
        self.con.commit()
        steps = task_steps.timeline(self.con, task)
        self.assertEqual([(s["id"], s["status"]) for s in steps],
                         [(tie, "done"), (early, "done"), (slow, "done"), (late, "done"), (asking, "current"),
                          (no_time, "todo")])

    def test_step_names_drop_helper_session_numbers(self):
        task = self.todo("통합DB 사진 노출 원인 분석 (11-16 보조2·5·1)")
        a = self.step(task, "보조2 | 외신 사진 비교")
        b = self.step(task, "필터를 풀면 안 보이는 원인 (보조4)")
        c = self.step(task, "M365 인증이 보조3 세션에 반영 안 됨")
        d = self.step(task, "보조 세션 허용 목록에 progress 추가")
        names = {s["id"]: s["name"] for s in task_steps.timeline(self.con, task)}
        self.assertEqual([names[a], names[b], names[c], names[d]],
                         ["외신 사진 비교", "필터를 풀면 안 보이는 원인", "M365 인증이 보조 세션에 반영 안 됨",
                          "보조 세션 허용 목록에 progress 추가"])
        self.assertEqual(task_steps.plain("11-16 보조5 가 팀즈로 결론을 냄 — 보조1 이 확인"),
                         "11-16 보조가 팀즈로 결론을 냄 — 보조가 확인")
        item = task_steps.with_task(self.con, {"id": b, "title": "필터를 풀면 안 보이는 원인 (보조4)"})
        self.assertEqual(item["title"], "통합DB 사진 노출 원인 분석 › 필터를 풀면 안 보이는 원인")

    def test_no_steps_before_unification(self):
        con = temp_db()
        task = todo_repo.create(con, "일", category_id=category_repo.list_all(con)[0]["id"])
        self.assertEqual(task_steps.timeline(con, task["id"]), [])
        self.assertEqual(task_steps.with_task(con, {"id": task["id"], "title": "일"})["title"], "일")

    def test_todo_detail_collects_step_decisions_and_timeline(self):
        task = self.todo("KT 락", 3)
        ask = self.step(task, "방식 결정", status="doing", kind="decision")
        self.con.execute("UPDATE todos SET mgr_status='open' WHERE id=?", (ask,))
        self.con.commit()
        rows = [{"id": ask, "title": "방식 결정", "kind": "decision", "status": "open", "session_id": "elsewhere",
                 "options": [], "priority": 2, "created_at": STAMP}]
        with mock.patch.object(decision_answer, "_call", return_value=rows):
            payload = decision_answer.for_todo(self.con, task)
        [item] = payload["items"]
        self.assertEqual((item["id"], item["title"]), (ask, "KT 락 › 방식 결정"))
        self.assertEqual([s["status"] for s in payload["steps"]], ["current"])


class CandidatesTest(Fixture):
    def test_picks_top_three_ready_tasks_and_counts_waiting(self):
        low = self.todo("낮음", 1)
        none = self.todo("우선순위 없음")
        top = self.todo("높음", 5, status="doing")
        mid = self.todo("중간", 3)
        extra = self.todo("중간 둘째", 3)
        self.todo("끝남", 9, status="done")
        # 기다리는 할일 — 결정 대기·확인 대기·권한 대기·선행 남음(매니저)·선행 남음(대시보드 연결)·단계가 결정 대기
        decision = self.todo("결정 대기", 9, kind="decision")
        confirm = self.todo("확인 대기", 9, kind="action")
        blocked = self.todo("권한 대기", 9, kind="action", blocked="permission")
        after = self.todo("선행 대기", 9, kind="action", after_ids=str(decision))
        self.con.execute("UPDATE todos SET mgr_status='open' WHERE id IN (?,?,?)", (decision, blocked, after))
        self.con.execute("UPDATE todos SET mgr_status='confirm' WHERE id=?", (confirm,))
        before = self.todo("앞 할일 아직", 0)
        preceded = self.todo("뒤 할일", 9)
        graph_repo.add_edge(self.con, (NODE_TODO, str(before)), (NODE_TODO, str(preceded)), REL_PRECEDES,
                            state=EDGE_CONFIRMED)
        stepped = self.todo("단계가 결정 대기", 9)
        step = self.step(stepped, "고르기", kind="decision")
        self.con.execute("UPDATE todos SET mgr_status='open' WHERE id=?", (step,))
        self.con.commit()
        result = candidates.snapshot(self.con)
        self.assertEqual([item["id"] for item in result["items"]], [top, mid, extra])
        self.assertEqual(result["waiting"], 6)
        self.assertEqual(result["items"][0]["priority_max"], 9)
        self.assertEqual(result["items"][0]["category_name"], self.category["name"])
        # 단계 행은 후보가 아니고, 끝난 선행은 막지 않는다
        self.con.execute("UPDATE todos SET mgr_status='done' WHERE id=?", (decision,))
        self.con.commit()
        result = candidates.snapshot(self.con, limit=20)
        ids = [item["id"] for item in result["items"]]
        self.assertIn(after, ids)
        self.assertNotIn(step, ids)
        # 할일도 단계도 아닌 행(보조 세션 피드백 기록 role=feedback)은 후보·대기·단계 어디에도 없다
        feedback = self.todo("피드백 기록", 9, role="feedback", kind="feedback", parent_id=stepped)
        self.con.execute("UPDATE todos SET mgr_status='open' WHERE id=?", (feedback,))
        self.con.commit()
        again = candidates.snapshot(self.con, limit=20)
        self.assertNotIn(feedback, [item["id"] for item in again["items"]])
        self.assertEqual(again["waiting"], result["waiting"])
        self.assertNotIn(feedback, [s["id"] for s in task_steps.timeline(self.con, stepped)])
        self.assertEqual(ids[-3:], [low, before, none])

    def test_task_worked_by_live_session_is_not_a_candidate(self):
        busy = self.todo("일하는 중", 5)
        helper_step = self.todo("단계를 일하는 중", 4)
        step = self.step(helper_step, "구현", status="doing")
        free = self.todo("비어 있음", 1)
        session_repo.register(self.con, "live", cwd="/tmp")
        session_repo.link_todo(self.con, "live", busy)
        session_repo.register(self.con, "helper", cwd="/tmp")
        session_repo.link_todo(self.con, "helper", step)
        self.assertEqual([item["id"] for item in candidates.snapshot(self.con)["items"]], [free])

    def test_snapshot_part_carries_waiting(self):
        self.todo("하나", 1)
        section = manager_panel.snapshot("candidates", now=NOW, con=self.con)["candidates"]
        self.assertEqual((len(section["items"]), section["waiting"], section["error"]), (1, 0, None))
        self.assertEqual(candidates.snapshot(None), {"items": [], "waiting": 0})


if __name__ == "__main__":
    unittest.main()
