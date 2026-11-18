// 트리 Map 의 루트(워크스페이스) 카드를 누르면 사람을 기다리는 할일의 상세 팝업이 열리는지 본다.
// 예전 루트 카드는 제목이 div 이고 클릭 처리가 없어, '사람 대기 1' 이 떠도 눌러서 그 할일로 갈 수 없었다.
// 대기가 없는 루트는 열 대상이 없어 제목이 글자로 남아야 한다. waitingTodos 의 고르는 규칙도 함께 본다.
// 브라우저 없이 돌려야 하므로 tree-map.js 가 만지는 DOM 만 흉내낸다.
// 실행: node tests/tree_root_card_check.mjs (tests/test_tree_root_card.py 가 부른다)
import assert from "node:assert/strict";
import { bootKorean } from "./i18n_boot.mjs";

const asked = [];
globalThis.fetch = async (url, options) => {
  const path = url.split("?")[0];
  asked.push(`${options?.method ?? "GET"} ${path}`);
  const body = {
    "/api/workspaces": [],
    "/api/categories": [],
    "/api/todos/368": { todo: { id: 368, title: "CORS 제한" }, sessions: [], worktrees: [] },
  }[path];
  return { ok: Boolean(body), status: body ? 200 : 404, json: async () => body ?? {} };
};

function fake(tag) {
  const made = {
    tagName: String(tag).toUpperCase(),
    className: "",
    textContent: "",
    title: "",
    type: "",
    hidden: false,
    open: false,
    children: [],
    dataset: {},
    listeners: {},
    style: { setProperty() {} },
    classList: {
      add: (...names) => (made.className = [made.className, ...names].filter(Boolean).join(" ")),
      remove() {},
      toggle() {},
      contains: (name) => made.className.split(" ").includes(name),
    },
    setAttribute() {},
    setPointerCapture() {},
    getBoundingClientRect: () => ({ width: 800, height: 600, left: 0, top: 0 }),
    addEventListener: (type, fn) => (made.listeners[type] ??= []).push(fn),
    append: (...kids) => made.children.push(...kids.filter((kid) => typeof kid === "object")),
    appendChild: (kid) => made.children.push(kid),
    replaceChildren: (...kids) => (made.children = kids.filter((kid) => typeof kid === "object")),
    showModal: () => (made.open = true),
    click: () => (made.listeners.click ?? []).forEach((fn) => fn({ stopPropagation() {} })),
  };
  return made;
}

const modal = fake("dialog");
const modalBody = fake("div");
globalThis.document = {
  createElement: fake,
  createElementNS: (_ns, tag) => fake(tag),
  getElementById: (id) => ({ "session-modal": modal, "session-modal-body": modalBody })[id] ?? null,
  querySelectorAll: () => [],
  addEventListener() {},
};
globalThis.window = globalThis;
globalThis.addEventListener = () => {};
globalThis.localStorage = { getItem: () => null, setItem() {} };

await bootKorean();
const { createTreeMap } = await import("../static/js/tree-map.js");
const { waitingTodos } = await import("../static/js/tree-todos.js");

const node = (id, title, { waiting = null, updated = null, kind = "todo", children = [] } = {}) => ({
  key: kind === "context" ? `c${id}` : `t${id}`,
  kind,
  id,
  title,
  status: "doing",
  waiting,
  parents: [],
  after: [],
  children,
  results: [],
  extra_children: [],
  progress: { done: 0, total: 0 },
  updated_at: updated,
});
const tree = (id, name, children, waiting) => ({
  workspace: { id, name, category_name: "운영", category_color: "#2aa77a" },
  children,
  complete: false,
  waiting,
  progress: { done: 9, total: 18 },
  counts: { todo: 3, doing: 6 },
});

const all = (root) => [root, ...root.children.flatMap(all)];
const rootOf = (host) => all(host).find((item) => item.className === "tm-card tm-root");
const inRoot = (root, cls) => all(root).find((item) => item.className === cls);

{
  // 고르는 규칙 — 기다리는 할일만, 최근 손댄 순, 맥락은 할일이 아니라 빠진다
  const ws = tree(26, "허브 인증 우회 차단", [
    node(300, "상위", {
      updated: "2026-11-01T00:00:00+00:00",
      children: [
        node(368, "CORS 제한", { waiting: "permission", updated: "2026-11-17T00:00:00+00:00" }),
        node(369, "오래된 대기", { waiting: "input", updated: "2026-11-02T00:00:00+00:00" }),
      ],
    }),
    node(5, "맥락", { kind: "context", waiting: "input" }),
  ], 2);
  assert.deepEqual(waitingTodos(ws).map((item) => item.id), [368, 369]);
  assert.deepEqual(waitingTodos(tree(1, "빈", [], 0)), []);
}

{
  // 사람 대기 1 인 루트 카드 — 제목·배지가 버튼이고, 누르면 #368 상세 팝업이 열린다
  const host = fake("div");
  const map = createTreeMap(host);
  map.render([
    tree(26, "허브 인증 우회 차단", [
      node(300, "상위", { children: [node(368, "CORS 제한", { waiting: "permission" })] }),
    ], 1),
  ]);
  const root = rootOf(host);
  assert.ok(root, "루트 카드가 그려져야 한다");
  const title = inRoot(root, "tm-title");
  const badge = inRoot(root, "tm-waiting");
  assert.equal(title.tagName, "BUTTON", "대기가 있으면 제목은 누를 수 있는 버튼");
  assert.equal(badge.tagName, "BUTTON", "사람 대기 배지도 버튼");
  assert.equal(badge.textContent, "사람 대기 1");
  assert.match(title.title, /#368 CORS 제한/);

  title.click();
  assert.equal(modal.open, true, "제목을 누르면 상세 팝업이 떠야 한다");
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.ok(asked.includes("GET /api/todos/368"), `기다리는 할일을 불러야 한다: ${asked.join(", ")}`);

  modal.open = false;
  asked.length = 0;
  badge.click();
  assert.equal(modal.open, true, "배지를 눌러도 같은 팝업");
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.ok(asked.includes("GET /api/todos/368"));
}

{
  // 대기가 없는 루트는 열 대상이 없다 — 제목은 글자 그대로
  const host = fake("div");
  createTreeMap(host).render([tree(3, "작업 대시보드", [node(1, "할일")], 0)]);
  const root = rootOf(host);
  assert.equal(inRoot(root, "tm-title").tagName, "DIV");
  assert.equal(inRoot(root, "tm-waiting"), undefined);
}

console.log("tree root card ok");
