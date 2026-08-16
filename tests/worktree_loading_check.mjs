// 워크트리 목록을 받는 동안 빈 칸 대신 도는 원이 서는지 본다. 응답이 오면 사라져야 한다.
// 브라우저 없이 돌려야 하므로 worktrees.js 가 만지는 DOM 만 흉내낸다.
// 실행: node tests/worktree_loading_check.mjs
// (tests/test_worktree_loading.py 가 이걸 부른다)
import assert from "node:assert/strict";
import { bootKorean } from "./i18n_boot.mjs";

const GROUPS = [
  {
    id: 1, name: "작업 대시보드", category_id: 2, category_name: "카테고리",
    category_color: null, repo: "/repo", base: "master", hidden_branches: 0,
    rows: [
      {
        branch: "master", path: "/repo", is_base: true, ahead: 0, behind: 0,
        summary: "메인", todo_id: null, processes: [], commits: [],
      },
    ],
  },
];

// 목록 응답만 붙잡아 둔다 — 그 사이 화면에 무엇이 서 있는지가 이 체크의 전부다
let release;
const answered = new Promise((resolve) => (release = resolve));
globalThis.fetch = async (url) => {
  if (url.startsWith("/api/worktrees")) {
    await answered;
    return { ok: true, status: 200, json: async () => ({ groups: GROUPS }) };
  }
  return { ok: true, status: 200, json: async () => [] };
};

globalThis.localStorage = { getItem: () => null, setItem() {} };

const node = () => {
  const made = {
    textContent: "", title: "", className: "", hidden: false, open: false,
    // 목록 자리는 화면 위에서 200px 아래 — 로딩 칸은 남은 600px 을 받아야 한다
    getBoundingClientRect: () => ({ top: 200 }),
    css: {},
    style: { setProperty: (name, value) => (made.css[name] = value) },
    classList: { toggle() {}, add() {}, remove() {} },
    children: [],
    attributes: {},
    setAttribute: (name, value) => (made.attributes[name] = value),
    append: (...kids) => made.children.push(...kids),
    appendChild: (kid) => (made.children.push(kid), kid),
    addEventListener() {},
  };
  // innerHTML = "" 이 목록을 비우는 것만 흉내낸다
  Object.defineProperty(made, "innerHTML", {
    get: () => "",
    set: (value) => {
      if (value === "") made.children.length = 0;
    },
  });
  return made;
};

const elements = {};
// worktrees.js 는 board.js 를 거쳐 main.js 까지 끌고 들어온다(순환 참조) — main.js 가
// 모듈 최상단에서 라우팅을 한 번 돌리므로 history·location·window 도 흉내내야 한다
globalThis.innerHeight = 800;
globalThis.location = { pathname: "/" };
globalThis.history = { pushState() {}, replaceState() {} };
globalThis.window = { addEventListener() {} };
globalThis.document = {
  getElementById: (id) => (elements[id] ??= node()),
  createElement: () => node(),
  querySelectorAll: () => [],
  addEventListener() {},
};

await bootKorean();
const worktrees = await import("../static/js/worktrees.js");
const list = document.getElementById("worktree-list");

// 응답을 붙잡아 둔 채로 — 목록 자리에는 도는 원 하나만 있어야 한다
const drawing = worktrees.renderWorktrees();
assert.equal(list.children.length, 1, "받는 동안 표시가 없다");
const spinner = list.children[0];
assert.equal(spinner.className, "wt-loading");
assert.equal(spinner.attributes.role, "status");
assert.equal(spinner.attributes["aria-label"], "불러오는 중");
// 화면 아래까지 남은 높이를 그대로 받아야 그 한가운데에 설 수 있다
assert.equal(spinner.css["--wt-loading-room"], "600px");

// 응답이 오면 원은 사라지고 목록이 그 자리를 차지한다
release();
await drawing;
assert.ok(
  !list.children.some((child) => child.className === "wt-loading"),
  "다 받았는데 도는 원이 남아 있다"
);
assert.equal(list.children.length, 1, "저장소 카드 하나가 그려져야 한다");

console.log("ok");
