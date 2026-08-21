// 자율 수행 후보 끌어서 순서 바꾸기. 손잡이를 눌러야 끌리는지, 끄는 동안 놓일 자리에
// 선이 뜨는지, 놓았을 때 서버로 가는 순서가 화면에 보이던 순서와 같은지 본다.
// 브라우저 없이 돌려야 하므로 이 코드가 만지는 DOM 만 흉내낸다.
// 실행: node tests/autorun_drag_check.mjs (tests/test_autorun_drag.py 가 이걸 부른다)
import assert from "node:assert/strict";
import { bootKorean } from "./i18n_boot.mjs";

const ROW_HEIGHT = 20;
const CANDIDATES = [
  { todo_id: 1, title: "첫째", workspace_name: "A", blocker: "ready", precondition: null },
  { todo_id: 2, title: "둘째", workspace_name: "A", blocker: "ready", precondition: null },
  { todo_id: 3, title: "셋째", workspace_name: "B", blocker: "claimed", precondition: null },
];

const asked = [];
globalThis.fetch = async (url, options) => {
  asked.push({ url, method: options?.method ?? "GET", body: options?.body });
  const payload = {
    "/api/autorun": { state: { enabled: 1 }, runs: [], candidates: CANDIDATES },
    "/api/reorder": { reordered: 3 },
  }[url];
  return { ok: true, status: 200, json: async () => payload ?? {} };
};

// classList 를 실제로 담아야 삽입선이 어느 줄에 붙었는지 볼 수 있다
function node() {
  const classes = new Set();
  const self = {
    textContent: "",
    className: "",
    dataset: {},
    draggable: false,
    title: "",
    children: [],
    listeners: {},
    style: { setProperty() {} },
    classList: {
      add: (...names) => names.forEach((name) => classes.add(name)),
      remove: (...names) => names.forEach((name) => classes.delete(name)),
      toggle() {},
      contains: (name) => classes.has(name),
    },
    setAttribute() {},
    append(...kids) {
      self.children.push(...kids);
    },
    appendChild(kid) {
      self.children.push(kid);
      return kid;
    },
    addEventListener(type, handler) {
      self.listeners[type] = handler;
    },
    // 줄 높이를 20 으로 두면 중앙은 top+10 이다. 그 위·아래로 선이 갈린다
    getBoundingClientRect: () => ({ top: self.top ?? 0, height: ROW_HEIGHT }),
    closest: () => self,
    querySelectorAll: () => [],
    querySelector: () => null,
  };
  return self;
}

const rows = [];
const list = {
  ...node(),
  children: rows,
  appendChild(kid) {
    rows.push(kid);
    return kid;
  },
  set innerHTML(_) {
    rows.length = 0;
  },
  querySelectorAll: (selector) =>
    rows.filter((row) =>
      selector
        .split(", ")
        .some((name) => row.classList.contains(name.replace(".", ""))),
    ),
  querySelector: (selector) => list.querySelectorAll(selector)[0] ?? null,
};
const elements = { "autorun-candidates": list };
globalThis.document = {
  getElementById: (id) => (elements[id] ??= node()),
  createElement: node,
};
globalThis.setInterval = () => 0;
globalThis.clearInterval = () => {};

await bootKorean();
const autorun = await import("../static/js/autorun.js");
await autorun.renderAutorun();

assert.equal(rows.length, 3, "후보 세 줄이 안 그려졌다");
rows.forEach((row, index) => {
  row.top = index * ROW_HEIGHT;
});

// 손잡이를 누르기 전에는 끌리지 않는다 — 줄 전체가 드래그 대상이면 팝업을 열려던
// 클릭이 조금만 흔들려도 드래그로 샌다
const [first, second, third] = rows;
const grip = first.children[0];
assert.equal(grip.className, "ar-grip");
assert.equal(grip.title, "끌어서 순서 바꾸기");
assert.equal(first.draggable, false);
grip.listeners.mousedown();
assert.equal(first.draggable, true);

// 첫 줄을 셋째 줄 아래쪽 절반으로 끈다 → 셋째 줄 뒤에 선이 뜬다
let prevented = false;
list.listeners.dragstart({ target: first });
list.listeners.dragover({
  target: third,
  clientY: third.top + ROW_HEIGHT - 1,
  preventDefault: () => (prevented = true),
});
assert.equal(prevented, true, "preventDefault 가 없으면 브라우저가 드롭을 안 받는다");
assert.equal(third.classList.contains("drop-after"), true, "삽입선이 안 붙었다");
assert.equal(first.classList.contains("dragging"), true);

// 위쪽 절반으로 옮기면 선도 위로 옮겨 붙는다. 한 번에 한 줄만 표시한다
list.listeners.dragover({
  target: third,
  clientY: third.top + 1,
  preventDefault: () => {},
});
assert.equal(third.classList.contains("drop-before"), true);
assert.equal(third.classList.contains("drop-after"), false);

// 둘째 줄 위에 걸쳤다가 셋째 줄 뒤로 다시 옮겨 놓는다
list.listeners.dragover({
  target: third,
  clientY: third.top + ROW_HEIGHT - 1,
  preventDefault: () => {},
});
list.listeners.drop({ preventDefault: () => {} });
await new Promise((done) => setTimeout(done, 0));

const sent = asked.find((call) => call.url === "/api/reorder");
assert.ok(sent, asked.map((call) => call.url).join(", "));
// 보드 순서(todos)와 다른 열에 저장한다 — 후보는 여러 워크스페이스가 섞인 목록이다
// scope_id 는 api.reorder 가 늘 싣는다. 이 종류는 묶음이 없어 서버가 안 본다
assert.deepEqual(JSON.parse(sent.body), { kind: "autorun", ids: [2, 3, 1], scope_id: null });
// 놓고 나면 표시가 남지 않는다
assert.equal(third.classList.contains("drop-after"), false);
assert.equal(first.classList.contains("dragging"), false);
assert.equal(first.draggable, false);

console.log("ok");
