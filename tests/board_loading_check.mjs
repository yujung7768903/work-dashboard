// 할일 케밥의 "시작"·"삭제" 가 도는 동안 목록 자리에 도는 원이 서는지 본다.
// 시작은 워크트리를 만들고 세션을 띄우느라 몇 초가 걸린다 — 그동안 목록이 그대로면
// 눌린 건지 알 수 없다. 끝나면 원은 사라지고 목록이 그 자리를 되찾아야 한다.
// 브라우저 없이 돌려야 하므로 board.js 가 만지는 DOM 만 흉내낸다.
// 실행: node tests/board_loading_check.mjs (tests/test_board_loading.py 가 부른다)
import assert from "node:assert/strict";
import { bootKorean } from "./i18n_boot.mjs";

const TODO_ID = 137;
const TODO_TITLE = "할일 케밥의 시작·삭제에 로딩 표시";
const GROUP = {
  id: 3, kind: "workspace", name: "작업 대시보드", total_count: 1, done_count: 0,
  todos: [{ id: TODO_ID, title: TODO_TITLE, status: "todo", labels: [] }],
};
const STARTED_MESSAGE = `세션을 시작했습니다 — #${TODO_ID} | ${TODO_TITLE}`;

// 조작 응답만 붙잡아 둔다 — 그 사이 목록 자리에 무엇이 서 있는지가 이 체크의 전부다
let release = null;
const hold = () => new Promise((resolve) => (release = resolve));
let held = null;
// 마지막에 한 번 실패로 끝내 본다 — 그때도 원을 걷는지 봐야 한다
let fails = false;

globalThis.fetch = async (url, options) => {
  const method = options?.method ?? "GET";
  if (method === "POST" && url === "/api/todo-start") {
    await held;
    return { ok: true, status: 200, json: async () => ({ message: STARTED_MESSAGE }) };
  }
  if (method === "DELETE" && url === `/api/todos/${TODO_ID}`) {
    if (fails) return { ok: false, status: 500, json: async () => ({ error: "지울 수 없음" }) };
    await held;
    return { ok: true, status: 200, json: async () => ({}) };
  }
  const fixed = {
    "/api/tree?group_by=workspace": { groups: [GROUP] },
    "/api/next": null,
    "/api/categories": [],
    "/api/labels": [],
    "/api/autorun": { state: { enabled: 0 }, runs: [] },
    "/api/sessions": { sessions: [], waiting: [] },
  }[url];
  return { ok: true, status: 200, json: async () => (fixed === undefined ? {} : fixed) };
};

globalThis.alert = () => {};
globalThis.confirm = () => true;
// 목록 자리는 화면 위에서 200px 아래 — 도는 원은 남은 600px 을 받아야 한다
globalThis.innerHeight = 800;

const node = (tag) => {
  const made = {
    tag,
    value: "",
    textContent: "",
    hidden: false,
    open: false,
    checked: false,
    className: "",
    dataset: {},
    title: "",
    disabled: false,
    draggable: false,
    css: {},
    style: { setProperty: (name, value) => (made.css[name] = value) },
    classList: { toggle() {}, remove() {}, add() {} },
    children: [],
    listeners: {},
    attributes: {},
    getBoundingClientRect: () => ({ top: 200 }),
    append: (...kids) => made.children.push(...kids),
    appendChild: (kid) => (made.children.push(kid), kid),
    replaceChildren() {},
    querySelectorAll: () => [],
    getAttribute: () => null,
    setAttribute: (name, value) => (made.attributes[name] = value),
    focus() {},
    addEventListener: (type, handler) => (made.listeners[type] = handler),
  };
  // innerHTML = "" 이 목록을 비우는 것만 흉내낸다
  Object.defineProperty(made, "innerHTML", {
    get: () => "",
    set: (value) => {
      if (value === "") made.children.length = 0;
    },
  });
  return made;
};

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
globalThis.localStorage = { getItem: () => null, setItem() {} };

await bootKorean();
const board = await import("../static/js/board.js");
await board.renderBoard();

const settle = () => new Promise((resolve) => setTimeout(resolve, 0));
const groups = () => elements["groups"];
const spinners = () => groups().children.filter((kid) => kid.className === "loading-spin");
const toggle = () => created.filter((made) => made.textContent === "⋮").pop();
const buttonNamed = (label) => created.filter((made) => made.textContent === label).pop();

// 메뉴 항목을 누르고, 응답을 붙잡아 둔 채로 화면을 본다
async function press(label) {
  held = hold();
  toggle().listeners.click({ stopPropagation() {} });
  await settle();
  buttonNamed(label).listeners.click({ stopPropagation() {} });
  await settle();
}

for (const label of ["시작", "삭제"]) {
  assert.equal(spinners().length, 0, `${label}: 누르기 전인데 도는 원이 있다`);

  await press(label);
  assert.equal(groups().children.length, 1, `${label}: 도는 동안 목록이 그대로다`);
  const spinner = spinners()[0];
  assert.ok(spinner, `${label}: 도는 동안 표시가 없다`);
  assert.equal(spinner.attributes.role, "status");
  assert.equal(spinner.attributes["aria-label"], "불러오는 중");
  // 화면 아래까지 남은 높이를 그대로 받아야 그 한가운데에 설 수 있다
  assert.equal(spinner.css["--loading-room"], "600px");
  // 완료 영역이 그대로 남으면 원 아래에 예전 목록이 붙어 다 그려진 화면으로 읽힌다
  assert.equal(elements["done-today"].hidden, true, `${label}: 완료 영역이 남아 있다`);

  release();
  await settle();
  await settle();
  assert.equal(spinners().length, 0, `${label}: 끝났는데 도는 원이 남아 있다`);
  assert.equal(groups().children.length, 1, `${label}: 목록이 제자리를 못 찾았다`);
}

// 실패로 끝나도 원은 걷어야 한다 — 남으면 화면이 영영 도는 원으로 덮인다
fails = true;
toggle().listeners.click({ stopPropagation() {} });
await settle();
buttonNamed("삭제").listeners.click({ stopPropagation() {} });
await settle();
await settle();
assert.equal(spinners().length, 0, "실패로 끝났는데 도는 원이 남아 있다");

console.log("ok");
// renderBoard 가 자율 수행·세션 폴링 타이머를 켠다. 안 끄면 node 가 끝나지 않는다
process.exit(0);
