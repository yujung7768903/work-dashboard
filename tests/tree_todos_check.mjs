// 트리 메뉴 할일별 보기 검사 — 진행 중 할일만, 최근 손댄 순으로, 줄마다 자기 트리가 맨 앞이고
// 다른 상위가 있는 트리가 뒤에 붙는지. 다른 트리를 고르면 그 트리 + 카드까지의 가지를 그리는지.
// 실행: node tests/tree_todos_check.mjs (tests/test_tree_todos.py 가 부른다)
import assert from "node:assert/strict";
import { branchTo, doingTodos, panelTrees, treeIdOf, UNASSIGNED_TREE } from "../static/js/tree-todos.js";
import { layoutForest } from "../static/js/tree-layout.js";

const node = (id, status, { parents = [], children = [], seen = null, kind = "todo", results = [] } = {}) => ({
  key: kind === "context" ? `c${id}` : `t${id}`,
  kind,
  id,
  title: `할일${id}`,
  status,
  parents,
  children,
  results,
  last_session_at: seen,
  extra_children: [],
});
const parent = (key, state = "confirmed") => ({ key, title: `상위${key}`, state });
const tree = (id, name, children, color = null) => ({
  workspace: { id, name, category_color: color },
  children,
  complete: false,
  progress: { done: 0, total: 0 },
  counts: {},
});

// 보안(1): 점검 체계(10, 진행) ─ CORS 제한(11, 진행)
//                             └ 문서(12, 완료)
// 에이전트(2): 맥락 c5 ─ 정기 점검 제안(20, 할일)
// 미분류: 자체 점검 코드(30, 진행) — 상위가 보안 #10(확정)·에이전트 #20(제안)
//        로그 조회(31, 확인 대기), 오래된 진행(32, 진행 — 세션이 잡은 적 없음)
const SECURITY = tree(1, "보안", [
  node(10, "doing", {
    seen: "2026-11-17T09:00:00",
    children: [
      node(11, "doing", { parents: [{ ...parent("t10"), primary: true }], seen: "2026-11-17T10:00:00", results: [{ key: "r1-t11", children: [] }] }),
      node(12, "done", { parents: [parent("t10")] }),
    ],
  }),
], "#e5484d");
const AGENT = tree(2, "에이전트", [
  node(5, "context", { kind: "context", children: [node(20, "todo", { parents: [parent("c5")] })] }),
]);
const LOOSE = tree(null, null, [
  node(30, "doing", { parents: [parent("t20", "proposed"), parent("t10")], seen: "2026-11-17T11:00:00" }),
  node(31, "review", { seen: "2026-11-17T12:00:00" }),
  node(32, "doing"),
]);
const TREES = [SECURITY, AGENT, LOOSE];

{
  const rows = doingTodos(TREES);
  // 진행 중만 — 할일(20)·확인 대기(31)·완료(12)·맥락(c5)은 빠진다
  // 순서는 세션이 손댄 시각이 최근인 것부터, 한 번도 안 잡힌 32 는 맨 아래
  assert.deepEqual(rows.map((row) => row.node.id), [30, 11, 10, 32]);

  const loose = rows[0];
  assert.equal(loose.home, UNASSIGNED_TREE, "카드가 있는 트리는 미분류");
  // 자기 트리가 맨 앞, 다른 상위가 있는 트리는 화면의 트리 순서(보안 → 에이전트)
  assert.deepEqual(loose.trees.map((item) => item.id), [UNASSIGNED_TREE, 1, 2]);
  assert.equal(loose.trees[0].home, true);
  assert.equal(loose.trees[0].name, null, "미분류는 이름이 없다 — 화면이 '미분류' 로 쓴다");
  assert.equal(loose.trees[1].home, false);
  assert.equal(loose.trees[1].color, "#e5484d");
  assert.deepEqual(loose.trees[1].via, [{ key: "t10", id: 10, title: "상위t10" }]);
  assert.equal(loose.trees[1].proposed, false, "확정 연결");
  assert.equal(loose.trees[2].proposed, true, "제안뿐인 연결은 제안으로 표시");

  // 같은 트리 안의 상위는 다른 트리로 세지 않는다
  const child = rows[1];
  assert.equal(child.home, 1);
  assert.deepEqual(child.trees.map((item) => item.id), [1]);
  assert.deepEqual(child.trees[0].via, []);
}

{
  // 같은 트리에 상위가 둘이면 트리는 한 번, 상위는 둘 다. 하나라도 확정이면 제안 표시가 아니다
  const both = tree(null, null, [node(40, "doing", { parents: [parent("t10", "proposed"), parent("t11")] })]);
  const [row] = doingTodos([SECURITY, both]).filter((item) => item.node.id === 40);
  assert.deepEqual(row.trees.map((item) => item.id), [UNASSIGNED_TREE, 1]);
  assert.deepEqual(row.trees[1].via.map((item) => item.key), ["t10", "t11"]);
  assert.equal(row.trees[1].proposed, false);
}

{
  // 맥락 상위는 할일 id 가 없다
  const ctx = tree(null, null, [node(41, "doing", { parents: [parent("c5")] })]);
  const [row] = doingTodos([AGENT, ctx]).filter((item) => item.node.id === 41);
  assert.deepEqual(row.trees[1].via, [{ key: "c5", id: null, title: "상위c5" }]);
}

{
  // 자기 트리를 고르면 그 트리만
  assert.deepEqual(panelTrees(TREES, { treeId: 1, home: 1, focusKey: "t11" }), [SECURITY]);
  // home 을 모르면(트리별 목록에서 연 패널) 고른 트리만
  assert.deepEqual(panelTrees(TREES, { treeId: 1, focusKey: "t11" }), [SECURITY]);
  // 없어진 트리
  assert.deepEqual(panelTrees(TREES, { treeId: 99, home: 1, focusKey: "t11" }), []);

  // 다른 트리를 고르면 그 트리 + 카드까지의 가지 — 고른 트리가 위(패널 제목), 가지가 아래
  const shown = panelTrees(TREES, { treeId: 1, home: UNASSIGNED_TREE, focusKey: "t30" });
  assert.equal(shown.length, 2);
  assert.equal(shown[0], SECURITY);
  assert.equal(treeIdOf(shown[1]), UNASSIGNED_TREE);
  assert.deepEqual(shown[1].children.map((item) => item.id), [30], "미분류의 다른 할일(31·32)은 빠진다");

  // 판에 카드가 있어야 가운데로 데려가 강조한다 — 고른 트리의 상위(#10)와 카드(#30)가 함께 놓인다
  const layout = layoutForest(shown);
  assert.ok(layout.byKey.get("t10"));
  assert.ok(layout.byKey.get("t30"));
}

{
  // 가지는 거쳐 가는 카드의 다른 자식·결과물을 빼고, 카드 아래는 그대로 둔다
  const deep = tree(3, "깊은", [
    node(50, "doing", {
      results: [{ key: "r9-t50", children: [] }],
      children: [
        node(51, "doing", { children: [node(52, "todo")], results: [{ key: "r8-t51", children: [] }] }),
        node(53, "todo"),
      ],
    }),
    node(54, "todo"),
  ]);
  const branch = branchTo(deep, "t51");
  assert.deepEqual(branch.children.map((item) => item.id), [50]);
  assert.deepEqual(branch.children[0].children.map((item) => item.id), [51]);
  assert.deepEqual(branch.children[0].results, [], "거쳐 가는 카드의 결과물은 뺀다");
  assert.deepEqual(branch.children[0].children[0].children.map((item) => item.id), [52]);
  assert.deepEqual(branch.children[0].children[0].results, [{ key: "r8-t51", children: [] }], "카드의 결과물은 그대로");
  // 원래 트리는 건드리지 않는다
  assert.equal(deep.children.length, 2);
  assert.equal(deep.children[0].children.length, 2);
  assert.equal(branchTo(deep, "t999"), null);
}

console.log("tree todos ok");
