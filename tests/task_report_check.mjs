// 할일 상세의 직접 할 일·확인 대기 칸 — 결정 칸 아래에 그리고, 기본 버튼(완료·확인)은 바로 보내며 글만 보내는
// 버튼(진행 상황·고칠 것)은 글이 있어야 켜지는지. 보낸 뒤 한 건을 폴링해 전달 상태를 사람 말로 바꾸는지.
// 화면에서 알려 닫힌 것은 접어 두고, 붙은 것이 하나도 없으면 칸을 숨긴다.
// 실행: node tests/task_report_check.mjs (tests/test_task_report_ui.py 가 부른다)
import assert from "node:assert/strict";
import { bootKorean } from "./i18n_boot.mjs";

// 폴링 간격(2초)을 기다리지 않는다
const realSetTimeout = setTimeout;
globalThis.setTimeout = (fn, ms) => realSetTimeout(fn, ms >= 1000 ? 0 : ms);

function node(tag) {
  const self = {
    tagName: tag,
    className: "",
    textContent: "",
    title: "",
    value: "",
    placeholder: "",
    disabled: false,
    hidden: false,
    open: false,
    children: [],
    listeners: {},
    dataset: {},
    style: { setProperty() {} },
    classList: {
      toggle(name, on) {
        const names = new Set(self.className.split(" ").filter(Boolean));
        if (on) names.add(name);
        else names.delete(name);
        self.className = [...names].join(" ");
      },
      add(name) {
        self.classList.toggle(name, true);
      },
      remove(name) {
        self.classList.toggle(name, false);
      },
    },
    focus() {},
    addEventListener(type, handler) {
      self.listeners[type] = handler;
    },
    append(...kids) {
      self.children.push(...kids);
    },
    appendChild(kid) {
      self.children.push(kid);
      return kid;
    },
    add(kid) {
      self.children.push(kid);
    },
    replaceChildren(...kids) {
      self.children = kids;
    },
  };
  return self;
}

const modal = { ...node("dialog"), open: false, showModal() { modal.open = true; }, close() { modal.open = false; } };
const body = node("div");
globalThis.Option = function Option(text, value, _default, selected) {
  return { ...node("option"), textContent: text, value, selected };
};
globalThis.document = {
  createElement: node,
  createTextNode: (text) => ({ ...node("#text"), textContent: text }),
  getElementById: (id) => (id === "session-modal" ? modal : body),
};

const SESSION = { id: "s1", name: "보조2 | 로그 경로", state: "idle", waiting: null };
const ACTION = {
  id: 168, title: "KT 운영 서버 catalina 출력 옮기기", kind: "action", status: "open", report_kind: "action",
  detail: "서버 2대 작업", next_step: "chmod 755 /data2/log/kt-herb", reason: null, open_target: null,
  answer: null, answer_via: null, answer_state: "unanswered", session: SESSION, job: null,
};
const CONFIRM = {
  id: 161, title: "통합DB 검색 원인", kind: "action", status: "confirm", report_kind: "confirm",
  detail: "OpenSearch GET 재현", next_step: "원인 확인", reason: "원인 결론과 재현까지 끝냄", open_target: null,
  answer: null, answer_via: null, answer_state: "unanswered", session: { ...SESSION, state: "ended" }, job: null,
};
const REPORTED = {
  ...CONFIRM, id: 150, title: "지난 확인", status: "done", answer: "좋아", answer_via: "ui:confirm",
  answer_state: "parked",
};
const TODO = { id: 42, title: "로그 경로", created_at: "2026-11-17T10:00:00+00:00", precondition_items: [], note: "" };

let decisions = { available: true, items: [], reports: [ACTION, CONFIRM, REPORTED] };
let showQueue = [];
let reportReply = null;
const asked = [];
globalThis.fetch = (url, options) => {
  const method = options?.method ?? "GET";
  asked.push({ url, method, body: options?.body });
  let payload;
  let ok = true;
  if (url === "/api/todos/42") payload = { todo: TODO, sessions: [], worktrees: [] };
  else if (url === "/api/decisions?todo_id=42") payload = decisions;
  else if (url === "/api/task-report") [ok, payload] = reportReply;
  else if (url === "/api/prereq-action") payload = { task: { id: 9, state: "action", prereqs: [] } };
  else if (url.startsWith("/api/task-reports/")) payload = showQueue.length > 1 ? showQueue.shift() : showQueue[0];
  else payload = [];
  return Promise.resolve({ ok, status: ok ? 200 : 400, json: () => Promise.resolve(payload) });
};

await bootKorean();
const { openDetail } = await import("../static/js/sessions.js");

const settle = async (until, rounds = 100) => {
  for (let i = 0; !until() && i < rounds; i += 1) await new Promise((done) => realSetTimeout(done, 0));
  return until();
};
const text = (n) => (n.textContent ?? "") + (n.children ?? []).map(text).join("");
const find = (n, match) => {
  if (match(n)) return n;
  for (const kid of n.children ?? []) {
    const hit = find(kid, match);
    if (hit) return hit;
  }
  return null;
};
const all = (n, match, out = []) => {
  if (match(n)) out.push(n);
  (n.children ?? []).forEach((kid) => all(kid, match, out));
  return out;
};
const byClass = (name) => (n) => (n.className ?? "").split(" ").includes(name);

async function open() {
  body.children = [];
  openDetail({ todo: { id: 42 } });
  await settle(() => body.children.length === 4);
  const block = body.children[1].children[0];
  const slot = block.children[2];
  await settle(() => !slot.hidden || asked.some((entry) => entry.url.startsWith("/api/decisions?")) && slot.children.length);
  return { block, slot };
}

// ── 붙은 결정이 없어도 직접 할 일·확인 대기가 있으면 칸이 뜬다 ─────────────────────────
const { slot } = await open();
assert.equal(slot.className, "dlg-decisions");
assert.equal(slot.hidden, false);
assert.equal(text(slot.children[0]), "직접 할 일·확인 대기2", "라벨 + 응답 대기 건수");
const cards = all(slot, byClass("report-card"));
assert.equal(cards.length, 3);
const [actionCard, confirmCard, reportedCard] = cards;

// ── 직접 할 일 — 완료(기본) · 진행 상황 보내기(글이 있을 때) ───────────────────────────
const head = actionCard.children[0];
assert.equal(head.children[0].textContent, "#168 KT 운영 서버 catalina 출력 옮기기");
assert.equal(head.children[1].textContent, "내가 할 일");
assert.match(head.children[1].className, /\bwaiting\b/);
assert.match(text(actionCard), /다음 단계chmod 755/);
const buttons = (card) => all(card, byClass("dec-send"));
const input = (card) => find(card, (n) => n.tagName === "textarea");
let [note, main] = buttons(actionCard);
assert.deepEqual([note.textContent, main.textContent], ["진행 상황 보내기", "완료"]);
assert.ok(byClass("primary")(main), "닫는 버튼은 기본 버튼으로 갈라 둔다");
assert.equal(note.disabled, true, "글이 없으면 진행 상황은 못 보낸다");
assert.equal(main.disabled, false, "완료는 바로 누를 수 있다");
assert.match(input(actionCard).placeholder, /완료와 함께 보내면 완료 메모/);
assert.match(text(actionCard), /살아 있으면 그 세션에도 전해집니다/);

// 진행 상황 → 서버가 뒤에서 task-ui 를 돌린다 → 폴링: 전달 중 → 매니저에게 넘김
input(actionCard).value = "  1대 끝, 2대째  진행 중 ";
input(actionCard).listeners.input();
assert.equal(note.disabled, false);
reportReply = [true, { ...ACTION, job: { running: true, exit: null, error: null } }];
showQueue = [
  { ...ACTION, answer: "1대 끝, 2대째 진행 중", answer_via: "ui:progress", answer_state: "sending", job: { running: true } },
  {
    ...ACTION, answer: "1대 끝, 2대째 진행 중", answer_via: "ui:progress", answer_state: "relayed",
    job: { running: false, exit: 4, error: null },
  },
];
note.listeners.click();
let post = asked.find((entry) => entry.method === "POST");
assert.equal(post.url, "/api/task-report");
assert.deepEqual(JSON.parse(post.body), { id: 168, done: false, feedback: "1대 끝, 2대째  진행 중" });
const sentLine = (card) => find(card, byClass("dec-sent"));
assert.ok(await settle(() => sentLine(actionCard) && /보내는 중/.test(text(sentLine(actionCard)))), text(actionCard));
[note, main] = buttons(actionCard);
assert.ok(note.disabled && main.disabled, "넘기는 동안은 다시 못 누른다");
assert.equal(input(actionCard).value, "", "보낸 뒤 입력칸을 비운다");
assert.ok(await settle(() => /매니저에게 넘김/.test(text(actionCard))), text(actionCard));
assert.match(text(actionCard), /보낸 진행 상황: 1대 끝, 2대째 진행 중/);
assert.match(text(actionCard), /매니저가 이어서 전합니다/);
assert.equal(actionCard.children[0].children[1].textContent, "내가 할 일", "진행 상황은 일을 닫지 않는다");
[note, main] = buttons(actionCard);
assert.equal(main.disabled, false, "다시 완료할 수 있다");

// 완료 → 닫히면 응답 상자가 사라지고 결과만
reportReply = [true, { ...ACTION, job: { running: true, exit: null, error: null } }];
showQueue = [{
  ...ACTION, status: "done", answer: "작업 대시보드에서 완료를 눌렀다", answer_via: "ui:done", answer_state: "delivered",
  job: { running: false, exit: 0, error: null },
}];
main.listeners.click();
post = asked.filter((entry) => entry.method === "POST").at(-1);
assert.deepEqual(JSON.parse(post.body), { id: 168, done: true, feedback: null });
assert.ok(await settle(() => actionCard.children[0].children[1].textContent === "완료함"), text(actionCard));
assert.match(actionCard.className, /\banswered\b/);
assert.equal(buttons(actionCard).length, 0, "닫힌 일에는 버튼이 없다");
assert.match(text(actionCard), /완료로 알림: 작업 대시보드에서 완료를 눌렀다전달됨/);
const polls = asked.filter((entry) => entry.url === "/api/task-reports/168").length;
await new Promise((done) => realSetTimeout(done, 20));
assert.equal(asked.filter((entry) => entry.url === "/api/task-reports/168").length, polls, "끝나면 폴링을 멈춘다");

// ── 확인 대기 — 확인(기본) · 고칠 것 보내기. 끝낸 내용이 먼저 보인다 ────────────────────
assert.equal(confirmCard.children[0].children[1].textContent, "확인 대기");
assert.match(confirmCard.children[0].children[1].className, /\bconfirm\b/);
assert.match(text(confirmCard), /끝낸 내용원인 결론과 재현까지 끝냄/);
const [fix, ok] = buttons(confirmCard);
assert.deepEqual([fix.textContent, ok.textContent], ["고칠 것 보내기", "확인"]);
assert.match(text(confirmCard), /세션이 없으면 매니저가 이어 갈 보조를 띄울지 묻습니다/);
// 고칠 것을 보냈는데 그 세션이 꺼져 있으면 매니저가 보조를 띄울지 묻는다고 말한다
input(confirmCard).value = "출처 필터 켠 경우도";
input(confirmCard).listeners.input();
reportReply = [true, { ...CONFIRM, job: { running: true, exit: null, error: null } }];
showQueue = [{
  ...CONFIRM, status: "open", report_kind: "action", answer: "출처 필터 켠 경우도", answer_via: "ui:fix",
  answer_state: "parked", job: { running: false, exit: 5, error: null },
}];
fix.listeners.click();
post = asked.filter((entry) => entry.method === "POST").at(-1);
assert.deepEqual(JSON.parse(post.body), { id: 161, done: false, feedback: "출처 필터 켠 경우도" });
assert.ok(await settle(() => /보낸 고칠 것: 출처 필터 켠 경우도/.test(text(confirmCard))), text(confirmCard));
assert.match(text(confirmCard), /세션 꺼짐 — 기록만 남김/);
assert.match(text(confirmCard), /매니저가 보조를 띄울지 묻습니다/);

// 서버가 거절하면(입력 오류) 사유를 상자 안에 — 창을 띄우지 않는다
let alerted = 0;
globalThis.alert = () => {
  alerted += 1;
};
const [, again] = buttons(confirmCard);
reportReply = [false, { error: "이 할일에 보낸 응답을 아직 전하는 중입니다: #161" }];
again.listeners.click();
const status = find(confirmCard, byClass("dec-status"));
assert.ok(await settle(() => status.textContent.startsWith("이 할일에")), status.textContent);
assert.match(status.className, /\bdanger\b/);
assert.equal(again.disabled, false, "다시 보낼 수 있다");
assert.equal(alerted, 0);

// ── 화면에서 알려 닫힌 것 — 접어 두고 결과만 ─────────────────────────────────────
const fold = find(slot, byClass("dec-done"));
assert.equal(fold.tagName, "details");
assert.equal(fold.children[0].textContent, "화면에서 알린 일 1건");
assert.equal(reportedCard.children[0].children[1].textContent, "확인함");
assert.equal(buttons(reportedCard).length, 0);
assert.match(text(reportedCard), /확인으로 알림: 좋아/);
assert.match(text(reportedCard), /그 세션이 다시 뜨면 전해집니다/);

// ── 연결 세션이 없는 직접 할 일 — 매니저에만 남는다고 보내기 전에 말한다 ────────────────
decisions = { available: true, items: [], reports: [{ ...ACTION, id: 170, session: null }] };
const second = await open();
await settle(() => all(second.slot, byClass("report-card")).length === 1);
assert.match(text(second.slot), /연결된 세션이 없는 일입니다/);

// ── 선행 대기 — 다른 할일이 먼저 끝나야 하는 일은 응답 대기와 따로 묶고, 사전 조건 할일과 상태를 줄로 보인다.
// 답하는 칸은 없다. 사전 조건을 누르면 그 매니저 할일 팝업을 연다(manager.js openManagerTask)
const WAITING = {
  ...ACTION, id: 9, title: "문의 자동화에 KT 로그 붙이기", next_step: "PR #69 머지", prereq_waiting: true,
  after: [{ id: 168, title: "KT 서버 로그 경로", status: "open", finished: false },
    { id: 169, title: "KT 로그 Lambda 배포", status: "done", finished: true }],
};
decisions = { available: true, items: [], reports: [ACTION, WAITING] };
const third = await open();
await settle(() => all(third.slot, byClass("prereq-card")).length === 1);
assert.equal(all(third.slot, byClass("report-card")).length, 1, "선행 대기는 응답 카드로 그리지 않는다");
const labels = all(third.slot, byClass("label")).map(text);
assert.deepEqual(labels, ["직접 할 일·확인 대기1", "선행 대기1"]);
const prereqCard = find(third.slot, byClass("prereq-card"));
assert.equal(prereqCard.children[0].children[0].textContent, "#9 문의 자동화에 KT 로그 붙이기");
assert.match(prereqCard.children[0].children[1].className, /\bprereq\b/);
assert.equal(prereqCard.children[0].children[1].textContent, "선행 대기");
const prereqLines = all(prereqCard, byClass("prereq-item"));
assert.deepEqual(prereqLines.map((line) => text(find(line, byClass("prereq-open")))),
  ["#168 KT 서버 로그 경로남음", "#169 KT 로그 Lambda 배포끝남"]);
assert.ok(byClass("finished")(prereqLines[1]), "끝난 사전 조건은 흐리게");
assert.equal(buttons(prereqCard).length, 0, "답하는 칸이 없다");
assert.match(text(prereqCard), /다음 단계PR #69 머지/);
// 사전 조건 줄 오른쪽 끝 케밥 — 완료 처리하기는 되물은 뒤 보내고, 처리 뒤 이 할일에 붙은 것을 다시 읽어 선행 대기에서 뺀다
const menuItems = all(prereqLines[0], byClass("ws-menu-items"))[0].children;
assert.deepEqual(menuItems.map(text), ["사전 조건 제거하기", "완료 처리하기"]);
assert.deepEqual(all(prereqLines[1], byClass("ws-menu-items"))[0].children.map(text), ["사전 조건 제거하기"]);
globalThis.confirm = () => true;
decisions = { available: true, items: [], reports: [ACTION, { ...WAITING, prereq_waiting: false }] };
const before = asked.filter((entry) => entry.url === "/api/decisions?todo_id=42").length;
await menuItems[1].listeners.click({ stopPropagation() {} });
const posted = asked.filter((entry) => entry.url === "/api/prereq-action");
assert.deepEqual(posted.map((entry) => JSON.parse(entry.body)), [{ task_id: 9, prereq_id: 168, action: "finish" }]);
await settle(() => all(third.slot, byClass("prereq-card")).length === 0);
assert.equal(asked.filter((entry) => entry.url === "/api/decisions?todo_id=42").length, before + 1);
assert.equal(all(third.slot, byClass("prereq-card")).length, 0, "선행이 풀린 할일은 선행 대기에서 빠진다");

// ── 권한 대기 — 권한·로그인 막힘(blocked=permission)은 직접 할 일·결정 대기와 따로 맨 앞에 묶는다 ─────────────
decisions = { available: true, items: [], reports: [ACTION, { ...ACTION, id: 224, title: "Confluence 재로그인", blocked: "permission" }] };
const fourth = await open();
await settle(() => all(fourth.slot, byClass("report-card")).length === 2);
assert.deepEqual(all(fourth.slot, byClass("label")).map(text), ["권한 대기1", "직접 할 일·확인 대기1"]);

// ── 붙은 결정·직접 할 일 모두 없음 — 칸을 숨긴다 ────────────────────────────────
decisions = { available: true, items: [], reports: [] };
const none = await open();
await settle(() => asked.filter((entry) => entry.url === "/api/decisions?todo_id=42").length >= 4);
await new Promise((done) => realSetTimeout(done, 0));
assert.equal(none.slot.hidden, true);
assert.equal(none.slot.children.length, 0);

console.log("ok");
