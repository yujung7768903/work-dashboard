// 워크트리 케밥 메뉴의 서버 항목 검증 — 떠 있으면 "다시 띄우기·내리기", 없으면 "띄우기"
// 하나만 나오고, 누르면 그 동작으로 POST 되는지 본다.
// 브라우저 없이 돌려야 하므로 worktrees.js 가 만지는 DOM 만 흉내낸다.
// 실행: node tests/worktree_serve_menu_check.mjs  (tests/test_serve_menu.py 가 이걸 부른다)
import assert from "node:assert/strict";

const SERVING = "/repo/.claude/worktrees/up";
const IDLE = "/repo/.claude/worktrees/down";

const row = (branch, path, ports) => ({
  branch,
  path,
  is_base: false,
  ahead: 1,
  behind: 0,
  summary: "작업",
  processes: ports ? [{ pid: 1, command: "python3 server.py", ports }] : [],
  commits: [],
});

const GROUPS = [
  {
    id: 1,
    name: "작업 대시보드",
    category_id: null,
    category_name: "개발환경 개선",
    category_color: null,
    repo: "/repo",
    base: "master",
    hidden_branches: 0,
    rows: [row("worktree-up", SERVING, [9091]), row("worktree-down", IDLE, null)],
  },
];

const asked = [];
globalThis.fetch = async (url, options) => {
  asked.push({ method: options?.method ?? "GET", url, body: options?.body });
  const body = { "/api/worktrees": { groups: GROUPS } }[url];
  return { ok: true, status: 200, json: async () => body ?? {} };
};

const confirms = [];
globalThis.confirm = (message) => {
  confirms.push(message);
  return true;
};
globalThis.alert = () => {};

const node = () => {
  const made = {
    textContent: "",
    title: "",
    href: "",
    className: "",
    innerHTML: "",
    hidden: false,
    open: false,
    style: { setProperty() {} },
    classList: { toggle() {}, add() {}, remove() {} },
    children: [],
    listeners: {},
    append: (...kids) => made.children.push(...kids),
    appendChild: (kid) => made.children.push(kid),
    replaceChildren() {},
    showModal() {},
    addEventListener(type, handler) {
      made.listeners[type] = handler;
    },
  };
  return made;
};

const created = [];
const elements = { "worktree-list": node() };
// worktrees.js 는 board.js 를 거쳐 main.js 까지 끌고 들어온다 — main.js 가 모듈
// 최상단에서 라우팅을 한 번 돌리므로 location·history·window 도 흉내내야 한다
globalThis.location = { pathname: "/" };
globalThis.history = { pushState() {}, replaceState() {} };
globalThis.window = { addEventListener() {} };
globalThis.document = {
  getElementById: (id) => (elements[id] ??= node()),
  createElement: () => {
    const made = node();
    created.push(made);
    return made;
  },
  createTextNode: () => node(),
  querySelectorAll: () => [],
  addEventListener() {},
};

const worktrees = await import("../static/js/worktrees.js");
await worktrees.renderWorktrees();

const settle = () => new Promise((resolve) => setTimeout(resolve, 0));
const toggles = () => created.filter((made) => made.textContent === "⋮");
const labelsOfOpenMenu = () =>
  created
    .filter((made) => made.className === "ws-menu-items")
    .pop()
    .children.map((kid) => kid.textContent);
const buttonNamed = (label) => created.filter((made) => made.textContent === label).pop();

assert.equal(toggles().length, 2, "워크트리 줄마다 케밥 메뉴가 하나씩 있어야 한다");
assert.ok(toggles()[0].title.includes("띄우기"), toggles()[0].title);

// 떠 있는 줄 — 다시 띄우기·내리기. 아직 안 떴는데 내리라고 할 수는 없으므로 띄우기는 없다
toggles()[0].listeners.click({ stopPropagation() {} });
assert.deepEqual(labelsOfOpenMenu(), ["다시 띄우기", "내리기", "적용", "삭제"]);

// 떠 있지 않은 줄 — 띄우기만
toggles()[1].listeners.click({ stopPropagation() {} });
assert.deepEqual(labelsOfOpenMenu(), ["띄우기", "적용", "삭제"]);

// 띄우기는 확인창 없이 바로 그 브랜치로 POST 된다
buttonNamed("띄우기").listeners.click({ stopPropagation() {} });
await settle();
const posted = asked.filter((call) => call.method === "POST");
assert.equal(posted.length, 1, JSON.stringify(asked));
assert.deepEqual(JSON.parse(posted[0].body), {
  repo: "/repo",
  branch: "worktree-down",
  action: "start",
});
assert.deepEqual(confirms, [], "띄우기는 되묻지 않는다");
// 목록을 다시 받아 포트 칸이 갱신돼야 한다
assert.ok(asked.at(-1).url === "/api/worktrees" && asked.at(-1).method === "GET");

// 내리기는 남의 화면을 끊을 수 있어 확인을 받는다
toggles()[0].listeners.click({ stopPropagation() {} });
buttonNamed("내리기").listeners.click({ stopPropagation() {} });
await settle();
assert.equal(confirms.length, 1, confirms.join(" / "));
assert.ok(confirms[0].includes("9091"), confirms[0]);
assert.deepEqual(JSON.parse(asked.filter((call) => call.method === "POST").at(-1).body), {
  repo: "/repo",
  branch: "worktree-up",
  action: "stop",
});

console.log("ok");
