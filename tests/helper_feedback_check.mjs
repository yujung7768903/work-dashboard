// 매니저 탭 보조 세션 상세의 피드백 상자 — 살아 있는 세션이면 입력칸 + 보내기(글이 있어야 켜진다), 보낸 뒤 그 세션을
// 폴링해 전달 상태를 할일 상세 피드백과 같은 칩으로 보이는지. 세션이 끝났으면 입력칸 대신 그 사실을 보이고 보내지 않는지.
// 실행: node tests/helper_feedback_check.mjs (tests/test_helper_feedback_ui.py 가 부른다)
import assert from "node:assert/strict";
import { bootKorean } from "./i18n_boot.mjs";

// 폴링 간격(2초)을 기다리지 않는다
const realSetTimeout = setTimeout;
globalThis.setTimeout = (fn, ms) => realSetTimeout(fn, ms >= 1000 ? 0 : ms);

function node(tag) {
  const self = {
    tagName: tag, className: "", textContent: "", value: "", placeholder: "", disabled: false, type: "",
    children: [], listeners: {},
    addEventListener(type, handler) {
      self.listeners[type] = handler;
    },
    append(...kids) {
      self.children.push(...kids);
    },
    replaceChildren(...kids) {
      self.children = kids;
    },
  };
  return self;
}
globalThis.document = {
  createElement: node,
  createTextNode: (text) => ({ ...node("#text"), textContent: text }),
};

const SID = "cccccccc-1111";
const ALIVE = { id: SID, name: "보조3 | 피드백", alive: true };
const OLD = [
  { id: 9, answer: "로그도 봐 줘", answered_at: "2026-11-17T11:00:00", answer_state: "delivered" },
  { id: 8, answer: "둘째", answer_state: "delivered" },
  { id: 7, answer: "셋째", answer_state: "delivered" },
  { id: 6, answer: "넷째 — 안 보인다", answer_state: "delivered" },
];
let showQueue = [];
let postReply = null;
const asked = [];
globalThis.fetch = (url, options) => {
  const method = options?.method ?? "GET";
  asked.push({ url, method, body: options?.body });
  let payload;
  let ok = true;
  if (url === "/api/helper-feedback" && method === "POST") [ok, payload] = postReply;
  else if (url.startsWith("/api/helper-feedback?")) payload = showQueue.length > 1 ? showQueue.shift() : showQueue[0];
  else payload = {};
  return Promise.resolve({ ok, status: ok ? 200 : 400, json: () => Promise.resolve(payload) });
};

await bootKorean();
const { feedbackLoader } = await import("../static/js/helper-feedback.js");

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
const input = (box) => find(box, (n) => n.tagName === "textarea");
const sendButton = (box) => find(box, byClass("dec-send"));
const sentLines = (box) => all(box, byClass("dec-sent")).map(text);

async function load(show) {
  showQueue = [show];
  const box = feedbackLoader(SID);
  assert.match(text(box), /불러오는 중/);
  await settle(() => find(box, byClass("helper-feedback")));
  return box;
}

// ── 살아 있는 세션 — 입력칸 + 보내기. 보낸 글은 최근 3건만, 전달 상태 칩과 함께 ─────────────
let box = await load({ session: ALIVE, items: OLD, job: null });
assert.equal(asked[0].url, `/api/helper-feedback?session_id=${encodeURIComponent(SID)}`);
let send = sendButton(box);
assert.equal(send.textContent, "보내기");
assert.ok(byClass("primary")(send));
assert.equal(send.disabled, true, "글이 없으면 못 보낸다");
assert.match(input(box).placeholder, /이 보조 세션에 그대로 전합니다/);
assert.match(text(box), /할일 상태는 바뀌지 않습니다/);
assert.deepEqual(sentLines(box), ["보낸 피드백: 로그도 봐 줘전달됨", "보낸 피드백: 둘째전달됨", "보낸 피드백: 셋째전달됨"]);

// 보내기 → 서버가 뒤에서 helper-ui 를 돌린다 → 폴링: 보내는 중 → 매니저에게 넘김
input(box).value = "  표는 빼고   본문만 ";
input(box).listeners.input();
assert.equal(send.disabled, false);
postReply = [true, { session_id: SID, job: { running: true, exit: null, error: null } }];
const relayed = { id: 13, answer: "표는 빼고 본문만", answer_state: "relayed" };
showQueue = [
  { session: ALIVE, items: OLD, job: { running: true } },
  { session: ALIVE, items: [relayed, ...OLD], job: { running: false, exit: 4, error: null } },
];
send.listeners.click();
const post = asked.find((entry) => entry.method === "POST");
assert.equal(post.url, "/api/helper-feedback");
assert.deepEqual(JSON.parse(post.body), { session_id: SID, feedback: "표는 빼고   본문만" });
assert.ok(await settle(() => /보낸 피드백: 표는 빼고 본문만보내는 중/.test(text(box))), text(box));
assert.equal(input(box).disabled, true, "넘기는 동안은 다시 못 보낸다");
assert.equal(input(box).value, "", "보낸 뒤 입력칸을 비운다");
assert.ok(await settle(() => /보낸 피드백: 표는 빼고 본문만매니저에게 넘김/.test(text(box))), text(box));
assert.match(text(box), /세션이 작업 중이라 매니저가 이어서 전합니다/);
assert.equal(sentLines(box).length, 3);
assert.equal(input(box).disabled, false, "다시 보낼 수 있다");
const polls = asked.filter((entry) => entry.method === "GET").length;
await new Promise((done) => realSetTimeout(done, 20));
assert.equal(asked.filter((entry) => entry.method === "GET").length, polls, "끝나면 폴링을 멈춘다");

// 서버가 거절하면(보내는 중 겹침) 사유를 상자 안에 — 창을 띄우지 않는다
let alerted = 0;
globalThis.alert = () => {
  alerted += 1;
};
input(box).value = "또";
input(box).listeners.input();
postReply = [false, { error: "이 보조 세션에 보낸 피드백을 아직 전하는 중입니다" }];
send = sendButton(box);
send.listeners.click();
const status = find(box, byClass("dec-status"));
assert.ok(await settle(() => status.textContent.startsWith("이 보조 세션에")), status.textContent);
assert.match(status.className, /\bdanger\b/);
assert.equal(send.disabled, false);
assert.equal(alerted, 0);

// ── 보내는 사이 세션이 끝났다(helper-ui exit 3) — 입력칸이 사라지고 보내지 않은 글로 남는다 ─────────
box = await load({ session: ALIVE, items: [], job: null });
input(box).value = "이것도 해 줘";
input(box).listeners.input();
postReply = [true, { session_id: SID, job: { running: true, exit: null, error: null } }];
showQueue = [{ session: { ...ALIVE, alive: false }, items: [], job: { running: false, exit: 3, error: null } }];
sendButton(box).listeners.click();
assert.ok(await settle(() => /이미 끝나 피드백을 보내지 않습니다/.test(text(box))), text(box));
assert.equal(input(box), null);
assert.deepEqual(sentLines(box), ["보낸 피드백: 이것도 해 줘세션이 끝나 보내지 않음"]);

// ── 열 때부터 끝난 세션 — 입력칸 없이 사실만, 지난 글과 상태는 그대로 ─────────────────────
box = await load({ session: { ...ALIVE, alive: false }, items: [{ ...relayed, answer_state: "parked" }], job: null });
assert.equal(input(box), null);
assert.equal(sendButton(box), null);
assert.match(text(box), /이 보조 세션은 이미 끝나 피드백을 보내지 않습니다/);
assert.match(text(box), /세션 꺼짐 — 기록만 남김/);
assert.match(text(box), /보내는 사이 세션이 꺼져 기록만 남겼습니다/);

// ── 매니저가 사용법 오류로 끝냈으면 그 사유를 보인다 ────────────────────────────────
box = await load({ session: ALIVE, items: [], job: { running: false, exit: 2, error: "--feedback 이 비어 있다" } });
assert.match(text(find(box, byClass("danger"))), /--feedback 이 비어 있다/);

// ── 불러오기 실패 ───────────────────────────────────────────────────────────────
globalThis.fetch = () => Promise.resolve({ ok: false, status: 500, json: () => Promise.resolve({ error: "매니저가 없습니다: /x" }) });
const failed = feedbackLoader(SID);
assert.ok(await settle(() => /불러오지 못했습니다/.test(text(failed))), text(failed));

console.log("ok");
