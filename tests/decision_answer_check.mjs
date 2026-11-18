// 할일 상세의 결정 칸 — 제목 아래에 답 대기 결정을 선택지 버튼·의견 입력칸으로 그리고, 고른 것·쓴 것만
// 보내기로 보내며(누르는 즉시 보내지 않는다), 보낸 뒤 한 건을 폴링해 답 상태를 사람 말로 바꾸는지.
// 이미 답한 결정은 접어 두고 다시 답할 수 있다. 선택지가 없는 결정은 입력칸만, 붙은 결정이 없으면 칸을 숨긴다.
// 실행: node tests/decision_answer_check.mjs (tests/test_decision_answer_ui.py 가 부른다)
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

const OPTIONS = [
  { key: "A", label: "고친다", desc: "inbox 로 매니저를 깨운다" },
  { key: "B", label: "그대로 둔다", desc: "화면 표시만" },
];
const OPEN = {
  id: 191, title: "실패하면 매니저를 깨울지", status: "open", detail: "배경과 추천 이유\nhttps://example.com/pr/1",
  next_step: null, open_target: null, options: OPTIONS, recommend: "A", answer_state: "unanswered",
  answer: null, answer_choice: null, answer_feedback: null, job: null,
  session: { id: "s1", name: "보조4", state: "ended", waiting: null },
};
const OPEN_FREE = {
  ...OPEN, id: 193, title: "열린 질문", options: [], recommend: null, detail: "어떻게 할지 적어 주세요",
};
const ANSWERED = {
  ...OPEN, id: 190, title: "지난 결정", status: "done", answer_state: "delivered", answer: "A(고친다)", answer_choice: "A",
};
const TODO = { id: 42, title: "결정 버튼", created_at: "2026-11-16T10:00:00+00:00", precondition_items: [], note: "" };

let decisions = { available: true, items: [OPEN, OPEN_FREE, ANSWERED] };
// 보낸 뒤 폴링이 차례로 받을 한 건
let showQueue = [];
let answerReply = null;
const asked = [];
globalThis.fetch = (url, options) => {
  const method = options?.method ?? "GET";
  asked.push({ url, method, body: options?.body });
  let payload;
  let ok = true;
  if (url === "/api/todos/42") payload = { todo: TODO, sessions: [], worktrees: [] };
  else if (url === "/api/decisions?todo_id=42") payload = decisions;
  else if (url === "/api/decision-answer") [ok, payload] = answerReply;
  else if (url.startsWith("/api/decisions/")) payload = showQueue.length > 1 ? showQueue.shift() : showQueue[0];
  else payload = [];
  return Promise.resolve({ ok, status: ok ? 200 : 400, json: () => Promise.resolve(payload) });
};

await bootKorean();
const { openDetail } = await import("../static/js/sessions.js");

const settle = async (until, rounds = 100) => {
  for (let i = 0; !until() && i < rounds; i += 1) await new Promise((done) => realSetTimeout(done, 0));
  return until();
};
// 스텁은 글자를 넣고 자식을 붙이면 둘 다 들고 있다 — 실제 DOM 처럼 글자 뒤에 자식 글자를 잇는다
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
  // 제목 아래 첫 칸은 권한 요청(이 할일엔 없어 숨김), 그다음이 결정
  const slot = block.children[2];
  await settle(() => !slot.hidden || asked.some((entry) => entry.url.startsWith("/api/decisions?")) && slot.children.length);
  return { block, slot };
}

// ── 답 대기 결정 — 제목 바로 아래, 선택지 버튼·추천·의견 입력 ────────────────────────
const { block, slot } = await open();
assert.equal(block.children[0].textContent, "#42 | 결정 버튼", "제목이 맨 위");
assert.equal(block.children[1].className, "dlg-permissions", "권한 요청 칸이 제목 바로 아래");
assert.equal(block.children[1].hidden, true, "기다리는 권한이 없으면 숨긴다");
assert.equal(slot.className, "dlg-decisions", "결정 칸은 권한 요청 칸 다음");
assert.equal(slot.hidden, false);
assert.equal(text(slot.children[0]), "결정 대기2", "라벨 + 답 대기 건수");

const cards = all(slot, byClass("dec-card"));
const [card, freeCard, answeredCard] = cards;
assert.equal(cards.length, 3);
const head = card.children[0];
assert.equal(head.children[0].textContent, "#191 실패하면 매니저를 깨울지");
assert.equal(head.children[1].textContent, "답 대기");
assert.match(head.children[1].className, /\bwaiting\b/, "사람을 기다리는 칩 색");
// 배경 글의 주소는 누를 수 있다
const link = find(card, (n) => n.tagName === "a");
assert.equal(link?.href, "https://example.com/pr/1");

const choices = () => all(card, byClass("choice"));
assert.equal(choices().length, 2);
assert.equal(text(choices()[0]), "✓A 고친다추천inbox 로 매니저를 깨운다", "키·라벨·추천 태그·설명");
assert.ok(!choices().some((button) => byClass("selected")(button)), "추천은 표시만 — 미리 골라 두지 않는다");
const send = () => find(card, byClass("dec-send"));
const how = () => find(card, byClass("how"));
const input = () => find(card, (n) => n.tagName === "textarea");
assert.equal(send().textContent, "답 보내기");
assert.equal(send().disabled, true, "고른 것도 쓴 것도 없으면 못 보낸다");
assert.equal(input().placeholder, "의견 (선택) — 고른 선택지에 덧붙이거나 의견만 보낼 수 있습니다");

// 누르면 고르기만 한다 — 아무것도 보내지 않는다
choices()[1].listeners.click();
assert.ok(byClass("selected")(choices()[1]));
assert.ok(!asked.some((entry) => entry.method === "POST"), "누르는 즉시 보내지 않는다");
assert.equal(how().textContent, "보낼 답: B(그대로 둔다)");
assert.equal(send().disabled, false);
// 같은 것을 다시 누르면 푼다
choices()[1].listeners.click();
assert.ok(!byClass("selected")(choices()[1]));
assert.equal(send().disabled, true);
choices()[1].listeners.click();
input().value = "  화면만  보면\n충분해 ";
input().listeners.input();
assert.equal(how().textContent, "보낼 답: B(그대로 둔다) — 추가 의견: 화면만 보면 충분해", "원 세션이 받을 문장 모양");

// 보내기 → 서버가 뒤에서 answer-ui 를 돌린다 → 폴링: 전달 중 → 전달됨
answerReply = [true, { ...OPEN, job: { running: true, exit: null, error: null } }];
showQueue = [
  { ...OPEN, answer_state: "sending", answer: "B(그대로 둔다) — 추가 의견: 화면만 보면 충분해", job: { running: true } },
  {
    ...OPEN, status: "done", answer_state: "delivered", answer: "B(그대로 둔다) — 추가 의견: 화면만 보면 충분해",
    answer_choice: "B", job: { running: false, exit: 0, error: null },
  },
];
send().listeners.click();
const post = asked.find((entry) => entry.method === "POST");
assert.equal(post.url, "/api/decision-answer");
assert.deepEqual(JSON.parse(post.body), { id: 191, choice: "B", feedback: "화면만  보면\n충분해" });
assert.ok(await settle(() => card.children[0].children[1].textContent === "보내는 중"), "보낸 직후");
assert.ok(choices().every((button) => button.disabled), "넘기는 동안은 다시 못 누른다");
assert.equal(input().value, "", "보낸 뒤 입력칸을 비운다");
assert.ok(await settle(() => card.children[0].children[1].textContent === "전달 중"), text(card));
assert.match(text(card), /원 세션에 답을 넣는 중입니다/);
assert.ok(await settle(() => card.children[0].children[1].textContent === "전달됨"), text(card));
assert.match(card.children[0].children[1].className, /\bconfirm\b/);
assert.match(text(card), /보낸 답: B\(그대로 둔다\) — 추가 의견: 화면만 보면 충분해/);
assert.equal(text(choices()[1]), "✓B 그대로 둔다보낸 답화면 표시만", "고른 답 표시");
assert.equal(send().textContent, "다시 답하기", "이미 답한 결정은 다시 답할 수 있다");
assert.equal(choices()[0].disabled, false);
const polls = asked.filter((entry) => entry.url === "/api/decisions/191").length;
await new Promise((done) => realSetTimeout(done, 20));
assert.equal(asked.filter((entry) => entry.url === "/api/decisions/191").length, polls, "끝나면 폴링을 멈춘다");

// ── 선택지 없는 결정 — 입력칸만 ──────────────────────────────────────────────
assert.equal(all(freeCard, byClass("choice")).length, 0);
const freeInput = find(freeCard, (n) => n.tagName === "textarea");
assert.equal(freeInput.placeholder, "원 세션에 전할 답을 적어 주세요");
assert.match(text(freeCard), /선택지가 없는 결정입니다/);
const freeSend = find(freeCard, byClass("dec-send"));
assert.equal(freeSend.disabled, true);
freeInput.value = "B 로 가되 문구만 고쳐";
freeInput.listeners.input();
assert.equal(find(freeCard, byClass("how")).textContent, "보낼 답: B 로 가되 문구만 고쳐");
// 서버가 거절하면(입력 오류) 그 사유를 상자 안에 — 창을 띄우지 않는다
let alerted = 0;
globalThis.alert = () => {
  alerted += 1;
};
answerReply = [false, { error: "이 결정에 보낸 답을 아직 전하는 중입니다: #193" }];
freeSend.listeners.click();
const freeStatus = find(freeCard, byClass("dec-status"));
assert.ok(await settle(() => freeStatus.textContent.startsWith("이 결정에")), freeStatus.textContent);
assert.match(freeStatus.className, /\bdanger\b/);
assert.equal(freeSend.disabled, false, "다시 보낼 수 있다");
assert.equal(alerted, 0);

// ── 이미 답한 결정 — 접어 두고, 펴면 상태·보낸 답·다시 답하기 ────────────────────────
const fold = find(slot, byClass("dec-done"));
assert.equal(fold.tagName, "details");
assert.equal(fold.children[0].textContent, "답한 결정 1건");
assert.match(answeredCard.className, /\banswered\b/);
assert.equal(answeredCard.children[0].children[1].textContent, "전달됨");
assert.match(text(answeredCard), /보낸 답: A\(고친다\)/);

// ── 사용법 오류는 사유를, 원 세션에 못 닿은 답은 사람 말로 ─────────────────────────────
decisions = {
  available: true,
  items: [
    { ...OPEN, id: 201, answer_state: "unanswered", job: { running: false, exit: 2, error: "할일 201 은 답 없이 닫혔다(done)" } },
    { ...ANSWERED, id: 202, answer_state: "failed" },
    { ...ANSWERED, id: 203, answer_state: "no_session", session: null },
    { ...ANSWERED, id: 204, answer_state: "relayed" },
  ],
};
const second = await open();
await settle(() => all(second.slot, byClass("dec-card")).length === 4);
const [usage, failed, gone, relayed] = all(second.slot, byClass("dec-card"));
assert.match(text(usage), /할일 201 은 답 없이 닫혔다/);
// 연결 세션이 있으면 보통 안내, 없으면 답이 매니저에만 남는다고 보내기 전에 말한다
assert.match(text(usage), /원 세션이 그 답으로 이어서 진행합니다/);
assert.match(text(gone), /연결된 세션이 없는 결정입니다/);
assert.equal(failed.children[0].children[1].textContent, "전달 확인 못 함 — 답은 저장됨");
assert.match(failed.children[0].children[1].className, /\bfailed\b/);
assert.equal(gone.children[0].children[1].textContent, "원 세션 없음 — 답만 저장됨");
assert.equal(relayed.children[0].children[1].textContent, "매니저에게 넘김");
assert.match(text(relayed), /매니저가 이어서 전합니다/);

// ── 진행 단계 — 단계 목록을 사전 조건 줄 모양으로, 멈춘 단계 줄 아래에 답하는 상자(선택지·의견)를 넣는다 ──────
const STEPS = [
  { name: "조사·선택지 정리", status: "done" },
  { name: "선택지 결정", status: "current", unblock: "A/B 중 하나 고르기 (추천 A)" },
  { name: "PR 작성", status: "todo" },
];
decisions = { available: true, items: [{ ...OPEN, id: 181, steps: STEPS }, { ...ANSWERED, id: 182, steps: STEPS }] };
const stepped = await open();
await settle(() => all(stepped.slot, byClass("dec-card")).length === 2);
const [stepCard, closedCard] = all(stepped.slot, byClass("dec-card"));
const stepLines = all(stepCard, byClass("step-item"));
assert.deepEqual(stepLines.map((line) => text(line.children[0])), ["1조사·선택지 정리끝남", "2선택지 결정여기서 멈춤", "3PR 작성남음"]);
assert.ok(byClass("stuck")(stepLines[1]), "멈춘 단계를 강조");
assert.equal(text(stepLines[1].children[1]), "넘어가려면A/B 중 하나 고르기 (추천 A)");
assert.equal(stepLines[1].children[2].className, "dec-answer", "답하는 상자는 멈춘 단계 줄 바로 아래");
assert.equal(all(stepLines[1], byClass("choice")).length, 2);
assert.equal(stepCard.children.at(-1).className.includes("step-list"), true, "카드 끝에 상자가 따로 붙지 않는다");
// 닫힌 결정 — 단계는 보이되 멈춘 단계를 강조하지 않고, 다시 답하는 상자는 목록 아래에 그대로
const closedLines = all(closedCard, byClass("step-item"));
assert.equal(closedLines.filter(byClass("stuck")).length, 0);
assert.equal(text(closedLines[1].children[0]), "2선택지 결정", "닫힌 할일의 멈춘 단계엔 칩이 없다");
assert.equal(text(closedLines[2].children[0]), "3PR 작성", "닫힌 할일의 남은 단계도 칩이 없다");
assert.equal(text(closedLines[0].children[0]), "1조사·선택지 정리끝남");
assert.equal(closedCard.children.at(-1).className, "dec-answer");

// ── 단계 행(할일 통합 뒤) — 답할 것이 없는 동안은 진행 단계만 따로, 단계의 결정이 있으면 그 카드가 목록을 그린다 ──
const ROW_STEPS = [
  { id: 301, name: "자료 조사", status: "done", by: "보조2", at: "2026-11-18T05:05:00Z", result: "후보 3개 정리" },
  { id: 302, name: "방식 결정", status: "current", unblock: "A·B 중 고르기", ask: "decision" },
];
decisions = { available: true, items: [], reports: [], steps: ROW_STEPS };
const timelineOnly = await open();
await settle(() => all(timelineOnly.slot, byClass("step-item")).length === 2);
assert.equal(timelineOnly.slot.hidden, false, "결정이 없어도 진행 단계가 있으면 칸을 연다");
assert.equal(text(timelineOnly.slot.children[0]), "진행 단계");
const metaLine = find(timelineOnly.slot, byClass("step-meta"));
assert.match(text(metaLine), /^보조2 · 11-18 \d\d:05 · 후보 3개 정리$/, "끝난 단계는 누가·언제·결과 한 줄");
assert.equal(text(find(timelineOnly.slot, byClass("step-unblock"))), "넘어가려면A·B 중 고르기");

const STEP_ASK = { ...OPEN, id: 302, title: "결정 버튼 › 방식 결정", task_id: 42, steps: ROW_STEPS };
decisions = { available: true, items: [STEP_ASK], reports: [], steps: ROW_STEPS };
const stepAsk = await open();
await settle(() => all(stepAsk.slot, byClass("dec-card")).length === 1);
assert.equal(all(stepAsk.slot, byClass("step-list")).length, 1, "단계의 결정 카드가 목록을 그리면 따로 두지 않는다");
const askCard = all(stepAsk.slot, byClass("dec-card"))[0];
assert.equal(askCard.children[0].children[0].textContent, "#302 결정 버튼 › 방식 결정", "단계는 할일 제목과 함께");
const askLines = all(askCard, byClass("step-item"));
assert.equal(askLines[1].children.at(-1).className, "dec-answer", "답하는 상자는 멈춘 단계(단계 행) 아래");

// ── 붙은 결정이 없거나 매니저가 없는 PC — 칸을 숨긴다 ─────────────────────────────
decisions = { available: false, items: [] };
const none = await open();
await settle(() => asked.filter((entry) => entry.url === "/api/decisions?todo_id=42").length >= 3);
await new Promise((done) => realSetTimeout(done, 0));
assert.equal(none.slot.hidden, true);
assert.equal(none.slot.children.length, 0);

console.log("ok");
