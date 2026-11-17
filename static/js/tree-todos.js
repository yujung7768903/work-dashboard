// 트리 메뉴의 할일별 보기 — 무엇을 어떤 순서로 세우고, 줄마다 어느 트리를 붙이고, 패널에 무엇을 그리는지.
// 진행 중 = 할일 상태 doing (보드 상태별 뷰의 '진행중' 칸과 같은 기준). 순서도 그 칸과 같다 — 세션이 방금
// 손댄 것이 위로(last_session_at), 한 번도 안 잡힌 것은 아래.
// 할일 카드는 자기 트리(워크스페이스, 없으면 미분류) 하나에만 그려지고, 다른 트리와는 '다른 상위' 연결로만
// 이어진다(app/services/todo_tree.py). 그래서 줄에 붙는 트리 맨 앞은 늘 카드가 있는 자기 트리고,
// 다른 상위가 있는 트리가 뒤에 붙는다. 다른 트리를 고르면 그 트리 + 자기 트리에서 카드까지의 가지를 함께
// 그려 카드가 판에 있게 하고, 그 트리의 상위에서 카드로 선이 그어진다.
// DOM 을 모르는 순수 함수라 node 로 바로 검사한다 (tests/tree_todos_check.mjs)

export const UNASSIGNED_TREE = "none";
const DOING = "doing";
const TODO = "todo";
const PROPOSED = "proposed";

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

// 상태별 뷰(static/js/kanban.js)와 같은 비교. 같으면 목록에 나오는 순서 그대로(정렬은 안정적이다)
function byRecency(left, right) {
  const a = left.node.last_session_at ?? "";
  const b = right.node.last_session_at ?? "";
  if (a === b) return 0;
  return a < b ? 1 : -1;
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
