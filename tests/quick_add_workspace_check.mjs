// 보드 위쪽 빠른 추가가 할일이 아니라 워크스페이스를 만드는지 본다. 할일은 카드마다
// + 버튼이 있으니 빠른 추가는 워크스페이스 몫이다.
// 실행: node tests/quick_add_workspace_check.mjs (tests/test_quick_add_workspace.py 가 부른다)
import assert from "node:assert/strict";
import { bootKorean } from "./i18n_boot.mjs";

const GROUP = { id: 7, kind: "workspace", name: "작업 대시보드", todos: [], status: "doing" };
const CATEGORY = { id: 3, name: "운영", color: "#888" };

const posted = [];
globalThis.fetch = async (url, options) => {
  if (options?.method === "POST") posted.push({ url, body: JSON.parse(options.body) });
  const body = {
    "/api/tree?group_by=workspace": { groups: [GROUP] },
    "/api/next": null,
    "/api/categories": [CATEGORY],
    "/api/labels": [],
    "/api/autorun": { state: { enabled: 0 }, runs: [] },
    "/api/sessions": { sessions: [], waiting: [] },
    "/api/workspaces": { id: 9 },
  }[url];
  return { ok: true, status: 200, json: async () => (body === undefined ? {} : body) };
};

const node = (id) => ({
  id,
  value: "",
  textContent: "",
  hidden: false,
  open: false,
  checked: false,
  innerHTML: "",
  className: "",
  dataset: {},
  title: "",
  style: { setProperty() {} },
  classList: { toggle() {}, remove() {}, add() {} },
  children: [],
  listeners: {},
  append() {},
  appendChild() {},
  replaceChildren() {},
  querySelectorAll: () => [],
  focus() {},
  showModal() {},
  close() {},
  addEventListener(type, handler) {
    this.listeners[type] = handler;
  },
});

const elements = {};
globalThis.document = {
  getElementById: (id) => (elements[id] ??= node(id)),
  createElement: () => node(),
  createTextNode: () => node(),
  addEventListener() {},
  querySelectorAll: () => [],
};
globalThis.location = { pathname: "/board" };
globalThis.window = { addEventListener() {}, location: globalThis.location };
globalThis.history = { pushState() {}, replaceState() {} };

await bootKorean();
const board = await import("../static/js/board.js");
await board.renderBoard();

// 빠른 추가 칸은 렌더가 손대지 않으므로 elements 캐시에 없을 수 있다 — 여기서 만든다
const name = document.getElementById("quick-name");
name.value = "새 워크스페이스";
document.getElementById("quick-category").value = String(CATEGORY.id);
elements["quick-add"].listeners.submit({ preventDefault() {} });
await new Promise((resolve) => setTimeout(resolve, 0));

assert.equal(posted.length, 1, JSON.stringify(posted));
assert.equal(posted[0].url, "/api/workspaces", "할일이 아니라 워크스페이스를 만들어야 한다");
assert.deepEqual(posted[0].body, { name: "새 워크스페이스", category_id: 3 });
// 다음 입력을 바로 받도록 비워야 한다
assert.equal(name.value, "");

console.log("ok");
// renderBoard 가 자율 수행·세션 폴링 타이머를 켠다. 안 끄면 node 가 끝나지 않는다
process.exit(0);
