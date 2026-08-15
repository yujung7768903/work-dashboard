// 자율 수행 on/off 스위치. 켜면 설정이 켜지고 끄면 꺼지는지, 서버가 거절하면 스위치가
// 되돌아오는지 본다. 브라우저 없이 돌려야 하므로 autorun.js 가 만지는 DOM 만 흉내낸다.
// 실행: node tests/autorun_toggle_check.mjs (tests/test_autorun_toggle.py 가 이걸 부른다)
import assert from "node:assert/strict";
import { bootKorean } from "./i18n_boot.mjs";

let enabled = 0;
let reject = false;
const asked = [];

globalThis.fetch = async (url, options) => {
  const method = options?.method ?? "GET";
  asked.push(`${method} ${url}`);
  if (url === "/api/autorun" && method === "PATCH") {
    if (reject) return { ok: false, status: 400, json: async () => ({ error: "안 됨" }) };
    enabled = JSON.parse(options.body).enabled ? 1 : 0;
  }
  return { ok: true, status: 200, json: async () => ({ state: { enabled }, runs: [] }) };
};

const node = () => ({
  textContent: "",
  checked: false,
  title: "",
  classList: { toggle() {}, remove() {}, add() {} },
  listeners: {},
  append() {},
  appendChild() {},
  addEventListener(type, handler) {
    this.listeners[type] = handler;
  },
});

const elements = {};
globalThis.document = {
  getElementById: (id) => (elements[id] ??= node()),
  createElement: () => node(),
};
globalThis.setInterval = () => 0;
globalThis.clearInterval = () => {};

await bootKorean();
const autorun = await import("../static/js/autorun.js");
autorun.startAutorunPolling();
await new Promise((resolve) => setTimeout(resolve, 0));

// 한 번도 안 돌았으면 tick 시각이 없다 — 빈 자리 대신 없다고 적는다
assert.equal(elements["autorun-cycle"].textContent, "5분마다 | 마지막 수행 없음");

const toggle = elements["autorun-toggle"];
const label = elements["autorun-switch"];
assert.equal(typeof toggle.listeners.change, "function", "스위치에 핸들러가 없다");

// 켜면 설정이 켜진다
toggle.checked = true;
toggle.listeners.change();
await new Promise((resolve) => setTimeout(resolve, 0));
assert.ok(asked.includes("PATCH /api/autorun"), asked.join(", "));
assert.equal(enabled, 1, "on 인데 설정이 안 켜졌다");

// 끄면 꺼진다
toggle.checked = false;
toggle.listeners.change();
await new Promise((resolve) => setTimeout(resolve, 0));
assert.equal(enabled, 0, "off 인데 설정이 안 꺼졌다");

// 서버가 거절하면 스위치도 되돌아와야 한다 — 켠 줄 알고 자리를 뜨면 안 된다
reject = true;
toggle.checked = true;
toggle.listeners.change();
await new Promise((resolve) => setTimeout(resolve, 0));
assert.equal(toggle.checked, false, "거절당했는데 스위치가 켜진 채다");
assert.equal(label.title, "안 됨");

// summary 안이라 스위치 클릭이 위로 새면 패널이 접혔다 펴진다
let stopped = false;
label.listeners.click({ stopPropagation: () => (stopped = true) });
assert.equal(stopped, true);

console.log("ok");
