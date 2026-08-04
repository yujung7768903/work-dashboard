// 자율 수행 줄을 누르면 그 실행의 할일로 상세 팝업이 열리는지, '확인 필요' 배지를 누르면
// 팝업 대신 확인 요청이 나가는지 본다. 브라우저 없이 돌려야 하므로 autorun.js 가 만지는
// DOM 만 흉내낸다. 실행: node tests/autorun_row_click_check.mjs
// (tests/test_autorun_row_click.py 가 이걸 부른다)
import assert from "node:assert/strict";

const RUN = {
  id: 2,
  todo_id: 57,
  todo_title: "제목",
  workspace_name: "작업 대시보드",
  worktree_path: "/home/u/work/work-dashboard/.claude/worktrees/고침",
  worktree: "고침",
  ports: [9081],
};
const REVIEW_RUN = { id: 3, todo_id: 58, todo_title: "확인 대기", outcome: "review" };
const TICK_AT = new Date(Date.now() - 3 * 60 * 1000).toISOString(); // 3분 전 tick
const REASON = "돌릴 수 있는 할일이 없음"; // 켜져 있는데 안 도는 이유. 주기 옆에 같이 보인다

const asked = [];
globalThis.fetch = async (url, options) => {
  asked.push(`${options?.method ?? "GET"} ${url}`);
  const body = {
    "/api/autorun": {
      state: { enabled: 1, last_tick_at: TICK_AT, last_tick_reason: REASON },
      runs: [RUN, REVIEW_RUN],
    },
    "/api/workspaces": [],
    "/api/categories": [],
    "/api/todos/57": { todo: { id: 57, title: "제목" }, sessions: [] },
    "/api/autorun-runs/3": { id: 3, outcome: "done" },
  }[url];
  return { ok: Boolean(body), status: body ? 200 : 404, json: async () => body ?? {} };
};

const node = () => ({
  textContent: "",
  hidden: false,
  open: false,
  style: { setProperty() {} },
  classList: { toggle() {}, remove() {}, add() {} },
  children: [],
  listeners: {},
  // 칸 순서를 보려면 붙은 것을 들고 있어야 한다
  append(...items) {
    this.children.push(...items);
  },
  appendChild() {},
  replaceChildren() {},
  showModal() {
    this.open = true;
  },
  addEventListener(type, handler) {
    this.listeners[type] = handler;
  },
});

const rows = [];
const created = [];
const list = { ...node(), appendChild: (item) => rows.push(item) };
const elements = { "autorun-list": list };
globalThis.document = {
  getElementById: (id) => (elements[id] ??= node()),
  createElement: () => {
    const made = node();
    created.push(made);
    return made;
  },
};

const autorun = await import("../static/js/autorun.js");
await autorun.renderAutorun();

// 주기 옆에 마지막 tick 과 그 판정 사유가 붙는다 — 크론이 죽었는지, 켜져 있는데 왜 안
// 도는지 이 줄로만 알 수 있다
assert.equal(
  elements["autorun-cycle"].textContent,
  `5분마다 | 마지막 수행 3m 전 · ${REASON}`,
);

// 칸 순서 — 워크스페이스 / 할일 / 워크트리 / 포트 / 상태 / 경과
assert.deepEqual(
  rows[0].children.map((cell) => cell.className),
  ["scope", "prompt", "wt", "ports", "badge outcome-running", "age"],
);
assert.equal(rows[0].children[2].textContent, "고침");

// 포트는 그 서버로 가는 링크다. 눌러도 줄 클릭(팝업)으로 새면 안 된다
const port = rows[0].children[3].children[0];
assert.equal(port.textContent, ":9081");
assert.equal(port.href, "http://localhost:9081");
let portStopped = false;
port.listeners.click({ stopPropagation: () => (portStopped = true) });
assert.equal(portStopped, true);

// 줄마다 클릭 핸들러가 붙어 있어야 한다 — 안 붙으면 눌러도 아무 일도 없다
assert.equal(rows.length, 2);
assert.equal(typeof rows[0].listeners.click, "function");

rows[0].listeners.click();
// 팝업이 읽는 것은 세션이 아니라 그 실행의 할일이다 (todo_id 57)
await new Promise((resolve) => setTimeout(resolve, 0));
assert.ok(asked.includes("GET /api/todos/57"), asked.join(", "));
assert.equal(elements["session-modal"].open, true);

// 확인 필요 배지는 눌리는 버튼이고, 눌러도 줄 클릭(팝업)으로 새지 않아야 한다
const badge = created.find((made) => made.textContent === "확인 필요");
assert.ok(badge, "확인 필요 배지가 없다");
assert.equal(typeof badge.listeners.click, "function");
let stopped = false;
badge.listeners.click({ stopPropagation: () => (stopped = true) });
assert.equal(stopped, true);
await new Promise((resolve) => setTimeout(resolve, 0));
assert.ok(asked.includes("PATCH /api/autorun-runs/3"), asked.join(", "));

console.log("ok");
