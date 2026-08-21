// 칸반이 상태별 컬럼 → 워크스페이스 카드 → 그 상태의 할일 순서로 그려지는지 본다.
// 실행: node tests/kanban_view_check.mjs (tests/test_kanban_view.py 가 부른다)
import assert from "node:assert/strict";
import { bootKorean } from "./i18n_boot.mjs";

const DASHBOARD = {
  id: 3, kind: "workspace", name: "작업 대시보드", category_id: 1,
  category_color: "#4a5ae8", total_count: 3, done_count: 1,
  todos: [
    { id: 11, title: "칸반 뷰", status: "doing", labels: [] },
    { id: 12, title: "결정 대기 큐", status: "todo", labels: [] },
    { id: 13, title: "라벨 필터", status: "done", labels: [] },
  ],
};
// 진행중이 없는 워크스페이스. 그 컬럼에서는 카드째 빠져야 한다
const CONCURRENCY = {
  id: 2, kind: "workspace", name: "KT 동시성", category_id: 1,
  category_color: "#4a5ae8", total_count: 1, done_count: 0,
  todos: [{ id: 21, title: "락 재설계", status: "todo", labels: [] }],
};

const calls = [];
globalThis.fetch = async (url, options = {}) => {
  calls.push(`${options.method ?? "GET"} ${url}`);
  const body = {
    "/api/tree?group_by=workspace": { groups: [DASHBOARD, CONCURRENCY] },
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
  // 빈 문자열을 넣으면 자식이 지워지는 것까지 흉내낸다 — 다시 그렸는지 세려면 필요하다
  get innerHTML() {
    return this.html ?? "";
  },
  set innerHTML(value) {
    this.html = value;
    if (!value) this.children.length = 0;
  },
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

const elements = {};
globalThis.document = {
  getElementById: (id) => (elements[id] ??= node("div")),
  createElement: node,
  createTextNode: () => node("text"),
  addEventListener() {},
  querySelectorAll: () => [],
};
globalThis.location = { pathname: "/board" };
globalThis.window = { addEventListener() {}, location: globalThis.location };
globalThis.history = { pushState() {}, replaceState() {} };

await bootKorean();
globalThis.localStorage = { getItem: () => null, setItem() {} };

const kanban = await import("../static/js/kanban.js");
await kanban.renderKanban();

const columns = elements.kanban.children;
assert.equal(columns.length, 3, "컬럼은 대기·진행중·완료 셋이어야 한다");
assert.deepEqual(
  columns.map((column) => column.dataset.status),
  ["todo", "doing", "done"],
  "컬럼 순서는 대기 → 진행중 → 완료"
);
// 상태는 클래스로 붙이지 않는다 — .todo·.done 은 할일 줄 스타일이라 컬럼에 걸린다
assert.deepEqual(
  columns.map((column) => column.className),
  ["kanban-col", "kanban-col", "kanban-col"]
);

const [head, ...cards] = columns[0].children;
assert.equal(head.className, "kanban-head", "컬럼 첫 줄은 머리글이어야 한다");
assert.equal(head.children[0].textContent, "대기");
assert.equal(head.children[1].textContent, "2", "머리글 숫자는 그 컬럼의 할일 수");
assert.equal(cards.length, 2, "대기 컬럼에는 두 워크스페이스 카드가 들어간다");

const [cardHead, ...rows] = cards[0].children;
assert.equal(cardHead.tag, "header", "카드 첫 줄은 워크스페이스 머리글");
assert.equal(cardHead.children[0].textContent, "작업 대시보드");
assert.equal(rows.length, 1, "카드 안에는 그 상태의 할일만 들어간다");
assert.equal(rows[0].children[2].textContent, "결정 대기 큐");

// 진행중이 없는 워크스페이스는 그 컬럼에서 카드째 빠진다
const doing = columns[1].children.slice(1);
assert.equal(doing.length, 1);
assert.equal(doing[0].children[0].children[0].textContent, "작업 대시보드");

// 상태 버튼은 다음 상태로 옮기는 유일한 손잡이다. 누르면 목록이 아니라 이 화면이
// 다시 그려져야 한다 — 안 그러면 옮긴 할일이 그 자리에 남아 있는 것처럼 보인다
calls.length = 0;
rows[0].children[0].listeners.click({ stopPropagation() {} });
// 버튼 핸들러는 안쪽 비동기를 기다리지 않는다 — 요청·재렌더가 끝날 틈을 준다
await new Promise((resolve) => setTimeout(resolve, 50));
assert.equal(elements.error.textContent, "", "상태 변경이 오류로 끝났다");
assert.ok(
  calls.includes("PATCH /api/todos/12"),
  `상태 변경 요청이 안 나갔다: ${calls}`
);
assert.equal(
  calls.filter((call) => call === "GET /api/tree?group_by=workspace").length,
  1,
  "칸반이 다시 그려져야 한다"
);
assert.equal(elements.kanban.children.length, 3, "컬럼이 새로 세 개만 남아야 한다");

console.log("ok");
// 세션·자율 수행 폴링 타이머가 켜져 있으면 node 가 끝나지 않는다
process.exit(0);
