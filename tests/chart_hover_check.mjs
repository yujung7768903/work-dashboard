// 차트 호버의 계산 부분만 검증한다. 브라우저 없이 돌려야 하므로 DOM 을 만지지 않는
// nearestSlot·placeTip 두 개만 대상이고, 툴팁·카드는 stub 객체로 대신한다.
// 실행: node tests/chart_hover_check.mjs (tests/test_chart_hover.py 가 이걸 부른다)
import assert from "node:assert/strict";

import { nearestSlot, placeTip } from "../static/js/chart.js";

const slots = [10, 30, 50, 70].map((x) => ({ x, title: `t${x}` }));

// 가까운 쪽을 짚는다. 두 표본 사이 어디를 짚어도 값 하나로 떨어져야 한다
assert.equal(nearestSlot(slots, 31).title, "t30");
assert.equal(nearestSlot(slots, 39).title, "t30");
assert.equal(nearestSlot(slots, 41).title, "t50");
// 플롯 밖으로 나가도 양 끝에 붙는다 — 축 라벨 위에서도 툴팁이 살아 있어야 한다
assert.equal(nearestSlot(slots, -100).title, "t10");
assert.equal(nearestSlot(slots, 999).title, "t70");
assert.equal(nearestSlot([slots[0]], 500).title, "t10");

const tip = () => ({ offsetWidth: 150, offsetHeight: 80, style: {} });
const box = { clientWidth: 600, clientHeight: 200 };

// 기본은 기준선 오른쪽
const right = tip();
placeTip(right, box, 100, 100);
assert.equal(right.style.left, "112px");
assert.equal(right.style.top, "60px");

// 오른쪽이 모자라면 왼쪽으로 넘긴다
const flipped = tip();
placeTip(flipped, box, 500, 100);
assert.equal(flipped.style.left, "338px");

// 어느 쪽으로도 모자라면 카드 안에 붙인다 — 잘려 나가는 편이 최악이다
const narrow = tip();
placeTip(narrow, { clientWidth: 160, clientHeight: 200 }, 20, 100);
assert.equal(narrow.style.left, "0px");

// 위아래도 카드를 넘지 않는다
const high = tip();
placeTip(high, box, 100, 0);
assert.equal(high.style.top, "0px");
const low = tip();
placeTip(low, box, 100, 200);
assert.equal(low.style.top, "120px");

console.log("chart hover check ok");
