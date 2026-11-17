// 할일 상세의 권한 요청 칸 — 제목 바로 아래에 연결 세션이 기다리는 권한을 도구·명령 전문·대상·기다린 시간과 함께
// 그리고, 매니저 훅이 기다리는 요청만 허용·거부를 고른 뒤 '답 보내기'로 넘기는지(누르는 즉시 보내지 않는다).
// 전문을 확인하지 못한 요청은 허용을 고를 수 없고, 터미널 프롬프트로 넘어간 요청·꺼진 세션은 어디서 답하는지만 보인다.
// 실행: node tests/permission_answer_check.mjs (tests/test_permission_answer_ui.py 가 부른다)
import assert from "node:assert/strict";
import { bootKorean } from "./i18n_boot.mjs";

// 요청 시각·기한은 로컬 시각으로 그린다 — 이 PC(KST) 밖에서 돌려도 같은 글자가 나오게 고정
process.env.TZ = "Asia/Seoul";

// 다시 읽기 지연(1.5초)을 기다리지 않는다
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

const COMMAND = "cd /repo && git push -u origin fix/cors && gh pr create --title 'CORS' --body-file pr.md";
const SESSION = { id: 7, claude_session_id: "s1", short: "6074df53", name: "보조1 | CORS", cwd: "/home/u/work/manager" };
const CALL = {
  tool_use_id: "toolu_1", tool: "Bash", description: "Push branches and open PRs", target: null,
  text: COMMAND, is_command: true, at: "2026-11-17T00:59:00Z",
};
const GATE = {
  key: "s1:0411", mode: "gate", session: SESSION,
  request: { id: "0411", created_at: "2026-11-17T09:59:00", tool_name: "Bash", deliver: "terminal", preview: "{...}" },
  calls: [CALL], verified: true, requested_at: "2026-11-17T09:59:00+09:00", waited_sec: 125,
  deadline_at: "2026-11-17T10:08:00+09:00", attach: null,
};
const UNVERIFIED = {
  ...GATE, key: "s2:0412", session: { ...SESSION, claude_session_id: "s2", name: "" },
  request: { ...GATE.request, id: "0412", preview: '{"command": "cd /repo && git push -u [REDACTED] fix' },
  calls: [], verified: false,
};
const TERMINAL = {
  ...GATE, key: "s3:t", mode: "terminal", request: null, deadline_at: null, verified: false,
  session: { ...SESSION, claude_session_id: "s3", short: "abcd1234" },
  calls: [{ ...CALL, tool: "Edit", description: null, target: "/repo/a.py", is_command: false, text: '{\n  "file_path": "/repo/a.py"\n}' }],
  waited_sec: 4 * 86400 + 3 * 3600, attach: "claude attach abcd1234",
};
const ENDED = { ...TERMINAL, key: "s4:t", mode: "ended", attach: null, session: { ...SESSION, claude_session_id: "s4" } };
const TODO = { id: 42, title: "CORS 제한", created_at: "2026-11-16T10:00:00+00:00", precondition_items: [], note: "" };

let permissions = { items: [GATE, UNVERIFIED, TERMINAL, ENDED] };
let answerReply = [true, { id: "0411", decision: "allow", session_id: "s1" }];
const asked = [];
globalThis.fetch = (url, options) => {
  const method = options?.method ?? "GET";
  asked.push({ url, method, body: options?.body });
  let payload;
  let ok = true;
  if (url === "/api/todos/42") payload = { todo: TODO, sessions: [], worktrees: [] };
  else if (url === "/api/permissions?todo_id=42") payload = permissions;
  else if (url === "/api/decisions?todo_id=42") payload = { available: true, items: [] };
  else if (url === "/api/permission-answer") [ok, payload] = answerReply;
  else payload = [];
  return Promise.resolve({ ok, status: ok ? 200 : 409, json: () => Promise.resolve(payload) });
};
let alerted = 0;
globalThis.alert = () => {
  alerted += 1;
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
const gets = () => asked.filter((entry) => entry.url === "/api/permissions?todo_id=42").length;

async function open() {
  body.children = [];
  openDetail({ todo: { id: 42 } });
  await settle(() => body.children.length === 4);
  const block = body.children[1].children[0];
  const slot = block.children[1];
  await settle(() => !slot.hidden && slot.children.length);
  return { block, slot };
}

// ── 칸 — 제목 바로 아래, 건수와 다시 불러오기 ─────────────────────────────────────────
const { block, slot } = await open();
assert.equal(block.children[0].textContent, "#42 | CORS 제한");
assert.equal(slot.className, "dlg-permissions", "권한 요청 칸은 제목 바로 아래");
assert.equal(text(slot.children[0]), "권한 요청4다시 불러오기", "라벨 + 건수 + 다시 불러오기");
const cards = all(slot, byClass("perm-card"));
assert.equal(cards.length, 4);
const [gate, unverified, terminal, ended] = cards;

// ── 화면에서 답할 수 있는 요청 — 도구·세션·기다린 시간·명령 전문, 고른 뒤 보내기 ─────────────
assert.equal(gate.children[0].children[0].textContent, "Bash · 보조1 | CORS");
assert.equal(gate.children[0].children[1].textContent, "답 대기");
assert.match(gate.children[0].children[1].className, /\bwaiting\b/);
assert.equal(gate.children[1].textContent, "11-17 09:59 요청 · 2분째 기다림 · 작업 위치 /home/u/work/manager");
assert.match(text(gate), /설명Push branches and open PRs/);
const pre = find(gate, (n) => n.tagName === "pre");
assert.equal(pre.textContent, COMMAND, "명령 전문 그대로 — 자르지 않는다");
assert.match(text(gate), /10:08까지 답하지 않으면 세션 터미널 프롬프트로 넘어가/);
const choices = () => all(gate, byClass("choice"));
const send = () => find(gate, byClass("dec-send"));
assert.deepEqual(choices().map((button) => text(button)), ["✓허용", "✓거부"]);
assert.ok(!choices().some((button) => byClass("selected")(button)), "미리 골라 두지 않는다");
assert.equal(send().disabled, true, "고르기 전엔 못 보낸다");
choices()[0].listeners.click();
assert.ok(byClass("selected")(choices()[0]));
assert.ok(!asked.some((entry) => entry.method === "POST"), "누르는 즉시 보내지 않는다");
assert.equal(find(gate, byClass("how")).textContent, "보낼 답: 허용");
choices()[0].listeners.click();
assert.equal(send().disabled, true, "같은 것을 다시 누르면 푼다");
choices()[0].listeners.click();
const before = gets();
send().listeners.click();
const post = asked.find((entry) => entry.method === "POST");
assert.equal(post.url, "/api/permission-answer");
assert.deepEqual(JSON.parse(post.body), {
  id: "0411", answer: "yes", session_id: "s1", created_at: "2026-11-17T09:59:00", tool_use_id: "toolu_1",
}, "본 요청(세션·생성 시각)과 본 호출 id 를 같이 보낸다");
assert.ok(await settle(() => /허용을 보냈습니다/.test(text(gate))), text(gate));
assert.ok(choices().every((button) => button.disabled), "보낸 뒤엔 다시 못 누른다");
assert.ok(await settle(() => gets() > before), "답을 넘긴 뒤 칸을 다시 읽는다");

// ── 전문을 확인하지 못한 요청 — 허용은 고를 수 없고 미리보기와 사유를 보인다 ───────────────────
assert.equal(unverified.children[0].children[0].textContent, "Bash · 6074df53", "세션 이름이 없으면 짧은 id");
assert.deepEqual(all(unverified, byClass("choice")).map((button) => text(button)), ["✓거부"]);
assert.match(text(unverified), /허용은 막았습니다/);
assert.equal(find(unverified, byClass("preview")).textContent, UNVERIFIED.request.preview);
// 거부는 호출 id 없이 보낸다. 서버가 거절하면 사유를 카드 안에 — 창을 띄우지 않는다
answerReply = [false, { error: "이 권한 요청은 이미 끝났거나 바뀌었습니다 — 다시 불러와 확인해 주세요" }];
all(unverified, byClass("choice"))[0].listeners.click();
find(unverified, byClass("dec-send")).listeners.click();
assert.ok(await settle(() => /이미 끝났거나 바뀌었습니다/.test(text(unverified))), text(unverified));
const denyPost = asked.filter((entry) => entry.method === "POST").at(-1);
assert.equal(JSON.parse(denyPost.body).tool_use_id, null);
assert.equal(JSON.parse(denyPost.body).answer, "no");
assert.match(find(unverified, byClass("dec-status")).className, /\bdanger\b/);
assert.equal(find(unverified, byClass("dec-send")).disabled, false, "다시 보낼 수 있다");
assert.equal(alerted, 0);

// ── 터미널 프롬프트로 넘어간 요청 — 대상과 입력 전체, 붙을 명령만. 답하는 버튼은 없다 ─────────────
assert.equal(terminal.children[0].children[1].textContent, "터미널에서만 답함");
assert.match(text(terminal), /4일 3시간째 기다림/);
assert.match(text(terminal), /대상\/repo\/a\.py/);
assert.equal(find(terminal, byClass("perm-attach")).textContent, "claude attach abcd1234");
assert.equal(all(terminal, byClass("choice")).length, 0);
assert.equal(find(terminal, byClass("dec-send")), null);

// ── 꺼진 세션 — 권한 창이 없어졌다고 말한다 ─────────────────────────────────────────
assert.equal(ended.children[0].children[1].textContent, "세션 꺼짐");
assert.match(ended.children[0].children[1].className, /\bfailed\b/);
assert.match(text(ended), /세션이 꺼져 이 권한 창도 없어졌습니다/);
assert.equal(find(ended, byClass("dec-send")), null);

// ── 기다리는 권한이 없으면 칸을 숨긴다 ─────────────────────────────────────────────
permissions = { items: [] };
const none = await open();
await settle(() => gets() >= 3);
await new Promise((done) => realSetTimeout(done, 0));
assert.equal(none.slot.hidden, true);
assert.equal(none.slot.children.length, 0);

console.log("ok");
