"""매니저 spawn 이 띄운 세션 — 할일을 바로 만들어 수행으로 잇고, 원래 세션 할일을 상위(계기) 제안으로,
임시 자리에 만든 할일은 세션이 분류할 때 따라간다"""
import unittest

from app.constants import (
    BY_SPAWN,
    EDGE_PROPOSED,
    REL_PARENT,
    SPAWN_FALLBACK_CATEGORY,
    SPAWN_TODO_MARK,
    STATUS_DOING,
)
from app.repositories import categories as category_repo
from app.repositories import graph as graph_repo
from app.repositories import sessions as session_repo
from app.repositories import todos as todo_repo
from app.repositories import workspaces as workspace_repo
from app.services import manager_links, spawn_link
from tests.support import temp_db


class SpawnLinkTest(unittest.TestCase):
    def setUp(self):
        self.con = temp_db()
        self.category = category_repo.list_all(self.con)[0]
        self.space = workspace_repo.create(self.con, self.category["id"], "통합DB")

    def _origin(self):
        todo = todo_repo.create(self.con, "사진 분석", workspace_id=self.space["id"])
        session_repo.register(self.con, "origin-1", cwd="/tmp")
        session_repo.link_todo(self.con, "origin-1", todo["id"])
        return todo

    def test_spawn_creates_todo_in_origin_workspace_with_proposed_parent(self):
        origin = self._origin()
        todo = spawn_link.on_spawn(self.con, "spawned-1", "보조4 | 필터 원인", "origin-1", 161, "자료ID 6674783")
        self.assertEqual(todo["title"], "필터 원인")
        self.assertEqual(todo["workspace_id"], self.space["id"])
        self.assertEqual(todo["status"], STATUS_DOING)
        self.assertTrue(todo["note"].startswith(SPAWN_TODO_MARK))
        self.assertIn("매니저 할일 161", todo["note"])
        self.assertEqual(session_repo.linked_todo_ids(self.con, "spawned-1"), [todo["id"]])
        edges = [e for e in graph_repo.list_edges(self.con, relations=(REL_PARENT,)) if e["created_by"] == BY_SPAWN]
        self.assertEqual(len(edges), 1)
        self.assertEqual((edges[0]["src_id"], edges[0]["dst_id"], edges[0]["state"]),
                         (str(origin["id"]), str(todo["id"]), EDGE_PROPOSED))

    def test_spawn_without_origin_goes_to_fallback_category_and_follows_classification(self):
        category_repo.create(self.con, SPAWN_FALLBACK_CATEGORY)
        todo = spawn_link.on_spawn(self.con, "spawned-2", "보조1 | 팀즈 문의 확인", None, 166, "한국일보 체크 시 미노출")
        fallback = category_repo.get_by_name(self.con, SPAWN_FALLBACK_CATEGORY)
        self.assertEqual((todo["workspace_id"], todo["category_id"]), (None, fallback["id"]))
        self.assertIn(spawn_link.PROVISIONAL_LINE, todo["note"])
        # 세션이 워크스페이스로 분류하면 임시 할일만 따라간다
        self.assertEqual(spawn_link.follow_classification(self.con, "spawned-2", None, self.space["id"]), [todo["id"]])
        moved = todo_repo.get(self.con, todo["id"])
        self.assertEqual(moved["workspace_id"], self.space["id"])
        self.assertNotIn(spawn_link.PROVISIONAL_LINE, moved["note"])
        # 한 번 자리를 잡으면 다시 분류해도 옮기지 않는다
        other = workspace_repo.create(self.con, self.category["id"], "다른 일")
        self.assertEqual(spawn_link.follow_classification(self.con, "spawned-2", None, other["id"]), [])

    def test_category_only_classification_moves_category(self):
        # 임시 카테고리가 지워졌으면 맨 앞 카테고리 — 할일은 카테고리 없이 만들 수 없다
        todo = spawn_link.on_spawn(self.con, "spawned-3", "보조2 | 로그 확인")
        self.assertEqual(todo["category_id"], self.category["id"])
        target = category_repo.list_all(self.con)[1]
        spawn_link.follow_classification(self.con, "spawned-3", target["id"])
        self.assertEqual(todo_repo.get(self.con, todo["id"])["category_id"], target["id"])

    def test_session_that_already_holds_a_todo_gets_no_new_one(self):
        self._origin()
        mine = todo_repo.create(self.con, "이미 잡은 일", workspace_id=self.space["id"])
        session_repo.register(self.con, "spawned-4", cwd="/tmp")
        session_repo.link_todo(self.con, "spawned-4", mine["id"])
        before = self.con.execute("SELECT COUNT(*) FROM todos").fetchone()[0]
        todo = spawn_link.on_spawn(self.con, "spawned-4", "보조3 | 일", "origin-1", 1)
        self.assertEqual(todo["id"], mine["id"])
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM todos").fetchone()[0], before)
        # 출처는 남아 이미 잡은 할일에도 상위 제안이 붙는다
        self.assertTrue(any(e["created_by"] == BY_SPAWN for e in graph_repo.list_edges(self.con)))

    def test_ordinary_todos_do_not_follow_classification(self):
        loose = todo_repo.create(self.con, "보통 할일", category_id=self.category["id"])
        session_repo.register(self.con, "sess", cwd="/tmp")
        session_repo.link_todo(self.con, "sess", loose["id"])
        self.assertEqual(spawn_link.follow_classification(self.con, "sess", None, self.space["id"]), [])
        self.assertIsNone(todo_repo.get(self.con, loose["id"])["workspace_id"])

    def test_manager_tab_strips_the_new_spawn_paragraph(self):
        self.assertIn("DASH_TODO", manager_links.SPAWN_SUFFIXES)


class UnifiedSpawnTest(unittest.TestCase):
    """할일 통합 뒤 — 매니저 할일에서 띄운 보조 세션의 일은 새 할일이 아니라 그 할일의 단계다"""

    def setUp(self):
        from app.db import UNIFIED_FLAG, meta_set

        self.con = temp_db()
        meta_set(self.con, UNIFIED_FLAG)
        self.category = category_repo.list_all(self.con)[0]
        self.task = todo_repo.create(self.con, "KT 락 방식", category_id=self.category["id"])
        self.con.execute("UPDATE todos SET mgr_kind='decision', mgr_status='open' WHERE id=?", (self.task["id"],))
        self.con.commit()

    def _count(self):
        return self.con.execute("SELECT COUNT(*) FROM todos").fetchone()[0]

    def test_spawn_with_manager_task_makes_a_step_under_that_task(self):
        before = self._count()
        step = spawn_link.on_spawn(self.con, "helper-1", "보조2 | 락 구현", None, self.task["id"], "낙관적 락")
        self.assertEqual(self._count(), before + 1)
        self.assertEqual((step["title"], step["role"], step["parent_id"]), ("락 구현", "step", self.task["id"]))
        self.assertEqual(step["category_id"], self.category["id"])
        self.assertEqual(session_repo.linked_todo_ids(self.con, "helper-1"), [step["id"]])
        parents = [e for e in graph_repo.list_edges(self.con, relations=(REL_PARENT,))
                   if e["dst_id"] == str(step["id"]) and e["src_id"] == str(self.task["id"])]
        self.assertEqual(len(parents), 1)

    def test_manager_task_that_is_a_step_uses_its_parent_task(self):
        first = spawn_link.on_spawn(self.con, "helper-1", "보조2 | 락 구현", None, self.task["id"])
        second = spawn_link.on_spawn(self.con, "helper-2", "보조3 | 락 테스트", None, first["id"])
        self.assertEqual((second["role"], second["parent_id"]), ("step", self.task["id"]))

    def test_unknown_manager_task_falls_back_to_new_todo(self):
        todo = spawn_link.on_spawn(self.con, "helper-3", "보조1 | 다른 일", None, 99999)
        self.assertIsNone(todo["role"])
        self.assertIsNone(todo["parent_id"])

    def test_before_unification_keeps_creating_a_new_todo(self):
        con = temp_db()
        category = category_repo.list_all(con)[0]
        task = todo_repo.create(con, "매니저 할일 id 와 우연히 같은 할일", category_id=category["id"])
        todo = spawn_link.on_spawn(con, "helper-4", "보조1 | 일", None, task["id"])
        self.assertNotEqual(todo["id"], task["id"])
        self.assertIsNone(todo["role"])


if __name__ == "__main__":
    unittest.main()
