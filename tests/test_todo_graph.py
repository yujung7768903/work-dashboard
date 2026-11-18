"""할일 관계 그래프 — edges 저장 규칙(종류·순환·상태), parent_id 이관·짝 맞추기, 근거 키 추출,
note 근거 자동 연결, 같은 근거 관련, spawn 출처 제안, 트리 조립(다중 상위·맥락·미분류), API·CLI"""
import io
import re
import os
import unittest
from contextlib import redirect_stderr, redirect_stdout

import dash
import server
from app import db, evidence
from app.constants import (
    BASIS_BACKGROUND,
    BASIS_TRIGGER,
    BY_NOTE,
    BY_SHARED_DOC,
    BY_SPAWN,
    DB_PATH_ENV,
    EDGE_BASIS_MSG,
    EDGE_CONFIRMED,
    EDGE_CYCLE_MSG,
    EDGE_KIND_MSG,
    EDGE_PROPOSED,
    EDGE_REJECTED,
    EDGE_SELF_MSG,
    NODE_CONTEXT,
    NODE_DOC,
    NODE_TODO,
    REL_EVIDENCE,
    REL_PARENT,
    REL_PRECEDES,
    REL_RELATED,
    SESSION_ID_ENV,
    SHARED_DOC_MAX_TODOS,
    STATUS_DONE,
)
from app.db import connect
from app.errors import Validation
from app.repositories import categories as category_repo
from app.repositories import graph as graph_repo
from app.repositories import sessions as session_repo
from app.repositories import todos as todo_repo
from app.services import todo_tree
from tests.support import temp_db, temp_db_path


def T(todo):
    return (NODE_TODO, todo["id"])


class GraphFixture(unittest.TestCase):
    def setUp(self):
        self.con = temp_db()
        self.category = category_repo.list_all(self.con)[0]
        # 워크스페이스는 없다 — 상위 없는 할일이 트리 맨 위다
        self.space = todo_repo.create(self.con, "통합DB 검색", category_id=self.category["id"])
        self.other = todo_repo.create(self.con, "자료라이브러리", category_id=self.category["id"])

    def _todo(self, title, workspace=None, note=None):
        """workspace(맨 위 할일)를 주면 그 아래, 아니면 상위 없는 할일(제 트리의 맨 위)"""
        if workspace is not None:
            return todo_repo.create(self.con, title, parent_id=workspace["id"], note=note)
        return todo_repo.create(self.con, title, category_id=self.category["id"], note=note)

    def _parent(self, parent, child, state=EDGE_CONFIRMED, basis=BASIS_TRIGGER):
        return graph_repo.add_edge(self.con, parent, child, REL_PARENT, basis=basis, state=state)

    def _edges(self, relation=None, created_by=None):
        rows = graph_repo.list_edges(self.con, relations=(relation,) if relation else None)
        return [row for row in rows if created_by is None or row["created_by"] == created_by]


class EdgeRuleTest(GraphFixture):
    def test_parent_needs_basis_and_known_kinds(self):
        a, b = self._todo("사진 분석"), self._todo("필터 원인")
        with self.assertRaisesRegex(Validation, re.escape(EDGE_BASIS_MSG)):
            graph_repo.add_edge(self.con, T(a), T(b), REL_PARENT)
        with self.assertRaisesRegex(Validation, EDGE_KIND_MSG):
            graph_repo.add_edge(self.con, T(a), (NODE_DOC, "jira:PFD-1"), REL_PARENT, basis=BASIS_TRIGGER)
        with self.assertRaisesRegex(Validation, EDGE_SELF_MSG):
            graph_repo.add_edge(self.con, T(a), T(a), REL_PRECEDES)

    def test_parent_cycle_is_rejected_on_save(self):
        a, b, c = self._todo("가"), self._todo("나"), self._todo("다")
        self._parent(T(a), T(b))
        self._parent(T(b), T(c))
        with self.assertRaisesRegex(Validation, EDGE_CYCLE_MSG):
            self._parent(T(c), T(a))
        # 제안도 순환이면 막는다 — 확인을 누르는 순간 고리가 되면 안 된다
        with self.assertRaisesRegex(Validation, EDGE_CYCLE_MSG):
            self._parent(T(c), T(a), state=EDGE_PROPOSED)

    def test_precedes_cycle_is_rejected_separately_from_parent(self):
        a, b = self._todo("가"), self._todo("나")
        self._parent(T(a), T(b))
        # 상위와 선행은 다른 관계 — 하위를 먼저 끝내야 상위를 끝내는 건 고리가 아니다
        graph_repo.add_edge(self.con, T(b), T(a), REL_PRECEDES)
        with self.assertRaisesRegex(Validation, EDGE_CYCLE_MSG):
            graph_repo.add_edge(self.con, T(a), T(b), REL_PRECEDES)

    def test_rejected_edge_does_not_count_for_cycle_and_is_checked_when_revived(self):
        a, b = self._todo("가"), self._todo("나")
        first = self._parent(T(a), T(b), state=EDGE_PROPOSED)
        graph_repo.set_state(self.con, first["id"], EDGE_REJECTED)
        reverse = self._parent(T(b), T(a))
        self.assertEqual(reverse["state"], EDGE_CONFIRMED)
        with self.assertRaisesRegex(Validation, EDGE_CYCLE_MSG):
            graph_repo.set_state(self.con, first["id"], EDGE_CONFIRMED)

    def test_automatic_writes_never_override_people(self):
        a, b = self._todo("가"), self._todo("나")
        proposed = self._parent(T(a), T(b), state=EDGE_PROPOSED)
        graph_repo.set_state(self.con, proposed["id"], EDGE_REJECTED)
        again = graph_repo.add_edge(
            self.con, T(a), T(b), REL_PARENT, basis=BASIS_TRIGGER, state=EDGE_PROPOSED, created_by=BY_SPAWN
        )
        self.assertEqual(again["state"], EDGE_REJECTED)
        # 사람이 다시 이으면 사람 뜻대로
        mine = self._parent(T(a), T(b))
        self.assertEqual(mine["state"], EDGE_CONFIRMED)

    def test_related_is_stored_once_regardless_of_direction(self):
        a, b = self._todo("가"), self._todo("나")
        graph_repo.add_edge(self.con, T(b), T(a), REL_RELATED)
        graph_repo.add_edge(self.con, T(a), T(b), REL_RELATED)
        self.assertEqual(len(self._edges(REL_RELATED)), 1)

    def test_ancestors_follow_multiple_parents(self):
        context = graph_repo.create_context(self.con, "검색 결과 이상", category_id=self.category["id"])
        a, b, c = self._todo("사진 분석"), self._todo("필터 원인"), self._todo("한국일보 체크")
        self._parent((NODE_CONTEXT, context["id"]), T(a), basis=BASIS_BACKGROUND)
        self._parent(T(a), T(b))
        self._parent(T(c), T(b), state=EDGE_PROPOSED)
        found = graph_repo.ancestors(self.con, T(b))
        self.assertEqual(found[:2], sorted([(NODE_TODO, str(a["id"])), (NODE_TODO, str(c["id"]))]))
        self.assertIn((NODE_CONTEXT, str(context["id"])), found)


class ParentColumnTest(GraphFixture):
    def test_parent_id_is_mirrored_and_follows_changes(self):
        root, second, child = self._todo("설계"), self._todo("검토"), self._todo("API")
        todo_repo.update(self.con, child["id"], parent_id=root["id"])
        edges = self._edges(REL_PARENT)
        self.assertEqual([(e["src_id"], e["dst_id"]) for e in edges], [(str(root["id"]), str(child["id"]))])
        todo_repo.update(self.con, child["id"], parent_id=second["id"])
        edges = self._edges(REL_PARENT)
        self.assertEqual([(e["src_id"], e["dst_id"]) for e in edges], [(str(second["id"]), str(child["id"]))])

    def test_unify_and_manager_parent_edges_follow_parent_id_too(self):
        """이관(unify)·매니저 단계(manager)가 만든 상위 연결도 parent_id 짝이다 — 상위를 바꾸면 옛 연결이 남지 않는다.
        사람이 이은 상위(user)는 그대로 둔다"""
        for creator in ("unify", "manager"):
            with self.subTest(creator=creator):
                old, new, keep, child = self._todo("옛 상위"), self._todo("새 상위"), self._todo("사람이 이은 상위"), self._todo("단계")
                stamp = "2026-11-18T00:00:00+00:00"
                self.con.execute(
                    "INSERT INTO edges(src_kind, src_id, dst_kind, dst_id, relation, basis, evidence, state, created_by,"
                    " created_at, updated_at) VALUES('todo', ?, 'todo', ?, ?, 'background', NULL, ?, ?, ?, ?)",
                    (str(old["id"]), str(child["id"]), REL_PARENT, EDGE_CONFIRMED, creator, stamp, stamp),
                )
                self.con.execute("UPDATE todos SET parent_id=? WHERE id=?", (old["id"], child["id"]))
                self.con.commit()
                self._parent(T(keep), T(child))
                todo_repo.update(self.con, child["id"], parent_id=new["id"])
                sources = sorted(e["src_id"] for e in self._edges(REL_PARENT) if e["dst_id"] == str(child["id"]))
                self.assertEqual(sources, sorted([str(new["id"]), str(keep["id"])]))

    def test_removing_mirrored_edge_clears_parent_id(self):
        root = self._todo("설계")
        child = todo_repo.create(self.con, "API", parent_id=root["id"])
        edge = self._edges(REL_PARENT)[0]
        graph_repo.delete_edge(self.con, edge["id"])
        self.assertIsNone(todo_repo.get(self.con, child["id"])["parent_id"])

    def test_deleting_middle_todo_lifts_children_in_graph(self):
        top, middle, leaf = self._todo("맥락"), self._todo("중간"), self._todo("잎")
        self._parent(T(top), T(middle))
        self._parent(T(middle), T(leaf), state=EDGE_PROPOSED)
        todo_repo.delete(self.con, middle["id"])
        edges = self._edges(REL_PARENT)
        self.assertEqual(len(edges), 1)
        self.assertEqual((edges[0]["src_id"], edges[0]["dst_id"]), (str(top["id"]), str(leaf["id"])))
        self.assertEqual(edges[0]["state"], EDGE_PROPOSED)

    def test_old_parent_ids_become_edges_once(self):
        path = temp_db_path()
        con = connect(path)
        category_id = category_repo.list_all(con)[0]["id"]
        root = todo_repo.create(con, "루트", category_id=category_id)
        child = todo_repo.create(con, "자식", category_id=category_id)
        # 이 기능 전의 DB — 열 값만 있고 연결도 표시도 없다
        con.execute("UPDATE todos SET parent_id=? WHERE id=?", (root["id"], child["id"]))
        con.execute("DELETE FROM edges")
        con.execute("DELETE FROM meta WHERE key=?", (db.PARENT_EDGES_FLAG,))
        con.commit()
        con.close()
        reopened = connect(path)
        rows = reopened.execute("SELECT * FROM edges").fetchall()
        self.assertEqual([(r["src_id"], r["dst_id"], r["relation"]) for r in rows],
                         [(str(root["id"]), str(child["id"]), REL_PARENT)])
        # 열은 그대로 남는다 — 되돌릴 수 있게
        self.assertEqual(todo_repo.get(reopened, child["id"])["parent_id"], root["id"])
        reopened.execute("DELETE FROM edges")
        reopened.commit()
        reopened.close()
        self.assertEqual(connect(path).execute("SELECT COUNT(*) FROM edges").fetchone()[0], 0)


class EvidenceExtractTest(unittest.TestCase):
    def test_keys_urls_and_prs_are_normalized(self):
        text = (
            "관련 Jira: https://hankookilbo.atlassian.net/browse/PFD-5774?focusedCommentId=1 그리고 YAIW-71\n"
            "문서 https://hankookilbo.atlassian.net/wiki/spaces/2/pages/7233175648/AI+DB?xpis=x\n"
            "PR https://github.com/hkilbo/muni/pull/56 · hk-herb-server PR #27 · hkilbo/kt-cms-server#41"
        )
        self.assertEqual(
            evidence.extract(text),
            [
                "jira:PFD-5774",
                "jira:YAIW-71",
                "confluence:7233175648",
                "pr:hkilbo/muni#56",
                "pr:hkilbo/kt-cms-server#41",
                "pr:hkilbo/hk-herb-server#27",
            ],
        )

    def test_lookalikes_are_ignored(self):
        self.assertEqual(evidence.extract("UTF-8 · KT-1차 · L293 · SHA-256 · HK #35 · KT #41 · PR #32"), [])
        self.assertEqual(evidence.extract("fix/KT-1530-status-conflicts"), ["jira:KT-1530"])

    def test_urls(self):
        self.assertEqual(evidence.url_of("jira:PFD-1"), "https://hankookilbo.atlassian.net/browse/PFD-1")
        self.assertEqual(evidence.url_of("pr:hkilbo/muni#5"), "https://github.com/hkilbo/muni/pull/5")
        self.assertIn("pageId=7", evidence.url_of("confluence:7"))
        self.assertEqual(evidence.label_of("pr:hkilbo/muni#5"), "muni#5")


class NoteEvidenceTest(GraphFixture):
    def test_new_todo_and_note_change_follow_keys(self):
        todo = self._todo("YAIW-71 자료라이브러리 조회", note="PFD-6350 참고")
        refs = sorted(e["dst_id"] for e in self._edges(REL_EVIDENCE))
        self.assertEqual(refs, ["jira:PFD-6350", "jira:YAIW-71"])
        # 사람이 이은 근거는 note 가 바뀌어도 남는다
        graph_repo.add_edge(self.con, T(todo), (NODE_DOC, "confluence:99"), REL_EVIDENCE)
        todo_repo.update(self.con, todo["id"], note="이제 근거 없음")
        refs = sorted(e["dst_id"] for e in self._edges(REL_EVIDENCE))
        self.assertEqual(refs, ["confluence:99", "jira:YAIW-71"])

    def test_shared_doc_links_todos_as_related(self):
        a = self._todo("검색 누락", note="YAIW-71")
        b = self._todo("OpenSearch 조회", workspace=self.other, note="YAIW-71 확인")
        related = self._edges(REL_RELATED, BY_SHARED_DOC)
        self.assertEqual(len(related), 1)
        self.assertEqual(related[0]["evidence"], "같은 근거 YAIW-71")
        # 상위로 이어진 쌍이면 관련은 군더더기라 만들지 않는다
        c = self._todo("하위", note="PFD-9")
        self._parent(T(a), T(c))
        self._todo("상위로 이은 쌍", note="PFD-9")
        todo_repo.update(self.con, a["id"], note="YAIW-71 PFD-9")
        pairs = {(e["src_id"], e["dst_id"]) for e in self._edges(REL_RELATED, BY_SHARED_DOC)}
        self.assertNotIn((str(a["id"]), str(c["id"])), pairs)
        # 근거가 빠지면 자동 관련도 걷힌다
        todo_repo.update(self.con, b["id"], note="")
        pairs = {(e["src_id"], e["dst_id"]) for e in self._edges(REL_RELATED, BY_SHARED_DOC)}
        self.assertNotIn((str(a["id"]), str(b["id"])), pairs)

    def test_hub_document_does_not_link_every_pair(self):
        for index in range(SHARED_DOC_MAX_TODOS + 1):
            self._todo(f"배포 항목 {index}", note="정기배포 confluence https://hankookilbo.atlassian.net/wiki/spaces/2/pages/555")
        self.assertEqual(self._edges(REL_RELATED, BY_SHARED_DOC), [])
        self.assertEqual(len(self._edges(REL_EVIDENCE, BY_NOTE)), SHARED_DOC_MAX_TODOS + 1)


class SpawnOriginTest(GraphFixture):
    def setUp(self):
        super().setUp()
        self.origin_todo = self._todo("사진 분석")
        session_repo.register(self.con, "origin-sess", cwd="/tmp")
        session_repo.link_todo(self.con, "origin-sess", self.origin_todo["id"])
        session_repo.register(self.con, "spawned-sess", cwd="/tmp")

    def test_link_after_spawn_proposes_origin_todo_as_trigger(self):
        graph_repo.record_spawn(self.con, "spawned-sess", "origin-sess", 161, "필터 원인")
        child = self._todo("자료ID 6674783 필터 원인")
        session_repo.link_todo(self.con, "spawned-sess", child["id"])
        edges = self._edges(REL_PARENT, BY_SPAWN)
        self.assertEqual(len(edges), 1)
        self.assertEqual((edges[0]["src_id"], edges[0]["dst_id"]), (str(self.origin_todo["id"]), str(child["id"])))
        self.assertEqual((edges[0]["state"], edges[0]["basis"]), (EDGE_PROPOSED, BASIS_TRIGGER))
        self.assertIn("161", edges[0]["evidence"])
        # 수행은 session_todos 그대로 뷰에 보인다
        performs = [e for e in graph_repo.edges_of(self.con, T(child), include_performs=True)
                    if e["relation"] == "performs"]
        self.assertEqual(performs[0]["src_id"], "spawned-sess")

    def test_spawn_recorded_after_link_applies_immediately(self):
        child = self._todo("필터 원인")
        session_repo.link_todo(self.con, "spawned-sess", child["id"])
        made = graph_repo.record_spawn(self.con, "spawned-sess", "origin-sess")
        self.assertEqual(len(made), 1)

    def test_no_origin_session_means_no_proposal(self):
        graph_repo.record_spawn(self.con, "spawned-sess", None, 166, "팀즈 문의")
        child = self._todo("한국일보 체크 시 미노출")
        session_repo.link_todo(self.con, "spawned-sess", child["id"])
        self.assertEqual(self._edges(REL_PARENT, BY_SPAWN), [])


class ForestTest(GraphFixture):
    def _tree(self, top):
        """top: 트리 맨 위 할일(또는 (종류, id)). 그 트리와 전체 응답"""
        kind, ident = top if isinstance(top, tuple) else (NODE_TODO, top["id"])
        key = f"{'c' if kind == NODE_CONTEXT else 't'}{ident}"
        payload = todo_tree.forest(self.con)
        return next(t for t in payload["trees"] if t["key"] == key), payload

    def _flat(self, nodes):
        for node in nodes:
            yield node
            yield from self._flat(node["children"])

    def test_multi_parent_card_appears_once_and_counts_in_both(self):
        a, b, child = self._todo("사진 분석", self.space), self._todo("한국일보 체크", self.space), self._todo("필터 원인")
        self._parent(T(a), T(child))
        self._parent(T(b), T(child), state=EDGE_PROPOSED)
        todo_repo.update(self.con, child["id"], status=STATUS_DONE)
        tree, payload = self._tree(self.space)
        flat = list(self._flat(tree["children"]))
        self.assertEqual([node["id"] for node in flat].count(child["id"]), 1)
        nodes = {node["id"]: node for node in flat}
        # 확정 상위가 주 상위, 제안 상위는 extra 로
        self.assertEqual([c["id"] for c in nodes[a["id"]]["children"]], [child["id"]])
        self.assertEqual(nodes[b["id"]]["extra_children"], [f"t{child['id']}"])
        self.assertEqual(nodes[a["id"]]["progress"], {"done": 1, "total": 1})
        self.assertEqual(nodes[b["id"]]["progress"], {"done": 1, "total": 1})
        self.assertEqual(len(nodes[child["id"]]["parents"]), 2)
        self.assertEqual(payload["proposals"], 1)
        # 상위가 생긴 할일은 제 트리가 아니다
        self.assertNotIn(f"t{child['id']}", [t["key"] for t in payload["trees"]])

    def test_parent_in_other_tree_is_drawn_as_extra_link(self):
        """상위가 둘이고 둘이 다른 트리면 주 상위(먼저 확정한 것) 쪽에 카드, 다른 쪽은 선만"""
        mine = self._todo("검색 누락", self.space)
        foreign = self._todo("YAIW-71 조회", self.other)
        self._parent(T(foreign), T(mine))
        tree, payload = self._tree(self.space)
        self.assertIn(mine["id"], [node["id"] for node in tree["children"][0]["children"]])
        link = next(
            l for l in payload["links"]
            if l["relation"] == REL_PARENT and l["from"] == f"t{foreign['id']}"
        )
        self.assertFalse(link["primary"])
        other_tree, _ = self._tree(self.other)
        self.assertEqual(other_tree["children"][0]["children"][0]["extra_children"], [f"t{mine['id']}"])

    def test_context_is_a_root_and_done_when_everything_under_it_is(self):
        context = graph_repo.create_context(self.con, "검색 결과 이상", category_id=self.category["id"])
        a = self._todo("사진 분석")
        self._parent((NODE_CONTEXT, context["id"]), T(a), basis=BASIS_BACKGROUND)
        tree, _ = self._tree((NODE_CONTEXT, context["id"]))
        self.assertEqual(tree["children"][0]["kind"], NODE_CONTEXT)
        self.assertEqual(tree["children"][0]["children"][0]["id"], a["id"])
        self.assertEqual(tree["progress"]["total"], 1)  # 맥락은 할일 수에 들지 않는다
        todo_repo.update(self.con, a["id"], status=STATUS_DONE)
        tree, _ = self._tree((NODE_CONTEXT, context["id"]))
        self.assertEqual(tree["children"][0]["status"], STATUS_DONE)

    def test_parentless_todo_is_its_own_tree(self):
        loose = self._todo("소속 없음")
        tree, _ = self._tree(loose)
        self.assertEqual(tree["name"], "소속 없음")
        self.assertEqual(tree["children"][0]["id"], loose["id"])

    def test_docs_and_precedes_ride_on_nodes(self):
        a = self._todo("PR 배포", self.space, note="hk-herb-server PR #35")
        b = self._todo("완료 처리", self.space)
        graph_repo.add_edge(self.con, T(a), T(b), REL_PRECEDES)
        tree, _ = self._tree(self.space)
        nodes = {node["id"]: node for node in self._flat(tree["children"])}
        self.assertEqual(nodes[a["id"]]["docs"][0]["url"], "https://github.com/hkilbo/hk-herb-server/pull/35")
        self.assertEqual(nodes[b["id"]]["after"][0]["id"], a["id"])
        self.assertEqual(nodes[a["id"]]["before"][0]["id"], b["id"])


class ApiTest(GraphFixture):
    def test_edges_and_contexts_through_routes(self):
        a, b = self._todo("가"), self._todo("나")
        edge = server.route(self.con, "POST", "/api/edges", {}, {
            "src_kind": "todo", "src_id": a["id"], "dst_kind": "todo", "dst_id": b["id"],
            "relation": REL_PARENT, "basis": BASIS_TRIGGER, "state": EDGE_PROPOSED,
        })
        listed = server.route(self.con, "GET", "/api/graph-proposals", {}, {})["proposals"]
        self.assertEqual(listed[0]["from_title"], "가")
        confirmed = server.route(self.con, "PATCH", f"/api/edges/{edge['id']}", {}, {"state": EDGE_CONFIRMED})
        self.assertEqual(confirmed["state"], EDGE_CONFIRMED)
        server.route(self.con, "DELETE", f"/api/edges/{edge['id']}", {}, None)
        self.assertEqual(self._edges(REL_PARENT), [])
        context = server.route(self.con, "POST", "/api/contexts", {}, {"title": "배경", "category_id": self.category["id"]})
        child = server.route(self.con, "POST", "/api/todos", {}, {"title": "맥락 아래", "context_id": context["id"]})
        # 맥락 카드의 + 로 만든 할일은 그 맥락의 카테고리를 따른다
        self.assertEqual(child["category_id"], self.category["id"])
        self.assertEqual(self._edges(REL_PARENT)[0]["src_kind"], NODE_CONTEXT)


class CliTest(unittest.TestCase):
    def setUp(self):
        os.environ[DB_PATH_ENV] = temp_db_path()
        os.environ.pop(SESSION_ID_ENV, None)
        self.addCleanup(os.environ.pop, DB_PATH_ENV, None)

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            try:
                code = dash.main(list(argv))
            except SystemExit as exit_:
                code = exit_.code
        return code or 0, out.getvalue(), err.getvalue()

    def test_link_edges_and_states(self):
        # 할일 준비는 저장소로 — add-workspace·add-todo 명령은 없다
        con = connect()
        dev = category_repo.get_by_name(con, "개발")["id"]
        todo_repo.create(con, "사진 분석", category_id=dev)
        todo_repo.create(con, "필터 원인", category_id=dev)
        code, out, _ = self.run_cli("link", "상위", "1", "2", "--basis", "계기", "--evidence", "분석 중 발견", "--proposed")
        self.assertEqual(code, 0)
        self.assertIn("상위(계기)", out)
        self.assertIn("proposed", out)
        code, out, _ = self.run_cli("edge", "confirm", "1")
        self.assertIn("confirmed", out)
        code, _, err = self.run_cli("link", "상위", "2", "1", "--basis", "배경")
        self.assertNotEqual(code, 0)
        self.assertIn(EDGE_CYCLE_MSG, err)
        code, out, _ = self.run_cli("add-context", "검색 결과 이상", "--category", "개발")
        self.assertIn("ctx:1", out)
        code, out, _ = self.run_cli("edges", "#2")
        self.assertIn("todo:1 -상위(계기)-> todo:2", out)


if __name__ == "__main__":
    unittest.main()
