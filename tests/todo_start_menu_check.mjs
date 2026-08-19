// 할일 케밥 메뉴의 "시작" 항목 검증
//   1. 위치를 아는 할일 — 누르면 그 id 로 POST 되고, 목록을 다시 받은 뒤 서버 문장을 알린다
//   2. 위치를 모르는 할일 — 서버가 reason.noCwd 로 막으면 폴더 선택기를 연다. 하위 폴더로
//      내려가다 git 저장소를 고르면 그 경로로 재시도하고, 빵부스러기로 여러 단 위를
//      한 번에 건너뛸 수도 있다
// 브라우저 없이 돌려야 하므로 board.js·browse.js 가 만지는 DOM 만 흉내낸다.
// 실행: node tests/todo_start_menu_check.mjs (tests/test_todo_start_menu.py 가 부른다)
import assert from "node:assert/strict";
import { bootKorean } from "./i18n_boot.mjs";

const TODO_ID = 108;
const TODO_TITLE = "할일 케밥 메뉴에 시작 기능 추가";
const NO_CWD_ID = 105;
const NO_CWD_TITLE = "인물사전 문의 대응";
const GROUP = {
  id: 7, kind: "workspace", name: "작업 대시보드", total_count: 2, done_count: 0,
  todos: [
    { id: TODO_ID, title: TODO_TITLE, status: "todo", labels: [] },
    { id: NO_CWD_ID, title: NO_CWD_TITLE, status: "todo", labels: [] },
  ],
};
const STARTED_MESSAGE = `세션을 시작했습니다 — #${TODO_ID} | ${TODO_TITLE}`;
const NO_CWD_MESSAGE = "그 워크스페이스에서 작업하던 위치를 알 수 없음";
const NO_CWD_STARTED_MESSAGE = `세션을 시작했습니다 — #${NO_CWD_ID} | ${NO_CWD_TITLE}`;

// 폴더 선택기가 훑는 가짜 트리: /home/user(=ROOT) → work → hk-herb-server(git 저장소)
const ROOT = "/home/user";
const SUBDIR = "/home/user/work";
const CHOSEN_CWD = "/home/user/work/hk-herb-server";
const BROWSE = {
  [ROOT]: {
    path: ROOT, parent: "/home", is_git_repo: false,
    entries: [{ name: "work", path: SUBDIR, is_git_repo: false }],
  },
  [SUBDIR]: {
    path: SUBDIR, parent: ROOT, is_git_repo: false,
    entries: [{ name: "hk-herb-server", path: CHOSEN_CWD, is_git_repo: true }],
  },
  [CHOSEN_CWD]: { path: CHOSEN_CWD, parent: SUBDIR, is_git_repo: true, entries: [] },
};

const asked = [];
// 알림과 목록 갱신의 순서를 봐야 한다 — alert 가 먼저면 확인을 누를 때까지 화면이 안 바뀐다
const order = [];
globalThis.fetch = async (url, options) => {
  const method = options?.method ?? "GET";
  const body = options?.body ? JSON.parse(options.body) : undefined;
  asked.push({ method, url, body });
  order.push(`${method} ${url}`);
  if (method === "GET" && url.startsWith("/api/browse")) {
    const path = new URL(url, "http://x").searchParams.get("path");
    return { ok: true, status: 200, json: async () => BROWSE[path ?? ROOT] };
  }
  if (method === "POST" && url === "/api/todo-start") {
    if (body.id === TODO_ID) {
      return { ok: true, status: 200, json: async () => ({ message: STARTED_MESSAGE }) };
    }
    if (body.id === NO_CWD_ID && !body.cwd) {
      return { ok: false, status: 400, json: async () => ({ error: NO_CWD_MESSAGE }) };
    }
    if (body.id === NO_CWD_ID && body.cwd === CHOSEN_CWD) {
      return {
        ok: true, status: 200,
        json: async () => ({ message: NO_CWD_STARTED_MESSAGE }),
      };
    }
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
  replaceChildren() {},
  querySelectorAll: () => [],
  focus() {},
  addEventListener(type, handler) {
    this.listeners[type] = handler;
  },
  // <dialog> 만 쓰는 두 메서드. jsdom 없이 board.js·browse.js 를 그대로 돌리려고 흉내낸다
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

await bootKorean();
// 화면 모듈은 최상단에서 저장해 둔 값(뷰 모드·열 수)을 읽는다. 브라우저 밖에는 없는 것
globalThis.localStorage = { getItem: () => null, setItem() {} };

const board = await import("../static/js/board.js");
await board.renderBoard();

const settle = () => new Promise((resolve) => setTimeout(resolve, 0));
const toggles = () => created.filter((made) => made.textContent === "⋮");
// 빵부스러기는 button.textContent 를 그대로 쓰지만(단일 문자열), 폴더 목록 행은
// 아이콘·이름·배지 세 span 을 자식으로 붙여서 만든다(browse.js) — 그래서 행은
// textContent 가 아니라 자식(이름 span)으로 찾아야 한다
const buttonNamed = (label) => created.filter((made) => made.textContent === label).pop();
const rowNamed = (name) =>
  created
    .filter((made) => made.className === "dir-browse-entry")
    .filter((made) => made.children.some((kid) => kid.textContent === name))
    .pop();
const select = () => elements["dir-browse-select"];

assert.equal(toggles().length, 2, "할일 줄마다 케밥 메뉴가 하나씩 있어야 한다");

// 1. 위치를 아는 할일 — 바로 시작되고, 목록을 다시 받은 뒤 서버 문장을 알린다
toggles()[0].listeners.click({ stopPropagation() {} });
await settle();
buttonNamed("시작").listeners.click({ stopPropagation() {} });
await settle();

let posted = asked.filter((call) => call.method === "POST");
assert.equal(posted.length, 1, JSON.stringify(asked));
assert.deepEqual(posted[0].body, { id: TODO_ID });
assert.deepEqual(alerts, [STARTED_MESSAGE], alerts.join(" / "));
assert.equal(elements["dir-browse-modal"].open, false, "위치를 아는 할일은 폴더 선택기를 안 열어야 한다");
// 목록을 다시 받은 **뒤에** 알린다 — 순서가 뒤집히면 갱신되기 전 화면에 알림이 뜬다.
// 보드는 tree 외에도 여러 GET 을 한꺼번에 쏘므로, 알림이 맨 끝이고 그 사이에
// 갱신(tree 재조회)이 있었는지만 본다 — 몇 번째 GET 인지까지는 안 본다
let postIndex = order.indexOf("POST /api/todo-start");
assert.equal(order.at(-1), "alert", order.join(" → "));
assert.equal(
  order[postIndex + 1],
  "GET /api/tree?group_by=workspace",
  order.join(" → ")
);

// 2. 위치를 모르는 할일 — 서버가 reason.noCwd 로 막으면 폴더 선택기가 열린다
toggles()[1].listeners.click({ stopPropagation() {} });
await settle();
buttonNamed("시작").listeners.click({ stopPropagation() {} });
await settle();

assert.equal(elements["dir-browse-modal"].open, true, "위치를 모르면 폴더 선택기를 열어야 한다");
// 빵부스러기의 마지막 칸은 "지금 여기" 표시라 눌러도 아무 데도 못 가게 disabled 다
assert.equal(buttonNamed("user").disabled, true, "지금 폴더(ROOT)가 빵부스러기 마지막이어야 한다");
assert.equal(select().disabled, true, "지금 폴더는 git 저장소가 아니다");

// work 폴더로 내려간다 — 아직 git 저장소가 아니라 선택 버튼은 계속 비활성
rowNamed("work").listeners.click();
await settle();
assert.equal(buttonNamed("work").disabled, true, "이제 work 가 빵부스러기 마지막");
assert.equal(select().disabled, true);

// hk-herb-server 로 내려간다 — git 저장소라 선택 버튼이 켜진다
rowNamed("hk-herb-server").listeners.click();
await settle();
assert.equal(buttonNamed("hk-herb-server").disabled, true);
assert.equal(select().disabled, false);

// 빵부스러기로 두 단 위(work 도 아니라 그 위 ROOT)를 한 번에 건너뛴다 —
// "위로" 버튼이었다면 두 번 눌러야 했을 이동이 여기선 한 번이다
buttonNamed("user").listeners.click();
await settle();
assert.equal(select().disabled, true, "ROOT 로 돌아왔으니 다시 비활성");
assert.equal(buttonNamed("user").disabled, true);

// 다시 내려가 최종 선택
rowNamed("work").listeners.click();
await settle();
rowNamed("hk-herb-server").listeners.click();
await settle();
assert.equal(select().disabled, false);

// "이 폴더 선택" — 다이얼로그가 그 경로로 닫히고, 그 경로로 재시도한다
select().onclick();
await settle();

assert.equal(elements["dir-browse-modal"].open, false);
posted = asked.filter((call) => call.method === "POST");
assert.equal(posted.length, 3, JSON.stringify(asked));
assert.deepEqual(posted[1].body, { id: NO_CWD_ID }, "첫 시도는 경로 없이");
assert.deepEqual(
  posted[2].body,
  { id: NO_CWD_ID, cwd: CHOSEN_CWD },
  "고른 경로로 재시도"
);
assert.deepEqual(alerts, [STARTED_MESSAGE, NO_CWD_STARTED_MESSAGE], alerts.join(" / "));
// 실패한 첫 시도는 조용히 삼키고(자동 alert 없이) 선택기를 열어야 한다 —
// alert 가 먼저 뜨면 그 창을 닫기 전에는 선택기가 안 보인다
assert.equal(
  order.filter((entry) => entry === "alert").length,
  2,
  "실패한 첫 시도에서 자동 alert 가 뜨면 안 된다"
);

console.log("ok");
// renderBoard 가 자율 수행·세션 폴링 타이머를 켠다. 안 끄면 node 가 끝나지 않는다
process.exit(0);
