// 할일 상세에서 세션 탭을 열면 머리글이 개요와 같은 "#id | 제목" 인지 확인한다.
// 세션 줄에서 열었을 때는 예전대로 워크스페이스+카테고리가 남아야 한다 (분류 UI 의 맥락).
// 실행: node tests/session_tab_head_check.mjs (tests/test_session_tab_head.py 가 이걸 부른다)
import assert from "node:assert/strict";
import { bootKorean } from "./i18n_boot.mjs";

function node(tag) {
  const self = {
    tagName: tag,
    className: "",
    textContent: "",
    hidden: false,
    children: [],
    style: { setProperty() {} },
    classList: { toggle() {}, add() {}, remove() {} },
    addEventListener() {},
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
// 분류 select 은 new Option(...) 으로 항목을 만든다
globalThis.Option = function Option(text, value, _default, selected) {
  return { ...node("option"), textContent: text, value, selected };
};
globalThis.document = {
  createElement: node,
  getElementById: (id) => (id === "session-modal" ? modal : body),
};

const SESSION = {
  id: 3,
  claude_session_id: "abc",
  workspace_name: "작업 대시보드",
  category_id: 4,
  cwd: "/tmp",
  git_branch: "master",
  state: "working",
};
const TODO = { id: 42, title: "세션 탭 머리글 정리", created_at: "2026-08-05T10:00:00" };

const PAYLOAD = {
  "/api/workspaces": [],
  "/api/categories": [{ id: 4, name: "개발환경 개선" }],
  "/api/todos/42": { todo: TODO, sessions: [{ id: 3 }], worktrees: [] },
  "/api/sessions/3": { session: SESSION, messages: [], todos: [TODO], worktrees: [] },
};
globalThis.fetch = (url) =>
  Promise.resolve({ ok: true, json: () => Promise.resolve(PAYLOAD[url]) });

await bootKorean();
const { openDetail } = await import("../static/js/sessions.js");

// 팝업 본문은 [탭바, 개요, 세션, 워크트리, 결과물] 다섯 덩어리. 각 탭의 첫 dlg-title 을 뽑아 비교한다
const firstTitle = (pane) => {
  const stack = [...pane.children];
  while (stack.length) {
    const item = stack.shift();
    if (item?.className === "dlg-title") return item.textContent;
    if (item?.children) stack.push(...item.children);
  }
  return null;
};

async function titles(target) {
  // 앞 렌더 결과를 비워야 이번 렌더가 끝난 시점을 알 수 있다
  body.children = [];
  openDetail(target);
  // 팝업은 목록 fetch → 상세 fetch 두 단을 거쳐 그린다. 큐가 빌 때까지 기다린다
  for (let i = 0; body.children.length !== 5 && i < 50; i += 1) {
    await new Promise((done) => setTimeout(done, 0));
  }
  // 렌더가 실패하면 팝업은 본문을 에러 문구로 바꾼다 — 그걸 그대로 띄워 원인을 보인다
  assert.equal(body.children.length, 5, `팝업이 안 그려졌다: ${body.textContent}`);
  const [, overview, session] = body.children;
  return [firstTitle(overview), firstTitle(session)];
}

const [overviewTitle, sessionTitle] = await titles({ todo: { id: 42 } });
assert.equal(overviewTitle, "#42 | 세션 탭 머리글 정리");
assert.equal(sessionTitle, "#42 | 세션 탭 머리글 정리");

// 세션 줄에서 열면 분류할 대상을 알아야 하므로 워크스페이스 이름을 그대로 둔다
const [, fromSession] = await titles({ session: { id: 3 } });
assert.equal(fromSession, "작업 대시보드");

console.log("ok");
