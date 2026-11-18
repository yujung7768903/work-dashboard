// 할일 상세 팝업 동작 줄(static/js/todo-actions.js) 검증 — 보드 할일 케밥에 있던 시작·라벨·삭제를 옮긴 것
//   1. 시작 — 그 할일 id 로 POST 하고 서버 문장을 알린다
//   2. 라벨 — 누를 때마다 label_ids 를 켜고 끈 목록으로 PATCH 하고, 눌린 표시가 따라간다
//   3. 삭제 — 확인을 받은 뒤에만 DELETE 하고 onDeleted 를 부른다. 취소하면 아무것도 안 보낸다
// 실행: node tests/todo_actions_check.mjs (tests/test_todo_actions.py 가 부른다)
import assert from "node:assert/strict";
import { bootKorean } from "./i18n_boot.mjs";

const TODO = { id: 108, title: "시작 기능", labels: [{ id: 1, name: "auto" }] };
const LABELS = [
  { id: 1, name: "auto", color: "#4a5ae8" },
  { id: 2, name: "feature", color: null },
];

const sent = [];
globalThis.fetch = async (url, options = {}) => {
  const method = options.method ?? "GET";
  if (method !== "GET") sent.push([method, url, options.body ? JSON.parse(options.body) : null]);
  if (url === "/api/labels") return { ok: true, status: 200, json: async () => LABELS };
  if (url === "/api/todo-start") return { ok: true, status: 200, json: async () => ({ message: "세션을 띄웠습니다" }) };
  return { ok: true, status: 200, json: async () => ({}) };
};
const alerts = [];
globalThis.alert = (message) => alerts.push(message);
let answer = false;
globalThis.confirm = () => answer;

const node = (tag) => ({
  tag,
  textContent: "",
  className: "",
  title: "",
  type: "",
  disabled: false,
  attrs: {},
  style: { setProperty() {} },
  children: [],
  listeners: {},
  append(...kids) {
    this.children.push(...kids);
  },
  appendChild(kid) {
    this.children.push(kid);
    return kid;
  },
  setAttribute(name, value) {
    this.attrs[name] = value;
  },
  addEventListener(type, handler) {
    this.listeners[type] = handler;
  },
});
globalThis.document = { createElement: node, getElementById: () => node("div") };

await bootKorean();
const { todoActions } = await import("../static/js/todo-actions.js");

const tick = () => new Promise((done) => setTimeout(done, 0));
let deleted = 0;
const row = todoActions(TODO, { onDeleted: () => (deleted += 1) });
const [start, labels, remove] = row.children;
for (let i = 0; labels.children.length < LABELS.length && i < 20; i += 1) await tick();

// 1. 시작
await start.listeners.click();
assert.deepEqual(sent.shift(), ["POST", "/api/todo-start", { id: 108 }]);
assert.deepEqual(alerts, ["세션을 띄웠습니다"]);

// 2. 라벨 — 붙은 auto 는 눌린 채로 서고, feature 를 누르면 둘 다, auto 를 누르면 feature 만
const [auto, feature] = labels.children;
assert.equal(auto.attrs["aria-pressed"], "true");
assert.equal(feature.attrs["aria-pressed"], "false");
await feature.listeners.click();
assert.deepEqual(sent.shift(), ["PATCH", "/api/todos/108", { label_ids: [1, 2] }]);
assert.equal(feature.attrs["aria-pressed"], "true");
await auto.listeners.click();
assert.deepEqual(sent.shift(), ["PATCH", "/api/todos/108", { label_ids: [2] }]);
assert.equal(auto.attrs["aria-pressed"], "false");

// 3. 삭제 — 취소면 안 보내고, 확인이면 보내고 닫는다
answer = false;
await remove.listeners.click();
assert.equal(sent.length, 0);
assert.equal(deleted, 0);
answer = true;
await remove.listeners.click();
assert.deepEqual(sent.shift(), ["DELETE", "/api/todos/108", null]);
assert.equal(deleted, 1);

console.log("ok");
