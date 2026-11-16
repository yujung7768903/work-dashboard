// 트리 Map 배치 검사. 루트가 왼쪽, 자식이 오른쪽 열로, 부모가 자식들 가운데에 서는지 본다.
// 실행: node tests/tree_layout_check.mjs (tests/test_tree_layout.py 가 부른다)
import assert from "node:assert/strict";
import {
  CARD_H,
  CARD_W,
  COL_GAP,
  LANE_HEAD,
  LANE_PAD,
  ROW_GAP,
  isVisible,
  layoutForest,
  pathKeys,
} from "../static/js/tree-layout.js";

const todo = (id, status, children = []) => ({ id, title: `#${id}`, status, children });
const tree = (id, children, complete = false) => ({ workspace: { id, name: `w${id}` }, children, complete });

// 결제 개편: 설계(진행) ─ API(완료) ─ 엔드포인트(대기)
//                       └ 문서(완료)
//           배포(확인 대기)
const PAYMENT = tree(1, [
  todo(11, "doing", [todo(12, "done", [todo(13, "todo")]), todo(14, "done")]),
  todo(15, "review"),
]);
const FINISHED = tree(2, [todo(21, "done")], true);

{
  const layout = layoutForest([PAYMENT, FINISHED]);
  const at = (key) => layout.cards.find((card) => card.key === key);
  // 깊이가 곧 열 — 루트 0, 설계 1, API 2, 엔드포인트 3
  assert.equal(at("w1").x, 0);
  assert.equal(at("t11").x, CARD_W + COL_GAP);
  assert.equal(at("t13").x, 3 * (CARD_W + COL_GAP));
  // 잎은 위에서부터 한 줄씩: 엔드포인트, 문서, 배포. 맨 위는 트리 이름표 자리만큼 내려온다
  assert.equal(at("t13").y, LANE_HEAD);
  assert.equal(at("t14").y, LANE_HEAD + CARD_H + ROW_GAP);
  assert.equal(at("t15").y, LANE_HEAD + 2 * (CARD_H + ROW_GAP));
  // 자식이 하나면 일직선, 여럿이면 가운데
  assert.equal(at("t12").y, at("t13").y);
  assert.equal(at("t11").y, (at("t12").y + at("t14").y) / 2);
  assert.equal(at("w1").y, (at("t11").y + at("t15").y) / 2);
  // 두 번째 트리는 첫 트리 아래, 형제 간격보다 넓게 떨어진다
  assert.ok(at("w2").y - at("t15").y > CARD_H + ROW_GAP);
  assert.equal(layout.edges.length, 6);
  // 트리마다 구획 하나. 두 구획은 겹치지 않는다
  assert.equal(layout.lanes.length, 2);
  assert.ok(layout.lanes[0].bottom < layout.lanes[1].top);
  assert.ok(layout.lanes[1].top < at("w2").y);
  assert.equal(layout.width, 4 * CARD_W + 3 * COL_GAP);
}

{
  // 완료 숨김: 끝난 트리는 통째로, 끝난 가지는 빠지지만 아래에 안 끝난 일이 있는 완료 카드는 남는다
  const layout = layoutForest([PAYMENT, FINISHED], { hideDone: true });
  const keys = layout.cards.map((card) => card.key);
  assert.ok(!keys.includes("w2"));
  assert.ok(keys.includes("t12"), "엔드포인트(대기)를 잇는 API(완료)는 남아야 한다");
  assert.ok(!keys.includes("t14"), "아래가 다 끝난 문서(완료)는 빠진다");
  assert.equal(isVisible(PAYMENT.children[0].children[1], { hideDone: true }), false);
}

{
  // 방금 완료로 바꾼 카드는 숨김이어도 남는다 (keep)
  const layout = layoutForest([PAYMENT, FINISHED], { hideDone: true, keep: new Set([14, 21]) });
  const keys = layout.cards.map((card) => card.key);
  assert.ok(keys.includes("t14"));
  assert.ok(keys.includes("w2"), "keep 이 걸린 할일이 있는 완료 트리는 남는다");
}

{
  // 강조 길: 루트에서 그 할일까지
  const layout = layoutForest([PAYMENT]);
  assert.deepEqual([...pathKeys(layout, 13)].sort(), ["t11", "t12", "t13", "w1"]);
  assert.equal(pathKeys(layout, 999).size, 0);
}

{
  // 할일 없는 트리는 루트 카드 하나
  const layout = layoutForest([tree(3, [])]);
  assert.equal(layout.cards.length, 1);
  assert.equal(layout.height, LANE_HEAD + CARD_H + LANE_PAD);
  assert.equal(layoutForest([]).width, 0);
}

console.log("tree layout ok");
