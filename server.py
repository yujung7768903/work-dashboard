#!/usr/bin/env python3
"""작업 대시보드 HTTP 진입점. 라우팅과 직렬화만 담당"""
import argparse
import json
import os
import posixpath
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

from app.constants import ALLOWED_STATIC_SUFFIXES, DEFAULT_HOST, DEFAULT_PORT
from app.db import connect
from app.errors import Conflict, DomainError, NeedsConfirm, NotFound, Validation
from app.repositories import categories as category_repo
from app.repositories import subtasks as subtask_repo
from app.repositories import todos as todo_repo
from app.repositories import sessions as session_repo
from app.repositories import workspaces as workspace_repo
from app.services import board, planning, session_link, session_todo, usage

STATIC_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
INDEX_FILE = "index.html"
API_PREFIX = "/api/"
NONE_LITERAL = "none"
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
}
STATUS_BY_ERROR = (
    (NotFound, HTTPStatus.NOT_FOUND),
    (Conflict, HTTPStatus.CONFLICT),
    (Validation, HTTPStatus.BAD_REQUEST),
)
WORKSPACE_CREATE_FIELDS = ("background", "purpose", "goal", "considerations", "jira_id")


def status_for(error):
    """도메인 예외 타입만 보고 상태 코드 결정. 메시지 문자열은 보지 않음"""
    for error_type, status in STATUS_BY_ERROR:
        if isinstance(error, error_type):
            return int(status)
    return int(HTTPStatus.INTERNAL_SERVER_ERROR)


def resolve_static(url_path):
    """static/ 안의 허용 확장자 파일만 통과. 벗어나면 None"""
    decoded = unquote(url_path)
    if decoded.endswith("/"):
        decoded += INDEX_FILE
    normalized = posixpath.normpath(decoded).lstrip("/")
    if normalized.startswith(".."):
        return None
    candidate = os.path.normpath(os.path.join(STATIC_ROOT, normalized))
    if os.path.commonpath([candidate, STATIC_ROOT]) != STATIC_ROOT:
        return None
    if not candidate.endswith(ALLOWED_STATIC_SUFFIXES):
        return None
    return candidate


def route(con, method, path, query, body):
    """경로와 메서드를 도메인 호출로 연결. 도메인 로직은 갖지 않음"""
    segments = [part for part in path.strip("/").split("/") if part][1:]
    if not segments:
        raise NotFound("알 수 없는 엔드포인트")
    head = segments[0]
    item_id = int(segments[1]) if len(segments) > 1 else None
    routers = {
        "GET": lambda: _route_get(con, head, item_id, query),
        "POST": lambda: _route_post(con, head, body),
        "PATCH": lambda: _route_patch(con, head, item_id, body),
        "DELETE": lambda: _route_delete(con, head, item_id, query),
    }
    if method not in routers:
        raise Validation(f"지원하지 않는 메서드: {method}")
    return routers[method]()


def _route_get(con, head, item_id, query):
    if head == "tree":
        return board.tree(con, _single(query, "group_by", board.GROUP_BY_WORKSPACE))
    if head == "next":
        return planning.next_todo(con)
    if head == "done-today":
        return planning.done_on(con, _single(query, "date", None))
    if head == "categories":
        return category_repo.list_all(con)
    if head == "workspaces":
        if item_id:
            return {
                "workspace": workspace_repo.get(con, item_id),
                "todos": todo_repo.list_by_workspace(con, item_id),
            }
        return workspace_repo.list_all(con)
    if head == "todos":
        if not item_id:
            raise Validation("id 가 필요함")
        return session_link.todo_detail(con, item_id)
    if head == "sessions":
        if item_id:
            return session_link.detail(con, item_id)
        return session_link.active_payload(con)
    if head == "usage":
        return usage.snapshot(con)
    raise NotFound("알 수 없는 엔드포인트")


def _route_post(con, head, body):
    if head == "categories":
        return category_repo.create(con, body.get("name"))
    if head == "workspaces":
        extra = {key: body.get(key) for key in WORKSPACE_CREATE_FIELDS}
        return workspace_repo.create(
            con, body.get("category_id"), body.get("name"), **extra
        )
    if head == "todos":
        return todo_repo.create(
            con,
            body.get("title"),
            category_id=body.get("category_id"),
            workspace_id=body.get("workspace_id"),
            note=body.get("note"),
        )
    if head == "subtasks":
        return subtask_repo.create(con, body.get("todo_id"), body.get("title"))
    if head == "reorder":
        return _reorder(con, body)
    raise NotFound("알 수 없는 엔드포인트")


def _route_patch(con, head, item_id, body):
    if not item_id:
        raise Validation("id 가 필요함")
    if head == "categories":
        return category_repo.update(con, item_id, **body)
    if head == "workspaces":
        return workspace_repo.update(con, item_id, **body)
    if head == "todos":
        return todo_repo.update(con, item_id, **body)
    if head == "subtasks":
        return subtask_repo.update(con, item_id, **body)
    if head == "sessions":
        session = session_repo.classify_by_ids(
            con,
            item_id,
            category_id=body.get("category_id"),
            workspace_id=body.get("workspace_id"),
        )
        # 워크스페이스로 분류한 세션은 할일까지 만들어 붙인다. 카테고리만이면 None
        return {**session, "created_todo": session_todo.ensure_from_session(con, item_id)}
    raise NotFound("알 수 없는 엔드포인트")


def _route_delete(con, head, item_id, query):
    if not item_id:
        raise Validation("id 가 필요함")
    force = _single(query, "force", None) == "1"
    deleters = {
        "categories": lambda con, item_id: category_repo.delete(con, item_id, force),
        "workspaces": workspace_repo.delete,
        "todos": todo_repo.delete,
        "subtasks": subtask_repo.delete,
    }
    if head not in deleters:
        raise NotFound("알 수 없는 엔드포인트")
    deleters[head](con, item_id)
    return {"deleted": item_id}


def _reorder(con, body):
    kind, ids = body.get("kind"), body.get("ids") or []
    scope = body.get("scope_id")
    if kind == "categories":
        category_repo.reorder(con, ids)
    elif kind == "workspaces":
        workspace_repo.reorder(con, ids)
    elif kind == "todos":
        todo_repo.reorder(con, ids, None if scope in (None, NONE_LITERAL) else scope)
    elif kind == "subtasks":
        subtask_repo.reorder(con, ids, scope)
    else:
        raise Validation(f"알 수 없는 reorder 종류: {kind}")
    return {"reordered": len(ids)}


def _single(query, key, default):
    values = query.get(key)
    return values[0] if values else default


class Handler(BaseHTTPRequestHandler):
    server_version = "work-dashboard"

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path.startswith(API_PREFIX):
            self._dispatch("GET", parsed)
            return
        self._serve_static(parsed.path)

    def do_POST(self):
        self._dispatch("POST", urlparse(self.path))

    def do_PATCH(self):
        self._dispatch("PATCH", urlparse(self.path))

    def do_DELETE(self):
        self._dispatch("DELETE", urlparse(self.path))

    def log_message(self, fmt, *args):
        """기본 형식 대신 메서드와 경로만. 리다이렉트 시에도 바로 보이게 flush"""
        print(f"{self.command} {self.path}", flush=True)

    def _dispatch(self, method, parsed):
        con = connect()
        try:
            payload = route(
                con, method, parsed.path, parse_qs(parsed.query), self._read_body()
            )
            self._send_json(int(HTTPStatus.OK), payload)
        except NeedsConfirm as error:
            # 클라이언트가 되물은 뒤 ?force=1 로 재요청하도록 플래그로 구분해준다
            self._send_json(
                status_for(error), {"error": str(error), "confirm": True}
            )
        except DomainError as error:
            self._send_json(status_for(error), {"error": str(error)})
        except Exception as error:  # 예상 못한 오류도 JSON 으로 알려줌
            self._send_json(
                int(HTTPStatus.INTERNAL_SERVER_ERROR),
                {"error": f"{type(error).__name__}: {error}"},
            )

    def _read_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def _send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_static(self, url_path):
        resolved = resolve_static(url_path)
        if not resolved or not os.path.isfile(resolved):
            self.send_error(int(HTTPStatus.NOT_FOUND))
            return
        with open(resolved, "rb") as handle:
            body = handle.read()
        self.send_response(int(HTTPStatus.OK))
        self.send_header("Content-Type", CONTENT_TYPES[os.path.splitext(resolved)[1]])
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main(argv=None):
    parser = argparse.ArgumentParser(description="작업 대시보드 서버")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args(argv)
    connect()
    try:
        httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    except OSError as error:
        raise SystemExit(f"포트 {args.port} 를 열 수 없음: {error}")
    print(f"http://{args.host}:{args.port}", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
