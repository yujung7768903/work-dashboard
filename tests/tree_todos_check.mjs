// 트리 메뉴 할일별 보기 검사 — 진행 중 할일만, 최근 손댄 순으로, 줄마다 자기 트리가 맨 앞이고
// 다른 상위가 있는 트리가 뒤에 붙는지. 다른 트리를 고르면 그 트리 + 카드까지의 가지를 그리는지.
// 실행: node tests/tree_todos_check.mjs (tests/test_tree_todos.py 가 부른다)
import assert from "node:assert/strict";
import {
  activeAt,
  branchTo,
  doingTodos,
  holdersByTodo,
  latestFirst,
  panelTrees,
  treeIdOf,
  treeOfTodo,
} from "../static/js/tree-todos.js";
import { layoutForest } from "../static/js/tree-layout.js";

const node = (id, status, { parents = [], children = [], seen = null, updated = null, kind = "todo", results = [] } = {}) => ({
  key: kind === "context" ? `c${id}` : `t${id}`,
  kind,
  id,
  title: `할일${id}`,
  status,
  parents,
  children,
  results,
  last_session_at: seen,
  updated_at: updated,
  extra_children: [],
});
const parent = (key, state = "confirmed") => ({ key, title: `상위${key}`, state });
// 트리 = 맨 위 노드 하나(상위 없는 할일·맥락). id 는 그 key, 이름은 그 제목
const tree = (top, color = null) => ({
  key: top.key,
  name: top.title,
  category_color: color,
  children: [top],
  complete: false,
  progress: { done: 0, total: 0 },
  counts: {},
});
const primary = (key) => ({ ...parent(key), primary: true });

// 보안(t10): 점검 체계(10, 진행) ─ CORS 제한(11, 진행)
//                               └ 문서(12, 완료)
// 에이전트(c5): 맥락 c5 ─ 정기 점검 제안(20, 할일)
// 자체 점검(t3, 할일) ─ 자체 점검 코드(30, 진행) — 다른 상위가 보안 #10(확정)·에이전트 #20(제안)
//                     ├ 로그 조회(31, 확인 대기)
//                     └ 오래된 진행(32, 진행 — 세션이 잡은 적 없음)
const SECURITY = tree(
  node(10, "doing", {
    seen: "2026-11-17T09:00:00",
    children: [
      node(11, "doing", { parents: [primary("t10")], seen: "2026-11-17T10:00:00", results: [{ key: "r1-t11", children: [] }] }),
      node(12, "done", { parents: [parent("t10")] }),
    ],
  }),
  "#e5484d"
);
const AGENT = tree(node(5, "context", { kind: "context", children: [node(20, "todo", { parents: [primary("c5")] })] }));
const HOME = tree(
  node(3, "todo", {
    children: [
      node(30, "doing", { parents: [primary("t3"), parent("t20", "proposed"), parent("t10")], seen: "2026-11-17T11:00:00" }),
      node(31, "review", { parents: [primary("t3")], seen: "2026-11-17T12:00:00" }),
      node(32, "doing", { parents: [primary("t3")] }),
    ],
  })
);
const TREES = [SECURITY, AGENT, HOME];

{
  const rows = doingTodos(TREES);
  // 진행 중만 — 할일(3·20)·확인 대기(31)·완료(12)·맥락(c5)은 빠진다. 맨 위 할일(10)도 진행 중이면 든다
  // 순서는 세션이 손댄 시각이 최근인 것부터, 한 번도 안 잡힌 32 는 맨 아래
  assert.deepEqual(rows.map((row) => row.node.id), [30, 11, 10, 32]);

  const linked = rows[0];
  assert.equal(linked.home, "t3", "카드가 있는 트리는 자기 맨 위 할일의 트리");
  // 자기 트리가 맨 앞, 다른 상위가 있는 트리는 화면의 트리 순서(보안 → 에이전트)
  assert.deepEqual(linked.trees.map((item) => item.id), ["t3", "t10", "c5"]);
  assert.equal(linked.trees[0].home, true);
  assert.equal(linked.trees[0].name, "할일3", "트리 이름은 맨 위 할일 제목");
  assert.equal(linked.trees[1].home, false);
  assert.equal(linked.trees[1].color, "#e5484d");
  assert.deepEqual(linked.trees[1].via, [{ key: "t10", id: 10, title: "상위t10" }]);
  assert.equal(linked.trees[1].proposed, false, "확정 연결");
  assert.equal(linked.trees[2].proposed, true, "제안뿐인 연결은 제안으로 표시");

  // 같은 트리 안의 상위는 다른 트리로 세지 않는다
  const child = rows[1];
  assert.equal(child.home, "t10");
  assert.deepEqual(child.trees.map((item) => item.id), ["t10"]);
  assert.deepEqual(child.trees[0].via, []);
}

{
  // 같은 트리에 상위가 둘이면 트리는 한 번, 상위는 둘 다. 하나라도 확정이면 제안 표시가 아니다
  const both = tree(node(4, "todo", { children: [node(40, "doing", { parents: [primary("t4"), parent("t10", "proposed"), parent("t11")] })] }));
  const [row] = doingTodos([SECURITY, both]).filter((item) => item.node.id === 40);
  assert.deepEqual(row.trees.map((item) => item.id), ["t4", "t10"]);
  assert.deepEqual(row.trees[1].via.map((item) => item.key), ["t10", "t11"]);
  assert.equal(row.trees[1].proposed, false);
}

{
  // 맥락 상위는 할일 id 가 없다
  const ctx = tree(node(6, "todo", { children: [node(41, "doing", { parents: [primary("t6"), parent("c5")] })] }));
  const [row] = doingTodos([AGENT, ctx]).filter((item) => item.node.id === 41);
  assert.deepEqual(row.trees[1].via, [{ key: "c5", id: null, title: "상위c5" }]);
}

{
  assert.equal(treeIdOf(SECURITY), "t10");
  assert.equal(treeOfTodo(TREES, 31), HOME, "할일 카드가 있는 트리");
  assert.equal(treeOfTodo(TREES, 10), SECURITY, "맨 위 할일 자신도 그 트리");
  assert.equal(treeOfTodo(TREES, 999), null);
}

{
  // 자기 트리를 고르면 그 트리만
  assert.deepEqual(panelTrees(TREES, { treeId: "t10", home: "t10", focusKey: "t11" }), [SECURITY]);
  // home 을 모르면(트리별 목록에서 연 패널) 고른 트리만
  assert.deepEqual(panelTrees(TREES, { treeId: "t10", focusKey: "t11" }), [SECURITY]);
  // 없어진 트리
  assert.deepEqual(panelTrees(TREES, { treeId: "t99", home: "t10", focusKey: "t11" }), []);

  // 다른 트리를 고르면 그 트리 + 카드까지의 가지 — 고른 트리가 위(패널 제목), 가지가 아래
  const shown = panelTrees(TREES, { treeId: "t10", home: "t3", focusKey: "t30" });
  assert.equal(shown.length, 2);
  assert.equal(shown[0], SECURITY);
  assert.equal(treeIdOf(shown[1]), "t3");
  assert.deepEqual(shown[1].children.map((item) => item.id), [3]);
  assert.deepEqual(shown[1].children[0].children.map((item) => item.id), [30], "같은 트리의 다른 할일(31·32)은 빠진다");

  // 판에 카드가 있어야 가운데로 데려가 강조한다 — 고른 트리의 상위(#10)와 카드(#30)가 함께 놓인다
  const layout = layoutForest(shown);
  assert.ok(layout.byKey.get("t10"));
  assert.ok(layout.byKey.get("t30"));
}

{
  // 가지는 거쳐 가는 카드의 다른 자식·결과물을 빼고, 카드 아래는 그대로 둔다
  const deep = tree(
    node(9, "doing", {
      children: [
        node(50, "doing", {
          results: [{ key: "r9-t50", children: [] }],
          children: [
            node(51, "doing", { children: [node(52, "todo")], results: [{ key: "r8-t51", children: [] }] }),
            node(53, "todo"),
          ],
        }),
        node(54, "todo"),
      ],
    })
  );
  const branch = branchTo(deep, "t51");
  const top = branch.children[0];
  assert.deepEqual(branch.children.map((item) => item.id), [9]);
  assert.deepEqual(top.children.map((item) => item.id), [50]);
  assert.deepEqual(top.children[0].children.map((item) => item.id), [51]);
  assert.deepEqual(top.children[0].results, [], "거쳐 가는 카드의 결과물은 뺀다");
  assert.deepEqual(top.children[0].children[0].children.map((item) => item.id), [52]);
  assert.deepEqual(top.children[0].children[0].results, [{ key: "r8-t51", children: [] }], "카드의 결과물은 그대로");
  // 원래 트리는 건드리지 않는다
  assert.equal(deep.children[0].children.length, 2);
  assert.equal(deep.children[0].children[0].children.length, 2);
  assert.equal(branchTo(deep, "t999"), null);
}

{
  // 할일별 순서 = 연결 세션의 마지막 작업 시각(last_session_at)과 할일 자체의 수정 시각(updated_at) 중
  // 더 최근 값의 내림차순. 둘 다 없으면 맨 아래
  const kids = [
    node(60, "doing", { seen: "2026-11-17T08:00:00+00:00", updated: "2026-11-17T13:00:00+00:00" }),
    node(61, "doing", { seen: "2026-11-17T12:00:00+00:00", updated: "2026-11-17T01:00:00+00:00" }),
    node(62, "doing", { updated: "2026-11-17T12:30:00+00:00" }),
    node(63, "doing"),
  ];
  const mixed = tree(node(7, "todo", { children: kids }));
  assert.deepEqual(doingTodos([mixed]).map((row) => row.node.id), [60, 62, 61, 63]);
  assert.equal(activeAt(kids[0]), "2026-11-17T13:00:00+00:00", "수정이 더 최근이면 수정 시각");
  assert.equal(activeAt(kids[1]), "2026-11-17T12:00:00+00:00", "세션이 더 최근이면 세션 시각");
  assert.equal(activeAt(kids[3]), null);
}

{
  // 트리별 목록의 형제 순서 — 그 줄과 그 아래(주 상위로 붙은 하위 전부) 중 가장 최근 값. 하위에서 방금 일한
  // 상위가 위로 온다. 맥락은 세션이 없어 자기 수정 시각과 하위로 선다
  const old = node(70, "done", {
    updated: "2026-11-01T00:00:00+00:00",
    children: [node(71, "doing", { seen: "2026-11-17T09:00:00+00:00" })],
  });
  const fresh = node(72, "todo", { updated: "2026-11-16T00:00:00+00:00" });
  const ctx = node(8, "context", { kind: "context", updated: "2026-10-01T00:00:00+00:00" });
  const never = node(73, "todo");
  const siblings = [never, fresh, ctx, old];
  assert.deepEqual(latestFirst(siblings).map((item) => item.key), ["t70", "t72", "c8", "t73"]);
  assert.deepEqual(siblings.map((item) => item.key), ["t73", "t72", "c8", "t70"], "원래 배열은 그대로 — 맵이 같은 children 을 쓴다");
  // 같으면 원래 순서
  assert.deepEqual(latestFirst([node(80, "todo"), node(81, "todo")]).map((item) => item.id), [80, 81]);
}

{
  // 매니저 탭 보조 세션 줄(/api/manager?part=helpers 의 items) → 할일 id 별로 그 할일을 지금 잡은 보조 세션.
  // 이름은 앞의 '보조N' 만 — 할일 제목은 줄에 이미 있다
  const held = holdersByTodo([
    { session_id: "s1", name: "보조5 | 트리 색상 바", status: "작업 중", card: { todo_id: 403 } },
    { session_id: "s2", name: "보조2 | 원래 제목 (지금 이름: #399 | 고친 제목)", status: "결정 대기", card: { todo_id: 399 } },
    { session_id: "s3", name: "보조7 | 할일 없음", status: "작업 중", card: null },
    { session_id: "s4", name: "이름만 다른 세션", status: "쉼", card: { todo_id: 403 } },
  ]);
  assert.deepEqual([...held.keys()].sort(), [399, 403]);
  assert.deepEqual(held.get(403), [
    { label: "보조5", status: "작업 중" },
    { label: "이름만 다른 세션", status: "쉼" },
  ]);
  assert.deepEqual(held.get(399), [{ label: "보조2", status: "결정 대기" }]);
  assert.equal(holdersByTodo(undefined).size, 0, "매니저가 없거나 칸이 깨지면 빈 표");
}

console.log("tree todos ok");
