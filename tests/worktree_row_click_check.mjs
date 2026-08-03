// 워크트리 줄을 누르면 연결된 할일 상세 팝업이 열리는지, 연결된 할일이 없으면 안내만
// 뜨는지 본다. 포트 배지·커밋 셰브런 클릭은 줄 클릭(팝업)으로 새지 않아야 한다.
// 브라우저 없이 돌려야 하므로 worktrees.js 가 만지는 DOM 만 흉내낸다.
// 실행: node tests/worktree_row_click_check.mjs
// (tests/test_worktree_row_click.py 가 이걸 부른다)
import assert from "node:assert/strict";

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
  asked.push(`${options?.method ?? "GET"} ${url}`);
  const body = {
    "/api/worktrees": { groups: GROUPS },
    "/api/workspaces": [],
    "/api/categories": [],
    "/api/todos/57": { todo: { id: 57, title: "제목" }, sessions: [] },
  }[url];
  return { ok: Boolean(body), status: body ? 200 : 404, json: async () => body ?? {} };
};

const alerts = [];
globalThis.alert = (message) => alerts.push(message);

const node = () => ({
  textContent: "", title: "", href: "", target: "", rel: "", className: "",
  hidden: false, open: false,
  style: { setProperty() {} },
  classList: { toggle() {}, add() {}, remove() {} },
  children: [],
  listeners: {},
  append() {},
  appendChild() {},
  replaceChildren() {},
  showModal() {
    this.open = true;
  },
  addEventListener(type, handler) {
    this.listeners[type] = handler;
  },
});

const created = [];
const elements = { "worktree-list": node() };
// worktrees.js 는 board.js 를 거쳐 main.js 까지 끌고 들어온다(순환 참조) — main.js 가
// 모듈 최상단에서 라우팅을 한 번 돌리므로 history·location·window 도 흉내내야 한다
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

const worktrees = await import("../static/js/worktrees.js");
await worktrees.renderWorktrees();

const rows = created.filter((made) => made.className === "wt-row");
assert.equal(rows.length, 2, "워크트리 줄 두 개(master, worktree-feat)가 그려져야 한다");
assert.equal(typeof rows[0].listeners.click, "function");
assert.equal(typeof rows[1].listeners.click, "function");

// todo_id 가 있는 줄(master, 57) → 할일 상세 팝업이 열린다
rows[0].listeners.click();
await new Promise((resolve) => setTimeout(resolve, 0));
assert.ok(asked.includes("GET /api/todos/57"), asked.join(", "));
assert.equal(elements["session-modal"].open, true);

// todo_id 가 없는 줄(worktree-feat) → 팝업 대신 안내만 뜬다
rows[1].listeners.click();
assert.deepEqual(alerts, ["연결된 할일이 없습니다."]);
assert.ok(!asked.includes("GET /api/todos/undefined"), asked.join(", "));

// 포트 배지 클릭은 줄 클릭(팝업)까지 올라가지 않아야 한다
const port = created.find((made) => made.className === "wt-port");
assert.ok(port, "포트 배지가 없다");
let stopped = false;
port.listeners.click({ stopPropagation: () => (stopped = true) });
assert.equal(stopped, true);

console.log("ok");
