// 자율 수행 줄을 누르면 그 실행의 할일로 상세 팝업이 열리는지 본다. 브라우저 없이
// 돌려야 하므로 autorun.js 가 만지는 DOM 만 흉내내고, 팝업은 어느 할일을 읽었는지로 본다.
// 실행: node tests/autorun_row_click_check.mjs (tests/test_autorun_row_click.py 가 이걸 부른다)
import assert from "node:assert/strict";

const RUN = { id: 2, todo_id: 57, todo_title: "제목", workspace_name: "작업 대시보드" };

const asked = [];
globalThis.fetch = async (url) => {
  asked.push(url);
  const body = {
    "/api/autorun": { state: { enabled: 1 }, runs: [RUN] },
    "/api/workspaces": [],
    "/api/categories": [],
    "/api/todos/57": { todo: { id: 57, title: "제목" }, sessions: [] },
  }[url];
  return { ok: Boolean(body), status: body ? 200 : 404, json: async () => body ?? {} };
};

const node = () => ({
  textContent: "",
  hidden: false,
  open: false,
  style: { setProperty() {} },
  classList: { toggle() {}, remove() {}, add() {} },
  children: [],
  listeners: {},
  append() {},
  appendChild() {},
  replaceChildren() {},
  showModal() {
    this.open = true;
  },
  addEventListener(type, handler) {
    this.listeners[type] = handler;
  },
});

const rows = [];
const list = { ...node(), appendChild: (item) => rows.push(item) };
const elements = { "autorun-list": list };
globalThis.document = {
  getElementById: (id) => (elements[id] ??= node()),
  createElement: () => node(),
};

const autorun = await import("../static/js/autorun.js");
await autorun.renderAutorun();

// 줄마다 클릭 핸들러가 붙어 있어야 한다 — 안 붙으면 눌러도 아무 일도 없다
assert.equal(rows.length, 1);
assert.equal(typeof rows[0].listeners.click, "function");

rows[0].listeners.click();
// 팝업이 읽는 것은 세션이 아니라 그 실행의 할일이다 (todo_id 57)
await new Promise((resolve) => setTimeout(resolve, 0));
assert.ok(asked.includes("/api/todos/57"), asked.join(", "));
assert.equal(elements["session-modal"].open, true);

console.log("ok");
