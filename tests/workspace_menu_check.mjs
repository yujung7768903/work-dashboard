// 보드 카드 헤더 케밥 메뉴 검증 — + 버튼 대신 할일 추가·수정·삭제를 한 메뉴에 둔다
//   1. 워크스페이스 카드: 세 항목. 수정은 그 워크스페이스를 다시 받아 편집 팝업을 열고
//      저장하면 PATCH 뒤 팝업을 닫는다. 삭제는 이름을 넣어 되묻고 DELETE 한다
//   2. 미분류 카드: 고칠 워크스페이스가 없어 할일 추가만. 누르면 할일 추가 팝업이 열린다
// 브라우저 없이 돌려야 하므로 board.js·workspace.js 가 만지는 DOM 만 흉내낸다
// (tests/todo_start_menu_check.mjs 와 같은 방식).
// 실행: node tests/workspace_menu_check.mjs (tests/test_workspace_menu.py 가 부른다)
import assert from "node:assert/strict";
import { bootKorean } from "./i18n_boot.mjs";

const WS_ID = 7;
const WS_NAME = "작업 대시보드";
const NEW_NAME = "작업 대시보드 2차";
const WORKSPACE = {
  id: WS_ID, name: WS_NAME, category_id: 1, status: "active", jira_id: null,
  background: "", purpose: "", goal: "1차 완성", considerations: "",
};
const GROUPS = [
  {
    id: WS_ID, kind: "workspace", name: WS_NAME, category_id: 1, total_count: 1, done_count: 0,
    todos: [{ id: 108, title: "할일 하나", status: "todo", labels: [] }],
  },
  {
    id: null, kind: "unassigned", name: "미분류", total_count: 1, done_count: 0,
    todos: [{ id: 105, title: "미분류 할일", status: "todo", labels: [] }],
  },
];
const WS_MENU_TITLE = "할일 추가 · 수정 · 삭제";
const ADD_TODO = "할일 추가";

const asked = [];
globalThis.fetch = async (url, options) => {
  const method = options?.method ?? "GET";
  const body = options?.body ? JSON.parse(options.body) : undefined;
  asked.push({ method, url, body });
  if (url === `/api/workspaces/${WS_ID}`) {
    const payload =
      method === "GET" ? { workspace: WORKSPACE, todos: [] } : { ...WORKSPACE, ...body };
    return { ok: true, status: 200, json: async () => payload };
  }
  const fixed = {
    "/api/tree?group_by=workspace": { groups: GROUPS },
    "/api/next": null,
    "/api/categories": [{ id: 1, name: "개발", color: "#3355aa" }],
    "/api/labels": [],
    "/api/autorun": { state: { enabled: 0 }, runs: [] },
    "/api/sessions": { sessions: [], waiting: [] },
  }[url];
  return { ok: true, status: 200, json: async () => (fixed === undefined ? {} : fixed) };
};

const confirms = [];
globalThis.confirm = (message) => {
  confirms.push(message);
  return true;
};
globalThis.alert = (message) => {
  throw new Error(`뜻밖의 alert: ${message}`);
};

const node = (tag) => ({
  tag,
  value: "",
  textContent: "",
  hidden: false,
  open: false,
  checked: false,
  innerHTML: "",
  className: "",
  dataset: {},
  title: "",
  disabled: false,
  draggable: false,
  returnValue: "",
  style: { setProperty() {} },
  classList: { toggle() {}, remove() {}, add() {} },
  children: [],
  listeners: {},
  append(...kids) {
    this.children.push(...kids);
  },
  appendChild(kid) {
    this.children.push(kid);
    return kid;
  },
  replaceChildren(...kids) {
    this.children = kids;
  },
  querySelectorAll: () => [],
  getBoundingClientRect: () => ({ top: 0 }),
  getAttribute: () => null,
  setAttribute() {},
  focus() {},
  addEventListener(type, handler) {
    this.listeners[type] = handler;
  },
  showModal() {
    this.open = true;
  },
  close(returnValue) {
    if (returnValue !== undefined) this.returnValue = returnValue;
    this.open = false;
    this.listeners.close?.();
  },
});

const created = [];
const elements = {};
globalThis.document = {
  getElementById: (id) => (elements[id] ??= node("div")),
  createElement: (tag) => {
    const made = node(tag);
    created.push(made);
    return made;
  },
  createTextNode: () => node("text"),
  addEventListener() {},
  querySelectorAll: () => [],
};
globalThis.location = { pathname: "/board" };
globalThis.window = { addEventListener() {}, location: globalThis.location };
globalThis.history = { pushState() {}, replaceState() {} };
globalThis.innerHeight = 800;

await bootKorean();
globalThis.localStorage = { getItem: () => null, setItem() {} };

const board = await import("../static/js/board.js");
await board.renderBoard();

const settle = () => new Promise((resolve) => setTimeout(resolve, 0));
const click = (target) => target.listeners.click({ preventDefault() {}, stopPropagation() {} });
// 카드 헤더 케밥은 할일 줄 케밥과 같은 ⋮ 이라 툴팁으로 가른다
const kebabs = (title) =>
  created.filter((made) => made.textContent === "⋮" && made.title === title);
const buttonNamed = (label) => created.filter((made) => made.textContent === label).pop();
const menuItems = (since) =>
  created
    .slice(since)
    .filter((made) => made.className === "ws-menu-items")
    .pop()
    .children.map((kid) => kid.textContent);

assert.equal(kebabs(WS_MENU_TITLE).length, 1, "워크스페이스 카드 헤더에 케밥 하나");
assert.equal(kebabs(ADD_TODO).length, 1, "미분류 카드 헤더에도 케밥 하나");

// 1. 워크스페이스 카드 — 할일 추가·수정·삭제 세 항목, 자주 쓰는 것이 위, 되돌리기 어려운 것이 아래
let since = created.length;
click(kebabs(WS_MENU_TITLE).pop());
await settle();
assert.deepEqual(menuItems(since), [ADD_TODO, "수정", "삭제"]);

// 수정 — 그 워크스페이스를 다시 받아 편집 팝업을 열고, 제목에 이름을 쓴다
click(buttonNamed("수정"));
await settle();
assert.ok(
  asked.some((call) => call.method === "GET" && call.url === `/api/workspaces/${WS_ID}`),
  "본문(배경·목표)은 목록에 없으므로 그 워크스페이스를 다시 받아야 한다"
);
assert.equal(elements["ws-edit-modal"].open, true, "편집 팝업이 열려야 한다");
assert.equal(elements["ws-edit-title"].textContent, `${WS_NAME} 수정`);
const nameInput = created.filter((made) => made.tag === "input" && made.value === WS_NAME).pop();
assert.ok(nameInput, "편집 카드의 이름 칸에 지금 이름이 들어 있어야 한다");

// 이름을 고쳐 저장 — PATCH 뒤 팝업이 닫히고 목록을 다시 받는다
nameInput.value = NEW_NAME;
const treeCallsBeforeSave = asked.filter((call) => call.url.startsWith("/api/tree")).length;
click(buttonNamed("저장"));
await settle();
const patched = asked.filter((call) => call.method === "PATCH");
assert.equal(patched.length, 1, JSON.stringify(asked));
assert.equal(patched[0].url, `/api/workspaces/${WS_ID}`);
assert.equal(patched[0].body.name, NEW_NAME);
assert.equal(elements["ws-edit-modal"].open, false, "저장하면 팝업이 닫혀야 한다");
assert.ok(
  asked.filter((call) => call.url.startsWith("/api/tree")).length > treeCallsBeforeSave,
  "저장 뒤 보드를 다시 그려야 바뀐 이름이 보인다"
);

// 삭제 — 무엇을 지우는지 이름을 넣어 되묻고, 확인하면 DELETE
click(kebabs(WS_MENU_TITLE).pop());
await settle();
click(buttonNamed("삭제"));
await settle();
assert.equal(confirms.length, 1, "삭제 전에 한 번 되물어야 한다");
assert.ok(confirms[0].includes(WS_NAME), confirms[0]);
assert.deepEqual(
  asked.filter((call) => call.method === "DELETE").map((call) => call.url),
  [`/api/workspaces/${WS_ID}`]
);

// 2. 미분류 카드 — 할일 추가만. 누르면 카테고리 선택이 있는 할일 추가 팝업이 열린다
since = created.length;
click(kebabs(ADD_TODO).pop());
await settle();
assert.deepEqual(menuItems(since), [ADD_TODO], "미분류에는 고칠 워크스페이스가 없다");
click(buttonNamed(ADD_TODO));
await settle();
assert.equal(elements["todo-add-modal"].open, true, "할일 추가 팝업이 열려야 한다");
assert.equal(elements["todo-add-category-field"].hidden, false, "미분류는 카테고리를 골라야 한다");

console.log("ok");
// renderBoard 가 자율 수행·세션 폴링 타이머를 켠다. 안 끄면 node 가 끝나지 않는다
process.exit(0);
