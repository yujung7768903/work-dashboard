// 워크트리 케밥 메뉴의 서버 항목 검증 — 실행·재실행·중지가 떠 있든 없든 항상 보이고,
// 누르면 그 동작으로 POST 되는지, 확인창 문구가 대상(포트 또는 브랜치)을 가리키는지 본다.
// 브라우저 없이 돌려야 하므로 worktrees.js 가 만지는 DOM 만 흉내낸다.
// 실행: node tests/worktree_serve_menu_check.mjs  (tests/test_serve_menu.py 가 이걸 부른다)
import assert from "node:assert/strict";
import { bootKorean } from "./i18n_boot.mjs";

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

const DONE_MESSAGE = "실행했습니다 — http://127.0.0.1:9081/";

const asked = [];
// 알림과 목록 갱신의 순서를 봐야 한다 — alert 가 먼저면 확인을 누를 때까지 포트가 안 붙는다
const order = [];
globalThis.fetch = async (url, options) => {
  const method = options?.method ?? "GET";
  // 목록은 뷰 모드를 물음표 뒤에 달고 온다. 어느 모드든 같은 응답이므로 경로만 본다
  const path = url.split("?")[0];
  asked.push({ method, url, body: options?.body });
  order.push(`${method} ${path}`);
  // 서버는 조작 결과에 사람이 읽을 문장을 실어 준다 (app/services/serve.py)
  const body =
    method === "POST" ? { message: DONE_MESSAGE } : { "/api/worktrees": { groups: GROUPS } }[path];
  return { ok: true, status: 200, json: async () => body ?? {} };
};

const confirms = [];
globalThis.confirm = (message) => {
  confirms.push(message);
  return true;
};
const alerts = [];
globalThis.alert = (message) => {
  alerts.push(message);
  order.push("alert");
};

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

await bootKorean();
// 화면 모듈은 최상단에서 저장해 둔 값(뷰 모드·열 수)을 읽는다. 브라우저 밖에는 없는 것
globalThis.localStorage = { getItem: () => null, setItem() {} };

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
assert.ok(toggles()[0].title.includes("실행"), toggles()[0].title);

const SERVER_ITEMS = ["실행", "재실행", "중지", "적용", "삭제"];
// 떠 있는 줄·안 떠 있는 줄 모두 항목 구성이 같다 — 상태에 따라 사라지지 않는다
toggles()[0].listeners.click({ stopPropagation() {} });
assert.deepEqual(labelsOfOpenMenu(), SERVER_ITEMS);
toggles()[1].listeners.click({ stopPropagation() {} });
assert.deepEqual(labelsOfOpenMenu(), SERVER_ITEMS);

// 실행은 확인창 없이 바로 그 브랜치로 POST 된다
buttonNamed("실행").listeners.click({ stopPropagation() {} });
await settle();
const posted = asked.filter((call) => call.method === "POST");
assert.equal(posted.length, 1, JSON.stringify(asked));
assert.deepEqual(JSON.parse(posted[0].body), {
  repo: "/repo",
  branch: "worktree-down",
  action: "start",
});
assert.deepEqual(confirms, [], "실행은 되묻지 않는다");
// 끝난 것을 팝업으로 알린다 — 포트 배지가 조용히 붙는 것만으로는 완료를 알 수 없다
assert.deepEqual(alerts, [DONE_MESSAGE], alerts.join(" / "));
// 목록을 다시 받은 **뒤에** 알린다. 순서가 뒤집히면 확인을 누를 때까지 포트가 안 붙는다
assert.deepEqual(order.slice(-2), ["GET /api/worktrees", "alert"], order.join(" → "));

// 안 떠 있는 줄의 확인창은 포트가 없으니 브랜치 이름을 가리킨다
toggles()[1].listeners.click({ stopPropagation() {} });
buttonNamed("중지").listeners.click({ stopPropagation() {} });
await settle();
assert.ok(confirms.at(-1).includes("worktree-down"), confirms.at(-1));

// 중지는 남의 화면을 끊을 수 있어 확인을 받는다. 떠 있으면 그 포트를 가리킨다
toggles()[0].listeners.click({ stopPropagation() {} });
buttonNamed("중지").listeners.click({ stopPropagation() {} });
await settle();
assert.equal(confirms.length, 2, confirms.join(" / "));
assert.ok(confirms[1].includes("9091"), confirms[1]);
assert.deepEqual(JSON.parse(asked.filter((call) => call.method === "POST").at(-1).body), {
  repo: "/repo",
  branch: "worktree-up",
  action: "stop",
});

console.log("ok");
