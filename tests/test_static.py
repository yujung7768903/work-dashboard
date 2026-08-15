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


# resolve_static 이 내주면 안 되는 경로. 상위 탈출·인코딩된 탈출·허용 안 된 확장자·
# index 없는 디렉토리 — 하나라도 뚫리면 저장소 파일이 그대로 노출된다
UNSAFE_STATIC_PATHS = (
    "/../server.py",
    "/%2e%2e/server.py",
    "/index.txt",
    "/js",
)


class StaticPathTest(unittest.TestCase):
    def test_root_maps_to_index(self):
        resolved = server.resolve_static("/")
        self.assertTrue(resolved.endswith(os.path.join("static", "index.html")))

    def test_allows_nested_module(self):
        self.assertIsNotNone(server.resolve_static("/js/api.js"))

    def test_rejects_unsafe_or_unknown_paths(self):
        for path in UNSAFE_STATIC_PATHS:
            with self.subTest(path=path):
                self.assertIsNone(server.resolve_static(path))


class PagePathTest(unittest.TestCase):
    """탭 경로가 앱 화면으로 떨어지는지는 test_frontend_contract.TabPathTest 가
    index.html 의 탭을 전수 대조한다. 여기서는 자산·차단 경로만 본다"""

    def test_existing_asset_is_served_as_is(self):
        self.assertTrue(server.resolve_page("/js/api.js").endswith("api.js"))

    def test_missing_or_unsafe_asset_stays_not_found(self):
        for path in ("/js/nope.js", "/../server.py"):
            with self.subTest(path=path):
                self.assertIsNone(server.resolve_page(path))


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

    def test_route_rejects_bad_requests(self):
        """라우팅 거부 조건이 한자리에. 새 엔드포인트의 거부 규칙도 여기에 붙인다"""
        for exc, why, method, path, body in (
            (NotFound, "없는 엔드포인트", "GET", "/api/nope", {}),
            (Validation, "지원 안 하는 메서드", "PUT", "/api/tree", {}),
            (Validation, "reorder 의 알 수 없는 kind", "POST", "/api/reorder",
             {"kind": "x", "ids": []}),
            (Validation, "id 없이 할일 조회", "GET", "/api/todos", {}),
            (Validation, "id 없이 세션 수정", "PATCH", "/api/sessions", {"category_id": 1}),
        ):
            with self.subTest(why=why):
                with self.assertRaises(exc):
                    server.route(self.con, method, path, {}, body)

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

    def test_patch_session_classifies(self):
        from app.repositories import sessions as session_repo

        session_repo.register(self.con, "route-sess")
        row_id = session_repo.get(self.con, "route-sess")["id"]
        ops = category_repo.get_by_name(self.con, "운영")["id"]
        payload = server.route(
            self.con, "PATCH", f"/api/sessions/{row_id}", {}, {"category_id": ops}
        )
        self.assertEqual(payload["category_id"], ops)

    def test_delete_todo_endpoint(self):
        ops = category_repo.get_by_name(self.con, "운영")["id"]
        created = server.route(
            self.con, "POST", "/api/todos", {}, {"title": "문의", "category_id": ops}
        )
        payload = server.route(
            self.con, "DELETE", f"/api/todos/{created['id']}", {}, {}
        )
        self.assertEqual(payload["deleted"], created["id"])
