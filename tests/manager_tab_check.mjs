// 매니저 탭 — 주기 구조를 사람 말로 옮기고, 세 칸을 한 줄에 하나씩 그리며, 한 칸이 실패해도
// 나머지는 그리는지 본다. 실행: node tests/manager_tab_check.mjs (tests/test_manager_tab.py 가 부른다)
import assert from "node:assert/strict";
import { bootKorean } from "./i18n_boot.mjs";

const node = (tag) => {
  const self = {
    tag, className: "", textContent: "", title: "", children: [], listeners: {},
    addEventListener(type, fn) { self.listeners[type] = fn; },
    showModal() { self.open = true; },
    append(...kids) { self.children.push(...kids); },
    appendChild(kid) { self.children.push(kid); return kid; },
    replaceChildren(...kids) { self.children = kids; },
  };
  return self;
};
const elements = {};
globalThis.document = {
  createElement: node,
  createTextNode: (text) => ({ textContent: text }),
  getElementById: (id) => (elements[id] ??= node("ul")),
};

const inMinutes = (minutes) => new Date(Date.now() + minutes * 60000).toISOString();
const agoMinutes = (minutes) => new Date(Date.now() - minutes * 60000).toISOString();
const PAYLOAD = {
  automations: {
    error: null,
    items: [
      {
        source: "crontab", name: "자율 실행", desc: "자율 실행 판정 (5분 크론)", desc_from: "script", expr: "*/5 * * * *",
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
        source: "crontab", name: "skill-prune · tick", desc: null, expr: "@reboot", cycle: { reboot: true },
        next_at: null, last: null, command: "prune.py tick",
      },
    ],
  },
  helpers: { error: "RuntimeError: claude agents 응답 없음", items: [] },
  decisions: {
    error: null,
    items: [
      {
        id: 87, title: "우선순위 출처", state: "decision", detail: "A 추천", priority: 2, since: agoMinutes(30), held: false,
        popup: {
          detail: "todos 에 priority 칸이 없음\n선택지 A·B", next_step: "A 와 B 중 고르기", plan: null,
          plan_status: null, reason: null, source_ref: null, open_target: "/home/u/x.md",
          session_id: "s1", reply_tail: "…\nA 를 추천해.", reply_from: "transcript",
        },
      },
      {
        id: 61, title: "보조 한도", state: "confirm", detail: null, priority: 2, since: agoMinutes(90), held: false,
        popup: { detail: null, next_step: null, reason: "master 905f617 반영", session_id: null, reply_tail: null },
      },
    ],
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
  [{ days: { kind: "weekdays" }, time: { kind: "interval", minutes: 10, hours: [8, 20] } }, "10분마다 (평일 08~20시)"],
  [{ days: { kind: "every" }, time: { kind: "hourly", minute: 7, hours: null } }, "매시 07분"],
  [{ days: { kind: "dom", values: [5] }, time: { kind: "at", times: ["05:00"] } }, "매월 5일 05:00"],
  [{ days: { kind: "weekdays" }, time: { kind: "at", times: ["08:00", "09:00"] } }, "평일 08:00, 09:00"],
  [{ reboot: true }, "부팅 시"],
  [{ raw: "1 2 3" }, "1 2 3"],
  // 못 옮기는 모양은 원문 표현식으로
  [{ days: { kind: "custom" }, time: { kind: "at", times: ["01:00"] } }, "0 1 * 3 *"],
];
for (const [cycle, expected] of cases) {
  assert.equal(manager.cycleText(cycle, "0 1 * 3 *"), expected);
}
assert.match(manager.cycleText({ days: { kind: "dow", values: [3] }, time: { kind: "at", times: ["15:00"] } }), /^매주 수 15:00$/);

await manager.renderManager();

const [header, ...rows] = elements["mgr-automations"].children;
// 세 칸 표: 주기 / 자동화 내용 / 수행 시간 — 머리줄 하나 + 항목마다 한 줄
assert.deepEqual(header.children.map((cell) => cell.textContent), ["주기", "자동화 내용", "수행 시간"]);
assert.equal(rows.length, 4, "자동화는 항목마다 한 줄");
const cells = (row) => {
  const [cycle, main, side] = row.children;
  return [cycle.textContent, main.children[0].textContent, main.children[1].textContent,
    side.children[0].textContent, side.children[1].textContent];
};
// 주기는 맨 왼쪽 칸 — 이름 아래 줄로 내려가지 않는다
assert.deepEqual(cells(rows[0]), ["5분마다", "자율 실행", "자율 실행 판정 (5분 크론)", "3분 후", "성공 2m 전"]);
assert.deepEqual(cells(rows[1]), ["10분마다 (평일 08~20시)", "매니저 주기 점검", "설명 없음", "10분 안", "마지막 알림 14m 전"]);
assert.match(rows[1].children[1].children[1].className, /mgr-nodesc/);
assert.equal(cells(rows[2])[1], "SRE 체크 · 훅 차단 실패 1% 미만");
assert.equal(cells(rows[2])[0], "매일 11:30");
assert.match(rows[2].children[2].children[1].className, /fail/);
assert.deepEqual(cells(rows[3]).slice(0, 1).concat(cells(rows[3]).slice(3)), ["부팅 시", "부팅 시", "마지막 실행 모름"]);
assert.equal(elements["mgr-automations-count"].textContent, "4");

// 보조 세션 칸이 실패해도 그 칸에 사유만 남고 다른 칸은 그려진다
const helperRows = elements["mgr-helpers"].children;
assert.equal(helperRows.length, 1);
assert.match(helperRows[0].textContent, /claude agents 응답 없음/);
const decisionRows = elements["mgr-decisions"].children;
assert.equal(decisionRows.length, 2);
const texts = (row) => {
  const [main, side] = row.children;
  return [main.children[0].textContent, main.children[1].textContent, side.children[0].textContent, side.children[1].textContent];
};
assert.deepEqual(texts(decisionRows[0]), ["#87 우선순위 출처", "A 추천", "결정", "30m 전"]);

// 결정 대기 줄을 누르면 팝업 — 지금까지 한 일 / 결정할 것, 기록된 글만
decisionRows[0].listeners.click();
const modal = elements["mgr-decision-modal"];
assert.equal(modal.open, true);
const body = elements["mgr-decision-body"].children;
assert.equal(body[0].children[0].textContent, "#87 우선순위 출처");
const sectionText = (section) => section.children.map((kid) => kid.textContent || kid.children.map((c) => c.textContent).join("")).join("|");
assert.equal(body[1].children[0].textContent, "지금까지 한 일");
assert.match(sectionText(body[1]), /todos 에 priority 칸이 없음/);
assert.equal(body[2].children[0].textContent, "결정할 것");
assert.match(sectionText(body[2]), /A 와 B 중 고르기/);
assert.match(sectionText(body[2]), /연결 세션의 마지막 답 \(끝부분\)/);
assert.match(sectionText(body[2]), /A 를 추천해/);

// 확인 대기는 '확인할 것', 완료 근거는 한 일 쪽. 비어 있는 칸은 지어내지 않고 '기록 없음'
const confirmSections = manager.decisionSections(PAYLOAD.decisions.items[1]);
assert.deepEqual(confirmSections.map((section) => section.title), ["지금까지 한 일", "확인할 것"]);
decisionRows[1].listeners.click();
const confirmBody = elements["mgr-decision-body"].children;
assert.match(sectionText(confirmBody[1]), /완료 근거\|master 905f617 반영/);
assert.equal(sectionText(confirmBody[2]), "확인할 것|기록 없음");

// 칸마다 10줄씩 페이지로 넘긴다. 칸끼리 페이지가 따로 가고, 폴링으로 다시 그려도 보던 페이지가 남는다
const autoTemplate = PAYLOAD.automations.items[0];
PAYLOAD.automations.items = Array.from({ length: 23 }, (_, index) => ({ ...autoTemplate, name: `자동화 ${index + 1}` }));
PAYLOAD.decisions.items = Array.from({ length: 15 }, (_, index) => ({ ...PAYLOAD.decisions.items[0], id: index + 1 }));
PAYLOAD.helpers = { error: null, items: [{ name: "보조1 | 일", status: "작업 중", doing: "테스트", percent: 40, moved_at: agoMinutes(1) }] };
await manager.renderManager();
const autoList = () => elements["mgr-automations"].children;
const autoNames = () => autoList().slice(1).map((row) => row.children[1].children[0].textContent);
const pager = (part) => elements[`mgr-${part}-pager`];
const labels = (part) => pager(part).children.map((button) => button.textContent);
assert.equal(elements["mgr-automations-count"].textContent, "23", "개수는 전체");
assert.equal(autoList()[0].children[0].textContent, "주기", "페이지마다 머리줄");
assert.equal(autoNames().length, 10);
assert.equal(autoNames()[0], "자동화 1");
assert.equal(pager("automations").hidden, false);
assert.deepEqual(labels("automations"), ["이전", "1", "2", "3", "다음"]);
assert.equal(pager("automations").children[0].disabled, true, "첫 페이지에서 이전은 못 누른다");
assert.match(pager("automations").children[1].className, /\bon\b/);
// 한 페이지로 끝나는 칸은 넘김을 숨긴다
assert.equal(pager("helpers").hidden, true);
assert.deepEqual(labels("decisions"), ["이전", "1", "2", "다음"]);

pager("automations").children[3].listeners.click(); // 3쪽
assert.deepEqual(autoNames(), ["자동화 21", "자동화 22", "자동화 23"]);
assert.equal(pager("automations").children.at(-1).disabled, true, "마지막 페이지에서 다음은 못 누른다");
assert.equal(elements["mgr-decisions"].children[0].children[0].children[0].textContent, "#1 우선순위 출처", "다른 칸은 그대로");
pager("decisions").children.at(-1).listeners.click(); // 결정 다음
assert.equal(elements["mgr-decisions"].children.length, 5);
assert.equal(autoNames()[0], "자동화 21", "결정 칸을 넘겨도 자동화 칸은 그대로");
pager("automations").children[0].listeners.click(); // 이전 → 2쪽
assert.equal(autoNames()[0], "자동화 11");

// 폴링 재렌더 — 보던 페이지 유지. 줄이 줄어 그 페이지가 사라지면 마지막 페이지로
pager("automations").children[3].listeners.click();
await manager.renderManager();
assert.equal(autoNames()[0], "자동화 21");
PAYLOAD.automations.items = PAYLOAD.automations.items.slice(0, 12);
await manager.renderManager();
assert.deepEqual(autoNames(), ["자동화 11", "자동화 12"]);
assert.deepEqual(labels("automations"), ["이전", "1", "2", "다음"]);

console.log("ok");
