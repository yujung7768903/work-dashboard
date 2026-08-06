// 할일 상세 개요 탭의 착수 조건. 원문 한 덩어리가 아니라 항목별로 충족 표시가 붙고,
// 확인 명령이 달린 항목만 버튼이 생기며, 그 버튼이 명령이 아니라 항목 번호를 보내는지 본다.
// 실행: node tests/precondition_checklist_check.mjs
// (tests/test_precondition_checklist.py 가 이걸 부른다)
import assert from "node:assert/strict";

function node(tag) {
  const self = {
    tagName: tag,
    className: "",
    textContent: "",
    title: "",
    hidden: false,
    children: [],
    listeners: {},
    style: { setProperty() {} },
    classList: { toggle() {}, add() {}, remove() {} },
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

const modal = { ...node("dialog"), open: false, showModal() {}, close() {} };
const body = node("div");
globalThis.Option = function Option(text, value, _default, selected) {
  return { ...node("option"), textContent: text, value, selected };
};
globalThis.document = {
  createElement: node,
  createTextNode: (text) => ({ ...node("#text"), textContent: text }),
  getElementById: (id) => (id === "session-modal" ? modal : body),
};

const TODO = {
  id: 42,
  title: "조건 걸린 할일",
  created_at: "2026-08-05T10:00:00+00:00",
  precondition: "#7 이 done 일 것\n기획 확정\n확인: git status --short",
  precondition_items: [
    { text: "#7 이 done 일 것", command: "", kind: "todo", met: true },
    { text: "기획 확정", command: "", kind: "manual", met: null },
    { text: "작업트리가 깨끗할 것", command: "git status --short", kind: "command", met: null },
  ],
};

const asked = [];
globalThis.fetch = (url, options) => {
  asked.push({ url, body: options?.body });
  const payload = {
    "/api/workspaces": [],
    "/api/categories": [],
    "/api/todos/42": { todo: TODO, sessions: [], worktrees: [] },
    "/api/precondition-check": { command: "git status --short", exit_code: 0, output: "" },
  }[url];
  return Promise.resolve({ ok: true, json: () => Promise.resolve(payload) });
};

const { openDetail } = await import("../static/js/sessions.js");

body.children = [];
openDetail({ todo: { id: 42 } });
for (let i = 0; body.children.length !== 4 && i < 50; i += 1) {
  await new Promise((done) => setTimeout(done, 0));
}
assert.equal(body.children.length, 4, `팝업이 안 그려졌다: ${body.textContent}`);

const [, overview] = body.children;
const block = overview.children[0];
// 제목 / History / 착수 조건 / note 라벨 / note 본문
const conditions = block.children[2];
assert.equal(conditions.children[0].textContent, "착수 조건");

const rows = conditions.children[1].children;
assert.equal(rows.length, 3, "항목이 줄마다 하나씩 안 그려졌다");
// 판정 결과가 항목마다 보여야 한다 — 충족 / 미판정 / 미판정
assert.deepEqual(
  rows.map((row) => row.children[0].textContent),
  ["✓", "?", "?"],
);
assert.deepEqual(
  rows.map((row) => row.children[0].className),
  ["cond-mark met", "cond-mark unknown", "cond-mark unknown"],
);
// 확인 명령이 있는 항목에만 버튼이 붙는다
assert.equal(rows[0].children.length, 2);
assert.equal(rows[1].children.length, 2);
assert.equal(rows[2].children.length, 3);

const check = rows[2].children[2];
const [button, output] = check.children;
assert.equal(button.textContent, "확인");
assert.equal(button.title, "git status --short");

button.listeners.click();
await new Promise((done) => setTimeout(done, 0));
const call = asked.find((entry) => entry.url === "/api/precondition-check");
assert.ok(call, asked.map((entry) => entry.url).join(", "));
// 명령 문자열이 아니라 몇 번째 항목인지만 보낸다 — 보내면 임의 실행 창구가 된다
assert.deepEqual(JSON.parse(call.body), { todo_id: 42, index: 2 });
assert.equal(check.className, "cond-check met");
assert.equal(output.textContent, "exit 0");

console.log("ok");
