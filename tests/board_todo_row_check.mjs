// 보드 할일 줄이 상태·#id·우선순위·제목 순서로 그려지는지 본다.
// 우선순위는 '{이 할일}/{열린 할일 중 최고}', 정하지 않았으면 '-'.
// 실행: node tests/board_todo_row_check.mjs (tests/test_board_todo_row.py 가 부른다)
import assert from "node:assert/strict";
import { bootKorean } from "./i18n_boot.mjs";

const GROUP = {
  id: 7, kind: "workspace", name: "작업 대시보드", total_count: 1, done_count: 0,
  todos: [
    { id: 12, title: "결정 대기 큐 구현", status: "todo", labels: [], priority: 3 },
    { id: 13, title: "우선순위 없음", status: "todo", labels: [], priority: null },
  ],
};

globalThis.fetch = async (url) => {
  const body = {
    "/api/tree?group_by=workspace": { groups: [GROUP], priority_max: 10 },
    "/api/next": null,
    "/api/categories": [],
    "/api/labels": [],
    "/api/autorun": { state: { enabled: 0 }, runs: [] },
    "/api/sessions": { sessions: [], waiting: [] },
  }[url];
  return { ok: true, status: 200, json: async () => (body === undefined ? {} : body) };
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
  // 완료 항목 표시는 체크박스가 아니라 눌린 상태가 남는 아이콘이다 (board.js showDone)
  getAttribute: () => null,
  setAttribute() {},
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

const rows = created.filter((made) => made.className === "todo todo");
assert.equal(rows.length, 2, "할일 줄이 안 그려졌다");

const [status, id, priority, title] = rows[0].children;
assert.equal(status.tag, "button", "첫 칸은 상태 버튼이어야 한다");
assert.equal(status.textContent, "todo");
assert.equal(id.className, "todo-id", "둘째 칸은 #id 여야 한다");
assert.equal(id.textContent, "#12");
assert.equal(priority.className, "todo-priority", "셋째 칸은 우선순위여야 한다");
assert.equal(priority.textContent, "3/10");
assert.equal(title.className, "title", "넷째 칸은 제목이어야 한다");
assert.equal(title.textContent, "결정 대기 큐 구현");

assert.equal(rows[1].children[2].textContent, "-", "우선순위가 없으면 '-'");

console.log("ok");
// renderBoard 가 자율 수행·세션 폴링 타이머를 켠다. 안 끄면 node 가 끝나지 않는다
process.exit(0);
