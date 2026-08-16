// 열 수·레일 접힘 취향 검증. 브라우저 없이 돌려야 하므로 layout.js 가 쓰는 DOM 조각만
// 최소로 흉내낸다. 확인하는 것은 세 가지 — 저장해 둔 값이 다시 열 때 붙는지, 누르면
// 값이 바뀌어 남는지, 저장된 값이 없을 때 화면 폭이 기본값을 정하는지.
// 실행: node tests/layout_prefs_check.mjs [first] (tests/test_layout_prefs.py 가 이걸 부른다)
import assert from "node:assert/strict";
import { bootKorean } from "./i18n_boot.mjs";

// first = 저장해 둔 값이 없는 첫 방문. 그때만 화면 폭(넓음)이 기본값을 정한다
const first = process.argv[2] === "first";
const store = new Map(
  first ? [] : [["board-columns", "2"], ["side-collapsed", "true"]]
);

const classes = new Set();
const body = {
  dataset: {},
  classList: {
    toggle: (name, on) => (on ? classes.add(name) : classes.delete(name)),
    contains: (name) => classes.has(name),
  },
};

// 열 수 버튼 두 개. active 클래스가 붙었는지만 본다
const columnButtons = ["1", "2"].map((columns) => {
  const button = { dataset: { columns }, active: false };
  button.classList = { toggle: (name, on) => (button.active = on) };
  return button;
});

const listeners = {};
const elements = {};
const element = (id) => (elements[id] ??= {
  title: "",
  setAttribute(name, value) {
    this[name] = value;
  },
  addEventListener: (type, handler) => ((listeners[id] ??= {})[type] = handler),
});

globalThis.localStorage = {
  getItem: (key) => store.get(key) ?? null,
  setItem: (key, value) => store.set(key, value),
};
globalThis.matchMedia = () => ({ matches: first });
globalThis.document = {
  body,
  getElementById: element,
  querySelectorAll: () => columnButtons,
  // 열 수 버튼은 할일 탭·워크트리 탭이 함께 써서 문서에 위임으로 받는다
  addEventListener: (type, handler) => ((listeners.document ??= {})[type] = handler),
};

await bootKorean();
await import("../static/js/layout.js");

const sideToggle = element("side-toggle");
if (first) {
  // 처음 여는 넓은 화면. 두 줄로 시작하고 레일은 펼쳐져 있다
  assert.equal(body.dataset.boardColumns, "2");
  assert.equal(classes.has("side-collapsed"), false);
  assert.equal(sideToggle.title, "메뉴 접기");
} else {
  // 저장해 둔 값이 화면 폭보다 앞선다 (matchMedia 는 여기서 false 를 준다)
  assert.equal(body.dataset.boardColumns, "2");
  assert.equal(columnButtons[1].active, true);
  assert.equal(columnButtons[0].active, false);
  assert.equal(classes.has("side-collapsed"), true);
  assert.equal(sideToggle.title, "메뉴 펼치기");
}

// 한 줄 아이콘을 누르면 그 값이 화면과 저장소에 같이 남는다
listeners.document.click({ target: { closest: () => ({ dataset: { columns: "1" } }) } });
assert.equal(body.dataset.boardColumns, "1");
assert.equal(columnButtons[0].active, true);
assert.equal(store.get("board-columns"), "1");

// 접기 버튼은 누를 때마다 뒤집히고, 문구도 다음에 할 일로 바뀐다
const collapsed = classes.has("side-collapsed");
listeners["side-toggle"].click();
assert.equal(classes.has("side-collapsed"), !collapsed);
assert.equal(store.get("side-collapsed"), String(!collapsed));
assert.equal(sideToggle.title, collapsed ? "메뉴 접기" : "메뉴 펼치기");

console.log("ok");
