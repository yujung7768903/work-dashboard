// 탭 경로 라우팅 검증. 브라우저 없이 돌려야 하므로 main.js 가 쓰는 DOM·history 만
// 최소로 흉내낸다. 확인하는 것은 두 가지 — 주소가 탭을 정하고, 탭이 주소를 바꾼다.
// 실행: node tests/tab_routing_check.mjs (tests/test_tab_routing.py 가 이걸 부른다)
import assert from "node:assert/strict";
import { bootKorean } from "./i18n_boot.mjs";

// main.js 는 레일 메뉴(#tabs)와 보드 하위 탭(#board-tabs) 두 곳에 클릭을 건다.
// 요소를 하나로 흉내내면 나중 것이 앞의 핸들러를 덮으므로 id 별로 따로 만든다
const listeners = {};
const elements = {};
const element = (id) => (elements[id] ??= {
  textContent: "",
  hidden: false,
  classList: { toggle() {} },
  addEventListener(type, handler) {
    (listeners[id] ??= {})[type] = handler;
  },
});

globalThis.location = { pathname: process.argv[2] || "/" };
globalThis.history = {
  pushState: (state, title, url) => (location.pathname = url),
  replaceState: (state, title, url) => (location.pathname = url),
};
globalThis.window = { addEventListener() {} };
globalThis.document = {
  getElementById: (id) => element(id),
  querySelectorAll: () => [],
  addEventListener() {},
};
// 탭 렌더러는 API 를 부른다. 네트워크 없이 돌리려고 실패시키고, main.js 의 run 이 삼킨다
globalThis.fetch = () => Promise.reject(new Error("no network"));

await bootKorean();
// 화면 모듈은 최상단에서 저장해 둔 값(뷰 모드·열 수)을 읽는다. 브라우저 밖에는 없는 것
globalThis.localStorage = { getItem: () => null, setItem() {} };

await import("../static/js/main.js");

// 들어온 주소가 곧 탭이다. / 로 들어오면 기본 탭 경로로 정리된다
const expected = { "/": "/usage", "/board": "/board", "/nope": "/usage" };
assert.equal(location.pathname, expected[process.argv[2] || "/"]);

// 메뉴를 누르면 주소가 따라 바뀐다 — 그래야 새로고침이 제자리로 돌아온다
listeners.tabs.click({ target: { closest: () => ({ dataset: { tab: "settings" } }) } });
assert.equal(location.pathname, "/settings");

console.log("ok");
