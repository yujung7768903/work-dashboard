// 매니저 탭 — 휴대폰 '예약 작업' 목록처럼 한 줄에 하나씩, 보기 전용.
// 하위 탭 둘: '작업'(보조 세션·완료 확인 대기·결정 대기)과 '설정'(자동화·도구 목록).
// 칸은 서버에서 따로 받는다. 보조 세션 목록은 claude agents 를 부르느라 수 초 걸려, 한 번에 받으면
// 나머지 칸까지 그만큼 늦게 뜬다 (app/services/manager_panel.py). 보이는 하위 탭의 칸만 받고 폴링한다
import * as api from "./api.js";
import { language, t } from "./i18n.js";
import { formatAge, notePart, openDetail } from "./sessions.js";
import { linkify } from "./linkify.js";
import { CHEVRON_SVG, REFRESH_SVG } from "./icons.js";
import { priorityBadge } from "./priority.js";
import { createTreeMap, soloCard } from "./tree-map.js";
import { decisionLoader } from "./decision-answer.js";
import { reportLoader } from "./task-report.js";
import { prereqList, prereqSummary } from "./prereq.js";
import { currentStep, stepList } from "./steps.js";
import { feedbackLoader } from "./helper-feedback.js";

// 하위 탭마다 그 안의 칸 (화면 배치는 static/index.html)
const SUBTABS = {
  work: ["helpers", "confirms", "decisions", "permissions", "waits"],
  setup: ["automations", "tools"],
};
const PARTS = Object.values(SUBTABS).flat();
// 보드 하위 탭처럼 고른 것은 이 화면에 있는 동안만 기억한다 (main.js)
let activeSubtab = "work";
// 칸마다 한 번에 보이는 줄 수. 넘치면 칸 아래 페이지 넘김으로 본다 — 자동화만 27줄이라 아래 칸이 밀려났다
export const PAGE_SIZE = 10;
// 칸마다 지금 보는 페이지(0부터)와 마지막으로 받은 응답. 페이지를 넘길 때는 다시 받지 않는다
const pages = Object.fromEntries(PARTS.map((part) => [part, 0]));
const sections = {};
// 다음 실행까지 남은 시간이 분 단위라 1분마다 다시 받는다. 탭을 떠나면 멈춘다 (main.js)
const POLL_MS = 60000;
let timer = null;
let polling = false;

// 매니저가 내려주는 보조 세션 상태는 한국어 문장이다 — 화면 언어로 옮길 키
// (색 이름, 문구). 문구는 t("키") 를 그대로 둔다 — 사전 점검(tests/test_language.py)이 코드에서 키를 찾는다
const HELPER_STATUS = {
  "작업 중": ["working", () => t("manager.helperWorking")],
  "결정 대기": ["waiting", () => t("manager.helperWaiting")],
  // 권한·로그인 막힘(ask --blocked permission)이나 권한 창을 기다리는 보조 — 고를 것이 있는 결정 대기와 다르다
  "권한 대기": ["permission", () => t("manager.helperPermission")],
  쉼: ["idle", () => t("manager.helperIdle")],
};
// 보조 세션 상태를 화면 언어로. 트리 할일별 줄의 보조 세션 막대 툴팁(tree.js)도 같은 문구를 쓴다
export function helperStatusText(status) {
  const [, label] = HELPER_STATUS[status] ?? [null, () => status || "-"];
  return label();
}
const LAST_STATUS = {
  ok: ["ok", (age) => t("manager.lastOk", { age })],
  fail: ["fail", (age) => t("manager.lastFail", { age })],
  nodata: ["nodata", (age) => t("manager.lastNoData", { age })],
};

export function startManagerPolling() {
  stopManagerPolling();
  polling = true;
  const tick = async () => {
    await renderManager();
    if (polling) timer = setTimeout(tick, POLL_MS);
  };
  return tick();
}

export function stopManagerPolling() {
  polling = false;
  clearTimeout(timer);
  timer = null;
}

export async function renderManager() {
  bindToolSearch();
  bindRefresh();
  bindSubtabs();
  showSubtab();
  await renderParts(SUBTABS[activeSubtab]);
}

// 첫 진입에만 칸마다 '불러오는 중'. 보조 세션 칸은 수 초 걸려 빈 칸이 '없음'으로 읽힌다.
// 폴링 재렌더 때는 지금 목록을 둔 채 바꾼다 — 1분마다 깜빡이지 않게
async function renderParts(parts) {
  parts.forEach((part) => {
    const list = document.getElementById(`mgr-${part}`);
    if (!list.children.length) list.replaceChildren(note(t("common.loading")));
  });
  await Promise.all(parts.map((part) => renderPart(part)));
}

// ── 하위 탭 — 작업 · 설정 ─────────────────────────────────────────────────

let subtabsBound = false;
function bindSubtabs() {
  if (subtabsBound) return;
  subtabsBound = true;
  // 버튼이 아이콘 svg 를 품고 있어 event.target 이 버튼이 아닐 수 있다
  document.getElementById("manager-tabs").addEventListener("click", (event) => {
    const name = event.target.closest?.("button")?.dataset.subtab;
    if (name) selectManagerSubtab(name);
  });
}

// 하위 탭을 바꾸면 그 탭의 칸을 바로 받는다. 폴링(1분)은 다음 차례부터 이 탭 칸만 돈다
export function selectManagerSubtab(name) {
  if (!(name in SUBTABS) || name === activeSubtab) return Promise.resolve();
  activeSubtab = name;
  showSubtab();
  return renderParts(SUBTABS[name]);
}

function showSubtab() {
  Object.keys(SUBTABS).forEach((name) => {
    document.getElementById(`mgr-subtab-${name}`).classList.toggle("active", name === activeSubtab);
    document.getElementById(`mgr-pane-${name}`).hidden = name !== activeSubtab;
  });
}

async function renderPart(part) {
  let section;
  try {
    section = (await api.getManager(part))[part];
  } catch (error) {
    section = { items: [], error: error.message };
  }
  sections[part] = section;
  showPart(part);
}

// 칸 제목 줄의 새로고침 — 그 칸만 다시 받는다. 받는 동안 버튼을 잠가 아이콘이 돌고(CSS),
// 실패하면 보던 목록은 두고 카드 맨 위에 짧은 오류 한 줄. 전문은 그 줄의 title
let refreshBound = false;
function bindRefresh() {
  if (refreshBound) return;
  refreshBound = true;
  PARTS.forEach((part) => {
    const button = document.getElementById(`mgr-${part}-refresh`);
    button.innerHTML = REFRESH_SVG;
    button.addEventListener("click", () => refreshPart(part));
  });
}

export async function refreshPart(part) {
  const button = document.getElementById(`mgr-${part}-refresh`);
  if (button.disabled) return;
  button.disabled = true;
  button.setAttribute?.("aria-busy", "true");
  try {
    let section;
    let failure = null;
    try {
      section = (await api.getManager(part))[part];
      failure = section.error;
    } catch (error) {
      failure = error.message;
    }
    if (failure && sections[part] && !sections[part].error) {
      sections[part] = { ...sections[part], refreshError: failure };
    } else {
      sections[part] = section ?? { items: [], error: failure };
    }
    showPart(part);
  } finally {
    button.disabled = false;
    button.setAttribute?.("aria-busy", "false");
  }
}

function showPart(part) {
  const section = sections[part];
  document.getElementById(`mgr-${part}-count`).textContent = section.error
    ? ""
    : String(section.items.length);
  drawPart(part);
}

// 지금 페이지의 줄만 그린다. 폴링으로 줄 수가 줄어 보던 페이지가 사라지면 마지막 페이지로
function drawPart(part) {
  const section = sections[part];
  const list = document.getElementById(`mgr-${part}`);
  const items = part === "tools" ? drawToolsChrome(section) : section.items;
  const total = pageCount(items.length);
  pages[part] = Math.min(pages[part], total - 1);
  const start = pages[part] * PAGE_SIZE;
  const rows = items.slice(start, start + PAGE_SIZE).map(ROW_BUILDERS[part]);
  if (section.error) rows.unshift(note(t("manager.partFailed", { error: section.error }), "mgr-error"));
  else if (section.refreshError) rows.unshift(refreshFailedNote(section.refreshError));
  else if (!rows.length && section.items.length) rows.push(note(t("manager.toolsNoMatch")));
  else if (!rows.length) rows.push(note(EMPTY[part]()));
  else if (part === "automations") rows.unshift(automationHead());
  list.replaceChildren(...rows);
  drawPager(part, total);
}

export function pageCount(length) {
  return Math.max(1, Math.ceil(length / PAGE_SIZE));
}

// ‹ · 페이지 번호 · ›. 한 페이지로 끝나면 숨긴다.
// 이전·다음은 글자 대신 chevron 아이콘이고 이름은 title·aria-label 로 준다 — 번호와 글자가 섞이면 줄이 들쭉날쭉했다
function drawPager(part, total) {
  const pager = document.getElementById(`mgr-${part}-pager`);
  pager.hidden = total <= 1;
  if (pager.hidden) return pager.replaceChildren();
  const current = pages[part];
  const go = (index) => {
    pages[part] = index;
    drawPart(part);
  };
  const buttons = [arrowButton("prev", t("manager.pagePrev"), current === 0, () => go(current - 1))];
  for (let index = 0; index < total; index += 1) {
    const number = pagerButton("mgr-page", false, () => go(index));
    number.textContent = String(index + 1);
    if (index === current) {
      number.className += " on";
      number.setAttribute?.("aria-current", "page");
    }
    buttons.push(number);
  }
  buttons.push(arrowButton("next", t("manager.pageNext"), current === total - 1, () => go(current + 1)));
  pager.replaceChildren(...buttons);
}

function arrowButton(side, label, disabled, onClick) {
  const button = pagerButton(`mgr-page mgr-arrow ${side}`, disabled, onClick);
  button.innerHTML = CHEVRON_SVG;
  button.title = label;
  button.setAttribute?.("aria-label", label);
  return button;
}

function pagerButton(className, disabled, onClick) {
  const button = el("button", className);
  button.type = "button";
  button.disabled = disabled;
  button.addEventListener("click", onClick);
  return button;
}

// 키를 문자열 그대로 둔다 — 사전 점검(tests/test_language.py)이 코드에서 키를 찾는다
const EMPTY = {
  automations: () => t("manager.empty.automations"),
  helpers: () => t("manager.empty.helpers"),
  tools: () => t("manager.empty.tools"),
  decisions: () => t("manager.empty.decisions"),
  permissions: () => t("manager.empty.permissions"),
  confirms: () => t("manager.empty.confirms"),
  waits: () => t("manager.empty.waits"),
};

const ROW_BUILDERS = {
  automations: automationRow,
  helpers: helperRow,
  tools: toolRow,
  decisions: decisionRow,
  permissions: decisionRow,
  confirms: decisionRow,
  waits: decisionRow,
};

// ── 줄 하나: 왼쪽 위 이름·아래 설명, 오른쪽 위 주 값·아래 보조 값 ─────────────────

function row({ title, sub, aside, asideSub, hint, tone }) {
  const item = el("li", `mgr-row${tone ? ` ${tone}` : ""}`);
  if (hint) item.title = hint;
  const main = el("div", "mgr-main");
  // 글자만이면 그대로, 배지를 섞어야 하면 부르는 쪽이 만든 노드를 받는다
  main.append(
    typeof title === "string" ? el("span", "mgr-title", title) : title,
    sub && typeof sub === "object" ? sub : el("span", "mgr-sub", sub || "")
  );
  const side = el("div", "mgr-side");
  side.append(aside, asideSub ?? el("span", "mgr-sub", ""));
  item.append(main, side);
  return item;
}

// 자동화는 세 칸 표 — 주기 / 자동화 내용(이름·설명) / 수행 시간(다음 실행·마지막 실행).
// 같은 주기끼리 눈으로 묶어 읽게 주기를 맨 왼쪽에 둔다
function automationHead() {
  const head = el("li", "mgr-row mgr-auto mgr-colhead");
  head.append(
    el("span", "", t("manager.colCycle")),
    el("span", "", t("manager.colWhat")),
    el("span", "mgr-side", t("manager.colTime"))
  );
  return head;
}

function automationRow(item) {
  const line = el("li", `mgr-row mgr-auto${item.off_duty ? " off" : ""}`);
  line.title = [item.desc, item.command, item.last?.detail].filter(Boolean).join("\n");
  const cycle = el("span", "mgr-cycle", cycleText(item.cycle, item.expr));
  const main = el("div", "mgr-main");
  // 설명이 없으면 비워 두지 않고 드러낸다 — 빈 칸은 '설명할 게 없다'로 읽힌다
  const desc = item.desc
    ? el("span", "mgr-sub", item.desc)
    : el("span", "mgr-sub mgr-nodesc", t("manager.noDesc"));
  main.append(el("span", "mgr-title", automationName(item)), desc);
  const side = el("div", "mgr-side");
  side.append(el("span", "mgr-next", nextText(item)), lastBadge(item.last));
  line.append(cycle, main, side);
  return line;
}

function automationName(item) {
  if (item.source === "manager") return t("manager.checkName");
  if (item.source === "sre-watch") return t("manager.sreCheck", { name: item.name });
  return item.name;
}

function helperRow(item) {
  const [tone, label] = HELPER_STATUS[item.status] ?? ["idle", () => item.status || "-"];
  const status = el("span", `mgr-chip ${tone}`, label());
  const moved = item.moved_at ? t("manager.movedAgo", { age: formatAge(item.moved_at) }) : "";
  const percent = item.percent == null ? t("manager.noProgress") : `${item.percent}%`;
  // 붙잡은 카드가 있으면 카드 기준(트리 + 카드 제목). 없으면 지금처럼 세션 이름
  const line = row({
    title: item.card ? cardTitle(item.card) : item.name,
    sub: item.doing || t("common.unknown"),
    aside: status,
    asideSub: el("span", "mgr-sub", [percent, moved].filter(Boolean).join(" · ")),
    hint: item.name,
    tone: "mgr-click",
  });
  return clickable(line, () => openWork(helperWork(item)));
}

// 줄 제목을 카드 기준으로 — 어느 트리(워크스페이스)인지 칩 하나, 그 뒤 카드 번호·제목
function cardTitle(card) {
  const title = el("span", "mgr-title mgr-card-title");
  const name = card.workspace_name ?? t("common.unassigned");
  const tree = el("span", "mgr-tree-chip", name);
  if (card.category_color) tree.style?.setProperty("--cat", card.category_color);
  tree.title = t("manager.cardTree", { tree: name });
  title.append(tree, document.createTextNode(`#${card.todo_id} ${card.title}`));
  return title;
}

function clickable(line, open) {
  line.tabIndex = 0;
  line.addEventListener?.("click", open);
  line.addEventListener?.("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      open();
    }
  });
  return line;
}

// 매니저 할일 줄 상태(app/services/manager_panel.py STATE_*) → (칩 색, 문구, 트리 카드 상태).
// 선행 대기는 다른 할일이 끝나야 하는 것이라 사람을 기다리는 결정 대기(waiting)와 다른 색이다
const TASK_STATES = {
  decision: ["waiting", () => t("manager.stateDecision"), "doing"],
  // 권한 대기 — 사용자가 허용·로그인을 해 줘야 보조 세션이 움직인다. 고를 것이 있는 결정과 다른 색
  permission: ["permission", () => t("manager.statePermission"), "doing"],
  action: ["waiting", () => t("manager.stateAction"), "doing"],
  confirm: ["confirm", () => t("manager.stateConfirm"), "review"],
  prereq: ["prereq", () => t("manager.statePrereq"), "todo"],
  closed: ["", () => t("manager.stateClosed"), "done"],
};

function taskState(item) {
  return TASK_STATES[item.state] ?? TASK_STATES.decision;
}

function decisionRow(item) {
  const [tone, label] = taskState(item);
  const chip = el("span", `mgr-chip ${tone}`.trim(), label());
  const extra = [
    item.since ? t("manager.sinceAgo", { age: formatAge(item.since) }) : "",
    item.held ? t("manager.held") : "",
  ].filter(Boolean);
  // '#8 2/3 제목' — 번호 오른쪽에 보드 할일 줄과 같은 우선순위 배지. 분모는 매니저 DB 의 열린 할일 중 최고
  const title = el("span", "mgr-title");
  title.append(
    document.createTextNode(`#${item.id}`),
    priorityBadge(item.priority, item.priority_max),
    document.createTextNode(item.title)
  );
  // 붙어 있는 카드가 있으면 제목 줄은 카드(트리 + 카드 제목), 결정·확인할 것은 아랫줄로 내린다
  if (item.card) title.className = "mgr-sub";
  const line = row({
    title: item.card ? cardTitle(item.card) : title,
    sub: item.card ? title : (item.state === "prereq" && prereqSummary(item.prereqs)) || item.detail || "",
    aside: chip,
    asideSub: el("span", "mgr-sub", extra.join(" · ")),
    tone: `mgr-click${item.held ? " off" : ""}`,
  });
  return clickable(line, () => openDecision(item));
}

// ── 도구 목록 — 휴대폰 '앱 및 서비스 연결하기' 화면처럼 ─────────────────────────
// 위에 용도 칩·검색, '연결됨' 줄에 연결된 외부 도구 개수, 아래 줄마다 이름·설명(같은 줄, 좁으면 말줄임)·
// 제작 주체 배지·오른쪽 상태. 보기 전용 — 연결 버튼은 없다. 목록·용도·제작 주체·상태는 서버가 정한다
// (app/services/manager_tools.py). 칩·검색은 받은 목록을 화면에서 거르기만 한다

// 용도 칩 순서. 받은 목록에 있는 용도만 칩으로 낸다
const TOOL_CATEGORIES = {
  talk: () => t("manager.toolCat.talk"),
  docs: () => t("manager.toolCat.docs"),
  dev: () => t("manager.toolCat.dev"),
  infra: () => t("manager.toolCat.infra"),
  data: () => t("manager.toolCat.data"),
  command: () => t("manager.toolCat.command"),
  etc: () => t("manager.toolCat.etc"),
};
// 제작 주체 배지. 누가 만들었는지 모르는 것(maker 없음)은 배지를 달지 않는다
const TOOL_MAKERS = {
  inhouse: () => t("manager.toolMaker.inhouse"),
  external: () => t("manager.toolMaker.external"),
};
// 상태 → (칩 색, 문구). 확인하지 못한 것은 '확인 안 됨' 그대로 드러낸다
const TOOL_STATUS = {
  connected: ["ok", () => t("manager.toolStatus.connected")],
  available: ["ok", () => t("manager.toolStatus.available")],
  auth: ["waiting", () => t("manager.toolStatus.auth")],
  failed: ["failed", () => t("manager.toolStatus.failed")],
  unknown: ["", () => t("manager.toolStatus.unknown")],
};
const toolFilter = { category: "all", query: "" };
let searchBound = false;

function bindToolSearch() {
  if (searchBound) return;
  searchBound = true;
  const input = document.getElementById("mgr-tools-search");
  input.addEventListener?.("input", () => {
    toolFilter.query = input.value.trim().toLowerCase();
    pages.tools = 0;
    if (sections.tools) drawPart("tools");
  });
}

export function filterTools(items, { category, query }) {
  return items.filter((item) => {
    if (category !== "all" && item.category !== category) return false;
    if (!query) return true;
    const maker = TOOL_MAKERS[item.maker]?.();
    return [item.name, item.desc, item.source, maker].some((text) => text && text.toLowerCase().includes(query));
  });
}

// 칩·'연결됨' 줄을 그리고 지금 거른 목록을 돌려준다
function drawToolsChrome(section) {
  const present = Object.keys(TOOL_CATEGORIES).filter((key) => section.items.some((item) => item.category === key));
  if (toolFilter.category !== "all" && !present.includes(toolFilter.category)) toolFilter.category = "all";
  const chips = ["all", ...present].map((key) => {
    const chip = pagerButton(`mgr-cat${key === toolFilter.category ? " on" : ""}`, false, () => {
      toolFilter.category = key;
      pages.tools = 0;
      drawPart("tools");
    });
    chip.textContent = key === "all" ? t("manager.toolCat.all") : TOOL_CATEGORIES[key]();
    chip.setAttribute?.("aria-pressed", String(key === toolFilter.category));
    return chip;
  });
  document.getElementById("mgr-tools-cats").replaceChildren(...chips);
  drawConnected(section.items);
  return filterTools(section.items, toolFilter);
}

// '연결됨' 줄 — 연결된 외부 도구 개수와 확인 시각만. 글자 아이콘 묶음은 정보가 없어 뺐다
function drawConnected(items) {
  const box = document.getElementById("mgr-tools-connected");
  const connected = items.filter((item) => item.kind !== "command" && item.status === "connected");
  box.hidden = !connected.length;
  if (box.hidden) return box.replaceChildren();
  const checked = items.find((item) => item.checked_at)?.checked_at;
  box.replaceChildren(
    el("span", "mgr-connected-label", t("manager.toolConnected")),
    el("span", "mgr-connected-count", String(connected.length)),
    el("span", "mgr-sub mgr-checked", checked ? t("manager.toolChecked", { age: formatAge(checked) }) : "")
  );
}

// 한 줄: [이름 설명……] [용도] [제작 주체] [상태]. 용도는 '전체'로 볼 때만 — 칩으로 거르면 모두 같아 군더더기다
function toolRow(item) {
  const [tone, label] = TOOL_STATUS[item.status] ?? TOOL_STATUS.unknown;
  const line = el("li", "mgr-row mgr-tool");
  const maker = TOOL_MAKERS[item.maker];
  const category = TOOL_CATEGORIES[item.category];
  line.title = [item.name, item.detail || item.desc, item.kind === "command" ? "" : item.source]
    .filter(Boolean)
    .join("\n");
  const desc = item.desc
    ? el("span", "mgr-sub mgr-tool-desc", item.desc)
    : el("span", "mgr-sub mgr-tool-desc mgr-nodesc", t("manager.noDesc"));
  const main = el("div", "mgr-tool-main");
  main.append(el("span", "mgr-title", item.name), desc);
  const tags = [];
  if (toolFilter.category === "all" && category) tags.push(el("span", "mgr-tool-cat", category()));
  if (maker) tags.push(el("span", `mgr-maker ${item.maker}`, maker()));
  line.append(main, ...tags, el("span", `mgr-chip ${tone}`.trim(), label()));
  return line;
}

// ── 결정 대기·완료 확인 대기 팝업 ─────────────────────────────────────────────
// 매니저 DB 와 연결 세션의 마지막 답에 기록된 글만 옮긴다. 요약·추천을 화면이 지어내지 않는다.
// 결정: 지금까지 한 일 / 결정할 것. 완료 확인: 끝낸 내용 / 작업 사항 / 다음 단계 / 산출물(있을 때만)

// slot: 멈춘 단계 줄 아래에 넣을 답하는 상자(openDecision 이 준다)
export function decisionSections(item, slot = null) {
  const popup = item.popup || {};
  const sections = item.state === "confirm" ? confirmSections(popup) : openSections(popup);
  // 진행 단계 — 어느 단계에서 멈췄고 무엇을 하면 넘어가는지. 기록된 글 앞에 둔다: 무엇 때문에 멈췄는지가 먼저다
  if (item.steps?.length) {
    const node = stepList(item.steps, { active: item.state !== "closed", slot });
    sections.unshift({ title: t("steps.title"), node });
  }
  // 사전 조건 — 선행 대기면 맨 위에. 이미 풀린 선행도 무엇을 기다렸는지 보이게 남긴다
  if (item.prereqs?.length) {
    const node = prereqList(item.prereqs, { owner: item.id, onChange: afterPrereqChange });
    sections.unshift({ title: t("manager.popupPrereqs"), node });
  }
  if (popup.session_id) sections.push(sessionSection(popup, item.state === "confirm"));
  if (popup.source_ref) sections.push({ title: t("manager.popupSource"), parts: [{ text: popup.source_ref }] });
  return sections;
}

function openSections(popup) {
  const decide = [{ text: popup.next_step }];
  if (popup.open_target) decide.push({ label: t("manager.popupOutput"), text: popup.open_target });
  // 결정 사항은 보통 답 끝에 있어 결정할 것 쪽에 둔다
  if (popup.reply_tail) decide.push(replyPart(popup));
  return [
    { title: t("manager.popupDone"), parts: [{ text: popup.detail }, ...planPart(popup)] },
    { title: t("manager.popupDecide"), parts: decide },
  ];
}

function confirmSections(popup) {
  const sections = [
    { title: t("manager.popupFinished"), parts: [{ text: popup.reason }] },
    { title: t("manager.popupWork"), parts: [{ text: popup.detail }, ...planPart(popup)] },
    { title: t("manager.popupNext"), parts: [{ text: popup.next_step }] },
  ];
  if (popup.open_target) sections.push({ title: t("manager.popupOutput"), parts: [{ text: popup.open_target }] });
  return sections;
}

function planPart(popup) {
  return popup.plan ? [{ label: t("manager.popupPlan", { status: popup.plan_status || "-" }), text: popup.plan }] : [];
}

// 연결 세션 — 이름(없으면 세션 id 앞 8자리). 완료 확인은 마지막 답도 여기 붙인다
function sessionSection(popup, withReply) {
  const parts = [{ text: popup.session_name || popup.session_id.slice(0, 8) }];
  if (withReply && popup.reply_tail) parts.push(replyPart(popup));
  return { title: t("manager.popupSession"), parts };
}

function replyPart(popup) {
  const head = popup.reply_from === "dashboard_head";
  return {
    label: head ? t("manager.popupReplyHead") : t("manager.popupReply"),
    text: popup.reply_tail,
    quote: true,
  };
}

// 열린 결정은 '결정할 것' 바로 아래에서 답한다 — 선택지·답 상태는 줄에 없어 팝업을 열 때 한 건을 받는다
// (app/services/decision_answer.py). 할일에 붙은 결정도 여기서 답할 수 있다 — 같은 상자가 할일 상세에도 있다.
// 확인 대기는 '끝낸 내용' 바로 아래에서 확인하거나 고칠 것을 보낸다(app/services/task_report.py) — 무엇을 끝냈는지
// 읽고 바로 누르게
const ANSWER_AT = 2;
const CONFIRM_AT = 1;

// 선행 대기·닫힌 할일은 답하는 칸이 없다 — 선행 대기는 사전 조건 할일을 먼저 끝낸다.
// 진행 단계에 멈춘 단계가 있으면 결정·직접 할 일의 답하는 상자는 그 단계 줄 바로 아래에 들어간다
function openDecision(item) {
  const alive = () => document.getElementById("mgr-decision-modal").open;
  // 권한 대기는 종류대로 받는다 — 예전 ask 가 결정으로 남긴 막힘은 답 칸, 직접 할 일로 남긴 막힘은 완료 칸
  const answerAs = item.state === "permission" ? item.kind : item.state;
  if ((answerAs === "decision" || answerAs === "action") && currentStep(item.steps)) {
    const box = answerAs === "decision" ? decisionLoader(item.id, { alive }) : reportLoader(item.id, { alive });
    openWork(decisionWork(item, decisionSections(item, box)));
    return;
  }
  const sections = decisionSections(item);
  const shift = (item.prereqs?.length ? 1 : 0) + (item.steps?.length ? 1 : 0);
  if (answerAs === "decision") {
    sections.splice(ANSWER_AT + shift, 0, { title: t("decision.answerTitle"), node: decisionLoader(item.id, { alive }) });
  } else if (answerAs === "action") {
    sections.splice(ANSWER_AT + shift, 0, { title: t("report.actionTitle"), node: reportLoader(item.id, { alive }) });
  } else if (item.state === "confirm") {
    sections.splice(CONFIRM_AT + shift, 0, { title: t("report.confirmTitle"), node: reportLoader(item.id, { alive }) });
  }
  openWork(decisionWork(item, sections));
}

function decisionWork(item, sections) {
  return {
    title: `#${item.id} ${item.title}`,
    request: item.popup?.request,
    source: item.popup,
    sections,
    card: item.card,
    solo: decisionSolo(item),
  };
}

// 보조 세션 줄 — 상세는 사용자 요청 / 지금 하는 일 / 피드백 보내기 / 연결 세션.
// 피드백은 지금 하는 일을 읽고 바로 쓰게 그 아래에 둔다 — 그 세션에 글을 넘긴다(app/services/helper_feedback.py)
function helperWork(item) {
  const percent = item.percent == null ? t("manager.noProgress") : `${item.percent}%`;
  const alive = () => document.getElementById("mgr-decision-modal").open;
  return {
    title: item.card ? `#${item.card.todo_id} ${item.card.title}` : item.name,
    request: item.request,
    sections: [
      { title: t("manager.popupDoing"), parts: [{ text: [item.doing, percent].filter(Boolean).join(" · ") }] },
      { title: t("helper.feedbackTitle"), node: feedbackLoader(item.session_id, { alive }) },
      { title: t("manager.popupSession"), parts: [{ text: item.name }] },
    ],
    card: item.card,
    solo: helperSolo(item),
  };
}

// ── 트리 없는 일의 카드 한 장 ─────────────────────────────────────────────────
// 트리 탭에서 그 일이 트리에 붙어 있지 않으면 그 일 하나를 트리 카드와 같은 모양으로 그린다.
// 상태 색은 트리 카드 규칙(static/css/tree.css)을 따른다: 작업 중 = 진행 중, 쉼 = 할 일,
// 완료 확인 대기 = 확인 대기. 결정을 기다리는 일은 바탕이 진행 중이고, 사람을 기다린다는 것은
// 대기 표시가 말한다 — 트리 카드의 '진행 중 + 답 대기' 와 같은 모양.
// 대기 종류는 그 세션의 대시보드 대기 신호(item.waiting, 트리 카드와 같은 신호)를 먼저 쓴다 —
// 권한을 기다리는 세션은 '권한 대기' 로 보여야 한다
const HELPER_TREE_STATUS = { "작업 중": "doing", "결정 대기": "doing", "권한 대기": "doing", 쉼: "todo" };
const DECISION_WAIT = "input";
const PERMISSION_WAIT = "permission";
const HELPER_WAIT = { "결정 대기": DECISION_WAIT, "권한 대기": PERMISSION_WAIT };
const TASK_WAIT = { decision: DECISION_WAIT, action: DECISION_WAIT, permission: PERMISSION_WAIT };

function helperSolo(item) {
  const [, label] = HELPER_STATUS[item.status] ?? ["idle", () => item.status || "-"];
  return {
    title: item.name,
    status: HELPER_TREE_STATUS[item.status] ?? "todo",
    label: label(),
    waiting: item.waiting ?? HELPER_WAIT[item.status] ?? null,
  };
}

function decisionSolo(item) {
  const [, label, status] = taskState(item);
  return {
    id: item.id,
    title: item.title,
    status,
    label: label(),
    waiting: item.waiting ?? TASK_WAIT[item.state] ?? null,
  };
}

// 사전 조건을 빼거나 닫은 뒤 — 선행이 모두 풀린 할일은 선행 대기에서 빠져 결정 대기·직접 할 일로 간다.
// 두 칸을 다시 읽고, 열린 팝업은 갱신된 할일로 다시 그린다(풀렸으면 답하는 칸이 생긴다)
async function afterPrereqChange(task) {
  if (task && document.getElementById("mgr-decision-modal").open) openDecision(task);
  await Promise.all(["waits", "decisions", "permissions"].map(refreshPart));
}

/** 매니저 할일 한 건을 받아 그 팝업을 연다 — 사전 조건 할일을 누를 때(prereq.js) */
export async function openManagerTask(id) {
  openDecision(await api.getManagerTask(id));
}

// 붙은 할일이 있는데 워크스페이스가 없으면 트리가 없다 — 그 할일을 카드로 그리고 제목으로 상세를 연다.
// 붙은 할일이 아예 없으면 줄에 보이는 제목(세션 이름·매니저 할일 제목)과 그 일의 상태로 그린다
function drawSolo(host, work) {
  const card = work.card;
  const solo = card
    ? {
        id: card.todo_id,
        title: card.title,
        status: card.status,
        waiting: work.solo?.waiting ?? null,
        onOpen: () => openDetail({ todo: { id: card.todo_id } }),
      }
    : work.solo;
  const board = el("div", "tm-viewport mgr-solo");
  board.append(soloCard(solo), el("p", "mgr-solo-note", card ? t("manager.soloNoWorkspace") : t("manager.soloUnlinked")));
  host.replaceChildren(board);
}

// ── 팝업: 상세 · 트리 ─────────────────────────────────────────────────────────
// 상세는 그 일 자체(사용자 요청 + 기록된 글), 트리는 그 일이 붙은 카드의 트리를 트리 메뉴와 같은 맵으로
// 그리고 그 카드를 강조한다. 맵은 트리 탭을 열 때 그린다 — 숨긴 칸에서 그리면 크기를 0 으로 잰다
const POP_DETAIL = "detail";
const POP_TREE = "tree";
let openedWork = null;

function openWork(work) {
  openedWork = work;
  const dialog = document.getElementById("mgr-decision-modal");
  const head = el("div", "dlg-head");
  head.append(el("p", "dlg-title", work.title));
  document.getElementById("mgr-decision-head").replaceChildren(head);
  const sections = [requestSection(work), ...work.sections];
  document.getElementById("mgr-decision-body").replaceChildren(...sections.map(sectionBox));
  const tree = document.getElementById("mgr-decision-tree");
  tree.replaceChildren();
  delete tree.dataset?.drawn;
  bindPopupTabs();
  showPopupTab(POP_DETAIL);
  if (!dialog.open) dialog.showModal();
}

function sectionBox(section) {
  const box = el("section", "mgr-pop-sec");
  box.append(el("h3", "mgr-pop-title", section.title));
  if (section.node) {
    box.append(section.node);
    return box;
  }
  const filled = section.parts.filter((part) => part.text);
  if (!filled.length) box.append(el("p", "mgr-pop-none", t("manager.popupNone")));
  for (const part of filled) {
    if (part.label) box.append(el("p", "mgr-pop-label", part.label));
    const text = el(part.quote ? "blockquote" : "p", part.quote ? "mgr-pop-quote" : "mgr-pop-text");
    text.append(...linkify(part.text).map(notePart));
    box.append(text);
  }
  return box;
}

// 사용자 요청 — 그 일을 하는 세션이 맨 처음 받은 지시 전문(줄바꿈 그대로). 길면 접어 두고 펼친다
const REQUEST_FOLD_CHARS = 600;
const REQUEST_FOLD_LINES = 10;

function requestSection(work) {
  const request = work.request || {};
  const box = el("div", "mgr-request");
  if (request.status === "ok") {
    const text = el("p", "mgr-pop-text mgr-request-text");
    text.append(...linkify(request.text).map(notePart));
    box.append(text);
    const lines = request.text.split("\n").length;
    if (request.text.length > REQUEST_FOLD_CHARS || lines > REQUEST_FOLD_LINES) {
      box.classList.toggle("folded", true);
      const toggle = el("button", "mgr-request-toggle", t("manager.requestMore"));
      toggle.type = "button";
      toggle.addEventListener("click", () => {
        const fold = !box.className.split(" ").includes("folded");
        box.classList.toggle("folded", fold);
        toggle.textContent = fold ? t("manager.requestMore") : t("manager.requestLess");
      });
      box.append(toggle);
    }
  } else if (request.status === "not_found") {
    box.append(el("p", "mgr-pop-none", t("manager.requestNotFound")));
  } else if (request.status === "empty") {
    box.append(el("p", "mgr-pop-none", t("manager.requestEmpty")));
  } else {
    // 세션 없이 들어온 일(Jira·메일 훑기) — 무엇에서 왔는지를 대신 보인다
    box.append(el("p", "mgr-pop-none", t("manager.requestNoSession")));
    const from = [work.source?.source, work.source?.source_ref].filter(Boolean).join(" · ");
    if (from) {
      const text = el("p", "mgr-pop-text");
      text.append(...linkify(t("manager.requestSource", { source: from })).map(notePart));
      box.append(text);
    }
  }
  return { title: t("manager.popupRequest"), node: box };
}

let popupBound = false;
function bindPopupTabs() {
  if (popupBound) return;
  popupBound = true;
  document.getElementById("mgr-pop-tabs").addEventListener("click", (event) => {
    const tab = event.target.closest?.("button")?.dataset.tab;
    if (tab) showPopupTab(tab);
  });
}

function showPopupTab(tab) {
  const dialog = document.getElementById("mgr-decision-modal");
  document.querySelectorAll?.("#mgr-pop-tabs button").forEach((button) => {
    button.classList.toggle("active", button.dataset.tab === tab);
  });
  document.getElementById("mgr-decision-body").hidden = tab !== POP_DETAIL;
  document.getElementById("mgr-decision-tree").hidden = tab !== POP_TREE;
  // 맵은 넓어야 읽힌다 — 트리 탭에서만 팝업을 넓힌다. 트리 없이 카드 한 장이면 넓힐 까닭이 없다
  dialog.classList.toggle("wide", tab === POP_TREE && hasTree(openedWork));
  if (tab === POP_TREE) drawPopupTree(openedWork);
}

function hasTree(work) {
  return Boolean(work?.card?.workspace_id);
}

async function drawPopupTree(work) {
  const host = document.getElementById("mgr-decision-tree");
  const card = work?.card;
  host.classList.toggle("solo", !hasTree(work));
  if (!hasTree(work)) {
    drawSolo(host, work);
    return;
  }
  if (host.dataset.drawn === String(card.todo_id)) return;
  host.dataset.drawn = String(card.todo_id);
  const map = createTreeMap(host, {
    focusId: card.todo_id,
    onChange: async () => drawTreeOf(map, card.workspace_id),
  });
  await drawTreeOf(map, card.workspace_id);
}

// 그 카드의 트리 하나. 다른 상위·선행 선(links)은 양 끝이 이 판에 있는 것만 그려진다
async function drawTreeOf(map, workspaceId) {
  const { trees, links } = await api.getTodoTrees();
  map.render(trees.filter((tree) => tree.workspace.id === workspaceId), { hideDone: true, links });
}

function refreshFailedNote(error) {
  const line = note(t("manager.refreshFailed"), "mgr-error");
  line.title = error;
  return line;
}

function note(text, className = "mgr-empty") {
  return el("li", className, text);
}

// ── 다음 실행 · 마지막 결과 ────────────────────────────────────────────────

function nextText(item) {
  if (item.off_duty) return t("manager.offDuty");
  if (item.next_within_sec) {
    return t("manager.within", { time: span(item.next_within_sec) });
  }
  if (!item.next_at) return item.cycle?.reboot ? t("manager.onReboot") : "-";
  const sec = Math.max(0, (Date.parse(item.next_at) - Date.now()) / 1000);
  return t("manager.inTime", { time: span(sec) });
}

function lastBadge(last) {
  if (!last?.at) return el("span", "mgr-sub", t("manager.lastUnknown"));
  const age = formatAge(last.at);
  if (last.detail === "woke") return el("span", "mgr-sub", t("manager.lastWoke", { age }));
  const [tone, label] = LAST_STATUS[last.status] ?? ["", (ran) => t("manager.lastRan", { age: ran })];
  return el("span", `mgr-sub mgr-last ${tone}`, label(age));
}

// 남은 시간. 1분 미만은 '1분'으로 올린다 — 다음 실행이 '0분 후' 로 보이면 지나간 것처럼 읽힌다
function span(seconds) {
  const minutes = Math.max(1, Math.ceil(seconds / 60));
  if (minutes < 60) return t("duration.minutes", { count: minutes });
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return t("duration.hoursMinutes", { hours, minutes: minutes % 60 });
  return t("duration.daysHours", { days: Math.floor(hours / 24), hours: hours % 24 });
}

// ── 주기 → 사람 말 ────────────────────────────────────────────────────────
// 한 형식으로만 쓴다 — 칸마다 표기가 다르면 같은 주기끼리 눈으로 묶이지 않는다.
//   반복형: '10분마다'·'2시간마다'·'매시 07분', 요일·시간 범위는 뒤 괄호 '10분마다 (평일 08~20시)'
//   시각형: '매일 11:30'·'평일 08:00, 18:00'·'매주 수·목 15:00'·'매월 5일 05:00'
//   '부팅 시'. 옮기지 못하는 모양만 crontab 원문

export function cycleText(cycle, expr) {
  if (!cycle) return expr || "";
  if (cycle.reboot) return t("manager.onReboot");
  if (cycle.raw) return cycle.raw;
  if (cycle.every_days != null) return checkCycleText(cycle, expr);
  return scheduleText(cycle.days, cycle.time) ?? (expr || "");
}

// SRE 체크 — 러너 크론 시각에 every_days 일마다 돈다. 하루 한 번이면 러너 표기 그대로
function checkCycleText(cycle, expr) {
  if (cycle.manual) return t("manager.cycleManual");
  const runner = cycle.runner;
  if (cycle.every_days === 1) return cycleText(runner, expr);
  if (runner?.time?.kind !== "at") return cycleText(runner, expr);
  return t("manager.cycleEveryDays", { count: cycle.every_days, times: runner.time.times.join(", ") });
}

function scheduleText(days, time) {
  const dayWord = daysText(days);
  if (dayWord === null) return null;
  switch (time?.kind) {
    case "at":
      return `${dayWord || t("manager.daysEvery")} ${time.times.join(", ")}`;
    case "interval":
    case "hourly": {
      const base = repeatText(time);
      const range = time.hours ? t("manager.hourRange", { from: pad(time.hours[0]), to: pad(time.hours[1]) }) : "";
      const scope = [dayWord, range].filter(Boolean).join(" ");
      return scope ? t("manager.cycleScope", { cycle: base, scope }) : base;
    }
    default:
      return null;
  }
}

function repeatText(time) {
  if (time.kind === "hourly") return t("manager.hourlyAt", { minute: pad(time.minute) });
  if (time.every_hours) return t("manager.everyHours", { count: time.every_hours });
  return t("manager.everyMinutes", { count: time.minutes });
}

function daysText(days) {
  switch (days?.kind) {
    case "every":
      return "";
    case "weekdays":
      return t("manager.daysWeekdays");
    case "dow":
      return t("manager.daysWeekly", { days: days.values.map(weekdayName).join("·") });
    case "dom":
      return t("manager.daysMonthly", { days: days.values.join(", ") });
    default:
      return null;
  }
}

function pad(value) {
  return String(value).padStart(2, "0");
}

// 0=일요일. 2026-11-08 은 일요일이라 그 날짜에 요일 수를 더해 이름을 얻는다
function weekdayName(index) {
  const day = new Date(2026, 10, 8 + index);
  return new Intl.DateTimeFormat(language(), { weekday: "short" }).format(day);
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}
