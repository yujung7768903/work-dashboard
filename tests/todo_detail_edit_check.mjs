// 할일 상세 개요 탭의 수정. 제목 줄의 버튼이 제목·착수 조건·note 입력칸으로 바꿔치고,
// 저장이 그 세 값만 PATCH 로 보내며, 응답 대신 다시 읽은 할일로 보기 화면을 되돌리는지 본다.
// 실행: node tests/todo_detail_edit_check.mjs
// (tests/test_todo_detail_edit.py 가 이걸 부른다)
import assert from "node:assert/strict";
import { bootKorean } from "./i18n_boot.mjs";

function node(tag) {
  const self = {
    tagName: tag,
    className: "",
    textContent: "",
    title: "",
    value: "",
    placeholder: "",
    disabled: false,
    hidden: false,
    children: [],
    listeners: {},
    style: { setProperty() {} },
    classList: { toggle() {}, add() {}, remove() {} },
    focus() {},
    addEventListener(type, handler) {
      self.listeners[type] = handler;
    },
    append(...kids) {
      self.children.push(...kids);
    },
    appendChild(kid) {
      self.children.push(kid);
      return kid;
    },
    add(kid) {
      self.children.push(kid);
    },
    replaceChildren(...kids) {
      self.children = kids;
    },
  };
  return self;
}

const modal = { ...node("dialog"), open: false, showModal() {}, close() {} };
const body = node("div");
globalThis.Option = function Option(text, value, _default, selected) {
  return { ...node("option"), textContent: text, value, selected };
};
globalThis.document = {
  createElement: node,
  createTextNode: (text) => ({ ...node("#text"), textContent: text }),
  getElementById: (id) => (id === "session-modal" ? modal : body),
};

const BEFORE = {
  id: 42,
  title: "고칠 할일",
  created_at: "2026-08-20T10:00:00+00:00",
  precondition: "기획 확정",
  precondition_items: [{ text: "기획 확정", command: "", kind: "manual", met: null }],
  note: "예전 note",
};
const AFTER = {
  ...BEFORE,
  title: "고친 제목",
  precondition: null,
  precondition_items: [],
  note: "새 note",
};

const asked = [];
let patched = false;
globalThis.fetch = (url, options) => {
  asked.push({ url, method: options?.method, body: options?.body });
  if (url === "/api/todos/42" && options?.method === "PATCH") patched = true;
  const detail = { todo: patched ? AFTER : BEFORE, sessions: [], worktrees: [] };
  const payload =
    url === "/api/todos/42" && options?.method === "GET"
      ? detail
      : { "/api/workspaces": [], "/api/categories": [] }[url] ?? AFTER;
  return Promise.resolve({ ok: true, json: () => Promise.resolve(payload) });
};

await bootKorean();
const { openDetail } = await import("../static/js/sessions.js");

openDetail({ todo: { id: 42 } });
for (let i = 0; body.children.length !== 4 && i < 50; i += 1) {
  await new Promise((done) => setTimeout(done, 0));
}
assert.equal(body.children.length, 4, `팝업이 안 그려졌다: ${body.textContent}`);

const block = body.children[1].children[0];
const title = block.children[0];
assert.equal(title.textContent, "#42 | 고칠 할일");
const edit = title.children.at(-1);
assert.equal(edit.textContent, "수정");

edit.listeners.click();
// 제목 / 착수 조건 / note / 버튼 / 상태
assert.equal(block.children.length, 5);
assert.deepEqual(
  block.children.slice(0, 3).map((field) => field.children[0].textContent),
  ["제목", "착수 조건", "note"]
);
const [titleField, conditionField, noteField, actions] = block.children;
// 지금 값이 채워져 있어야 한다 — 빈 칸이면 고치려다 지운다
assert.equal(titleField.children.at(-1).value, "고칠 할일");
assert.equal(conditionField.children.at(-1).value, "기획 확정");
assert.equal(noteField.children.at(-1).value, "예전 note");

titleField.children.at(-1).value = "고친 제목";
conditionField.children.at(-1).value = "";
noteField.children.at(-1).value = "새 note";
const [save, cancel] = actions.children;
assert.equal(save.textContent, "저장");
assert.equal(cancel.textContent, "취소");

save.listeners.click();
for (let i = 0; !patched && i < 50; i += 1) {
  await new Promise((done) => setTimeout(done, 0));
}
const patch = asked.find((entry) => entry.method === "PATCH");
assert.ok(patch, asked.map((entry) => `${entry.method} ${entry.url}`).join(", "));
assert.equal(patch.url, "/api/todos/42");
// 빈 칸은 null 로 — 빈 문자열을 보내면 착수 조건이 '판정 불가 문장 하나'로 남는다
assert.deepEqual(JSON.parse(patch.body), {
  title: "고친 제목",
  precondition: null,
  note: "새 note",
});

for (let i = 0; block.children[0].tagName !== "p" && i < 50; i += 1) {
  await new Promise((done) => setTimeout(done, 0));
}
// 저장하면 보기 화면으로 되돌아오고, 다시 읽은 제목이 보인다
assert.equal(block.children[0].textContent, "#42 | 고친 제목");
assert.ok(
  asked.filter((entry) => entry.url === "/api/todos/42" && entry.method === "GET").length >= 2,
  "저장 뒤 할일을 다시 읽지 않았다 — 착수 조건 항목은 서버가 쪼개 준다"
);

console.log("ok");
