// 트리 메뉴의 할일별 보기 — 무엇을 어떤 순서로 세우고, 줄마다 어느 트리를 붙이고, 패널에 무엇을 그리는지.
// 진행 중 = 할일 상태 doing (보드 상태별 뷰의 '진행중' 칸과 같은 기준). 순서는 가장 최근에 작업하거나 고친 것이
// 위로 — 연결 세션이 마지막으로 살아 있던 시각(last_session_at)과 할일 자체의 수정 시각(updated_at) 중 더 최근
// 값(activeAt). 둘 다 없는 것은 아래. 트리별 목록의 형제 순서(latestFirst)도 같은 값을 쓴다.
// 줄 왼쪽 막대는 지금 떠 있는 보조 세션이 잡은 할일(holdersByTodo) — 매니저 탭 보조 세션 목록과 같은 판정이다.
// 할일 카드는 자기 트리(워크스페이스, 없으면 미분류) 하나에만 그려지고, 다른 트리와는 '다른 상위' 연결로만
// 이어진다(app/services/todo_tree.py). 그래서 줄에 붙는 트리 맨 앞은 늘 카드가 있는 자기 트리고,
// 다른 상위가 있는 트리가 뒤에 붙는다. 다른 트리를 고르면 그 트리 + 자기 트리에서 카드까지의 가지를 함께
// 그려 카드가 판에 있게 하고, 그 트리의 상위에서 카드로 선이 그어진다.
// DOM 을 모르는 순수 함수라 node 로 바로 검사한다 (tests/tree_todos_check.mjs)

export const UNASSIGNED_TREE = "none";
const DOING = "doing";
const TODO = "todo";
const PROPOSED = "proposed";
// 매니저 spawn 이 붙이는 세션 이름 머리 '보조N | 제목' (매니저 spawn.helper_name)
const HELPER_LABEL = /^보조\d+/;

// 미분류 트리는 워크스페이스 id 가 없어 글자 키로 부른다
export function treeIdOf(tree) {
  return tree.workspace.id ?? UNASSIGNED_TREE;
}

/**
 * 진행 중 할일 줄. [{ node, home, trees }] — home 은 카드가 있는 트리 id,
 * trees 는 [{ id, name, color, home, proposed, via }] 로 자기 트리가 맨 앞, 나머지는 트리 순서.
 * name 이 null 이면 미분류. proposed 는 그 트리와의 연결이 전부 아직 제안일 때.
 * via 는 그 트리 안에서 이 할일을 하위로 둔 상위들 [{ key, id, title }] (자기 트리면 빈 배열)
 */
export function doingTodos(trees) {
  const where = new Map();
  const order = [];
  trees.forEach((tree) =>
    walk(tree.children, (node) => {
      where.set(node.key, tree);
      order.push(node);
    })
  );
  const treeRank = new Map(trees.map((tree, index) => [treeIdOf(tree), index]));
  return order
    .filter((node) => (node.kind ?? TODO) === TODO && node.status === DOING)
    .map((node) => ({ node, home: treeIdOf(where.get(node.key)), trees: memberTrees(node, where, treeRank) }))
    .sort(byRecency);
}

/**
 * 패널에 그릴 트리. 고른 트리가 카드의 자기 트리면 그 트리만, 다른 트리면 그 트리 + 자기 트리에서 카드까지의
 * 가지. 고른 트리가 없어졌으면(다시 받는 사이 지워짐) 빈 배열
 */
export function panelTrees(trees, { treeId, home = null, focusKey = null }) {
  const chosen = trees.find((tree) => treeIdOf(tree) === treeId);
  if (!chosen) return [];
  if (home == null || home === treeId || focusKey == null) return [chosen];
  const own = trees.find((tree) => treeIdOf(tree) === home);
  const branch = own ? branchTo(own, focusKey) : null;
  return branch ? [chosen, branch] : [chosen];
}

/**
 * 루트에서 그 카드까지 한 줄기만 남긴 트리. 카드 아래(하위·결과물)는 그대로 두고, 거쳐 가는 카드의
 * 다른 가지·결과물은 뺀다 — 다른 트리 옆에 미분류처럼 큰 트리가 통째로 깔리면 카드를 찾기 어렵다.
 * 루트 카드의 진행률·상태별 개수는 원래 트리 것 그대로다. 카드가 없으면 null
 */
export function branchTo(tree, key) {
  const path = findPath(tree.children, key);
  if (!path) return null;
  let below = path[path.length - 1];
  for (let index = path.length - 2; index >= 0; index -= 1) {
    below = { ...path[index], children: [below], results: [] };
  }
  return { ...tree, children: [below] };
}

function memberTrees(node, where, treeRank) {
  const home = where.get(node.key);
  const found = new Map([[treeIdOf(home), entry(home, true)]]);
  (node.parents ?? []).forEach((parent) => {
    const tree = where.get(parent.key);
    if (!tree || tree === home) return;
    const id = treeIdOf(tree);
    const item = found.get(id) ?? entry(tree, false);
    item.proposed = item.via.length ? item.proposed && parent.state === PROPOSED : parent.state === PROPOSED;
    item.via.push({ key: parent.key, id: idOf(parent.key), title: parent.title });
    found.set(id, item);
  });
  const [own, ...others] = [...found.values()];
  others.sort((left, right) => treeRank.get(left.id) - treeRank.get(right.id));
  return [own, ...others];
}

function entry(tree, home) {
  return {
    id: treeIdOf(tree),
    name: tree.workspace.name ?? null,
    color: tree.workspace.category_color ?? null,
    home,
    proposed: false,
    via: [],
  };
}

/**
 * 그 할일을 마지막으로 작업하거나 고친 시각 — 연결 세션의 last_session_at 과 할일의 updated_at 중 더 최근 것.
 * 둘 다 서버 now()(UTC ISO 초 단위)라 글자 비교가 곧 시각 비교다. 둘 다 없으면 null
 */
export function activeAt(node) {
  const seen = node.last_session_at ?? "";
  const updated = node.updated_at ?? "";
  return (seen > updated ? seen : updated) || null;
}

/**
 * 트리별 목록의 형제 순서. 그 줄과 그 아래(주 상위로 붙은 하위 전부) 중 가장 최근 activeAt 이 위로 —
 * 하위에서 방금 일한 상위가 아래로 묻히지 않게. 같으면 받은 순서 그대로. 받은 배열은 건드리지 않는다
 * (맵·패널이 같은 children 순서로 카드를 놓는다)
 */
export function latestFirst(nodes) {
  const latest = new Map();
  const latestOf = (node) => {
    if (!latest.has(node)) {
      latest.set(node, (node.children ?? []).reduce((best, kid) => later(best, latestOf(kid)), activeAt(node) ?? ""));
    }
    return latest.get(node);
  };
  return [...nodes].sort((left, right) => newerFirst(latestOf(left), latestOf(right)));
}

/**
 * 매니저 탭 보조 세션 줄(/api/manager?part=helpers 의 items — manager.py 보조 --json 에 대시보드가
 * 붙인 card) → Map(할일 id → [{ label, status }]). card 는 그 세션이 가장 최근에 연결한 할일이다.
 * label 은 이름 앞의 '보조N' (할일 제목은 줄에 이미 있다), 없으면 이름 그대로
 */
export function holdersByTodo(helpers) {
  const found = new Map();
  (helpers ?? []).forEach((helper) => {
    const todoId = helper.card?.todo_id;
    if (todoId == null) return;
    const name = helper.name ?? "";
    const label = HELPER_LABEL.exec(name)?.[0] ?? name;
    found.set(todoId, [...(found.get(todoId) ?? []), { label, status: helper.status ?? null }]);
  });
  return found;
}

// 같으면 목록에 나오는 순서 그대로(정렬은 안정적이다)
function byRecency(left, right) {
  return newerFirst(activeAt(left.node) ?? "", activeAt(right.node) ?? "");
}

function newerFirst(a, b) {
  if (a === b) return 0;
  return a < b ? 1 : -1;
}

function later(a, b) {
  return a > b ? a : b;
}

function findPath(nodes, key) {
  for (const node of nodes) {
    if (node.key === key) return [node];
    const rest = findPath(node.children, key);
    if (rest) return [node, ...rest];
  }
  return null;
}

function walk(nodes, visit) {
  nodes.forEach((node) => {
    visit(node);
    walk(node.children, visit);
  });
}

// t12 → 12 (할일), c3 → null (맥락은 할일 id 가 아니다)
function idOf(key) {
  return /^t\d+$/.test(key) ? Number(key.slice(1)) : null;
}
