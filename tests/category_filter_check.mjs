// 카테고리 라벨 줄에 미분류 라벨이 서고, 누르면 워크스페이스 없는 미분류 카드만 남는지 본다.
// 실행: node tests/category_filter_check.mjs (tests/test_category_filter.py 가 부른다)
import assert from "node:assert/strict";
import { bootKorean } from "./i18n_boot.mjs";

const DEV = { id: 1, name: "개발", color: "#4a5ae8" };
const OPS = { id: 2, name: "운영", color: "#2a9d5c" };
const DASHBOARD = {
  id: 3, kind: "workspace", name: "작업 대시보드", category_id: 1,
  category_name: "개발", category_color: "#4a5ae8", total_count: 1, done_count: 0,
  todos: [{ id: 11, title: "미분류 라벨", status: "doing", labels: [] }],
};
const GITHUB = {
  id: 15, kind: "workspace", name: "Github 이관", category_id: 2,
  category_name: "운영", category_color: "#2a9d5c", total_count: 1, done_count: 0,
  todos: [{ id: 21, title: "코드 이관", status: "todo", labels: [] }],
};
// 서버는 미분류 카드에 category_id 를 실지 않는다 (app/services/board.py _unassigned_group)
const UNASSIGNED = {
  id: null, kind: "unassigned", name: "미분류", total_count: 1, done_count: 0,
  todos: [{ id: 31, title: "자잘한 건", status: "todo", labels: [] }],
};

globalThis.fetch = async (url) => {
  const body = {
    "/api/tree?group_by=workspace": { groups: [DASHBOARD, GITHUB, UNASSIGNED] },
    "/api/next": null,
    "/api/categories": [DEV, OPS],
    "/api/labels": [],
    "/api/autorun": { state: { enabled: 0 }, runs: [] },
    "/api/sessions": { sessions: [], waiting: [] },
  }[url];
  return { ok: true, status: 200, json: async () => (body === undefined ? {} : body) };
};

const element = (tag) => {
  // 선택 표시는 classList 로 켜고 끈다 (board.js syncActivePills) — 기록해 두고 본다
  const classes = new Set();
  return {
    tag,
    value: "",
    textContent: "",
    hidden: false,
    open: false,
    get innerHTML() {
      return this.html ?? "";
    },
    set innerHTML(value) {
      this.html = value;
      if (!value) this.children.length = 0;
    },
    className: "",
    // 실제 DOM 은 dataset 값을 문자열로 저장한다 — 라벨 선택 표시가 그 비교에 기댄다
    dataset: new Proxy({}, { set: (map, key, value) => ((map[key] = String(value)), true) }),
    title: "",
    disabled: false,
    draggable: false,
    style: { setProperty() {} },
    classList: {
      toggle(name, on) {
        on ? classes.add(name) : classes.delete(name);
      },
      add(name) {
        classes.add(name);
      },
      remove(name) {
        classes.delete(name);
      },
      contains(name) {
        return classes.has(name);
      },
    },
    children: [],
    listeners: {},
    // 라벨을 누르면 부모(라벨 줄)를 찾아 선택 표시를 다시 칠하므로 부모를 이어 둔다
    append(...kids) {
      kids.forEach((kid) => (kid.parentElement = this));
      this.children.push(...kids);
    },
    appendChild(kid) {
      kid.parentElement = this;
      this.children.push(kid);
      return kid;
    },
    replaceChildren() {},
    querySelectorAll(selector) {
      return selector === ".cat-pill"
        ? this.children.filter((kid) => kid.className === "cat-pill")
        : [];
    },
    getAttribute: () => null,
    setAttribute() {},
    focus() {},
    addEventListener(type, handler) {
      this.listeners[type] = handler;
    },
  };
};

const elements = {};
globalThis.document = {
  getElementById: (id) => (elements[id] ??= element("div")),
  createElement: element,
  createTextNode: () => element("text"),
  addEventListener() {},
  querySelectorAll: () => [],
};
globalThis.location = { pathname: "/board" };
globalThis.window = { addEventListener() {}, location: globalThis.location };
globalThis.history = { pushState() {}, replaceState() {} };
globalThis.localStorage = { getItem: () => null, setItem() {} };

await bootKorean();
const board = await import("../static/js/board.js");
await board.renderBoard();

const pills = elements["category-filter"].children;
assert.deepEqual(
  pills.map((pill) => pill.textContent),
  ["전체", "개발", "운영", "미분류"],
  "라벨은 전체 · 카테고리들 · 미분류 순"
);
assert.deepEqual(
  pills.map((pill) => pill.dataset.categoryId),
  ["", "1", "2", "unassigned"]
);
const kinds = () => elements.groups.children.map((group) => group.dataset.kind);
const activePills = () =>
  pills.filter((pill) => pill.classList.contains("active")).map((pill) => pill.textContent);
assert.deepEqual(kinds(), ["workspace", "workspace", "unassigned"], "전체는 다 보인다");
assert.deepEqual(activePills(), ["전체"]);

// 핸들러는 안쪽 비동기(다시 그리기)를 기다리지 않는다 — 끝날 틈을 준다
const click = async (pill) => {
  pill.listeners.click();
  await new Promise((resolve) => setTimeout(resolve, 50));
  assert.equal(elements.error.textContent, "", `${pill.textContent} 라벨이 오류로 끝났다`);
};

await click(pills[3]);
assert.deepEqual(kinds(), ["unassigned"], "미분류 라벨은 미분류 카드만 남긴다");
assert.deepEqual(activePills(), ["미분류"]);

await click(pills[1]);
assert.deepEqual(
  elements.groups.children.map((group) => [group.dataset.kind, group.dataset.groupId]),
  [["workspace", "3"]],
  "카테고리 라벨은 그 카테고리 워크스페이스만 — 미분류 카드는 숨는다"
);
assert.deepEqual(activePills(), ["개발"]);

await click(pills[0]);
assert.deepEqual(kinds(), ["workspace", "workspace", "unassigned"], "전체로 돌아온다");

console.log("ok");
// 세션·자율 수행 폴링 타이머가 켜져 있으면 node 가 끝나지 않는다
process.exit(0);
