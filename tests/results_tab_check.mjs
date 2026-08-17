// 결과물 메뉴의 카드 그리드. 카드에 작업 형태·세션 위치·연결된 할일·최종 작업 일자가
// 나오는지, 링크가 인라인으로 보이는지(없으면 목록 자체가 안 나오는지), 연결된 할일을
// 누르면 그 할일 팝업이 열리는지를 본다.
// 브라우저 없이 돌려야 하므로 results.js 가 만지는 DOM 만 흉내낸다.
// 실행: node tests/results_tab_check.mjs (tests/test_results_tab.py 가 이걸 부른다)
import assert from "node:assert/strict";
import { bootKorean } from "./i18n_boot.mjs";

const WITH_LINKS = {
  id: 5,
  todo_id: 12,
  todo_title: "이력서 Figma",
  kind: "Figma",
  summary: "이력서 초안 작성",
  session_cwd: "~/work/work-dashboard",
  links: [{ label: "", url: "https://figma.com/file/abc" }],
  created_at: "2026-08-17T08:00:00+00:00",
  updated_at: "2026-08-17T08:00:00+00:00",
};
const NO_LINKS = {
  id: 6,
  todo_id: 12,
  todo_title: "이력서 Figma",
  kind: "배포",
  summary: null,
  session_cwd: "~/work/work-dashboard",
  links: [],
  created_at: "2000-01-01T00:00:00+00:00",
  updated_at: "2000-01-01T00:00:00+00:00",
};
const PAGE = { items: [WITH_LINKS, NO_LINKS], total: 2, page: 1, page_size: 12 };

const asked = [];
globalThis.fetch = async (url, options) => {
  const method = options?.method ?? "GET";
  asked.push(`${method} ${url}`);
  const path = url.split("?")[0];
  const body = {
    "/api/results": PAGE,
    "/api/workspaces": [],
    "/api/categories": [],
    "/api/todos/12": { todo: { id: 12, title: "이력서 Figma" }, sessions: [] },
  }[path];
  return { ok: Boolean(body), status: body ? 200 : 404, json: async () => body ?? {} };
};

const node = () => {
  const made = {
    textContent: "",
    title: "",
    href: "",
    target: "",
    rel: "",
    className: "",
    hidden: false,
    open: false,
    disabled: false,
    style: { setProperty() {} },
    setAttribute() {},
    getBoundingClientRect: () => ({ top: 0 }),
    classes: new Set(),
    classList: { toggle() {}, add: (name) => made.classes.add(name), remove() {} },
    children: [],
    listeners: {},
    append(...kids) {
      made.children.push(...kids);
    },
    appendChild(kid) {
      made.children.push(kid);
      return kid;
    },
    add(kid) {
      made.children.push(kid);
    },
    replaceChildren(...kids) {
      made.children = kids;
    },
    showModal() {
      made.open = true;
    },
    addEventListener(type, handler) {
      made.listeners[type] = handler;
    },
  };
  return made;
};

const created = [];
const elements = { "results-list": node() };
// results.js 는 sessions.js(openDetail)·workspace.js(menuItem)·main.js(run) 를 끌고 들어온다.
// main.js 가 모듈 최상단에서 라우팅을 한 번 돌리므로 history·location·window 도 흉내내야 한다
// (worktree_row_click_check.mjs 와 같은 이유)
globalThis.innerHeight = 800;
globalThis.location = { pathname: "/" };
globalThis.history = { pushState() {}, replaceState() {} };
globalThis.window = { addEventListener() {} };
globalThis.document = {
  getElementById: (id) => (elements[id] ??= node()),
  createElement: () => {
    const made = node();
    created.push(made);
    return made;
  },
  querySelectorAll: () => [],
  addEventListener() {},
};

await bootKorean();
globalThis.localStorage = { getItem: () => null, setItem() {} };

const results = await import("../static/js/results.js");
await results.renderResultsTab();

assert.ok(asked.includes("GET /api/results?page=1"), asked.join(", "));

const cards = created.filter((made) => made.className === "rs-card");
assert.equal(cards.length, 2, "카드 두 장이 그려져야 한다");

const [withLinksCard, noLinksCard] = cards;
const texts = collect(withLinksCard);
assert.ok(texts.includes("Figma"), `작업 형태가 안 보인다: ${texts}`);
assert.ok(texts.includes("~/work/work-dashboard"), `세션 위치가 안 보인다: ${texts}`);
assert.ok(texts.includes("#12 | 이력서 Figma"), `연결된 할일이 안 보인다: ${texts}`);
assert.ok(texts.includes("이력서 초안 작성"), `요약이 인라인으로 안 보인다: ${texts}`);
// 오늘(고정 날짜가 아니라 실행 시각 기준)이므로 상대 시간이거나 YYYY-MM-DD 둘 중 하나다
assert.ok(
  texts.some((text) => /^(방금 전|\d+분 전|\d+시간 전|\d{4}-\d{2}-\d{2})$/.test(text)),
  `최종 작업 일자 표기가 없다: ${texts}`
);
// 링크는 인라인으로 — 새 창으로 여는 앵커 하나가 그 URL 을 그대로 갖는다
const link = created.find((made) => made.href === "https://figma.com/file/abc");
assert.ok(link, "링크가 인라인으로 안 보인다");
assert.equal(link.target, "_blank");

// 링크·요약이 없는 결과물은 그 부분만 빠지고(인라인 원칙), 카드 자체는 그대로 나온다
const noLinksTexts = collect(noLinksCard);
assert.ok(noLinksTexts.includes("배포"), `두 번째 카드의 작업 형태가 안 보인다: ${noLinksTexts}`);
assert.ok(
  !created.some((made) => made.href === "" && made.target === "_blank"),
  "빈 링크가 앵커로 만들어지면 안 된다"
);

// 날짜 필터는 버튼 나열이 아니라 드롭박스 — 토글을 누르면 열리고, 직접 입력을 고르면
// 옵션 목록 대신 날짜 범위가 나오며(드롭박스는 안 닫힌다), 적용을 누르면 그 범위로
// 다시 조회하고 드롭박스가 닫힌다. HTML 은 hidden 속성으로 닫힌 채 시작하므로 흉내낸다
// 토글 핸들러 안에서만 처음 조회되는 요소라 미리 흉내내 둔다(document.getElementById 와 같은 규칙)
elements["results-filter-menu"] ??= node();
elements["results-filter-menu"].hidden = true;
elements["results-filter-options"].hidden = false;
elements["results-filter-toggle"].listeners.click({ stopPropagation() {} });
assert.equal(elements["results-filter-menu"].hidden, false, "토글을 누르면 드롭박스가 열려야 한다");

elements["results-filter-options"].listeners.click({
  target: { closest: () => ({ dataset: { preset: "custom" } }) },
});
assert.equal(elements["results-filter-options"].hidden, true, "직접 입력을 고르면 옵션 목록이 숨어야 한다");
assert.equal(elements["results-range"].hidden, false, "직접 입력을 고르면 날짜 범위가 보여야 한다");
assert.equal(elements["results-filter-menu"].hidden, false, "직접 입력은 드롭박스를 닫지 않아야 한다");

elements["results-date-from"].value = "2026-08-01";
elements["results-date-to"].value = "2026-08-10";
asked.length = 0;
elements["results-range-apply"].listeners.click();
await new Promise((resolve) => setTimeout(resolve, 0));
assert.ok(
  asked.some((call) => call.includes("date_from=2026-08-01") && call.includes("date_to=2026-08-10")),
  asked.join(", ")
);
assert.equal(elements["results-filter-menu"].hidden, true, "적용을 누르면 드롭박스가 닫혀야 한다");

// 연결된 할일 줄을 누르면 그 할일 팝업이 열린다 (워크트리 탭의 연결 줄과 같은 규칙)
const todoLine = created.find((made) => made.textContent === "#12 | 이력서 Figma");
assert.ok(todoLine, "연결된 할일 줄이 없다");
assert.equal(typeof todoLine.listeners.click, "function");
todoLine.listeners.click();
await new Promise((resolve) => setTimeout(resolve, 0));
assert.ok(asked.includes("GET /api/todos/12"), asked.join(", "));
assert.equal(elements["session-modal"].open, true);

function collect(made) {
  const found = [];
  const stack = [made];
  while (stack.length) {
    const item = stack.shift();
    if (item?.textContent) found.push(item.textContent);
    if (item?.children) stack.push(...item.children);
  }
  return found;
}

console.log("ok");
