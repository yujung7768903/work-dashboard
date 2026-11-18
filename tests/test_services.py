import unittest
from datetime import datetime, timedelta, timezone

from app.constants import (
    OUTCOME_REVIEW,
    STATE_ENDED,
    STATUS_DOING,
    STATUS_DONE,
    UNASSIGNED_LABEL,
)
from app.errors import Validation
from app.repositories import autorun as autorun_repo
from app.repositories import categories as category_repo
from app.repositories import sessions as session_repo
from app.repositories import todos as todo_repo
from app.repositories import workspaces as workspace_repo
from app.services import board, planning
from tests.support import temp_db

INACTIVE = "inactive"
MINE = "sess-mine"
OTHER = "sess-other"


class BoardTreeTest(unittest.TestCase):
    def setUp(self):
        self.con = temp_db()
        self.dev = category_repo.get_by_name(self.con, "개발")["id"]
        self.ops = category_repo.get_by_name(self.con, "운영")["id"]
        self.kt = workspace_repo.create(self.con, self.dev, "KT 동시성")
        self.empty = workspace_repo.create(self.con, self.dev, "빈 워크스페이스")
        self.todo = todo_repo.create(self.con, "락 재설계", workspace_id=self.kt["id"])
        todo_repo.create(self.con, "문의 회신", category_id=self.ops)

    def _names(self, group_by):
        return [group["name"] for group in board.tree(self.con, group_by)["groups"]]

    def test_rejects_unknown_group_by(self):
        with self.assertRaises(Validation):
            board.tree(self.con, "priority")

    def test_workspace_grouping_shows_empty_workspace(self):
        """할일 0개여도 카드가 떠야 거기에 할일을 추가할 수 있다"""
        self.assertIn(self.empty["name"], self._names(board.GROUP_BY_WORKSPACE))

    def test_workspace_grouping_includes_unassigned_last(self):
        self.assertEqual(self._names(board.GROUP_BY_WORKSPACE)[-1], UNASSIGNED_LABEL)

    def test_unassigned_group_shown_even_when_empty(self):
        con = temp_db()
        groups = board.tree(con, board.GROUP_BY_WORKSPACE)["groups"]
        self.assertEqual([group["name"] for group in groups], [UNASSIGNED_LABEL])

    def test_workspace_group_carries_category_name(self):
        group = board.tree(self.con, board.GROUP_BY_WORKSPACE)["groups"][0]
        self.assertEqual(group["category_name"], "개발")

    def test_workspace_group_carries_category_id_and_color(self):
        """보드가 카드 상단 색과 카테고리 라벨 필터에 쓰는 값들"""
        group = board.tree(self.con, board.GROUP_BY_WORKSPACE)["groups"][0]
        dev = category_repo.get_by_name(self.con, "개발")
        self.assertEqual(group["category_id"], dev["id"])
        self.assertEqual(group["category_color"], dev["color"])

    def test_unassigned_group_has_no_category_color(self):
        """미분류는 색을 받지 않고 화면에서 옅은 회색 기본값으로 그려짐"""
        group = board.tree(self.con, board.GROUP_BY_WORKSPACE)["groups"][-1]
        self.assertEqual(group["kind"], board.KIND_UNASSIGNED)
        self.assertIsNone(group.get("category_color"))

    def test_todos_default_to_not_autorun_locked(self):
        group = board.tree(self.con, board.GROUP_BY_WORKSPACE)["groups"][0]
        self.assertFalse(group["todos"][0]["autorun_locked"])

    def test_todo_pending_review_is_autorun_locked(self):
        run = autorun_repo.start_run(self.con, self.todo["id"], "sess", "job")
        autorun_repo.close_run(self.con, run["id"], OUTCOME_REVIEW)
        group = board.tree(self.con, board.GROUP_BY_WORKSPACE)["groups"][0]
        todo = next(t for t in group["todos"] if t["id"] == self.todo["id"])
        self.assertTrue(todo["autorun_locked"])

    def test_counts_reflect_done_state(self):
        todo_repo.update(self.con, self.todo["id"], status=STATUS_DONE)
        group = board.tree(self.con, board.GROUP_BY_WORKSPACE)["groups"][0]
        self.assertEqual((group["done_count"], group["total_count"]), (1, 1))

    def test_category_grouping_includes_unassigned_todos(self):
        titles = [
            todo["title"]
            for group in board.tree(self.con, board.GROUP_BY_CATEGORY)["groups"]
            for todo in group["todos"]
        ]
        self.assertIn("문의 회신", titles)

    def test_category_grouping_hides_empty_categories(self):
        self.assertEqual(sorted(self._names(board.GROUP_BY_CATEGORY)), ["개발", "운영"])


class PlanningTest(unittest.TestCase):
    """트리(상위 없는 할일 하나와 그 아래) 순서대로 — 안 끝난 트리, 맨 위 우선순위, sort_order"""

    def setUp(self):
        self.con = temp_db()
        self.dev = category_repo.get_by_name(self.con, "개발")["id"]
        self.ops = category_repo.get_by_name(self.con, "운영")["id"]
        self.first = todo_repo.create(self.con, "KT 동시성", category_id=self.dev)
        self.second = todo_repo.create(self.con, "헤르메스 테스트", category_id=self.dev)
        # 두 맨 위 할일은 할일이 아니라 묶음처럼 쓴다 — 확인 대기면 후보가 아니다
        for top in (self.first, self.second):
            todo_repo.update(self.con, top["id"], status="review")

    def _under(self, title, top):
        return todo_repo.create(self.con, title, parent_id=top["id"])

    def test_returns_none_when_nothing_to_do(self):
        self.assertIsNone(planning.next_todo(self.con))

    def test_picks_first_tree_first_todo(self):
        self._under("락 재설계", self.first)
        self._under("시나리오 정리", self.second)
        picked = planning.next_todo(self.con)
        self.assertEqual(picked["todo"]["title"], "락 재설계")
        self.assertEqual(picked["root"]["title"], "KT 동시성")
        self.assertIsNone(picked["workspace"])

    def test_higher_priority_tree_goes_first(self):
        self._under("락 재설계", self.first)
        self._under("시나리오 정리", self.second)
        todo_repo.update(self.con, self.second["id"], priority=2)
        self.assertEqual(planning.next_todo(self.con)["todo"]["title"], "시나리오 정리")

    def test_doing_beats_todo_within_tree(self):
        self._under("먼저 등록", self.first)
        started = self._under("벌여둔 것", self.first)
        todo_repo.update(self.con, started["id"], status=STATUS_DOING)
        self.assertEqual(planning.next_todo(self.con)["todo"]["title"], "벌여둔 것")

    def test_skips_done_todos(self):
        finished = self._under("끝난 것", self.first)
        todo_repo.update(self.con, finished["id"], status=STATUS_DONE)
        self._under("남은 것", self.first)
        self.assertEqual(planning.next_todo(self.con)["todo"]["title"], "남은 것")

    def test_parentless_todo_is_its_own_tree(self):
        lone = todo_repo.create(self.con, "문의 회신", category_id=self.ops)
        picked = planning.next_todo(self.con)
        self.assertEqual(picked["todo"]["title"], "문의 회신")
        self.assertEqual(picked["root"]["id"], lone["id"])

    def test_steps_and_hidden_rows_are_not_candidates(self):
        task = self._under("열 정리", self.first)
        todo_repo.update(self.con, task["id"], status="review")
        step = self._under("셀 수정", task)
        note = todo_repo.create(self.con, "피드백 기록", category_id=self.ops)
        self.con.execute("UPDATE todos SET role='step' WHERE id=?", (step["id"],))
        self.con.execute("UPDATE todos SET role='feedback' WHERE id=?", (note["id"],))
        self.con.commit()
        self.assertIsNone(planning.next_todo(self.con))
        self.assertEqual(planning.ranked(self.con), [])

    def test_workspace_argument_is_ignored(self):
        """옛 CLI 가 넘기는 워크스페이스 id 는 무시한다 — 워크스페이스는 없어졌다"""
        self._under("락 재설계", self.first)
        self.assertEqual(planning.next_todo(self.con, 999)["todo"]["title"], "락 재설계")

    def test_ranked_carries_root_title(self):
        under = self._under("락 재설계", self.first)
        lone = todo_repo.create(self.con, "혼자", category_id=self.ops)
        rows = {row["id"]: row for row in planning.ranked(self.con)}
        self.assertEqual(rows[under["id"]]["root_title"], "KT 동시성")
        self.assertEqual(rows[under["id"]]["root_id"], self.first["id"])
        self.assertIsNone(rows[lone["id"]]["root_title"], "자기 자신이 맨 위면 트리 이름이 없다")

    def test_skips_todo_claimed_by_another_active_session(self):
        theirs = todo_repo.create(self.con, "남이 잡은 것", parent_id=self.first["id"])
        mine = todo_repo.create(self.con, "내 것", parent_id=self.first["id"])
        session_repo.register(self.con, OTHER)
        session_repo.link_todo(self.con, OTHER, theirs["id"])
        picked = planning.next_todo(self.con, claude_session_id=MINE)
        self.assertEqual(picked["todo"]["id"], mine["id"])

    def test_own_claimed_todo_comes_first(self):
        todo_repo.create(self.con, "먼저 등록", parent_id=self.first["id"])
        mine = todo_repo.create(self.con, "내가 잡은 것", parent_id=self.first["id"])
        session_repo.register(self.con, MINE)
        session_repo.link_todo(self.con, MINE, mine["id"])
        picked = planning.next_todo(self.con, claude_session_id=MINE)
        self.assertEqual(picked["todo"]["id"], mine["id"])

    def test_todo_of_ended_session_returns_to_pool(self):
        todo = todo_repo.create(self.con, "남기고 끝난 것", parent_id=self.first["id"])
        session_repo.register(self.con, OTHER)
        session_repo.link_todo(self.con, OTHER, todo["id"])
        session_repo.set_state(self.con, OTHER, STATE_ENDED)
        picked = planning.next_todo(self.con, claude_session_id=MINE)
        self.assertEqual(picked["todo"]["id"], todo["id"])

    def test_stale_doing_lists_only_old_ones(self):
        old = todo_repo.create(self.con, "오래 붙잡은 것", parent_id=self.first["id"])
        fresh = todo_repo.create(self.con, "방금 시작", parent_id=self.first["id"])
        for todo in (old, fresh):
            todo_repo.update(self.con, todo["id"], status=STATUS_DOING)
        self._age(old["id"], planning.STALE_DOING_HOURS + 1)
        self.assertEqual([row["id"] for row in planning.stale_doing(self.con)], [old["id"]])

    def _age(self, todo_id, hours):
        stamp = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat(
            timespec="seconds"
        )
        self.con.execute("UPDATE todos SET updated_at=? WHERE id=?", (stamp, todo_id))
        self.con.commit()

    def test_done_on_attaches_root_title(self):
        finished = self._under("락", self.first)
        todo_repo.update(self.con, finished["id"], status=STATUS_DONE)
        rows = planning.done_on(self.con, planning.today_text())
        self.assertEqual(rows[0]["root_title"], "KT 동시성")
        self.assertEqual(rows[0]["workspace_name"], "KT 동시성", "옛 CLI 용 별칭")

    def test_done_on_skips_hidden_rows(self):
        note = todo_repo.create(self.con, "피드백 기록", category_id=self.ops)
        todo_repo.update(self.con, note["id"], status=STATUS_DONE)
        self.con.execute("UPDATE todos SET role='feedback' WHERE id=?", (note["id"],))
        self.con.commit()
        self.assertEqual(planning.done_on(self.con, planning.today_text()), [])

    def test_done_on_excludes_other_dates(self):
        finished = todo_repo.create(self.con, "락", parent_id=self.first["id"])
        todo_repo.update(self.con, finished["id"], status=STATUS_DONE)
        self.assertEqual(planning.done_on(self.con, "2020-01-01"), [])

    def test_done_on_labels_unassigned(self):
        finished = todo_repo.create(self.con, "문의", category_id=self.ops)
        todo_repo.update(self.con, finished["id"], status=STATUS_DONE)
        rows = planning.done_on(self.con, planning.today_text())
        self.assertEqual(rows[0]["root_title"], UNASSIGNED_LABEL)
