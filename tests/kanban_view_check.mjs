// 칸반이 상태별 컬럼 → 워크스페이스 카드 → 그 상태의 할일 순서로 그려지는지 본다.
// 실행: node tests/kanban_view_check.mjs (tests/test_kanban_view.py 가 부른다)
import assert from "node:assert/strict";
import { bootKorean } from "./i18n_boot.mjs";

const DASHBOARD = {
  id: 3, kind: "workspace", name: "작업 대시보드", category_id: 1,
  category_color: "#4a5ae8", total_count: 3, done_count: 1,
  todos: [
    { id: 11, title: "칸반 뷰", status: "doing", labels: [] },
    // 세션이 한 번도 안 잡은 할일. 세션이 돈 것보다 아래로 내려가야 한다
    { id: 12, title: "결정 대기 큐", status: "todo", labels: [] },
    { id: 13, title: "라벨 필터", status: "done", labels: [] },
    // 자율 수행이 done 으로 닫았지만 사람이 아직 확인하지 않은 것
    {
      id: 14, title: "확인 대기 중인 것", status: "done",
      labels: [], autorun_locked: true,
    },
  ],
};
// 진행중이 없는 워크스페이스. 그 컬럼에서는 카드째 빠져야 한다
const CONCURRENCY = {
  id: 2, kind: "workspace", name: "KT 동시성", category_id: 1,
  category_color: "#4a5ae8", total_count: 1, done_count: 0,
  todos: [
    {
      id: 21, title: "락 재설계", status: "todo",
      labels: [], last_session_at: "2026-08-21T09:00:00Z",
    },
  ],
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
  // 완료 항목 표시는 체크박스가 아니라 눌린 상태가 남는 아이콘이다 (board.js showDone)
  getAttribute: () => null,
  setAttribute() {},
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
// 상태별 뷰는 브라우저에 남긴 취향으로 고른다 — board.js 가 모듈을 들일 때 이걸 읽는다
globalThis.localStorage = {
  getItem: (key) => (key === "todo-view" ? "status" : null),
  setItem() {},
};

const board = await import("../static/js/board.js");
await board.renderBoard();

// 두 뷰가 같은 자리에 그린다 — 상태별을 고르면 워크스페이스별 목록과 그 목록에만
// 쓰이는 손잡이(완료 표시·열 수)가 함께 사라져야 한다
assert.equal(elements.kanban.hidden, false);
assert.equal(elements.groups.hidden, true);
assert.equal(elements["done-today"].hidden, true);
assert.equal(elements["todo-tools"].hidden, true);

const columns = elements.kanban.children;
assert.equal(columns.length, 4, "컬럼은 대기·진행중·검토 대기·완료 넷이어야 한다");
assert.deepEqual(
  columns.map((column) => column.dataset.status),
  ["todo", "doing", "review", "done"],
  "컬럼은 할일 줄과 같은 상태 표기 넷"
);
// 상태는 클래스로 붙이지 않는다 — .todo·.done 은 할일 줄 스타일이라 컬럼에 걸린다
assert.deepEqual(
  columns.map((column) => column.className),
  ["kanban-col", "kanban-col", "kanban-col", "kanban-col"]
);

const [head, ...cards] = columns[0].children;
assert.equal(head.className, "kanban-head", "컬럼 첫 줄은 머리글이어야 한다");
assert.equal(head.children[0].textContent, "대기");
assert.equal(head.children[1].textContent, "2", "머리글 숫자는 그 컬럼의 할일 수");
// 할일 하나가 카드 하나. 워크스페이스를 카드로 감싸지 않는다
assert.equal(cards.length, 2, "대기 컬럼에는 대기 할일 두 건이 각자 카드로 들어간다");

// 세션이 돈 할일이 위로. 워크스페이스 순서(작업 대시보드가 먼저)를 뒤집는다
const [workspace, row] = cards[0].children;
assert.equal(workspace.className, "kanban-ws", "카드 첫 줄은 워크스페이스 이름");
assert.equal(workspace.textContent, "KT 동시성", "세션이 최근에 돈 할일이 맨 위");
assert.equal(row.children[1].textContent, "락 재설계");
assert.equal(cards[1].children[0].textContent, "작업 대시보드");
assert.equal(cards[1].children[1].children[1].textContent, "결정 대기 큐");
// 컬럼이 이미 상태를 말하므로 줄 안에 상태 칩을 두지 않는다 — #id·제목부터 시작한다
assert.deepEqual(
  row.children.map((cell) => cell.className),
  ["todo-id", "title", "todo-labels", "ws-menu"]
);


// 진행중 할일이 없는 워크스페이스는 그 컬럼에 아무것도 남기지 않는다
const doing = columns[1].children.slice(1);
assert.equal(doing.length, 1);
assert.equal(doing[0].children[0].textContent, "작업 대시보드");

// 검토 대기는 status 가 done 이어도 완료 칸에 섞이지 않는다
const review = columns[2].children.slice(1);
assert.equal(review.length, 1, "검토 대기 칸에 그 할일이 있어야 한다");
assert.equal(review[0].children[1].children[1].textContent, "확인 대기 중인 것");
assert.equal(columns[3].children.slice(1).length, 1, "완료 칸에는 나머지 하나만");

// 케밥은 카드에 남은 조작 손잡이다. 누르면 목록이 아니라 이 화면이 다시 그려져야 한다 —
// 안 그러면 메뉴가 숨어 있는 목록 쪽에만 열려 카드에서는 아무 일도 안 일어난 것처럼 보인다
calls.length = 0;
row.children[3].children[0].listeners.click({ stopPropagation() {} });
// 핸들러는 안쪽 비동기를 기다리지 않는다 — 재렌더가 끝날 틈을 준다
await new Promise((resolve) => setTimeout(resolve, 50));
assert.equal(elements.error.textContent, "", "케밥 열기가 오류로 끝났다");
assert.equal(
  calls.filter((call) => call === "GET /api/tree?group_by=workspace").length,
  1,
  "칸반이 다시 그려져야 한다"
);
assert.equal(elements.kanban.children.length, 4, "컬럼이 새로 네 개만 남아야 한다");

console.log("ok");
// 세션·자율 수행 폴링 타이머가 켜져 있으면 node 가 끝나지 않는다
process.exit(0);
