// 상단 우측 밝기 메뉴. 아이콘을 눌러야 목록이 열리는지, 고른 값이 이 기기에 남고
// <html data-theme> 에 그대로 붙는지, 기기 설정을 따를 때 화면 설정을 읽는지 본다.
// 브라우저 없이 돌려야 하므로 theme.js 가 만지는 DOM 만 흉내낸다.
// 실행: node tests/theme_menu_check.mjs (tests/test_theme_menu.py 가 이걸 부른다)
import assert from "node:assert/strict";
import { bootKorean } from "./i18n_boot.mjs";

const node = (tag) => {
  let html = "";
  return {
    tag,
    textContent: "",
    className: "",
    dataset: {},
    children: [],
    attributes: {},
    listeners: {},
    // 진짜 DOM 은 innerHTML 을 비우면 자식도 사라진다. 다시 그리는 코드가 그걸 쓴다
    get innerHTML() {
      return html;
    },
    set innerHTML(value) {
      html = value;
      if (!value) this.children = [];
    },
    setAttribute(name, value) {
      this.attributes[name] = value;
    },
    appendChild(child) {
      this.children.push(child);
      return child;
    },
    addEventListener(type, handler) {
      this.listeners[type] = handler;
    },
  };
};

const elements = {};
const root = node("html");
globalThis.document = {
  documentElement: root,
  getElementById: (id) => (elements[id] ??= node(id)),
  createElement: (tag) => node(tag),
  addEventListener() {},
};

const store = {};
globalThis.localStorage = {
  getItem: (key) => store[key] ?? null,
  setItem: (key, value) => {
    store[key] = value;
  },
};

// 기기 설정. 화면 밝기를 바꿔 가며 검사한다
let deviceDark = true;
globalThis.matchMedia = () => ({ matches: deviceDark, addEventListener() {} });

const box = (elements["theme-menu"] ??= node("theme-menu"));
const { renderThemeMenu } = await import("../static/js/theme.js");
await bootKorean(); // 화면 언어 = ko
renderThemeMenu();

// 고른 값이 없으면 기기 설정을 따른다
assert.equal(root.dataset.theme, "dark", "기기 설정(어둡게)을 안 따랐다");

// 처음에는 아이콘 하나. 목록은 눌러야 열린다
assert.equal(box.children.length, 1, "아이콘만 있어야 한다");
const toggle = box.children[0];
assert.equal(toggle.attributes["aria-expanded"], "false");
assert.ok(toggle.innerHTML.includes("<svg"), "밝기 아이콘이 없다");
assert.equal(toggle.attributes["aria-label"], "테마", toggle.attributes["aria-label"]);

toggle.listeners.click({ stopPropagation() {} });
assert.equal(box.children.length, 2, "누르면 목록이 열려야 한다");
const items = box.children[1].children;
assert.deepEqual(items.map((item) => item.textContent), [
  "✓ 기기 설정",
  "  밝게",
  "  어둡게",
]);
assert.equal(items[0].attributes["aria-current"], "true", "지금 값에 표시가 없다");

// 밝게를 고르면 기기 설정이 어두워도 밝은 화면이고, 그 값이 남는다
items[1].listeners.click({ stopPropagation() {} });
assert.equal(root.dataset.theme, "light", "고른 값을 안 붙였다");
assert.equal(store.theme, "light", "고른 값이 이 기기에 안 남았다");
assert.equal(box.children.length, 1, "고르면 목록이 닫혀야 한다");
assert.ok(box.children[0].innerHTML.includes("circle"), "밝은 화면인데 해 아이콘이 아니다");

// 다시 기기 설정으로 돌리면 화면 설정을 따라간다
box.children[0].listeners.click({ stopPropagation() {} });
box.children[1].children[0].listeners.click({ stopPropagation() {} });
assert.equal(root.dataset.theme, "dark");
deviceDark = false;
renderThemeMenu();
assert.equal(root.dataset.theme, "light", "기기 설정이 바뀌면 따라가야 한다");
