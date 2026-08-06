// 할일 상세의 워크트리 탭. 병합된 워크트리도 이름·상태로 남고, 끝난 시각은 병합이면
// 병합 시각으로(삭제 시각이 아니라) 보이는지 확인한다.
// 실행: node tests/todo_worktree_tab_check.mjs (tests/test_todo_worktree_tab.py 가 이걸 부른다)
import assert from "node:assert/strict";

function node(tag) {
  const self = {
    tagName: tag,
    className: "",
    textContent: "",
    title: "",
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
globalThis.Option = function Option(text, value, _default, selected) {
  return { ...node("option"), textContent: text, value, selected };
};
globalThis.document = {
  createElement: node,
  createTextNode: (text) => ({ ...node("#text"), textContent: text }),
  getElementById: (id) => (id === "session-modal" ? modal : body),
};

const TODO = { id: 42, title: "워크트리 탭", created_at: "2026-08-05T10:00:00+00:00" };
const MERGED = {
  path: "/repo/.claude/worktrees/done-thing",
  name: "done-thing",
  branch: "worktree-done-thing",
  base: "master",
  state: "merged",
  created_at: "2026-08-03T01:00:00+00:00",
  merged_at: "2026-08-04T02:00:00+00:00",
  deleted_at: null,
  ahead: 2,
  behind: 0,
  commits: [{ hash: "abc1234", subject: "feat: 무언가", at: "2026-08-04T01:00:00+00:00" }],
};
const DROPPED = {
  path: "/repo/.claude/worktrees/gave-up",
  name: "gave-up",
  branch: "worktree-gave-up",
  base: "master",
  state: "deleted",
  created_at: "2026-08-02T01:00:00+00:00",
  merged_at: null,
  deleted_at: "2026-08-02T05:00:00+00:00",
  ahead: 0,
  behind: 0,
  commits: [],
};

const PAYLOAD = {
  "/api/workspaces": [],
  "/api/categories": [],
  "/api/todos/42": { todo: TODO, sessions: [], worktrees: [MERGED, DROPPED] },
};
globalThis.fetch = (url) =>
  Promise.resolve({ ok: true, json: () => Promise.resolve(PAYLOAD[url]) });

const { openDetail } = await import("../static/js/sessions.js");

body.children = [];
openDetail({ todo: { id: 42 } });
for (let i = 0; body.children.length !== 4 && i < 50; i += 1) {
  await new Promise((done) => setTimeout(done, 0));
}
assert.equal(body.children.length, 4, `팝업이 안 그려졌다: ${body.textContent}`);

const [tabs, , , worktreePane] = body.children;
assert.deepEqual(
  tabs.children.map((button) => button.textContent),
  ["개요", "세션", "워크트리"]
);

// 워크트리 하나가 한 덩어리. 병합된 것도 지운 것도 다 남아야 한다
assert.equal(worktreePane.children.length, 2, "워크트리 두 줄이 안 그려졌다");

const texts = (pane) => {
  const found = [];
  const stack = [...pane.children];
  while (stack.length) {
    const item = stack.shift();
    if (item?.textContent && !item.children?.length) found.push(item.textContent);
    if (item?.children) stack.push(...item.children);
  }
  return found;
};

const merged = texts(worktreePane.children[0]);
assert.ok(merged.includes("done-thing"), `이름이 없다: ${merged}`);
assert.ok(merged.includes("병합"), `병합 상태·시각 라벨이 없다: ${merged}`);
assert.ok(!merged.includes("삭제"), `병합된 워크트리에 삭제 시각이 붙었다: ${merged}`);
assert.ok(merged.includes("생성"), `생성 시각이 없다: ${merged}`);
assert.ok(merged.includes("↑2"), `커밋 차이가 없다: ${merged}`);
assert.ok(merged.some((text) => text.includes("feat: 무언가")), `커밋 목록이 없다: ${merged}`);

const dropped = texts(worktreePane.children[1]);
assert.ok(dropped.includes("gave-up"), `이름이 없다: ${dropped}`);
// 병합 없이 지운 워크트리는 삭제 시각으로 남는다
assert.ok(dropped.includes("삭제"), `삭제 시각 라벨이 없다: ${dropped}`);
assert.ok(!dropped.includes("병합"), `병합하지 않은 워크트리에 병합이 붙었다: ${dropped}`);

console.log("ok");
