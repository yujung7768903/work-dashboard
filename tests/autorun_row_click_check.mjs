// 자율 수행 줄을 누르면 그 실행의 할일로 상세 팝업이 열리는지, '검토 대기' 배지를 누르면
// 팝업 대신 확인 요청이 나가는지, '작업 위치 미정' 칩을 누르면 폴더 선택기가 열려
// 고른 경로가 워크스페이스에 저장되는지 본다. 브라우저 없이 돌려야 하므로 autorun.js 가 만지는
// DOM 만 흉내낸다. 실행: node tests/autorun_row_click_check.mjs
// (tests/test_autorun_row_click.py 가 이걸 부른다)
import assert from "node:assert/strict";
import { bootKorean } from "./i18n_boot.mjs";

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
// 끝난 실행. 완료 구획은 접힌 채로 시작하므로 구획 줄만 나오고 그 아래 줄은 안 그려진다
const DONE_RUN = {
  id: 4, todo_id: 59, todo_title: "끝난 것", outcome: "done",
  started_at: "2026-08-18T01:02:00", ended_at: "2026-08-18T02:03:00",
};
// 후보는 못 도는 것도 싣는다 — 왜 안 도는지가 이 목록의 존재 이유다
const CANDIDATES = [
  { todo_id: 57, title: "지금 돌 것", workspace_name: "작업 대시보드", blocker: "ready",
    precondition: null },
  { todo_id: 60, title: "조건 걸림", workspace_name: "작업 대시보드",
    blocker: "precondition", precondition: { total: 3, met: 1, manual: 1 } },
  { todo_id: 61, title: "위치 모름", workspace_id: 3, workspace_name: "스터디",
    blocker: "cwd", precondition: null },
  // 소속 없는 할일 — 위치를 적어 둘 워크스페이스가 없어 할일 자체에 저장한다
  { todo_id: 62, title: "소속 없는 일", workspace_id: null, workspace_name: null,
    blocker: "cwd", precondition: null },
];
// 폴더 선택기가 처음 보여주는 곳. "이 폴더 선택" 을 누르면 이 경로가 그대로 답이 된다
const BROWSE_AT = "/home/u/study";
const TICK_AT = new Date(Date.now() - 3 * 60 * 1000).toISOString(); // 3분 전 tick
const REASON = "돌릴 수 있는 할일이 없음"; // 켜져 있는데 안 도는 이유. 주기 옆에 같이 보인다

const asked = [];
globalThis.fetch = async (url, options) => {
  asked.push(`${options?.method ?? "GET"} ${url}`);
  const body = {
    "/api/autorun": {
      state: { enabled: 1, last_tick_at: TICK_AT, last_tick_reason: REASON },
      runs: [RUN, REVIEW_RUN, DONE_RUN],
      candidates: CANDIDATES,
    },
    "/api/workspaces": [],
    "/api/browse": { path: BROWSE_AT, entries: [{ name: "자료", path: `${BROWSE_AT}/자료` }] },
    "/api/workspaces/3": { id: 3, cwd: BROWSE_AT },
    "/api/categories": [],
    "/api/todos/57": { todo: { id: 57, title: "제목" }, sessions: [] },
    "/api/todos/62": { id: 62, cwd: BROWSE_AT },
    "/api/autorun-runs/3": { id: 3, outcome: "done" },
  }[url];
  return { ok: Boolean(body), status: body ? 200 : 404, json: async () => body ?? {} };
};

const node = () => ({
  textContent: "",
  hidden: false,
  open: false,
  // 후보 목록은 끌어서 순서를 바꾼다 — 그 코드가 만지는 자리만 흉내낸다
  // (드래그 동작 자체는 tests/autorun_drag_check.mjs 가 본다)
  dataset: {},
  draggable: false,
  querySelectorAll: () => [],
  setAttribute() {},
  style: { setProperty() {} },
  classList: { toggle() {}, remove() {}, add() {} },
  children: [],
  listeners: {},
  // 칸 순서를 보려면 붙은 것을 들고 있어야 한다
  append(...items) {
    this.children.push(...items);
  },
  // 판 안에 리스트가 들어가므로 이쪽도 실제로 담아야 한다 — 빈 스텁이면
  // 판이 비어 보여 "접힌 판에 줄이 없다" 가 늘 참이 된다
  appendChild(item) {
    this.children.push(item);
    return item;
  },
  replaceChildren() {},
  showModal() {
    this.open = true;
  },
  // 브라우저는 close(value) 를 returnValue 에 담고 close 이벤트를 쏜다 (browse.js 가 그걸 읽는다)
  close(value) {
    this.returnValue = value ?? "";
    this.open = false;
    this.listeners.close?.();
  },
  addEventListener(type, handler) {
    this.listeners[type] = handler;
  },
});

const rows = [];
const created = [];
const list = { ...node(), appendChild: (item) => rows.push(item) };
const cands = [];
const candList = { ...node(), appendChild: (item) => cands.push(item) };
const elements = { "autorun-list": list, "autorun-candidates": candList };
globalThis.document = {
  getElementById: (id) => (elements[id] ??= node()),
  createElement: () => {
    const made = node();
    created.push(made);
    return made;
  },
};

await bootKorean();
const autorun = await import("../static/js/autorun.js");
await autorun.renderAutorun();

// 주기 옆에 마지막 tick 과 그 판정 사유가 붙는다 — 크론이 죽었는지, 켜져 있는데 왜 안
// 도는지 이 줄로만 알 수 있다
assert.equal(
  elements["autorun-cycle"].textContent,
  `5분마다 | 마지막 수행 3m 전 · ${REASON}`,
);

// 후보 줄 — 손잡이 / 워크스페이스 / 할일 / 사유 칩.
// 순위 숫자는 없다 — 순서는 목록에 보이는 차례가 곧 순위이고, 손잡이로 바꾼다
assert.deepEqual(
  cands[0].children.map((cell) => cell.className),
  ["ar-grip", "scope", "prompt", "badge blocker-ready"],
);
assert.equal(cands[0].children[3].textContent, "시작 가능");
// 조건에 막힌 줄은 몇 개 중 몇 개인지까지 적는다 — 무엇을 풀어야 도는지가 그 숫자다
assert.equal(cands[1].children[3].textContent, "착수 조건 1/3 · 사람 확인 1");

// 후보를 누르면 그 할일 상세가 열린다
assert.equal(typeof cands[0].listeners.click, "function");

// 상태마다 판 하나. 사람이 손댈 것(확인 필요)이 맨 위 판이고 진행 중이 그다음,
// 완료 판은 접힌 채로 시작해 머리만 나온다
assert.deepEqual(
  rows.map((row) => row.className),
  ["ar-group", "ar-group", "ar-group collapsed"],
);

// 펼친 판은 머리 + (칸 이름 줄 + 실행 줄들). 접힌 판은 머리만
const [head, body] = rows[0].children;
assert.equal(head.className, "ar-group-head");
assert.equal(body.className, "ar-group-rows");
assert.equal(rows[2].children.length, 1, "접힌 판에 줄이 그려졌다");

// 판 머리 — 꺾쇠 자리 / 이름 / 건수. 꺾쇠는 CSS 가 그리므로 칸은 비어 있다
assert.deepEqual(
  head.children.map((cell) => `${cell.className}:${cell.textContent}`),
  ["mark:", "text:확인 필요", "count:1"],
);
assert.equal(rows[1].children[0].children[1].textContent, "진행 중");
// 접힌 판도 몇 건인지는 보인다 — 접혀 있어서 안 보이는 것과 없는 것은 다르다
assert.deepEqual(
  rows[2].children[0].children.map((cell) => cell.textContent),
  ["", "완료", "1"],
);
// 판 머리는 눌러서 접고 편다
assert.equal(typeof head.listeners.click, "function");
assert.equal(typeof rows[2].children[0].listeners.click, "function");

// 칸 이름 줄은 판 안, 리스트 맨 위에 있다
assert.equal(body.children[0].className, "head");
assert.deepEqual(
  body.children[0].children.map((cell) => cell.textContent),
  ["워크스페이스", "할일", "워크트리", "포트", "상태", "시작", "종료", "경과"],
);

const runRow = rows[1].children[1].children[1];
// 칸 순서 — 워크스페이스 / 할일 / 워크트리 / 포트 / 상태 / 시작 / 종료 / 경과
assert.deepEqual(
  runRow.children.map((cell) => cell.className),
  ["scope", "prompt", "wt", "ports", "badge outcome-running", "when", "when", "age"],
);
assert.equal(runRow.children[2].textContent, "고침");
// 아직 안 끝난 실행은 종료 칸이 비어 있다 — 자리는 남겨야 뒤 칸이 안 당겨진다
assert.equal(runRow.children[6].textContent, "");

// 포트는 그 서버로 가는 링크다. 눌러도 줄 클릭(팝업)으로 새면 안 된다
const port = runRow.children[3].children[0];
assert.equal(port.textContent, ":9081");
assert.equal(port.href, "http://localhost:9081");
let portStopped = false;
port.listeners.click({ stopPropagation: () => (portStopped = true) });
assert.equal(portStopped, true);

// 줄마다 클릭 핸들러가 붙어 있어야 한다 — 안 붙으면 눌러도 아무 일도 없다
assert.equal(typeof runRow.listeners.click, "function");

runRow.listeners.click();
// 팝업이 읽는 것은 세션이 아니라 그 실행의 할일이다 (todo_id 57)
await new Promise((resolve) => setTimeout(resolve, 0));
assert.ok(asked.includes("GET /api/todos/57"), asked.join(", "));
assert.equal(elements["session-modal"].open, true);

// 검토 대기 배지는 눌리는 버튼이고, 눌러도 줄 클릭(팝업)으로 새지 않아야 한다
const badge = created.find((made) => made.textContent === "검토 대기");
assert.ok(badge, "검토 대기 배지가 없다");
assert.equal(typeof badge.listeners.click, "function");
let stopped = false;
badge.listeners.click({ stopPropagation: () => (stopped = true) });
assert.equal(stopped, true);
await new Promise((resolve) => setTimeout(resolve, 0));
assert.ok(asked.includes("PATCH /api/autorun-runs/3"), asked.join(", "));

// 작업 위치 미정 칩도 눌리는 버튼이다 — 이 자리에서 풀 수 있는 사유는 이것뿐이다
const cwdChip = cands[2].children[3];
assert.equal(cwdChip.className, "badge blocker-cwd");
assert.equal(cwdChip.textContent, "작업 위치 미정");
assert.equal(typeof cwdChip.listeners.click, "function");
let cwdStopped = false;
cwdChip.listeners.click({ stopPropagation: () => (cwdStopped = true) });
assert.equal(cwdStopped, true);
// 보드 케밥의 "시작" 과 같은 폴더 선택기가 열린다
assert.equal(elements["dir-browse-modal"].open, true);
await new Promise((resolve) => setTimeout(resolve, 0));
// "이 폴더 선택" 을 누르면 그 경로가 이 워크스페이스의 작업 위치로 저장된다 —
// 세션을 여기서 띄우지 않는다. 다음 tick 이 제 순서대로 시작한다
elements["dir-browse-select"].onclick();
await new Promise((resolve) => setTimeout(resolve, 0));
assert.ok(asked.includes("PATCH /api/workspaces/3"), asked.join(", "));

const looseChip = cands[3].children[3];
assert.equal(looseChip.className, "badge blocker-cwd");
assert.equal(typeof looseChip.listeners.click, "function");
let looseStopped = false;
looseChip.listeners.click({ stopPropagation: () => (looseStopped = true) });
assert.equal(looseStopped, true);
assert.equal(elements["dir-browse-modal"].open, true);
await new Promise((resolve) => setTimeout(resolve, 0));
elements["dir-browse-select"].onclick();
await new Promise((resolve) => setTimeout(resolve, 0));
assert.ok(asked.includes("PATCH /api/todos/62"), asked.join(", "));

console.log("ok");
