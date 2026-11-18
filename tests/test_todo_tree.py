"""할일 트리 — 상위 할일(parent_id) 검증, 확인 대기(review) 상태, 트리 조립, API·CLI"""
import io
import os
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

import dash
import server
from app.constants import (
    DB_PATH_ENV,
    PARENT_CYCLE_MSG,
    SESSION_ID_ENV,
    STATUS_DOING,
    STATUS_DONE,
    STATUS_REVIEW,
    STATUS_TODO,
)
from app import db
from app.db import connect
from app.errors import Validation
from app.repositories import categories as category_repo
from app.repositories import sessions as session_repo
from app.repositories import todos as todo_repo
from app.repositories import workspaces as workspace_repo
from app.services import planning, session_message, todo_tree
from tests.support import temp_db, temp_db_path


class TreeFixture(unittest.TestCase):
    """워크스페이스 없이 — 상위 없는 할일이 트리 하나의 맨 위다(사용자 결정 11-18)"""

    def setUp(self):
        self.con = temp_db()
        self.category = category_repo.list_all(self.con)[0]
        self.space = self._todo("결제 개편", top=True)
        self.other = self._todo("KT 동시성", top=True)

    def _todo(self, title, parent=None, top=False):
        """parent 를 안 주면 결제 개편(self.space) 아래. top 이면 상위 없는 새 트리"""
        if top:
            return todo_repo.create(self.con, title, category_id=self.category["id"])
        return todo_repo.create(self.con, title, parent_id=(parent or self.space)["id"])

    def _step(self, title, parent, status=STATUS_TODO, mgr_kind=None, mgr_status=None):
        """단계 행(role='step') — 매니저가 만드는 모양 그대로 parent_id·상위 연결로 할일 아래에 붙인다"""
        step = todo_repo.create(self.con, title, parent_id=parent["id"])
        self.con.execute(
            "UPDATE todos SET role='step', status=?, mgr_kind=?, mgr_status=? WHERE id=?",
            (status, mgr_kind, mgr_status, step["id"]),
        )
        self.con.commit()
        return step

    def _reload(self, todo):
        return todo_repo.get(self.con, todo["id"])


class ParentRuleTest(TreeFixture):
    def test_child_takes_category_of_parent(self):
        child = self._todo("API 초안")
        self.assertEqual(child["parent_id"], self.space["id"])
        self.assertEqual(child["category_id"], self.space["category_id"])
        self.assertIsNone(child["workspace_id"])

    def test_parent_from_any_tree_is_allowed(self):
        """워크스페이스 제약은 없다 — 다른 트리의 할일 아래로도 옮길 수 있다"""
        foreign = self._todo("락 재설계", parent=self.other)
        mine = self._todo("설계")
        moved = todo_repo.update(self.con, mine["id"], parent_id=foreign["id"])
        self.assertEqual(moved["parent_id"], foreign["id"])

    def test_top_level_todo_can_get_a_parent(self):
        loose = self._todo("미분류", top=True)
        other_loose = self._todo("미분류 2", top=True)
        moved = todo_repo.update(self.con, loose["id"], parent_id=other_loose["id"])
        self.assertEqual(moved["parent_id"], other_loose["id"])

    def test_self_parent_is_rejected(self):
        root = self._todo("설계")
        with self.assertRaisesRegex(Validation, PARENT_CYCLE_MSG):
            todo_repo.update(self.con, root["id"], parent_id=root["id"])

    def test_descendant_as_parent_is_rejected(self):
        root = self._todo("설계")
        child = self._todo("API", parent=root)
        grandchild = self._todo("엔드포인트", parent=child)
        with self.assertRaisesRegex(Validation, PARENT_CYCLE_MSG):
            todo_repo.update(self.con, root["id"], parent_id=grandchild["id"])
        self.assertEqual(self._reload(root)["parent_id"], self.space["id"])

    def test_reparent_and_lift_to_top(self):
        first = self._todo("설계")
        second = self._todo("구현")
        child = self._todo("API", parent=first)
        moved = todo_repo.update(self.con, child["id"], parent_id=second["id"])
        self.assertEqual(moved["parent_id"], second["id"])
        lifted = todo_repo.update(self.con, child["id"], parent_id=None)
        self.assertIsNone(lifted["parent_id"])

    def test_non_numeric_parent_is_rejected(self):
        root = self._todo("설계")
        with self.assertRaises(Validation):
            todo_repo.update(self.con, root["id"], parent_id="abc")

    def test_delete_lifts_children_one_level(self):
        """가운데를 지우면 그 아래 가지는 지운 할일의 부모에 붙는다 — 사라지지 않는다"""
        root = self._todo("설계")
        middle = self._todo("API", parent=root)
        leaf = self._todo("엔드포인트", parent=middle)
        todo_repo.delete(self.con, middle["id"])
        self.assertEqual(self._reload(leaf)["parent_id"], root["id"])


class ReviewStatusTest(TreeFixture):
    def test_review_is_a_valid_open_status(self):
        todo = todo_repo.update(self.con, self._todo("설계")["id"], status=STATUS_REVIEW)
        self.assertEqual(todo["status"], STATUS_REVIEW)
        self.assertIsNone(todo["completed_at"])

    def test_review_is_not_picked_as_next(self):
        todo_repo.update(self.con, self.other["id"], status=STATUS_DONE)
        waiting = todo_repo.update(self.con, self._todo("확인만 남음")["id"], status=STATUS_REVIEW)
        todo_repo.update(self.con, self.space["id"], status=STATUS_REVIEW)
        fresh = self._todo("새 일")
        picked = planning.next_todo(self.con)
        self.assertEqual(picked["todo"]["id"], fresh["id"])
        self.assertEqual(picked["root"]["id"], self.space["id"])
        self.assertNotIn(waiting["id"], [row["id"] for row in planning.ranked(self.con)])

    def test_linking_session_revives_review_to_doing(self):
        todo = todo_repo.update(self.con, self._todo("설계")["id"], status=STATUS_REVIEW)
        session_repo.register(self.con, "sess-a", cwd="/tmp")
        session_repo.link_todo(self.con, "sess-a", todo["id"])
        self.assertEqual(self._reload(todo)["status"], STATUS_DOING)


class ForestTest(TreeFixture):
    def _tree(self, top=None):
        trees = todo_tree.forest(self.con)["trees"]
        return next(t for t in trees if t["key"] == f"t{(top or self.space)['id']}")

    def _kids(self, top=None):
        return self._tree(top)["children"][0]["children"]

    def test_each_parentless_todo_is_its_own_tree(self):
        lone = self._todo("혼자", top=True)
        tree = self._tree(lone)
        self.assertEqual(tree["name"], "혼자")
        self.assertEqual([node["id"] for node in tree["children"]], [lone["id"]])
        self.assertEqual(tree["category_id"], self.category["id"])
        self.assertEqual(tree["category_name"], self.category["name"])

    def test_nested_children_and_subtree_progress(self):
        root = self._todo("설계")
        child = self._todo("API", parent=root)
        leaf = self._todo("엔드포인트", parent=child)
        todo_repo.update(self.con, leaf["id"], status=STATUS_DONE)
        tree = self._tree()
        node = self._kids()[0]
        self.assertEqual(node["id"], root["id"])
        self.assertEqual(node["children"][0]["children"][0]["id"], leaf["id"])
        # 하위 전체(자식·손자) 중 완료 수. 자기 자신은 세지 않는다
        self.assertEqual(node["progress"], {"done": 1, "total": 2})
        # 트리 진행률은 맨 위 할일까지 센다
        self.assertEqual(tree["progress"], {"done": 1, "total": 4})
        self.assertEqual(tree["counts"][STATUS_TODO], 3)
        self.assertFalse(tree["complete"])

    def test_steps_ride_inside_the_task_and_count_toward_progress(self):
        task = self._todo("열 정리")
        first = self._step("열 추가", task, status=STATUS_DONE)
        second = self._step("정렬 결정", task, mgr_kind="decision", mgr_status="open")
        child = self._todo("하위 할일", parent=task)
        node = self._kids()[0]
        # 단계는 하위 카드가 아니다 — children 에는 하위 할일만
        self.assertEqual([kid["id"] for kid in node["children"]], [child["id"]])
        self.assertEqual([step["id"] for step in node["steps"]], [first["id"], second["id"]])
        self.assertEqual([step["waiting"] for step in node["steps"]], [False, True])
        # 진행률 = 단계 + 하위 할일
        self.assertEqual(node["progress"], {"done": 1, "total": 3})
        # 트리 상태 개수에는 단계가 들지 않는다
        tree = self._tree()
        self.assertEqual(sum(tree["counts"].values()), 3)
        self.assertEqual(tree["waiting"], 1)

    def test_hidden_roles_are_not_in_the_tree(self):
        """role 이 NULL·step 이 아닌 행(매니저 보조 피드백 기록)은 어디에도 없다"""
        note = self._todo("피드백 기록", top=True)
        self.con.execute("UPDATE todos SET role='feedback', status='done' WHERE id=?", (note["id"],))
        self.con.commit()
        keys = [tree["key"] for tree in todo_tree.forest(self.con)["trees"]]
        self.assertNotIn(f"t{note['id']}", keys)

    def test_tree_is_complete_only_when_every_todo_is_done(self):
        child = self._todo("API")
        todo_repo.update(self.con, self.space["id"], status=STATUS_DONE)
        self.assertFalse(self._tree()["complete"])
        todo_repo.update(self.con, child["id"], status=STATUS_DONE)
        self.assertTrue(self._tree()["complete"])

    def test_order_unfinished_then_priority_then_sort_order(self):
        done = self._todo("끝난 트리", top=True)
        todo_repo.update(self.con, done["id"], status=STATUS_DONE)
        todo_repo.update(self.con, self.other["id"], priority=3)
        lone = self._todo("우선순위 없음", top=True)
        keys = [tree["key"] for tree in todo_tree.forest(self.con)["trees"]]
        self.assertEqual(keys[0], f"t{self.other['id']}")
        self.assertLess(keys.index(f"t{self.space['id']}"), keys.index(f"t{lone['id']}"))
        self.assertEqual(keys[-1], f"t{done['id']}")

    def test_waiting_mark_follows_sessions_current_todo(self):
        old = self._todo("지난 일")
        current = self._todo("지금 일")
        session_repo.register(self.con, "sess-a", cwd="/tmp")
        session_repo.link_todo(self.con, "sess-a", old["id"])
        session_repo.link_todo(self.con, "sess-a", current["id"])
        session_repo.set_waiting(self.con, "sess-a", "permission")
        nodes = {node["id"]: node for node in self._kids()}
        self.assertEqual(nodes[current["id"]]["waiting"], "permission")
        self.assertIsNone(nodes[old["id"]]["waiting"])
        self.assertEqual(self._tree()["waiting"], 1)

    def test_last_session_at_is_latest_seen_of_linked_sessions(self):
        """할일별 보기의 정렬 기준 — 세션이 마지막으로 살아 있던 시각"""
        touched = self._todo("잡은 일")
        idle = self._todo("안 잡은 일")
        session_repo.register(self.con, "sess-a", cwd="/tmp")
        session_repo.link_todo(self.con, "sess-a", touched["id"])
        seen = self.con.execute("SELECT last_seen_at FROM sessions WHERE claude_session_id='sess-a'").fetchone()[0]
        nodes = {node["id"]: node for node in self._kids()}
        self.assertEqual(nodes[touched["id"]]["last_session_at"], seen)
        self.assertIsNone(nodes[idle["id"]]["last_session_at"])

    def test_nodes_carry_updated_at_for_recency_order(self):
        """할일은 todos.updated_at, 맥락은 graph_nodes.updated_at. 상위 없는 맥락은 제 트리의 맨 위다"""
        from app.repositories import graph as graph_repo

        todo = self._todo("수정한 일")
        todo_repo.update(self.con, todo["id"], title="제목 고침")
        saved = self._reload(todo)["updated_at"]
        context = graph_repo.create_context(self.con, "배경", category_id=self.category["id"])
        nodes = {node["key"]: node for node in self._kids()}
        self.assertEqual(nodes[f"t{todo['id']}"]["updated_at"], saved)
        trees = todo_tree.forest(self.con)["trees"]
        top = next(tree for tree in trees if tree["key"] == f"c{context['id']}")
        self.assertEqual(top["children"][0]["updated_at"], context["updated_at"])

    def test_broken_parent_links_do_not_hide_todos(self):
        """손으로 고친 DB 의 고리도 어딘가의 맨 위 아래로 올라와 화면에 남는다"""
        first = self._todo("가")
        second = self._todo("나", parent=first)
        self.con.execute("UPDATE edges SET src_id=? WHERE dst_kind='todo' AND dst_id=? AND relation='parent'",
                         (str(second["id"]), str(first["id"])))
        self.con.commit()
        seen = []

        def walk(nodes):
            for node in nodes:
                seen.append(node["id"])
                walk(node["children"])

        for tree in todo_tree.forest(self.con)["trees"]:
            walk(tree["children"])
        self.assertIn(first["id"], seen)
        self.assertIn(second["id"], seen)


class LineageTest(TreeFixture):
    """워크스페이스가 주던 것(작업 위치·맨 위)을 상위 연결로 찾는다 (app/services/lineage.py)"""

    def test_cwd_comes_from_the_nearest_ancestor(self):
        import tempfile
        from app.services import autorun, lineage

        top_dir, mid_dir = tempfile.mkdtemp(), tempfile.mkdtemp()
        todo_repo.update(self.con, self.space["id"], cwd=top_dir)
        middle = self._todo("중간")
        leaf = self._todo("잎", parent=middle)
        self.assertEqual(lineage.nearest_cwd(self.con, self._reload(leaf)), top_dir)
        todo_repo.update(self.con, middle["id"], cwd=mid_dir)
        self.assertEqual(lineage.nearest_cwd(self.con, self._reload(leaf)), mid_dir)
        # 자율 수행의 위치 판정도 같은 답 — 사람이 지정한 위치가 추론보다 먼저다
        self.assertEqual(autorun.target_cwd(self.con, self._reload(leaf)), mid_dir)
        self.assertEqual(autorun.cwd_resolver(self.con)(self._reload(leaf)), mid_dir)
        # 없어진 경로는 건너뛴다
        todo_repo.update(self.con, middle["id"], cwd="/없는/경로")
        self.assertEqual(lineage.nearest_cwd(self.con, self._reload(leaf)), top_dir)

    def test_root_todo_and_tree_members(self):
        from app.services import lineage

        middle = self._todo("중간")
        leaf = self._todo("잎", parent=middle)
        self.assertEqual(lineage.root_todo(self.con, leaf["id"])["id"], self.space["id"])
        self.assertEqual(lineage.root_todo(self.con, self.other["id"])["id"], self.other["id"])
        self.assertEqual(
            lineage.tree_todo_ids(self.con, leaf["id"]), sorted([self.space["id"], middle["id"], leaf["id"]])
        )


class ApiTest(TreeFixture):
    def test_get_trees_and_create_child(self):
        root = self._todo("설계")
        created = server.route(
            self.con, "POST", "/api/todos", {}, {"title": "API", "parent_id": root["id"]}
        )
        self.assertEqual(created["category_id"], self.category["id"])
        payload = server.route(self.con, "GET", "/api/todo-trees", {}, {})
        self.assertIn(STATUS_REVIEW, payload["statuses"])
        tree = next(t for t in payload["trees"] if t["key"] == f"t{self.space['id']}")
        self.assertEqual(tree["children"][0]["children"][0]["children"][0]["id"], created["id"])

    def test_create_top_level_todo_needs_a_category(self):
        created = server.route(
            self.con, "POST", "/api/todos", {}, {"title": "새 트리", "category_id": self.category["id"]}
        )
        self.assertIsNone(created["parent_id"])
        keys = [tree["key"] for tree in server.route(self.con, "GET", "/api/todo-trees", {}, {})["trees"]]
        self.assertIn(f"t{created['id']}", keys)

    def test_patch_parent_and_status(self):
        root = self._todo("설계")
        child = self._todo("API")
        updated = server.route(
            self.con, "PATCH", f"/api/todos/{child['id']}", {}, {"parent_id": root["id"]}
        )
        self.assertEqual(updated["parent_id"], root["id"])
        reviewed = server.route(
            self.con, "PATCH", f"/api/todos/{child['id']}", {}, {"status": STATUS_REVIEW}
        )
        self.assertEqual(reviewed["status"], STATUS_REVIEW)

    def test_workspace_and_board_routes_are_gone(self):
        from app.errors import UnknownEndpoint

        for method, path in (("GET", "/api/workspaces"), ("GET", "/api/tree"), ("POST", "/api/workspaces")):
            with self.subTest(path=path, method=method), self.assertRaises(UnknownEndpoint):
                server.route(self.con, method, path, {}, {})


class CliTest(unittest.TestCase):
    def setUp(self):
        os.environ[DB_PATH_ENV] = temp_db_path()
        os.environ.pop(SESSION_ID_ENV, None)
        patcher = mock.patch.object(session_message, "live_sessions", lambda claude_bin=None: {})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(os.environ.pop, DB_PATH_ENV, None)

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = dash.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_set_parent(self):
        # 할일 준비는 저장소로 — add-workspace·add-todo 명령은 없다
        con = connect()
        space = workspace_repo.create(con, category_repo.get_by_name(con, "개발")["id"], "결제 개편")
        todo_repo.create(con, "설계", workspace_id=space["id"])
        todo_repo.create(con, "구현", workspace_id=space["id"])
        todo_repo.create(con, "API", parent_id=1)
        code, out, _ = self.run_cli("set-parent", "3", "2")
        self.assertEqual(code, 0)
        self.assertIn("#2", out)
        code, out, _ = self.run_cli("set-parent", "3", "none")
        self.assertEqual(code, 0)
        self.assertIn("워크스페이스 바로 아래", out)
        code, _, err = self.run_cli("set-parent", "1", "1")
        self.assertNotEqual(code, 0)
        self.assertIn(PARENT_CYCLE_MSG, err)


class MigrationTest(unittest.TestCase):
    def test_old_db_gets_only_a_nullable_parent_column(self):
        """운영 DB 에 붙는 것은 빈 열 하나뿐이다 — 기존 행·값은 그대로"""
        path = temp_db_path()
        # 이 열을 받기 전의 DB 를 만든다 — 마이그레이션 하나만 빼고 연다
        with mock.patch.object(db, "_add_todo_parent_column", lambda con: None):
            con = connect(path)
        self.assertNotIn(
            "parent_id", {row["name"] for row in con.execute("PRAGMA table_info(todos)")}
        )
        category_id = category_repo.list_all(con)[0]["id"]
        space = workspace_repo.create(con, category_id, "결제 개편")
        con.execute(
            "INSERT INTO todos(category_id, workspace_id, title, status, sort_order,"
            " created_at, updated_at) VALUES(?,?,?,?,?,?,?)",
            (category_id, space["id"], "설계", "doing", 1, "2026-11-01", "2026-11-01"),
        )
        con.commit()
        before = dict(con.execute("SELECT * FROM todos").fetchone())
        tables = sorted(row[0] for row in con.execute("SELECT name FROM sqlite_master"))
        con.close()

        reopened = connect(path)
        columns = {row["name"]: row for row in reopened.execute("PRAGMA table_info(todos)")}
        self.assertIn("parent_id", columns)
        self.assertEqual(columns["parent_id"]["notnull"], 0)
        after = dict(reopened.execute("SELECT * FROM todos").fetchone())
        self.assertIsNone(after.pop("parent_id"))
        self.assertEqual(after, before)
        # 표·색인을 새로 만들지 않는다
        self.assertEqual(
            sorted(row[0] for row in reopened.execute("SELECT name FROM sqlite_master")), tables
        )


if __name__ == "__main__":
    unittest.main()
