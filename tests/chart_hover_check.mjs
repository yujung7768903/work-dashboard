// 차트 호버의 계산 부분만 검증한다. 브라우저 없이 돌려야 하므로 DOM 을 만지지 않는
// nearestSlot·placeTip 두 개만 대상이고, 툴팁·카드는 stub 객체로 대신한다.
// 실행: node tests/chart_hover_check.mjs (tests/test_chart_hover.py 가 이걸 부른다)
import assert from "node:assert/strict";

import { labelStride, nearestSlot, placeTip, spreadEnds } from "../static/js/chart.js";
import { isHoliday, weekLabels } from "../static/js/usage.js";

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

// 축 라벨 — 자리가 되면 전부, 촘촘하면 건너뛴다
const days = Array.from({ length: 14 }, (_, i) => ({ text: `07-${18 + i}` }));
const barSpec = { height: 190, pad: { top: 12, right: 10, bottom: 22, left: 46 } };
const band = (620 - 46 - 10) / 14;
assert.equal(labelStride(days, barSpec, (i) => 46 + band * i + band / 2), 1);
// 24시간 추이(5분 버킷 288개)는 자리가 없어 반드시 건너뛴다
const stamps = Array.from({ length: 288 }, () => ({ text: "오후 07:55" }));
const lineSpec = { height: 178, pad: { top: 12, right: 88, bottom: 22, left: 40 } };
const step = (620 - 40 - 88) / 287;
assert.ok(labelStride(stamps, lineSpec, (i) => 40 + step * i) > 20);
assert.equal(labelStride([{ text: "07-31" }], barSpec, () => 0), 1);

// 끝점 라벨 — 겹치면 벌리고, 떨어져 있으면 값 자리를 지킨다
const plot = { y: 12, height: 144 };
const tight = spreadEnds([{ y: 100 }, { y: 104 }], plot);
assert.ok(tight[1].y - tight[0].y >= 12);
assert.equal(tight[0].y, 100);
const loose = spreadEnds([{ y: 40 }, { y: 90 }], plot);
assert.deepEqual(loose.map((e) => e.y), [40, 90]);
// 바닥에 닿으면 두 라벨을 함께 위로 당긴다 — 플롯 밖으로 흘리지 않는다
const pushed = spreadEnds([{ y: 154 }, { y: 156 }], plot);
assert.ok(pushed[pushed.length - 1].y <= plot.y + plot.height);
assert.ok(pushed[1].y - pushed[0].y >= 12);

// 휴일 — 주말과 양력 고정 공휴일
assert.equal(isHoliday("2026-08-15"), true); // 광복절(토)
assert.equal(isHoliday("2026-01-01"), true); // 신정
assert.equal(isHoliday("2026-08-02"), true); // 일요일
assert.equal(isHoliday("2026-08-01"), true); // 토요일
assert.equal(isHoliday("2026-07-31"), false); // 금요일
assert.equal(isHoliday(""), false);

// 주차 이름 — 진행 중인 창이 "이번 주", 닫힌 창은 최근에서 거슬러 센다
const week = (in_progress) => ({ in_progress });
assert.deepEqual(weekLabels([week(false), week(false), week(false), week(true)]), [
  "3주 전",
  "2주 전",
  "지난주",
  "이번 주",
]);
// 진행 중인 창이 없으면(오래 안 쓴 계정) 마지막도 "지난주"부터 센다 — "이번 주"를 만들지 않는다
assert.deepEqual(weekLabels([week(false), week(false)]), ["2주 전", "지난주"]);
assert.deepEqual(weekLabels([week(true)]), ["이번 주"]);
assert.deepEqual(weekLabels([]), []);

console.log("chart hover check ok");
