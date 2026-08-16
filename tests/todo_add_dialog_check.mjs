// 워크스페이스 카드의 + 버튼이 팝업을 열고, 그 폼이 제목·착수 조건·note 를 한 번에
// 보내는지 본다. prompt 를 쓰면 브라우저가 둘째부터 억제해 제목만 물어본 꼴이 되므로
// prompt 를 아예 호출하지 않는 것도 함께 본다.
// 실행: node tests/todo_add_dialog_check.mjs (tests/test_todo_add_dialog.py 가 부른다)
import assert from "node:assert/strict";
import { bootKorean } from "./i18n_boot.mjs";

const GROUP = { id: 7, kind: "workspace", name: "작업 대시보드", todos: [], status: "doing" };
const UNASSIGNED = { id: null, kind: "unassigned", name: "미분류", todos: [] };
const CATEGORY = { id: 3, name: "운영", color: "#888" };

const posted = [];
globalThis.fetch = async (url, options) => {
  if (options?.method === "POST") posted.push({ url, body: JSON.parse(options.body) });
  const body = {
    "/api/tree?group_by=workspace": { groups: [GROUP, UNASSIGNED] },
    "/api/next": null,
    "/api/categories": [CATEGORY],
    "/api/labels": [],
    "/api/autorun": { state: { enabled: 0 }, runs: [] },
    "/api/sessions": { sessions: [], waiting: [] },
    "/api/todos": { id: 1 },
  }[url];
  // null 도 응답이다 — /api/next 는 다음에 할 일이 없으면 null 을 준다
  return { ok: true, status: 200, json: async () => (body === undefined ? {} : body) };
};

globalThis.prompt = () => {
  throw new Error("prompt 를 쓰면 안 된다 — 팝업 폼으로 받아야 한다");
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
  showModal() {
    this.open = true;
  },
  close() {
    this.open = false;
  },
  addEventListener(type, handler) {
    this.listeners[type] = handler;
  },
});

const created = [];
const elements = {};
globalThis.document = {
  getElementById: (id) => (elements[id] ??= node(id)),
  createElement: () => {
    const made = node();
    created.push(made);
    return made;
  },
  createTextNode: () => node(),
  addEventListener() {},
  querySelectorAll: () => [],
};
// board.js 가 main.js 를 타고 들어오면서 라우팅·히스토리를 건드린다
globalThis.location = { pathname: "/board" };
globalThis.window = { addEventListener() {}, location: globalThis.location };
globalThis.history = { pushState() {}, replaceState() {} };

await bootKorean();
// 화면 모듈은 최상단에서 저장해 둔 값(뷰 모드·열 수)을 읽는다. 브라우저 밖에는 없는 것
globalThis.localStorage = { getItem: () => null, setItem() {} };

const board = await import("../static/js/board.js");
await board.renderBoard();

// + 버튼은 카드마다 하나 — 미분류 카드에도 있어야 한다 (자잘한 건은 거기서 끝낸다)
const plusButtons = created.filter((made) => made.className === "group-add");
assert.equal(plusButtons.length, 2, "+ 버튼이 워크스페이스·미분류 두 카드에 없다");
const [plus, unassignedPlus] = plusButtons;
plus.listeners.click({ preventDefault() {}, stopPropagation() {} });
assert.equal(elements["todo-add-modal"].open, true, "팝업이 안 열렸다");
assert.equal(elements["todo-add-scope"].textContent, "작업 대시보드에 할일 추가");
// 워크스페이스가 카테고리를 결정하므로 카테고리 칸은 숨어 있어야 한다
assert.equal(elements["todo-add-category-field"].hidden, true);

// 팝업에서 세 값을 채워 보내면 한 번의 POST 에 다 실려야 한다
elements["todo-add-title"].value = "제목";
elements["todo-add-precondition"].value = "#57 이 done 일 것";
elements["todo-add-note"].value = "컨텍스트";
elements["todo-add-form"].listeners.submit({ preventDefault() {} });
await new Promise((resolve) => setTimeout(resolve, 0));

assert.equal(posted.length, 1, JSON.stringify(posted));
assert.deepEqual(posted[0].body, {
  title: "제목",
  workspace_id: 7,
  precondition: "#57 이 done 일 것",
  note: "컨텍스트",
});
assert.equal(elements["todo-add-modal"].open, false, "보낸 뒤 팝업이 닫혀야 한다");

// 미분류 카드는 워크스페이스가 없으니 팝업에서 카테고리를 골라 그걸 실어 보내야 한다
unassignedPlus.listeners.click({ preventDefault() {}, stopPropagation() {} });
assert.equal(elements["todo-add-scope"].textContent, "미분류에 할일 추가");
assert.equal(elements["todo-add-category-field"].hidden, false, "카테고리 칸이 숨어 있다");
assert.match(elements["todo-add-category"].innerHTML, /운영/, "카테고리 목록이 안 채워졌다");
elements["todo-add-title"].value = "자잘한 건";
elements["todo-add-category"].value = String(CATEGORY.id);
elements["todo-add-form"].listeners.submit({ preventDefault() {} });
await new Promise((resolve) => setTimeout(resolve, 0));

assert.equal(posted.length, 2, JSON.stringify(posted));
assert.deepEqual(posted[1].body, {
  title: "자잘한 건",
  category_id: 3,
  precondition: null,
  note: null,
});

console.log("ok");
// renderBoard 가 자율 수행·세션 폴링 타이머를 켠다. 안 끄면 node 가 끝나지 않는다
process.exit(0);
