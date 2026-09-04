// 세션 탭의 입력칸과 답변 대기 선택지. 선택지를 누르면 입력칸이 "질문 - 라벨" 로 채워지고
// (복수 선택은 ", " 로 잇고 다시 누르면 빠진다), 보내기가 POST /api/session-message 에
// {session_id, text} 를 보내며, 질문이 없으면 선택지 블록이 없고 Ctrl+Enter 로도 보내는지 본다.
// 그린 직후에는 타이머가 없어야 한다 — 있으면 이 스크립트가 끝나지 않는다.
// 실행: node tests/session_message_check.mjs  (tests/test_session_message_check.py 가 부른다)
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
    classList: {
      toggle(name, force) {
        const names = new Set(self.className.split(" ").filter(Boolean));
        if (force) names.add(name);
        else names.delete(name);
        self.className = [...names].join(" ");
      },
      add() {},
      remove() {},
    },
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

const SESSION = { id: 7, claude_session_id: "sess-7", cwd: "/w", git_branch: "b", state: "working" };
const QUESTION = {
  tool_use_id: "toolu_1",
  questions: [
    {
      question: "제목 문체는?",
      header: "제목",
      multiSelect: false,
      options: [
        { label: "질문형", description: "묻는 제목" },
        { label: "명사형", description: "목차형" },
      ],
    },
    {
      question: "본문 문체는?",
      header: "본문",
      multiSelect: true,
      options: [
        { label: "평서", description: "단정형" },
        { label: "경어", description: "존대형" },
        { label: "명사형", description: "개조식" },
      ],
    },
  ],
};
const detail = (id, pending) => ({
  session: { ...SESSION, id },
  messages: [{ role: "user", text: "초안 써줘" }],
  pending_question: pending,
  todos: [],
  worktrees: [],
});

const posted = [];
globalThis.fetch = (url, options) => {
  if (url === "/api/session-message") {
    posted.push(JSON.parse(options.body));
    return Promise.resolve({
      ok: true,
      json: () => Promise.resolve({ delivered: "socket", priority: "now" }),
    });
  }
  const payload = {
    "/api/workspaces": [],
    "/api/categories": [],
    "/api/sessions/7": detail(7, QUESTION),
    "/api/sessions/8": detail(8, null),
  }[url];
  assert.ok(payload, `예상 밖 요청: ${options?.method ?? "GET"} ${url}`);
  return Promise.resolve({ ok: true, json: () => Promise.resolve(payload) });
};

function text(root) {
  return root.children.length ? root.children.map(text).join("") : root.textContent;
}
function find(root, name) {
  if ((root.className ?? "").split(" ").includes(name)) return root;
  for (const kid of root.children ?? []) {
    const hit = find(kid, name);
    if (hit) return hit;
  }
  return null;
}
async function open(id) {
  // 실제 DOM 은 textContent 를 바꾸면 자식이 비지만 스텁은 안 빈다 — 옛 팝업을 잡지 않게 비운다
  body.children = [];
  openDetail({ session: { id } });
  for (let i = 0; body.children.length !== 4 && i < 50; i += 1) {
    await new Promise((done) => setTimeout(done, 0));
  }
  assert.equal(body.children.length, 4, `팝업이 안 그려졌다: ${body.textContent}`);
  return body.children[2]; // 탭 바 / 개요 / 세션 / 워크트리
}
// POST 가 기록된 뒤에도 응답 반영(상태 줄·입력칸 비움)은 몇 틱 뒤다 — 상태 줄이 바뀔 때까지 기다린다
async function settle(count, status) {
  for (
    let i = 0;
    (posted.length < count || (status && status.textContent === "보내는 중…")) && i < 50;
    i += 1
  ) {
    await new Promise((done) => setTimeout(done, 0));
  }
}

await bootKorean();
const { openDetail } = await import("../static/js/sessions.js");

// ── 선택창이 열려 있는 세션 ──
let pane = await open(7);
const pending = find(pane, "pending");
assert.ok(pending, "답변 대기 블록이 없다");
const questions = pending.children.slice(1);
assert.equal(questions.length, 2);
const [first, second] = questions.map((block) => block.children[1].children.map((li) => li.children[0]));
assert.equal(first.length, 2);
assert.equal(second.length, 3);
assert.equal(second[0].className, "choice multi");

const compose = find(pane, "compose");
const [input, hint, actions, status] = compose.children;
const [how, send] = actions.children;
assert.equal(send.textContent, "답변 보내기");
assert.ok(text(how).startsWith("바로 전달"), text(how));
assert.equal(hint.textContent, "선택지를 누르면 여기에 채워집니다. 고쳐 쓰거나 한 줄 덧붙여도 됩니다. Ctrl+Enter 로 보냅니다.");

first[0].listeners.click();
assert.equal(input.value, "제목 문체는? - 질문형");
assert.equal(first[0].className, "choice selected");
first[1].listeners.click(); // 단일 선택은 바꿔 끼운다
assert.equal(input.value, "제목 문체는? - 명사형");
assert.equal(first[0].className, "choice");
second[0].listeners.click();
second[2].listeners.click();
assert.equal(input.value, "제목 문체는? - 명사형\n본문 문체는? - 평서, 명사형");
second[0].listeners.click(); // 복수 선택은 다시 누르면 빠진다
assert.equal(input.value, "제목 문체는? - 명사형\n본문 문체는? - 명사형");

input.value += "\n둘 다 짧게 가자"; // 채워진 문장에 한 줄 덧붙일 수 있다
send.listeners.click();
await settle(1, status);
assert.deepEqual(posted, [{ session_id: 7, text: "제목 문체는? - 명사형\n본문 문체는? - 명사형\n둘 다 짧게 가자" }]);
assert.ok(status.textContent.startsWith("보냄"), status.textContent);
assert.equal(status.className, "session-status ok");
assert.equal(input.value, "");

// ── 질문이 없는 세션: 선택지 블록 없음, Ctrl+Enter 로 보냄 ──
pane = await open(8);
assert.equal(find(pane, "pending"), null, "질문이 없는데 선택지 블록이 그려졌다");
const plain = find(pane, "compose");
const [plainInput, plainHint, plainActions] = plain.children;
assert.equal(plainActions.children[1].textContent, "보내기");
assert.ok(text(plainActions.children[0]).startsWith("작업 끝나면 전달"));
assert.equal(plainHint.textContent, "Ctrl+Enter 로 보냅니다.");
plainInput.value = "테스트 돌려줘";
let prevented = false;
plainInput.listeners.keydown({ key: "Enter", ctrlKey: true, preventDefault: () => { prevented = true; } });
await settle(2, plain.children[3]);
assert.ok(prevented);
assert.deepEqual(posted[1], { session_id: 8, text: "테스트 돌려줘" });
plainInput.value = "줄바꿈만";
plainInput.listeners.keydown({ key: "Enter", ctrlKey: false, preventDefault: () => {} });
await new Promise((done) => setTimeout(done, 0));
assert.equal(posted.length, 2, "Ctrl 없는 Enter 는 보내면 안 된다");

console.log("ok");
