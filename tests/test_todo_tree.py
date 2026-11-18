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
    PARENT_NEEDS_WORKSPACE_MSG,
    PARENT_OTHER_WORKSPACE_MSG,
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
    def setUp(self):
        self.con = temp_db()
        self.category = category_repo.list_all(self.con)[0]
        self.space = workspace_repo.create(self.con, self.category["id"], "결제 개편")
        self.other = workspace_repo.create(self.con, self.category["id"], "KT 동시성")

    def _todo(self, title, workspace=None, parent=None):
        return todo_repo.create(
            self.con,
            title,
            workspace_id=(workspace or self.space)["id"] if parent is None else None,
            parent_id=parent["id"] if parent else None,
        )

    def _reload(self, todo):
        return todo_repo.get(self.con, todo["id"])


class ParentRuleTest(TreeFixture):
    def test_child_takes_workspace_of_parent(self):
        root = self._todo("설계")
        child = self._todo("API 초안", parent=root)
        self.assertEqual(child["parent_id"], root["id"])
        self.assertEqual(child["workspace_id"], self.space["id"])
        self.assertEqual(child["category_id"], self.space["category_id"])

    def test_existing_todos_stay_directly_under_workspace(self):
        """컬럼이 생겨도 기존 할일은 NULL 이라 지금처럼 워크스페이스 바로 아래다"""
        self.assertIsNone(self._todo("기존 할일")["parent_id"])

    def test_parent_in_other_workspace_is_rejected(self):
        foreign = self._todo("락 재설계", workspace=self.other)
        mine = self._todo("설계")
        with self.assertRaisesRegex(Validation, PARENT_OTHER_WORKSPACE_MSG):
            todo_repo.update(self.con, mine["id"], parent_id=foreign["id"])
        with self.assertRaisesRegex(Validation, PARENT_OTHER_WORKSPACE_MSG):
            todo_repo.create(
                self.con, "섞인 것", workspace_id=self.space["id"], parent_id=foreign["id"]
            )

    def test_unassigned_todo_cannot_have_parent(self):
        loose = todo_repo.create(self.con, "미분류", category_id=self.category["id"])
        other_loose = todo_repo.create(self.con, "미분류 2", category_id=self.category["id"])
        with self.assertRaisesRegex(Validation, PARENT_NEEDS_WORKSPACE_MSG):
            todo_repo.update(self.con, loose["id"], parent_id=other_loose["id"])

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
        self.assertIsNone(self._reload(root)["parent_id"])

    def test_reparent_within_tree_and_back_to_root(self):
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

    def test_moving_to_other_workspace_carries_subtree(self):
        root = self._todo("설계")
        middle = self._todo("API", parent=root)
        leaf = self._todo("엔드포인트", parent=middle)
        todo_repo.update(self.con, middle["id"], workspace_id=self.other["id"])
        moved, carried = self._reload(middle), self._reload(leaf)
        self.assertIsNone(moved["parent_id"])  # 옛 부모는 다른 트리라 루트 바로 아래로
        self.assertEqual(carried["workspace_id"], self.other["id"])
        self.assertEqual(carried["parent_id"], middle["id"])
        self.assertEqual(self._reload(root)["workspace_id"], self.space["id"])

    def test_saving_same_workspace_keeps_parent(self):
        """상세 팝업처럼 같은 워크스페이스를 다시 보내도 부모가 풀리면 안 된다"""
        root = self._todo("설계")
        child = self._todo("API", parent=root)
        todo_repo.update(self.con, child["id"], workspace_id=self.space["id"])
        self.assertEqual(self._reload(child)["parent_id"], root["id"])

    def test_deleting_workspace_flattens_tree(self):
        root = self._todo("설계")
        child = self._todo("API", parent=root)
        workspace_repo.delete(self.con, self.space["id"])
        demoted = self._reload(child)
        self.assertIsNone(demoted["workspace_id"])
        self.assertIsNone(demoted["parent_id"])


class ReviewStatusTest(TreeFixture):
    def test_review_is_a_valid_open_status(self):
        todo = todo_repo.update(self.con, self._todo("설계")["id"], status=STATUS_REVIEW)
        self.assertEqual(todo["status"], STATUS_REVIEW)
        self.assertIsNone(todo["completed_at"])

    def test_review_is_not_picked_as_next(self):
        waiting = todo_repo.update(self.con, self._todo("확인만 남음")["id"], status=STATUS_REVIEW)
        fresh = self._todo("새 일")
        picked = planning.next_todo(self.con, workspace_id=self.space["id"])
        self.assertEqual(picked["todo"]["id"], fresh["id"])
        self.assertNotIn(waiting["id"], [row["id"] for row in planning.ranked(self.con)])

    def test_linking_session_revives_review_to_doing(self):
        todo = todo_repo.update(self.con, self._todo("설계")["id"], status=STATUS_REVIEW)
        session_repo.register(self.con, "sess-a", cwd="/tmp")
        session_repo.link_todo(self.con, "sess-a", todo["id"])
        self.assertEqual(self._reload(todo)["status"], STATUS_DOING)


class ForestTest(TreeFixture):
    def _tree(self, workspace=None):
        trees = todo_tree.forest(self.con)["trees"]
        return next(t for t in trees if t["workspace"]["id"] == (workspace or self.space)["id"])

    def test_nested_children_and_subtree_progress(self):
        root = self._todo("설계")
        child = self._todo("API", parent=root)
        leaf = self._todo("엔드포인트", parent=child)
        todo_repo.update(self.con, leaf["id"], status=STATUS_DONE)
        tree = self._tree()
        node = tree["children"][0]
        self.assertEqual(node["id"], root["id"])
        self.assertEqual(node["children"][0]["children"][0]["id"], leaf["id"])
        # 하위 전체(자식·손자) 중 완료 수. 자기 자신은 세지 않는다
        self.assertEqual(node["progress"], {"done": 1, "total": 2})
        self.assertEqual(tree["progress"], {"done": 1, "total": 3})
        self.assertEqual(tree["counts"][STATUS_TODO], 2)
        self.assertFalse(tree["complete"])

    def test_tree_is_complete_only_when_every_todo_is_done(self):
        root = self._todo("설계")
        child = self._todo("API", parent=root)
        todo_repo.update(self.con, root["id"], status=STATUS_DONE)
        self.assertFalse(self._tree()["complete"])
        todo_repo.update(self.con, child["id"], status=STATUS_DONE)
        self.assertTrue(self._tree()["complete"])

    def test_empty_tree_is_not_complete(self):
        self.assertFalse(self._tree(self.other)["complete"])

    def test_complete_trees_come_last(self):
        done = self._todo("락", workspace=self.other)
        todo_repo.update(self.con, done["id"], status=STATUS_DONE)
        self._todo("설계")
        trees = todo_tree.forest(self.con)["trees"]
        self.assertEqual(trees[-1]["workspace"]["id"], self.other["id"])

    def test_waiting_mark_follows_sessions_current_todo(self):
        old = self._todo("지난 일")
        current = self._todo("지금 일")
        session_repo.register(self.con, "sess-a", cwd="/tmp")
        session_repo.link_todo(self.con, "sess-a", old["id"])
        session_repo.link_todo(self.con, "sess-a", current["id"])
        session_repo.set_waiting(self.con, "sess-a", "permission")
        nodes = {node["id"]: node for node in self._tree()["children"]}
        self.assertEqual(nodes[current["id"]]["waiting"], "permission")
        self.assertIsNone(nodes[old["id"]]["waiting"])
        self.assertEqual(self._tree()["waiting"], 1)

    def test_last_session_at_is_latest_seen_of_linked_sessions(self):
        """할일별 보기의 정렬 기준. 보드 상태별 뷰와 같은 값(세션이 마지막으로 살아 있던 시각)이다"""
        touched = self._todo("잡은 일")
        idle = self._todo("안 잡은 일")
        session_repo.register(self.con, "sess-a", cwd="/tmp")
        session_repo.link_todo(self.con, "sess-a", touched["id"])
        seen = self.con.execute("SELECT last_seen_at FROM sessions WHERE claude_session_id='sess-a'").fetchone()[0]
        nodes = {node["id"]: node for node in self._tree()["children"]}
        self.assertEqual(nodes[touched["id"]]["last_session_at"], seen)
        self.assertIsNone(nodes[idle["id"]]["last_session_at"])

    def test_nodes_carry_updated_at_for_recency_order(self):
        """트리 목록이 '최근 작업·수정 순' 으로 세울 재료. 할일은 todos.updated_at, 맥락은 graph_nodes.updated_at"""
        from app.repositories import graph as graph_repo

        todo = self._todo("수정한 일")
        todo_repo.update(self.con, todo["id"], title="제목 고침")
        saved = self._reload(todo)["updated_at"]
        context = graph_repo.create_context(self.con, "배경", workspace_id=self.space["id"])
        nodes = {node["key"]: node for node in self._tree()["children"]}
        self.assertEqual(nodes[f"t{todo['id']}"]["updated_at"], saved)
        self.assertEqual(nodes[f"c{context['id']}"]["updated_at"], context["updated_at"])

    def test_broken_parent_links_do_not_hide_todos(self):
        """손으로 고친 DB 의 고리·남의 트리 부모도 루트 아래로 올라와 화면에 남는다"""
        first = self._todo("가")
        second = self._todo("나", parent=first)
        foreign = self._todo("다른 트리", workspace=self.other)
        third = self._todo("라")
        self.con.execute("UPDATE todos SET parent_id=? WHERE id=?", (second["id"], first["id"]))
        self.con.execute("UPDATE todos SET parent_id=? WHERE id=?", (foreign["id"], third["id"]))
        self.con.commit()
        tree = self._tree()
        seen = []

        def walk(nodes):
            for node in nodes:
                seen.append(node["id"])
                walk(node["children"])

        walk(tree["children"])
        self.assertEqual(sorted(seen), sorted([first["id"], second["id"], third["id"]]))


class ApiTest(TreeFixture):
    def test_get_trees_and_create_child(self):
        root = self._todo("설계")
        created = server.route(
            self.con, "POST", "/api/todos", {}, {"title": "API", "parent_id": root["id"]}
        )
        self.assertEqual(created["workspace_id"], self.space["id"])
        payload = server.route(self.con, "GET", "/api/todo-trees", {}, {})
        self.assertIn(STATUS_REVIEW, payload["statuses"])
        tree = next(t for t in payload["trees"] if t["workspace"]["id"] == self.space["id"])
        self.assertEqual(tree["children"][0]["children"][0]["id"], created["id"])

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
