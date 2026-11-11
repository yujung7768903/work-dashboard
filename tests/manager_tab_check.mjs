// 매니저 탭 — 주기 구조를 사람 말로 옮기고, 세 칸을 한 줄에 하나씩 그리며, 한 칸이 실패해도
// 나머지는 그리는지 본다. 실행: node tests/manager_tab_check.mjs (tests/test_manager_tab.py 가 부른다)
import assert from "node:assert/strict";
import { bootKorean } from "./i18n_boot.mjs";

const node = (tag) => {
  const self = {
    tag, className: "", textContent: "", title: "", children: [],
    append(...kids) { self.children.push(...kids); },
    appendChild(kid) { self.children.push(kid); return kid; },
    replaceChildren(...kids) { self.children = kids; },
  };
  return self;
};
const elements = {};
globalThis.document = {
  createElement: node,
  getElementById: (id) => (elements[id] ??= node("ul")),
};

const inMinutes = (minutes) => new Date(Date.now() + minutes * 60000).toISOString();
const agoMinutes = (minutes) => new Date(Date.now() - minutes * 60000).toISOString();
const PAYLOAD = {
  automations: {
    error: null,
    items: [
      {
        source: "crontab", name: "자율 실행", desc: null, expr: "*/5 * * * *",
        cycle: { days: { kind: "every" }, time: { kind: "interval", minutes: 5, hours: null } },
        next_at: inMinutes(3), last: { at: agoMinutes(2), status: "ok", detail: null }, command: "dash.py autorun-tick",
      },
      {
        source: "manager", name: "manager-check", expr: null,
        cycle: { days: { kind: "weekdays" }, time: { kind: "interval", minutes: 10, hours: [8, 20] } },
        next_at: null, next_within_sec: 600, off_duty: false,
        last: { at: agoMinutes(14), status: null, detail: "woke" }, command: "hook",
      },
      {
        source: "sre-watch", name: "훅 차단 실패 1% 미만", expr: "30 11 * * *",
        cycle: { every_days: 1, manual: false, runner: { days: { kind: "every" }, time: { kind: "at", times: ["11:30"] } } },
        next_at: inMinutes(60 * 15), last: { at: agoMinutes(500), status: "fail", detail: "4%" }, command: "run.py",
      },
      {
        source: "crontab", name: "skill-prune · tick", expr: "@reboot", cycle: { reboot: true },
        next_at: null, last: null, command: "prune.py tick",
      },
    ],
  },
  helpers: { error: "RuntimeError: claude agents 응답 없음", items: [] },
  decisions: {
    error: null,
    items: [{ id: 87, title: "우선순위 출처", state: "decision", detail: "A 추천", priority: 2, since: agoMinutes(30), held: false }],
  },
};
globalThis.fetch = async (url) => {
  const part = new URL(url, "http://x").searchParams.get("part");
  return { ok: true, status: 200, json: async () => ({ [part]: PAYLOAD[part] }) };
};

await bootKorean();
const manager = await import("../static/js/manager.js");

// 주기 → 사람 말
const cases = [
  [{ days: { kind: "weekdays" }, time: { kind: "interval", minutes: 10, hours: [8, 20] } }, "평일 · 8~20시 10분마다"],
  [{ days: { kind: "every" }, time: { kind: "hourly", minute: 7, hours: null } }, "매시 07분"],
  [{ days: { kind: "dom", values: [5] }, time: { kind: "at", times: ["05:00"] } }, "매월 5일 · 05:00"],
  [{ days: { kind: "weekdays" }, time: { kind: "at", times: ["08:00", "09:00"] } }, "평일 · 08:00, 09:00"],
  [{ reboot: true }, "재부팅 시"],
  [{ raw: "1 2 3" }, "1 2 3"],
  // 못 옮기는 모양은 원문 표현식으로
  [{ days: { kind: "custom" }, time: { kind: "at", times: ["01:00"] } }, "0 1 * 3 *"],
];
for (const [cycle, expected] of cases) {
  assert.equal(manager.cycleText(cycle, "0 1 * 3 *"), expected);
}
assert.match(manager.cycleText({ days: { kind: "dow", values: [3] }, time: { kind: "at", times: ["15:00"] } }), /^매주 수 · 15:00$/);

await manager.renderManager();

const rows = elements["mgr-automations"].children;
assert.equal(rows.length, 4, "자동화는 항목마다 한 줄");
const texts = (row) => {
  const [main, side] = row.children;
  return [main.children[0].textContent, main.children[1].textContent, side.children[0].textContent, side.children[1].textContent];
};
assert.deepEqual(texts(rows[0]), ["자율 실행", "5분마다", "3분 후", "성공 2m 전"]);
assert.deepEqual(texts(rows[1]), ["매니저 주기 점검", "평일 · 8~20시 10분마다", "10분 안", "마지막 알림 14m 전"]);
assert.equal(texts(rows[2])[0], "SRE 체크 · 훅 차단 실패 1% 미만");
assert.equal(texts(rows[2])[1], "매일 (11:30)");
assert.match(rows[2].children[1].children[1].className, /fail/);
assert.deepEqual(texts(rows[3]).slice(2), ["재부팅 시", "마지막 실행 모름"]);
assert.equal(elements["mgr-automations-count"].textContent, "4");

// 보조 세션 칸이 실패해도 그 칸에 사유만 남고 다른 칸은 그려진다
const helperRows = elements["mgr-helpers"].children;
assert.equal(helperRows.length, 1);
assert.match(helperRows[0].textContent, /claude agents 응답 없음/);
assert.equal(elements["mgr-decisions"].children.length, 1);
assert.deepEqual(texts(elements["mgr-decisions"].children[0]), ["#87 우선순위 출처", "A 추천", "결정", "30m 전"]);

console.log("ok");
