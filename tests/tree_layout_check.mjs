// 트리 Map 배치 검사. 맨 위 할일이 왼쪽, 자식이 오른쪽 열로, 부모가 자식들 가운데에 서는지 본다.
// 실행: node tests/tree_layout_check.mjs (tests/test_tree_layout.py 가 부른다)
import assert from "node:assert/strict";
import {
  CARD_H,
  CARD_W,
  COL_GAP,
  LANE_HEAD,
  LANE_PAD,
  MORE,
  RESULT,
  RESULT_SHOW,
  ROW_GAP,
  isVisible,
  layoutForest,
  pathKeys,
} from "../static/js/tree-layout.js";

const todo = (id, status, children = []) => ({ id, title: `#${id}`, status, children });
// 트리 = 맨 위 할일 하나(상위 없는 할일). 그 카드가 트리의 첫 카드다 — 워크스페이스 루트 카드는 없다
const tree = (id, children, complete = false) => ({
  key: `t${id}`,
  name: `#${id}`,
  children: [todo(id, complete ? "done" : "doing", children)],
  complete,
});

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
  assert.equal(at("t1").x, 0);
  assert.equal(at("t11").x, CARD_W + COL_GAP);
  assert.equal(at("t13").x, 3 * (CARD_W + COL_GAP));
  // 잎은 위에서부터 한 줄씩: 엔드포인트, 문서, 배포. 맨 위는 트리 이름표 자리만큼 내려온다
  assert.equal(at("t13").y, LANE_HEAD);
  assert.equal(at("t14").y, LANE_HEAD + CARD_H + ROW_GAP);
  assert.equal(at("t15").y, LANE_HEAD + 2 * (CARD_H + ROW_GAP));
  // 자식이 하나면 일직선, 여럿이면 가운데
  assert.equal(at("t12").y, at("t13").y);
  assert.equal(at("t11").y, (at("t12").y + at("t14").y) / 2);
  assert.equal(at("t1").y, (at("t11").y + at("t15").y) / 2);
  // 두 번째 트리는 첫 트리 아래, 형제 간격보다 넓게 떨어진다
  assert.ok(at("t2").y - at("t15").y > CARD_H + ROW_GAP);
  assert.equal(layout.edges.length, 6);
  // 트리마다 구획 하나. 두 구획은 겹치지 않는다
  assert.equal(layout.lanes.length, 2);
  assert.ok(layout.lanes[0].bottom < layout.lanes[1].top);
  assert.ok(layout.lanes[1].top < at("t2").y);
  assert.equal(layout.width, 4 * CARD_W + 3 * COL_GAP);
}

{
  // 완료 숨김: 끝난 트리는 통째로, 끝난 가지는 빠지지만 아래에 안 끝난 일이 있는 완료 카드는 남는다
  const layout = layoutForest([PAYMENT, FINISHED], { hideDone: true });
  const keys = layout.cards.map((card) => card.key);
  assert.ok(!keys.includes("t2"));
  assert.ok(keys.includes("t12"), "엔드포인트(대기)를 잇는 API(완료)는 남아야 한다");
  assert.ok(!keys.includes("t14"), "아래가 다 끝난 문서(완료)는 빠진다");
  assert.equal(isVisible(PAYMENT.children[0].children[0].children[1], { hideDone: true }), false);
}

{
  // 방금 완료로 바꾼 카드는 숨김이어도 남는다 (keep)
  const layout = layoutForest([PAYMENT, FINISHED], { hideDone: true, keep: new Set([14, 21]) });
  const keys = layout.cards.map((card) => card.key);
  assert.ok(keys.includes("t14"));
  assert.ok(keys.includes("t2"), "keep 이 걸린 할일이 있는 완료 트리는 남는다");
}

{
  // 강조 길: 맨 위 할일에서 그 할일까지
  const layout = layoutForest([PAYMENT]);
  assert.deepEqual([...pathKeys(layout, 13)].sort(), ["t1", "t11", "t12", "t13"]);
  assert.equal(pathKeys(layout, 999).size, 0);
}

{
  // 아래가 없는 트리는 맨 위 할일 카드 하나
  const layout = layoutForest([tree(3, [])]);
  assert.equal(layout.cards.length, 1);
  assert.equal(layout.height, LANE_HEAD + CARD_H + LANE_PAD);
  assert.equal(layoutForest([]).width, 0);
}

{
  // 세션 결과물: 할일 오른쪽 열에 하위 할일 다음 잎으로. 많으면 RESULT_SHOW 장 + '+N 더' 한 장, 펼치면 다
  const result = (id) => ({ key: `r${id}-t31`, kind: RESULT, doc_kind: "pr", children: [] });
  const owner = { ...todo(31, "doing", [todo(32, "todo")]), key: "t31", results: [1, 2, 3, 4, 5, 6].map(result) };
  const work = tree(4, [owner]);
  const layout = layoutForest([work]);
  const at = (key) => layout.cards.find((card) => card.key === key);
  const kids = layout.cards.filter((card) => card.parent?.key === "t31").map((card) => [card.kind, card.key]);
  assert.deepEqual(kids, [
    ["todo", "t32"],
    [RESULT, "r1-t31"],
    [RESULT, "r2-t31"],
    [RESULT, "r3-t31"],
    [MORE, "t31-more"],
  ]);
  assert.equal(RESULT_SHOW, 3);
  assert.equal(at("t31-more").data.count, 3);
  assert.equal(at("r1-t31").x, at("t32").x, "결과물은 하위 할일과 같은 열");
  assert.ok(layout.edges.some((edge) => edge.from.key === "t31" && edge.to.key === "t31-more"));
  const opened = layoutForest([work], { openResults: new Set(["t31"]) });
  assert.equal(opened.cards.filter((card) => card.kind === RESULT).length, 6);
  assert.ok(!opened.cards.some((card) => card.kind === MORE));
  // 넷이면 접지 않는다 — '+1 더' 한 장이 카드 한 장과 같은 자리를 먹는다
  const four = layoutForest([tree(5, [{ ...owner, results: owner.results.slice(0, 4) }])]);
  assert.equal(four.cards.filter((card) => card.kind === RESULT).length, 4);
  // 끝난 할일을 숨기면 그 결과물도 같이 빠지고, 결과물이 끝난 할일을 붙잡지 않는다
  const doneOwner = { ...todo(41, "done"), key: "t41", results: [result(9)] };
  const hidden = layoutForest([tree(6, [doneOwner, todo(42, "todo")])], { hideDone: true });
  assert.ok(!hidden.cards.some((card) => card.key === "t41" || card.kind === RESULT));
}

console.log("tree layout ok");
