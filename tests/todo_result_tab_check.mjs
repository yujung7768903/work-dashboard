// 할일 상세의 결과물 탭. 결과물이 하나뿐이면 펼쳐서, 둘 이상이면 모두 접어서 보여주는지,
// 요약·세션 위치·링크가 인라인으로 나오는지 확인한다.
// 실행: node tests/todo_result_tab_check.mjs (tests/test_todo_result_tab.py 가 이걸 부른다)
import assert from "node:assert/strict";
import { bootKorean } from "./i18n_boot.mjs";

function node(tag) {
  const self = {
    tagName: tag,
    className: "",
    textContent: "",
    title: "",
    href: "",
    target: "",
    rel: "",
    hidden: false,
    open: false,
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
globalThis.Option = function Option(text, value, _default, selected) {
  return { ...node("option"), textContent: text, value, selected };
};
globalThis.document = {
  createElement: node,
  createTextNode: (text) => ({ ...node("#text"), textContent: text }),
  getElementById: (id) => (id === "session-modal" ? modal : body),
};

const SINGLE_TODO = { id: 78, title: "블로그 글" };
const SINGLE_RESULT = {
  id: 10,
  todo_id: 78,
  todo_title: "블로그 글",
  kind: "Velog",
  summary: "동시성 이슈 원인과 해결 방향 정리",
  session_cwd: "~/work/work-dashboard",
  links: [{ label: "", url: "https://velog.io/@me/post" }],
  created_at: "2026-08-17T09:00:00+00:00",
  updated_at: "2026-08-17T09:00:00+00:00",
};

const MULTI_TODO = { id: 77, title: "포트폴리오" };
const FIGMA_RESULT = {
  id: 1,
  todo_id: 77,
  todo_title: "포트폴리오",
  kind: "Figma",
  summary: "이력서 초안 작성",
  session_cwd: "~/work/work-dashboard",
  links: [{ label: "", url: "https://figma.com/file/abc" }],
  created_at: "2026-08-17T08:00:00+00:00",
  updated_at: "2026-08-17T08:00:00+00:00",
};
const DEPLOY_RESULT = {
  id: 2,
  todo_id: 77,
  todo_title: "포트폴리오",
  kind: "배포",
  summary: null,
  session_cwd: "~/work/work-dashboard",
  links: [
    { label: "Backend - Railway", url: "https://railway.app/x" },
    { label: "Front - Vercel", url: "https://vercel.com/y" },
  ],
  created_at: "2026-08-10T08:00:00+00:00",
  updated_at: "2026-08-10T08:00:00+00:00",
};

const PAYLOAD = {
  "/api/workspaces": [],
  "/api/categories": [],
  "/api/todos/78": { todo: SINGLE_TODO, sessions: [], worktrees: [], results: [SINGLE_RESULT] },
  // 백엔드(result_repo.list_by_todo_ids)와 같은 순서 — 최근 작업(updated_at) 먼저
  "/api/todos/77": {
    todo: MULTI_TODO,
    sessions: [],
    worktrees: [],
    results: [FIGMA_RESULT, DEPLOY_RESULT],
  },
};
globalThis.fetch = (url) =>
  Promise.resolve({ ok: true, json: () => Promise.resolve(PAYLOAD[url]) });

await bootKorean();
const { openDetail } = await import("../static/js/sessions.js");

async function open(todoId, paneCount) {
  body.children = [];
  openDetail({ todo: { id: todoId } });
  for (let i = 0; body.children.length !== paneCount && i < 50; i += 1) {
    await new Promise((done) => setTimeout(done, 0));
  }
  assert.equal(body.children.length, paneCount, `팝업이 안 그려졌다: ${body.textContent}`);
  return body.children;
}

// 결과물 하나뿐 — 탭은 있지만 팝업 첫 화면은 개요 탭이다. 결과물 탭 내용만 검사한다
{
  const children = await open(78, 5);
  const [, , , , resultPane] = children;
  assert.equal(resultPane.children.length, 1, "결과물 패널이 하나여야 한다");
  const panel = resultPane.children[0];
  assert.equal(panel.open, true, "결과물이 하나면 펼쳐져 있어야 한다");
  assert.ok(collect(panel).includes("Velog"), "작업 형태(kind)가 안 보인다");
  assert.ok(
    collect(panel).includes("동시성 이슈 원인과 해결 방향 정리"),
    "요약이 인라인으로 안 보인다"
  );
  assert.ok(collect(panel).includes("~/work/work-dashboard"), "세션 위치가 안 보인다");
  const link = panel.children.find((child) => child.className === "rs-links");
  assert.ok(link, "링크 목록이 없다");
}

// 결과물 둘 이상 — 모두 접혀서 보여야 한다
{
  const children = await open(77, 5);
  const [, , , , resultPane] = children;
  assert.equal(resultPane.children.length, 2, "결과물 패널이 둘이어야 한다");
  resultPane.children.forEach((panel) => {
    assert.equal(panel.open, false, "결과물이 둘 이상이면 접혀 있어야 한다");
  });
  const kinds = resultPane.children.map((panel) => panel.children[0].children[0].textContent);
  // 최근 작업 순 — 08-17(Figma)이 08-10(배포)보다 먼저
  assert.deepEqual(kinds, ["Figma", "배포"]);
}

function collect(node_) {
  const found = [];
  const stack = [node_];
  while (stack.length) {
    const item = stack.shift();
    if (item?.textContent) found.push(item.textContent);
    if (item?.children) stack.push(...item.children);
  }
  return found;
}

console.log("ok");
