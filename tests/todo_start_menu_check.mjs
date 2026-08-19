// 할일 케밥 메뉴의 "시작" 항목 검증 — 누르면 그 할일 id 로 POST 되고, 서버가 준
// 문장을 알림으로 보여주는지, 목록을 다시 받은 뒤에 알리는지 본다.
// 브라우저 없이 돌려야 하므로 board.js 가 만지는 DOM 만 흉내낸다.
// 실행: node tests/todo_start_menu_check.mjs (tests/test_todo_start_menu.py 가 부른다)
import assert from "node:assert/strict";
import { bootKorean } from "./i18n_boot.mjs";

const TODO_ID = 108;
const TODO_TITLE = "할일 케밥 메뉴에 시작 기능 추가";
const GROUP = {
  id: 7, kind: "workspace", name: "작업 대시보드", total_count: 1, done_count: 0,
  todos: [{ id: TODO_ID, title: TODO_TITLE, status: "todo", labels: [] }],
};
const STARTED_MESSAGE = `세션을 시작했습니다 — #${TODO_ID} | ${TODO_TITLE}`;

const asked = [];
// 알림과 목록 갱신의 순서를 봐야 한다 — alert 가 먼저면 확인을 누를 때까지 화면이 안 바뀐다
const order = [];
globalThis.fetch = async (url, options) => {
  const method = options?.method ?? "GET";
  asked.push({ method, url, body: options?.body });
  order.push(`${method} ${url}`);
  if (method === "POST" && url === "/api/todo-start") {
    return { ok: true, status: 200, json: async () => ({ message: STARTED_MESSAGE }) };
  }
  const body = {
    "/api/tree?group_by=workspace": { groups: [GROUP] },
    "/api/next": null,
    "/api/categories": [],
    "/api/labels": [],
    "/api/autorun": { state: { enabled: 0 }, runs: [] },
    "/api/sessions": { sessions: [], waiting: [] },
  }[url];
  return { ok: true, status: 200, json: async () => (body === undefined ? {} : body) };
};

const alerts = [];
globalThis.alert = (message) => {
  alerts.push(message);
  order.push("alert");
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
  replaceChildren() {},
  querySelectorAll: () => [],
  focus() {},
  addEventListener(type, handler) {
    this.listeners[type] = handler;
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

await bootKorean();
// 화면 모듈은 최상단에서 저장해 둔 값(뷰 모드·열 수)을 읽는다. 브라우저 밖에는 없는 것
globalThis.localStorage = { getItem: () => null, setItem() {} };

const board = await import("../static/js/board.js");
await board.renderBoard();

const settle = () => new Promise((resolve) => setTimeout(resolve, 0));
const toggles = () => created.filter((made) => made.textContent === "⋮");
const buttonNamed = (label) => created.filter((made) => made.textContent === label).pop();

assert.equal(toggles().length, 1, "할일 줄마다 케밥 메뉴가 하나씩 있어야 한다");

toggles()[0].listeners.click({ stopPropagation() {} });
await settle();
const startButton = buttonNamed("시작");
assert.ok(startButton, "케밥 메뉴에 시작 항목이 있어야 한다");

startButton.listeners.click({ stopPropagation() {} });
await settle();

const posted = asked.filter((call) => call.method === "POST");
assert.equal(posted.length, 1, JSON.stringify(asked));
assert.deepEqual(JSON.parse(posted[0].body), { id: TODO_ID });

assert.deepEqual(alerts, [STARTED_MESSAGE], alerts.join(" / "));
// 목록을 다시 받은 **뒤에** 알린다 — 순서가 뒤집히면 갱신되기 전 화면에 알림이 뜬다.
// 보드는 tree 외에도 여러 GET 을 한꺼번에 쏘므로, 알림이 맨 끝이고 그 사이에
// 갱신(tree 재조회)이 있었는지만 본다 — 몇 번째 GET 인지까지는 안 본다
const postIndex = order.indexOf("POST /api/todo-start");
assert.equal(order.at(-1), "alert", order.join(" → "));
assert.equal(
  order[postIndex + 1],
  "GET /api/tree?group_by=workspace",
  order.join(" → ")
);

console.log("ok");
// renderBoard 가 자율 수행·세션 폴링 타이머를 켠다. 안 끄면 node 가 끝나지 않는다
process.exit(0);
