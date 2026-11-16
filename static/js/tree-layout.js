// 할일 트리 배치. 루트(워크스페이스)가 왼쪽, 자식이 오른쪽 열로 한 칸씩 나간다.
// 상위가 여럿인 할일은 서버가 고른 주 상위 밑에 한 번만 놓는다 — 다른 상위·선행 선은 tree-map.js 가 긋는다.
// 잎(보이는 자식이 없는 카드)이 위에서부터 한 줄씩 자리를 받고, 부모는 첫 자식과 마지막
// 자식의 가운데에 선다 — 자식이 하나면 일직선, 여럿이면 부채꼴로 퍼진다(참고 이미지의 노드 그래프).
// DOM 을 모르는 순수 함수라 node 로 바로 검사한다 (tests/tree_layout_check.mjs)

// 카드 한 장의 크기. 카드 안 줄(머리·제목 두 줄·꼬리)이 들어가는 높이로 고정한다 —
// 높이가 카드마다 다르면 형제 사이 간격이 들쭉날쭉해지고 선이 카드 가운데를 못 맞춘다
// 높이는 머리·제목 두 줄·관계 줄(근거 문서·다른 상위·선행 칩)·꼬리가 들어가는 만큼
export const CARD_W = 248;
export const CARD_H = 136;
export const COL_GAP = 72; // 열 사이. 곡선이 휘어 들어갈 자리
export const ROW_GAP = 16; // 형제 카드 사이
// 트리와 트리 사이. 트리마다 옅은 구획(레인)을 깔고 그 위쪽에 이름표를 얹으므로
// 이름표 자리(LANE_HEAD)와 구획 아래 여백(LANE_PAD)이 이 안에 들어간다
export const TREE_GAP = 64;
export const LANE_HEAD = 32;
export const LANE_PAD = 16;
const DONE = "done";

/**
 * trees: /api/todo-trees 의 trees. 반환은 그릴 카드(좌표 포함)·연결선·전체 크기.
 * hideDone 이면 끝난 가지를 뺀다. keep 은 숨김에서 빼 줄 할일 id —
 * 방금 완료로 바꾼 카드가 눌린 자리에서 바로 사라지지 않고 흐려진 채 남게 한다
 */
export function layoutForest(trees, { hideDone = false, keep = new Set() } = {}) {
  const cards = [];
  const edges = [];
  const lanes = [];
  const state = { cursor: LANE_HEAD, depth: 0 };
  const options = { hideDone, keep };
  let drawn = 0;
  for (const tree of trees) {
    if (hideDone && tree.complete && !hasKept(tree.children, keep)) continue;
    if (drawn) state.cursor += TREE_GAP - ROW_GAP;
    const top = state.cursor;
    place({ kind: "root", tree, data: tree }, 0, null, state, options, cards, edges);
    lanes.push({ tree, top: top - LANE_HEAD, bottom: state.cursor - ROW_GAP + LANE_PAD });
    drawn += 1;
  }
  const columns = state.depth + 1;
  return {
    cards,
    edges,
    lanes,
    // 주 상위 밖의 연결(다른 상위·선행)을 그릴 때 양 끝 카드를 key 로 찾는다
    byKey: new Map(cards.map((card) => [card.key, card])),
    width: drawn ? columns * CARD_W + (columns - 1) * COL_GAP : 0,
    height: drawn ? state.cursor - ROW_GAP + LANE_PAD : 0,
  };
}

/** 그 노드를 그리는지. 끝났어도 아래에 안 끝난 할일이 있으면 남긴다 — 부모를 빼면 가지가 뜬다 */
export function isVisible(node, { hideDone = false, keep = new Set() } = {}) {
  if (!hideDone || node.status !== DONE || keep.has(node.id)) return true;
  return node.children.some((child) => isVisible(child, { hideDone, keep }));
}

/** 루트에서 그 할일까지 거치는 카드 key. 강조할 길을 고를 때 쓴다 */
export function pathKeys(layout, todoId) {
  const target = layout.cards.find((card) => card.kind === "todo" && card.data.id === todoId);
  const keys = new Set();
  for (let card = target; card; card = card.parent) keys.add(card.key);
  return keys;
}

// 루트 = 워크스페이스(미분류 트리는 id 가 없다). 할일·맥락은 서버가 준 key(t12·c3)
export function cardKey(kind, data) {
  if (kind === "root") return `w${data.workspace.id ?? "none"}`;
  return data.key ?? `t${data.id}`;
}

function place(item, depth, parent, state, options, cards, edges) {
  const card = {
    key: cardKey(item.kind, item.data),
    kind: item.kind,
    tree: item.tree,
    data: item.data,
    parent,
    depth,
    x: depth * (CARD_W + COL_GAP),
    y: 0,
  };
  cards.push(card);
  state.depth = Math.max(state.depth, depth);
  const kids = item.data.children.filter((child) => isVisible(child, options));
  if (!kids.length) {
    card.y = state.cursor;
    state.cursor += CARD_H + ROW_GAP;
    return card;
  }
  const placed = kids.map((child) =>
    place({ kind: child.kind ?? "todo", tree: item.tree, data: child }, depth + 1, card, state, options, cards, edges)
  );
  card.y = (placed[0].y + placed[placed.length - 1].y) / 2;
  placed.forEach((child) => edges.push({ from: card, to: child }));
  return card;
}

function hasKept(nodes, keep) {
  return nodes.some((node) => keep.has(node.id) || hasKept(node.children, keep));
}
