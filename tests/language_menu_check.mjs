// 상단 우측 언어 메뉴. 아이콘을 눌러야 목록이 열리는지, 지금 언어에 표시가 붙는지,
// 다른 언어를 고르면 서버에 저장하는지 본다. 브라우저 없이 돌려야 하므로
// language.js 가 만지는 DOM 만 흉내낸다.
// 실행: node tests/language_menu_check.mjs (tests/test_language_menu.py 가 이걸 부른다)
import assert from "node:assert/strict";
import { bootKorean } from "./i18n_boot.mjs";

const asked = [];
globalThis.fetch = async (url, options) => {
  const method = options?.method ?? "GET";
  asked.push({ method, url, body: options?.body && JSON.parse(options.body) });
  return { ok: true, status: 200, json: async () => ({ language: "ko" }) };
};

const node = (tag) => {
  let html = "";
  return {
    tag,
    textContent: "",
    className: "",
    lang: "",
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

// language.js 는 main.js(run)를 거치므로 화면 모듈 전체가 함께 뜬다 — id 마다 빈 노드를
// 내주어 그것들이 최상단에서 붙이는 리스너가 터지지 않게 한다
const elements = {};
globalThis.document = {
  getElementById: (id) => (elements[id] ??= node(id)),
  createElement: (tag) => node(tag),
  querySelectorAll: () => [],
  addEventListener() {},
};
globalThis.history = { pushState() {}, replaceState() {} };
globalThis.location = {
  pathname: "/board",
  reload: () => asked.push({ method: "RELOAD" }),
};
globalThis.setInterval = () => 0;
globalThis.clearInterval = () => {};
globalThis.addEventListener = () => {};
globalThis.window = { addEventListener() {} };
const box = elements["lang-menu"] ??= node("lang-menu");

// 화면 모듈은 최상단에서 저장해 둔 값(뷰 모드·열 수)을 읽는다. 브라우저 밖에는 없는 것
globalThis.localStorage = { getItem: () => null, setItem() {} };

const { renderLanguageMenu } = await import("../static/js/language.js");
await bootKorean(); // 화면 언어 = ko
renderLanguageMenu();

// 처음에는 아이콘 하나. 목록은 눌러야 열린다
assert.equal(box.children.length, 1, "아이콘만 있어야 한다");
const toggle = box.children[0];
assert.equal(toggle.attributes["aria-expanded"], "false");
assert.ok(toggle.innerHTML.includes("<svg"), "지구본 아이콘이 없다");
assert.equal(toggle.attributes["aria-label"], "언어", toggle.attributes["aria-label"]);

toggle.listeners.click({ stopPropagation() {} });
assert.equal(box.children.length, 2, "누르면 목록이 열려야 한다");
const items = box.children[1].children;
assert.deepEqual(
  items.map((item) => item.lang),
  ["en", "ko", "ja", "zh"],
  "네 언어가 원어 이름으로 있어야 한다"
);
assert.deepEqual(
  items.map((item) => item.textContent),
  ["  English", "✓ 한국어", "  日本語", "  中文"]
);
assert.equal(items[1].attributes["aria-current"], "true", "지금 언어에 표시가 없다");

// 다른 언어를 고르면 저장하고 화면을 다시 띄운다
items[2].listeners.click({ stopPropagation() {} });
await new Promise((resolve) => setTimeout(resolve, 0));
const saved = asked.find((call) => call.method === "PATCH");
assert.ok(saved, `저장 요청이 없다: ${JSON.stringify(asked)}`);
assert.equal(saved.url, "/api/settings");
assert.deepEqual(saved.body, { language: "ja" });
assert.ok(asked.some((call) => call.method === "RELOAD"), "새로고침을 안 한다");

// 지금 언어를 다시 고르면 저장하지 않는다 — 새로고침만 헛돈다
asked.length = 0;
box.children[0].listeners.click({ stopPropagation() {} });
box.children[1].children[1].listeners.click({ stopPropagation() {} });
await new Promise((resolve) => setTimeout(resolve, 0));
assert.deepEqual(asked, [], `같은 언어인데 요청을 보냈다: ${JSON.stringify(asked)}`);
