import os
import unittest

import server
from app.errors import Conflict, NotFound, Validation
from app.repositories import categories as category_repo
from app.repositories import workspaces as workspace_repo
from tests.support import temp_db

NOT_FOUND = 404
CONFLICT = 409
BAD_REQUEST = 400
SERVER_ERROR = 500


class StaticPathTest(unittest.TestCase):
    def test_root_maps_to_index(self):
        resolved = server.resolve_static("/")
        self.assertTrue(resolved.endswith(os.path.join("static", "index.html")))

    def test_allows_nested_module(self):
        self.assertIsNotNone(server.resolve_static("/js/api.js"))

    def test_rejects_parent_traversal(self):
        self.assertIsNone(server.resolve_static("/../server.py"))

    def test_rejects_encoded_traversal(self):
        self.assertIsNone(server.resolve_static("/%2e%2e/server.py"))

    def test_rejects_disallowed_suffix(self):
        self.assertIsNone(server.resolve_static("/index.txt"))

    def test_rejects_directory_without_index(self):
        self.assertIsNone(server.resolve_static("/js"))


class ErrorMappingTest(unittest.TestCase):
    def test_maps_domain_errors_to_status(self):
        self.assertEqual(server.status_for(NotFound("x")), NOT_FOUND)
        self.assertEqual(server.status_for(Conflict("x")), CONFLICT)
        self.assertEqual(server.status_for(Validation("x")), BAD_REQUEST)

    def test_unknown_error_is_server_error(self):
        self.assertEqual(server.status_for(RuntimeError("x")), SERVER_ERROR)


class RouteTest(unittest.TestCase):
    def setUp(self):
        self.con = temp_db()

    def test_tree_endpoint_returns_groups(self):
        payload = server.route(self.con, "GET", "/api/tree", {}, {})
        self.assertIn("groups", payload)

    def test_create_category_endpoint(self):
        payload = server.route(self.con, "POST", "/api/categories", {}, {"name": "새것"})
        self.assertEqual(payload["name"], "새것")

    def test_workspaces_list_endpoint(self):
        dev = category_repo.get_by_name(self.con, "개발")["id"]
        workspace_repo.create(self.con, dev, "빈 워크스페이스")
        payload = server.route(self.con, "GET", "/api/workspaces", {}, {})
        self.assertEqual([item["name"] for item in payload], ["빈 워크스페이스"])

    def test_workspace_detail_endpoint(self):
        dev = category_repo.get_by_name(self.con, "개발")["id"]
        created = workspace_repo.create(self.con, dev, "KT")
        payload = server.route(
            self.con, "GET", f"/api/workspaces/{created['id']}", {}, {}
        )
        self.assertEqual(payload["workspace"]["name"], "KT")
        self.assertEqual(payload["todos"], [])

    def test_unknown_endpoint_raises_not_found(self):
        with self.assertRaises(NotFound):
            server.route(self.con, "GET", "/api/nope", {}, {})

    def test_unsupported_method_raises_validation(self):
        with self.assertRaises(Validation):
            server.route(self.con, "PUT", "/api/tree", {}, {})

    def test_reorder_endpoint_rejects_unknown_kind(self):
        with self.assertRaises(Validation):
            server.route(self.con, "POST", "/api/reorder", {}, {"kind": "x", "ids": []})

    def test_sessions_endpoint_shape(self):
        from app.repositories import sessions as session_repo

        session_repo.register(self.con, "route-sess", cwd="/tmp")
        session_repo.set_last_prompt(self.con, "route-sess", "무엇을 하나")
        payload = server.route(self.con, "GET", "/api/sessions", {}, {})
        self.assertEqual(payload["unclassified_count"], 1)
        self.assertEqual(len(payload["sessions"]), 1)

    def test_todo_endpoint_carries_note_and_sessions(self):
        from app.repositories import sessions as session_repo
        from app.repositories import todos as todo_repo

        ops = category_repo.get_by_name(self.con, "운영")["id"]
        todo = todo_repo.create(self.con, "락 재설계", category_id=ops, note="컨텍스트 본문")
        session_repo.register(self.con, "route-sess")
        session_repo.link_todo(self.con, "route-sess", todo["id"])

        payload = server.route(self.con, "GET", f"/api/todos/{todo['id']}", {}, {})
        self.assertEqual(payload["todo"]["note"], "컨텍스트 본문")
        self.assertEqual(
            [row["claude_session_id"] for row in payload["sessions"]], ["route-sess"]
        )

    def test_todo_endpoint_requires_id(self):
        with self.assertRaises(Validation):
            server.route(self.con, "GET", "/api/todos", {}, {})

    def test_patch_session_classifies(self):
        from app.repositories import sessions as session_repo

        session_repo.register(self.con, "route-sess")
        row_id = session_repo.get(self.con, "route-sess")["id"]
        ops = category_repo.get_by_name(self.con, "운영")["id"]
        payload = server.route(
            self.con, "PATCH", f"/api/sessions/{row_id}", {}, {"category_id": ops}
        )
        self.assertEqual(payload["category_id"], ops)

    def test_patch_session_without_id_is_validation(self):
        with self.assertRaises(Validation):
            server.route(self.con, "PATCH", "/api/sessions", {}, {"category_id": 1})

    def test_delete_todo_endpoint(self):
        ops = category_repo.get_by_name(self.con, "운영")["id"]
        created = server.route(
            self.con, "POST", "/api/todos", {}, {"title": "문의", "category_id": ops}
        )
        payload = server.route(
            self.con, "DELETE", f"/api/todos/{created['id']}", {}, {}
        )
        self.assertEqual(payload["deleted"], created["id"])
