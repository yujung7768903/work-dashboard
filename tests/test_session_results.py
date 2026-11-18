"""세션 결과물 — transcript 쓰기 호출·완료 보고에서 뽑기(읽기·실패 제외), 증분 오프셋, 근거 노드 재사용,
트리에서 그때 맡던 할일 밑에 붙이기, 폴더 열기가 결과물 파일 노드 id 만 받는지, 훅이 턴마다 모으는지"""
import importlib.util
import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

import dash
import server
from app import evidence
from app.constants import (
    DB_PATH_ENV,
    NODE_DOC,
    NODE_SESSION,
    NODE_TODO,
    REL_EVIDENCE,
    REL_RESULT,
)
from app.db import connect
from app.errors import NotFound, Validation
from app.repositories import categories as category_repo
from app.repositories import graph as graph_repo
from app.repositories import sessions as session_repo
from app.repositories import todos as todo_repo
from app.services import session_results, todo_tree
from tests.support import temp_db, temp_db_path

SID = "11111111-2222-3333-4444-555555555555"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PR_CREATE = "gh pr " + "create"  # 훅이 이 글자를 명령으로 오인하지 않게 나눠 적는다


# ── transcript 줄 만들기 ────────────────────────────────────────────────


class Transcript:
    """도구 호출·결과 줄을 차례로 쌓는다. 시각은 줄마다 1초씩"""

    def __init__(self):
        self.lines = []
        self.seq = 0

    def call(self, name, data, result, error=False, extra=None):
        self.seq += 1
        ident = f"toolu_{self.seq:04d}"
        stamp = f"2026-11-16T01:{self.seq // 60:02d}:{self.seq % 60:02d}.000Z"
        self.lines.append({
            "type": "assistant", "timestamp": stamp,
            "message": {"role": "assistant", "content": [{"type": "tool_use", "id": ident, "name": name, "input": data}]},
        })
        if result is None:
            return ident
        block = {"type": "tool_result", "tool_use_id": ident, "content": result}
        if error:
            block["is_error"] = True
        entry = {"type": "user", "timestamp": stamp, "message": {"role": "user", "content": [block]}}
        if extra is not None:
            entry["toolUseResult"] = extra
        self.lines.append(entry)
        return ident

    def result(self, ident, text, extra=None):
        entry = {"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": ident, "content": text}]}}
        if extra is not None:
            entry["toolUseResult"] = extra
        self.lines.append(entry)

    def text(self):
        return "".join(json.dumps(line, ensure_ascii=False) + "\n" for line in self.lines)

    def extract(self, is_result_file=None):
        extractor = session_results.Extractor(is_result_file=is_result_file)
        for raw in self.text().encode("utf-8").splitlines(keepends=True):
            extractor.feed(raw)
        return extractor.found


def confluence_page(page_id, title):
    return [{"type": "text", "text": json.dumps({"parentId": "7000000001", "id": page_id, "title": title})}]


class ExtractTest(unittest.TestCase):
    def test_confluence_create_and_update_but_not_reads_or_blocked_calls(self):
        log = Transcript()
        log.call("mcp__claude_ai_Atlassian_Rovo__getConfluencePage", {"pageId": "7100000000"}, "본문")
        log.call("mcp__claude_ai_Atlassian_Rovo__createConfluencePage", {"title": "막힌 페이지"},
                 "PreToolUse:... hook error: doc-style 먼저", error=True)
        log.call("mcp__claude_ai_Atlassian_Rovo__createConfluencePage", {"title": "스캐닝 결과", "parentId": "7000000001"},
                 confluence_page("7334068299", "스캐닝 결과"))
        log.call("mcp__claude_ai_Atlassian_MCP__updateConfluenceContent", {"pageId": "7319289879", "title": "보완 방안"},
                 confluence_page("7319289879", "보완 방안"))
        found = log.extract()
        self.assertEqual(
            [(item["ref"], item["action"], item["title"]) for item in found],
            [("confluence:7334068299", "생성", "스캐닝 결과"), ("confluence:7319289879", "수정", "보완 방안")],
        )
        # 시각은 DB 모양(+00:00, 초) — 할일 연결 시각과 글자로 견준다
        self.assertEqual(found[0]["at"], "2026-11-16T01:00:03+00:00")

    def test_jira_create_edit_comment_need_a_real_key(self):
        log = Transcript()
        log.call("mcp__claude_ai_Atlassian_Rovo__createJiraIssue", {"summary": "권한 검사 누락"},
                 json.dumps({"issues": {"nodes": [{"id": "55261", "key": "PFD-6528"}]}}))
        log.call("mcp__claude_ai_Atlassian_Rovo__editJiraIssue", {"issueIdOrKey": "PFD-6517", "fields": {"summary": "로그 평문"}}, "ok")
        log.call("mcp__claude_ai_Atlassian_Rovo__addCommentToJiraIssue", {"issueIdOrKey": "PFD-6349"}, "ok")
        log.call("mcp__claude_ai_Atlassian_Rovo__editJiraIssue", {"issueIdOrKey": "55001"}, "ok")  # 숫자 id 는 키가 아니다
        log.call("mcp__claude_ai_Atlassian_Rovo__getJiraIssue", {"issueIdOrKey": "PFD-1"}, "읽기")
        self.assertEqual(
            [(item["ref"], item["action"], item["title"]) for item in log.extract()],
            [("jira:PFD-6528", "생성", "PFD-6528 권한 검사 누락"),
             ("jira:PFD-6517", "수정", "PFD-6517 로그 평문"),
             ("jira:PFD-6349", "댓글", None)],
        )

    def test_artifact_publish_only(self):
        log = Transcript()
        log.call("Artifact", {"action": "read", "url": "https://claude.ai/artifact/DRkobpKn43HNpdMgoGdaae"}, "html")
        log.call("Artifact", {"action": "publish", "url": "https://claude.ai/artifact/DRkobpKn43HNpdMgoGdaae",
                              "file_path": "/x/main.html", "asset": True}, "uploaded")
        log.call("Artifact", {"file_path": "/x/main.html"},
                 "Published /x/main.html at https://claude.ai/artifact/DRkobpKn43HNpdMgoGdaae (Version 17)",
                 extra={"url": "https://claude.ai/artifact/DRkobpKn43HNpdMgoGdaae", "title": "대나무숲"})
        log.call("Artifact", {"file_path": "/x/dex.html"},
                 "Published /x/dex.html at https://claude.ai/code/artifact/e3e31310-afee-4344-bf74-c3648863def6 (Version 1)")
        found = log.extract()
        self.assertEqual([item["ref"] for item in found],
                         ["artifact:DRkobpKn43HNpdMgoGdaae", "artifact:e3e31310-afee-4344-bf74-c3648863def6"])
        self.assertEqual(found[0]["title"], "대나무숲")
        self.assertEqual(evidence.url_of(found[1]["ref"]),
                         "https://claude.ai/code/artifact/e3e31310-afee-4344-bf74-c3648863def6")

    def test_pull_request_from_git_operation_or_output(self):
        log = Transcript()
        log.call("Bash", {"command": f"git push -u origin feat && {PR_CREATE} --title \"로그 조회에 KT 더하기\" --body x"},
                 "https://github.com/hkilbo/muni/pull/69",
                 extra={"stdout": "https://github.com/hkilbo/muni/pull/69",
                        "gitOperation": {"pr": {"number": 69, "url": "https://github.com/hkilbo/muni/pull/69", "action": "created"}}})
        log.call("Bash", {"command": f"{PR_CREATE} --title 'fix: 락 해제'"},
                 "Creating pull request\nhttps://github.com/hkilbo/kt-cms-server/pull/41\n")
        # 이미 있는 PR(실패)·push 안내 주소는 PR 이 아니다
        log.call("Bash", {"command": f"{PR_CREATE} --title x"},
                 "a pull request already exists: https://github.com/hkilbo/muni/pull/12", error=True)
        log.call("Bash", {"command": f"{PR_CREATE} --fill"}, "remote: https://github.com/hkilbo/muni/pull/new/feat/x")
        self.assertEqual(
            [(item["ref"], item["title"]) for item in log.extract()],
            [("pr:hkilbo/muni#69", "muni#69 로그 조회에 KT 더하기"), ("pr:hkilbo/kt-cms-server#41", "kt-cms-server#41 fix: 락 해제")],
        )

    def test_report_open_targets(self):
        folder = tempfile.mkdtemp()
        report = os.path.join(folder, "보고서.md")
        open(report, "w").close()
        log = Transcript()
        mgr = "python3 ~/work/manager/manager.py"
        log.call("Bash", {"command": f"{mgr} 퇴근-보조 --summary '끝' --open https://hkilbo.github.io/hk-techblog-client/blog/a/ --no-restart"}, "세션을 끈다")
        log.call("Bash", {"command": f"{mgr} ask --kind decision --title '고를 것' --open '{report}'"}, "183")
        log.call("Bash", {"command": f"cd ~/work/manager && python3 manager.py ask --title t --open https://hankookilbo.atlassian.net/wiki/spaces/2/pages/7333969921"}, "184")
        # 산출물이 아닌 것: 권한 막힘 질문 · 로컬 미리보기 · 변수 · 없는 파일 · 브라우저 접두사
        log.call("Bash", {"command": f"{mgr} ask --blocked permission --title 콘솔 --open https://console.aws.amazon.com/"}, "185")
        log.call("Bash", {"command": f"{mgr} 퇴근-보조 --summary s --open http://127.0.0.1:9080/tree --no-restart"}, "ok")
        log.call("Bash", {"command": f"{mgr} ask --title t --open \"$U\""}, "186")
        log.call("Bash", {"command": f"{mgr} ask --title t --open {folder}/없는파일.md"}, "187")
        log.call("Bash", {"command": f"{mgr} ask --title t --open agent-chrome:https://example.com/"}, "188")
        self.assertEqual(
            [(item["ref"], item["action"]) for item in log.extract()],
            [("site:https://hkilbo.github.io/hk-techblog-client/blog/a/", "보고"),
             (f"file:{report}", "보고"),
             ("confluence:7333969921", "보고")],
        )

    def test_write_keeps_only_new_files_outside_repos_and_agent_folders(self):
        base = tempfile.mkdtemp()
        loose = os.path.join(base, "reports", "plan.html")
        in_repo = os.path.join(base, "repo", "src", "app.py")
        hidden = os.path.join(base, ".config", "nvim", "init.lua")
        appdata = os.path.join(base, "AppData", "Local", "tool.ps1")
        for path in (loose, in_repo, hidden, appdata):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            open(path, "w").close()
        os.makedirs(os.path.join(base, "repo", ".git"))
        log = Transcript()
        for path in (loose, in_repo, hidden, appdata):
            log.call("Write", {"file_path": path}, f"File created successfully at: {path}",
                     extra={"type": "create", "filePath": path})
        log.call("Write", {"file_path": loose}, "updated", extra={"type": "update", "filePath": loose})
        log.call("Write", {"file_path": os.path.join(base, "x.md")}, "blocked by hook", error=True)
        session_results._repo_cache.clear()
        with mock.patch.object(session_results, "RESULT_FILE_SKIP_DIRS", ()):  # 임시 폴더(/tmp) 밑에서 검사한다
            found = log.extract()
        self.assertEqual([item["ref"] for item in found], [f"file:{loose}"])
        # 에이전트 작업 폴더·/tmp 는 기본 설정에서 빠진다
        self.assertFalse(session_results.result_file_ok(loose))


class TargetRefTest(unittest.TestCase):
    def test_target_ref_normalizes_like_evidence(self):
        self.assertEqual(evidence.target_ref("https://hankookilbo.atlassian.net/browse/PFD-6528"), "jira:PFD-6528")
        self.assertEqual(evidence.target_ref("https://github.com/hkilbo/hk-backend-plugins/pull/12;"),
                         "pr:hkilbo/hk-backend-plugins#12")
        self.assertEqual(evidence.target_ref("https://claude.ai/artifact/3EZC15RtAyVHgfo944uCmo"),
                         "artifact:3EZC15RtAyVHgfo944uCmo")
        self.assertIsNone(evidence.target_ref("http://localhost:4321/blog/"))
        self.assertIsNone(evidence.target_ref("으로"))
        self.assertEqual(evidence.label_of("site:https://hkilbo.github.io/blog/a/"), "hkilbo.github.io/blog/a")
        self.assertEqual(evidence.label_of("file:/home/u/work/a/b.md"), "b.md")
        self.assertIsNone(evidence.url_of("file:/home/u/work/a/b.md"))


# ── 저장·트리·폴더 열기 ──────────────────────────────────────────────────


class ResultFixture(unittest.TestCase):
    def setUp(self):
        self.con = temp_db()
        category = category_repo.list_all(self.con)[0]
        self.space = todo_repo.create(self.con, "취약점 점검", category_id=category["id"])
        self.first = todo_repo.create(self.con, "스캐닝", parent_id=self.space["id"])
        self.second = todo_repo.create(self.con, "보고서", parent_id=self.space["id"])
        session_repo.register(self.con, SID, cwd="/tmp")
        self.session_row = session_repo.find(self.con, SID)["id"]

    def link(self, todo, at):
        self.con.execute("INSERT INTO session_todos(session_id, todo_id, created_at) VALUES(?,?,?)",
                         (self.session_row, todo["id"], at))
        self.con.commit()

    def results_of(self, todo):
        forest = todo_tree.forest(self.con)
        found = {}

        def walk(nodes):
            for node in nodes:
                found[node["id"]] = node
                walk(node["children"])
        for tree in forest["trees"]:
            walk(tree["children"])
        return found[todo["id"]]["results"]


class StoreTest(ResultFixture):
    def test_reuses_the_evidence_node_and_merges_actions(self):
        graph_repo.add_edge(self.con, (NODE_TODO, self.first["id"]), (NODE_DOC, "confluence:7319289879"), REL_EVIDENCE)
        nodes_before = self.con.execute("SELECT COUNT(*) FROM graph_nodes").fetchone()[0]
        graph_repo.add_result(self.con, SID, "confluence:7319289879", "수정", "2026-11-16T02:00:00+00:00", title="보완 방안")
        graph_repo.add_result(self.con, SID, "confluence:7319289879", "생성", "2026-11-16T01:00:00+00:00")
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM graph_nodes").fetchone()[0], nodes_before)
        edges = graph_repo.edges_of(self.con, (NODE_SESSION, SID))
        self.assertEqual(len(edges), 1)
        self.assertEqual(edges[0]["relation"], REL_RESULT)
        self.assertEqual(edges[0]["evidence"], "생성·수정")
        self.assertEqual(edges[0]["created_at"], "2026-11-16T01:00:00+00:00")
        # 근거 문서 노드 제목이 라벨뿐이었으면 결과가 아는 제목으로 채운다
        self.assertEqual(graph_repo.get_doc(self.con, "confluence:7319289879")["title"], "보완 방안")

    def test_unknown_session_is_skipped(self):
        self.assertIsNone(graph_repo.add_result(self.con, "모르는-세션", "jira:PFD-1", "생성", None))

    def test_tree_puts_results_under_the_todo_held_at_that_time(self):
        self.link(self.first, "2026-11-16T01:00:00+00:00")
        self.link(self.second, "2026-11-16T03:00:00+00:00")
        graph_repo.add_result(self.con, SID, "jira:PFD-10", "생성", "2026-11-16T00:30:00+00:00")  # 첫 연결 전 → 첫 할일
        graph_repo.add_result(self.con, SID, "pr:hkilbo/muni#69", "생성", "2026-11-16T02:00:00+00:00")
        graph_repo.add_result(self.con, SID, "artifact:DRkobpKn43HNpdMgoGdaae", "발행", "2026-11-16T04:00:00+00:00",
                              title="대나무숲", url="https://claude.ai/artifact/DRkobpKn43HNpdMgoGdaae")
        first = self.results_of(self.first)
        second = self.results_of(self.second)
        # 최근 것이 위
        self.assertEqual([item["ref"] for item in first], ["pr:hkilbo/muni#69", "jira:PFD-10"])
        self.assertEqual([item["ref"] for item in second], ["artifact:DRkobpKn43HNpdMgoGdaae"])
        self.assertEqual(second[0]["url"], "https://claude.ai/artifact/DRkobpKn43HNpdMgoGdaae")
        self.assertEqual(second[0]["title"], "대나무숲")
        self.assertEqual(first[0]["url"], "https://github.com/hkilbo/muni/pull/69")
        # 결과물은 할일이 아니다 — 진행률에 안 센다
        tree = todo_tree.forest(self.con)["trees"][0]
        self.assertEqual(tree["progress"]["total"], 3)  # 맨 위 할일 + 두 할일

    def test_session_without_todo_has_no_place_in_the_tree(self):
        graph_repo.add_result(self.con, SID, "jira:PFD-10", "생성", "2026-11-16T00:30:00+00:00")
        self.assertEqual(self.results_of(self.first), [])

    def test_file_card_reports_missing_file(self):
        self.link(self.first, "2026-11-16T01:00:00+00:00")
        graph_repo.add_result(self.con, SID, "file:/없는/폴더/보고서.md", "보고", "2026-11-16T02:00:00+00:00")
        card = self.results_of(self.first)[0]
        self.assertEqual(card["doc_kind"], "file")
        self.assertEqual(card["path"], "/없는/폴더/보고서.md")
        self.assertTrue(card["missing"])
        self.assertIsNone(card["url"])


class OpenFolderTest(ResultFixture):
    def setUp(self):
        super().setUp()
        self.folder = tempfile.mkdtemp()
        self.file = os.path.join(self.folder, "보고서.md")
        open(self.file, "w").close()
        graph_repo.add_result(self.con, SID, f"file:{self.file}", "보고", None)
        graph_repo.add_result(self.con, SID, "confluence:7319289879", "수정", None)
        graph_repo.add_edge(self.con, (NODE_TODO, self.first["id"]), (NODE_DOC, "jira:PFD-77"), REL_EVIDENCE)

    def node_id(self, ref):
        return graph_repo.get_doc(self.con, ref)["id"]

    def test_opens_only_registered_result_files(self):
        with mock.patch.object(session_results.browse, "reveal", return_value={"ok": True}) as reveal:
            session_results.open_folder(self.con, self.node_id(f"file:{self.file}"))
        reveal.assert_called_once_with(self.file)
        for other in ("confluence:7319289879", "jira:PFD-77"):  # 결과물이지만 파일이 아님 · 근거일 뿐
            with self.subTest(other), self.assertRaises(NotFound):
                session_results.open_folder(self.con, self.node_id(other))
        with self.assertRaises(NotFound):
            session_results.open_folder(self.con, 999999)
        with self.assertRaises(Validation):
            session_results.open_folder(self.con, "/etc")

    def test_api_ignores_a_path_in_the_request(self):
        with mock.patch.object(session_results.browse, "reveal", return_value={"ok": True}) as reveal:
            server.route(self.con, "POST", "/api/result-folder", {},
                         {"id": self.node_id(f"file:{self.file}"), "path": "/etc/passwd"})
        reveal.assert_called_once_with(self.file)


# ── 증분 읽기·훅·CLI ─────────────────────────────────────────────────────


class ScanTest(ResultFixture):
    def setUp(self):
        super().setUp()
        self.root = tempfile.mkdtemp()
        project = os.path.join(self.root, "-home-u-work-x")
        os.makedirs(os.path.join(project, SID, "subagents"))
        self.path = os.path.join(project, f"{SID}.jsonl")
        self.sub = os.path.join(project, SID, "subagents", "agent-1.jsonl")
        self.addCleanup(shutil.rmtree, self.root)

    def write(self, path, log, mode="w"):
        with open(path, mode, encoding="utf-8") as handle:
            handle.write(log.text())

    def refs(self):
        return sorted(edge["dst_id"] for edge in graph_repo.edges_of(self.con, (NODE_SESSION, SID)))

    def test_reads_only_the_new_tail_and_holds_for_a_pending_call(self):
        log = Transcript()
        log.call("mcp__claude_ai_Atlassian_Rovo__addCommentToJiraIssue", {"issueIdOrKey": "PFD-1"}, "ok")
        pending = log.call("mcp__claude_ai_Atlassian_Rovo__addCommentToJiraIssue", {"issueIdOrKey": "PFD-2"}, None)
        self.write(self.path, log)
        session_results.collect(self.con, SID, root=self.root)
        self.assertEqual(self.refs(), ["jira:PFD-1"])
        held = self.con.execute("SELECT offset FROM transcript_scans WHERE path=?", (self.path,)).fetchone()["offset"]
        self.assertLess(held, os.path.getsize(self.path), "결과를 못 받은 호출 줄부터 다시 읽는다")
        tail = Transcript()
        tail.result(pending, "ok")
        self.write(self.path, tail, mode="a")
        session_results.collect(self.con, SID, root=self.root)
        self.assertEqual(self.refs(), ["jira:PFD-1", "jira:PFD-2"])
        done = self.con.execute("SELECT offset FROM transcript_scans WHERE path=?", (self.path,)).fetchone()["offset"]
        self.assertEqual(done, os.path.getsize(self.path))

    def test_subagent_results_belong_to_the_parent_session(self):
        self.write(self.path, Transcript())
        log = Transcript()
        log.call("mcp__claude_ai_Atlassian_Rovo__createConfluencePage", {"title": "하위 페이지"},
                 confluence_page("7335018548", "하위 페이지"))
        self.write(self.sub, log)
        session_results.collect(self.con, SID, root=self.root)
        self.assertEqual(self.refs(), ["confluence:7335018548"])

    def test_hook_stop_collects_this_turn(self):
        log = Transcript()
        log.call("mcp__claude_ai_Atlassian_Rovo__createJiraIssue", {"summary": "새 이슈"},
                 json.dumps({"key": "PFD-9000"}))
        self.write(self.path, log)
        spec = importlib.util.spec_from_file_location("dash_hook_under_test", os.path.join(ROOT, "hooks", "dash_hook.py"))
        hook = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(hook)
        with mock.patch.object(session_results, "TRANSCRIPT_ROOT", self.root):
            hook._on_stop(self.con, SID, {})
        self.assertEqual(self.refs(), ["jira:PFD-9000"])

    def test_cli_backfill_reports_counts_and_is_repeatable(self):
        log = Transcript()
        log.call("Artifact", {"file_path": "/x/a.html"}, "Published /x/a.html at https://claude.ai/artifact/AbCdEfGh12345678 (Version 1)")
        self.write(self.path, log)
        path = temp_db_path()
        session_repo.register(connect(path), SID, cwd="/tmp")
        out = io.StringIO()
        with mock.patch.dict(os.environ, {DB_PATH_ENV: path}), \
                mock.patch.object(session_results, "TRANSCRIPT_ROOT", self.root), redirect_stdout(out):
            dash.main(["collect-results"])
            dash.main(["collect-results"])
        text = out.getvalue()
        self.assertIn("결과 1건 이었음", text)
        self.assertIn("artifact: 1", text)
        self.assertIn("세션 0개에서 결과 0건", text, "두 번째는 새로 읽을 것이 없다")


if __name__ == "__main__":
    unittest.main()
