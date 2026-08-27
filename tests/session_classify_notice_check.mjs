// 할일 상세의 세션 탭에서 분류를 저장하면 팝업이 닫히지 않고 "분류 완료됐습니다." 를 띄우는지,
// 다시 그린 팝업이 세션 탭에 머무는지 확인한다.
// 실행: node tests/session_classify_notice_check.mjs (tests/test_session_classify_notice.py 가 이걸 부른다)
import assert from "node:assert/strict";
import { bootKorean } from "./i18n_boot.mjs";

function node(tag) {
  const self = {
    tagName: tag,
    className: "",
    textContent: "",
    innerHTML: "",
    hidden: false,
    children: [],
    listeners: {},
    style: { setProperty() {} },
    classList: { toggle() {}, add() {}, remove() {} },
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

let closed = 0;
const modal = {
  ...node("dialog"),
  open: true,
  showModal() {},
  close() {
    closed += 1;
  },
};
const body = node("div");
// renderSessions 가 만지는 목록 요소들 — 팝업 밖이라 내용은 보지 않는다
const others = { "session-count": node("span"), "session-warn": node("p"), "session-list": node("ul") };
globalThis.Option = function Option(text, value, _default, selected) {
  return { ...node("option"), textContent: text, value, selected };
};
globalThis.document = {
  createElement: node,
  getElementById: (id) => (id === "session-modal" ? modal : others[id] ?? body),
};

const SESSION = {
  id: 3,
  claude_session_id: "abc",
  workspace_id: null,
  workspace_name: null,
  category_id: 4,
  cwd: "/tmp",
  git_branch: "master",
  state: "idle",
};
const TODO = { id: 42, title: "분류 안내 확인", created_at: "2026-08-05T10:00:00" };
const WORKSPACE = { id: 7, name: "비개발자 스터디", category_id: 4, status: "active" };

const GET = {
  "/api/workspaces": [WORKSPACE],
  "/api/categories": [{ id: 4, name: "공부" }],
  "/api/todos/42": { todo: TODO, sessions: [{ id: 3 }], worktrees: [] },
  "/api/sessions/3": { session: SESSION, messages: [], todos: [TODO], worktrees: [] },
  "/api/sessions": { sessions: [], unclassified_count: 0 },
};
const patched = [];
globalThis.fetch = (url, options = {}) => {
  if (options.method === "PATCH") {
    patched.push([url, JSON.parse(options.body)]);
    return Promise.resolve({
      ok: true,
      json: () => Promise.resolve({ ...SESSION, workspace_id: 7, created_todo: null }),
    });
  }
  return Promise.resolve({ ok: true, json: () => Promise.resolve(GET[url]) });
};

await bootKorean();
const { openDetail } = await import("../static/js/sessions.js");

const tick = () => new Promise((done) => setTimeout(done, 0));
// 팝업은 목록 fetch → 상세 fetch 를 거쳐 [탭바, 개요, 세션, 워크트리] 네 덩어리로 그린다
async function rendered() {
  for (let i = 0; body.children.length !== 4 && i < 50; i += 1) await tick();
  assert.equal(body.children.length, 4, `팝업이 안 그려졌다: ${body.textContent}`);
  return body.children;
}
const find = (root, className) => {
  const stack = [root];
  while (stack.length) {
    const item = stack.shift();
    if (item?.className === className) return item;
    if (item?.children) stack.push(...item.children);
  }
  return null;
};

openDetail({ todo: { id: 42 } });
let [, , sessionPane] = await rendered();
const row = find(sessionPane, "session-classify");
assert.ok(row, "분류 줄이 없다");
const [select, save] = row.children;
select.value = "w:7";

body.children = [];
await save.listeners.click();
assert.deepEqual(patched, [["/api/sessions/3", { workspace_id: 7 }]]);

// 닫히지 않고 다시 그린다 — 세션 탭에 머물며 끝났다는 안내가 남아야 한다
assert.equal(closed, 0, "저장 뒤 팝업이 닫혔다");
let overview;
[, overview, sessionPane] = await rendered();
assert.equal(sessionPane.hidden, false, "세션 탭이 숨겨졌다");
assert.equal(overview.hidden, true, "개요 탭으로 넘어갔다");
const status = find(sessionPane, "session-status");
assert.equal(status.textContent, "분류 완료됐습니다.");

console.log("ok");
