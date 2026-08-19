// 워크트리 줄을 누르면 연결된 할일 상세 팝업이 열리는지, 연결된 할일이 없으면 안내만
// 뜨는지 본다. 포트 배지·커밋 셰브런 클릭은 줄 클릭(팝업)으로 새지 않아야 한다.
// 브라우저 없이 돌려야 하므로 worktrees.js 가 만지는 DOM 만 흉내낸다.
// 실행: node tests/worktree_row_click_check.mjs
// (tests/test_worktree_row_click.py 가 이걸 부른다)
import assert from "node:assert/strict";
import { bootKorean } from "./i18n_boot.mjs";

const GROUPS = [
  {
    id: 1, name: "작업 대시보드", category_id: 2, category_name: "카테고리",
    category_color: null, repo: "/repo", base: "master", hidden_branches: 0,
    rows: [
      {
        branch: "master", path: "/repo", is_base: true, ahead: 0, behind: 0,
        summary: "메인", todo_id: 57,
        processes: [{ pid: 1, command: "python3 server.py", ports: [9080] }],
        commits: [],
      },
      {
        branch: "worktree-feat", path: "/repo/.claude/worktrees/feat", is_base: false,
        ahead: 1, behind: 0, summary: "기능 작업", todo_id: null, processes: [],
        commits: [{ hash: "abc1234", subject: "feat: 새 기능", at: "2026-08-01T00:00:00+09:00" }],
      },
    ],
  },
];

const asked = [];
globalThis.fetch = async (url, options) => {
  // 목록은 뷰 모드를 물음표 뒤에 달고 온다. 어느 모드든 같은 응답이므로 경로만 본다
  const path = url.split("?")[0];
  asked.push(`${options?.method ?? "GET"} ${path}`);
  const body = {
    "/api/worktrees": { groups: GROUPS },
    "/api/workspaces": [],
    "/api/categories": [],
    "/api/todos/57": { todo: { id: 57, title: "제목" }, sessions: [] },
  }[path];
  return { ok: Boolean(body), status: body ? 200 : 404, json: async () => body ?? {} };
};

const alerts = [];
globalThis.alert = (message) => alerts.push(message);

const node = () => {
  const made = {
    textContent: "", title: "", href: "", target: "", rel: "", className: "",
    hidden: false, open: false,
    style: { setProperty() {} },
    setAttribute() {},
    getBoundingClientRect: () => ({ top: 0 }),
    // 어떤 클래스가 붙었는지 봐야 한다 — 누를 수 있는 칸에만 linked 가 붙는다
    classes: new Set(),
    classList: {
      toggle() {},
      add: (name) => made.classes.add(name),
      remove() {},
    },
    children: [],
    listeners: {},
    append() {},
    appendChild() {},
    replaceChildren() {},
    showModal() {
      made.open = true;
    },
    addEventListener(type, handler) {
      made.listeners[type] = handler;
    },
  };
  return made;
};

const created = [];
const elements = { "worktree-list": node() };
// worktrees.js 는 board.js 를 거쳐 main.js 까지 끌고 들어온다(순환 참조) — main.js 가
// 모듈 최상단에서 라우팅을 한 번 돌리므로 history·location·window 도 흉내내야 한다
globalThis.innerHeight = 800;
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
  querySelectorAll: () => [],
  addEventListener() {},
};

await bootKorean();
// 화면 모듈은 최상단에서 저장해 둔 값(뷰 모드·열 수)을 읽는다. 브라우저 밖에는 없는 것
globalThis.localStorage = { getItem: () => null, setItem() {} };

const worktrees = await import("../static/js/worktrees.js");
await worktrees.renderWorktrees();

const rows = created.filter((made) => made.className === "wt-row");
const names = created.filter((made) => made.className === "wt-name");
assert.equal(rows.length, 2, "워크트리 줄 두 개(master, worktree-feat)가 그려져야 한다");
assert.equal(names.length, 2);

// 누를 수 있는 범위는 이름 칸까지 — 줄 전체에는 핸들러가 붙지 않는다
assert.equal(rows[0].listeners.click, undefined, "줄 전체가 눌리면 안 된다");
assert.equal(rows[1].listeners.click, undefined, "줄 전체가 눌리면 안 된다");

// todo_id 가 있는 줄(master, 57) → 이름 칸을 누르면 할일 상세 팝업이 열린다
assert.equal(typeof names[0].listeners.click, "function");
assert.ok(names[0].classes.has("linked"), "누를 수 있는 칸에는 linked 가 붙어야 한다");
names[0].listeners.click();
await new Promise((resolve) => setTimeout(resolve, 0));
assert.ok(asked.includes("GET /api/todos/57"), asked.join(", "));
assert.equal(elements["session-modal"].open, true);

// todo_id 가 없는 줄(worktree-feat) → 아예 안 눌린다. 손 모양도 안 뜬다
assert.equal(names[1].listeners.click, undefined);
assert.ok(!names[1].classes.has("linked"));
assert.deepEqual(alerts, [], "안 눌리는 칸이므로 안내창도 뜨지 않는다");
assert.ok(!asked.includes("GET /api/todos/undefined"), asked.join(", "));

// 포트 배지 클릭은 줄 클릭(팝업)까지 올라가지 않아야 한다
const port = created.find((made) => made.className === "wt-port");
assert.ok(port, "포트 배지가 없다");
let stopped = false;
port.listeners.click({ stopPropagation: () => (stopped = true) });
assert.equal(stopped, true);

console.log("ok");
