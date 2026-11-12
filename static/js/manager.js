// 매니저 탭 — 휴대폰 '예약 작업' 목록처럼 한 줄에 하나씩, 보기 전용.
// 세 칸(자동화·보조 세션·결정 대기)은 서버에서 따로 받는다. 보조 세션 목록은 claude agents 를
// 부르느라 수 초 걸려, 한 번에 받으면 나머지 두 칸까지 그만큼 늦게 뜬다 (app/services/manager_panel.py)
import * as api from "./api.js";
import { language, t } from "./i18n.js";
import { formatAge, notePart } from "./sessions.js";
import { linkify } from "./linkify.js";

// 화면 순서 — 보조 세션이 맨 위 (static/index.html)
const PARTS = ["helpers", "automations", "decisions"];
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
  쉼: ["idle", () => t("manager.helperIdle")],
};
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
  // 첫 진입에만 칸마다 '불러오는 중'. 보조 세션 칸은 수 초 걸려 빈 칸이 '없음'으로 읽힌다.
  // 폴링 재렌더 때는 지금 목록을 둔 채 바꾼다 — 1분마다 깜빡이지 않게
  PARTS.forEach((part) => {
    const list = document.getElementById(`mgr-${part}`);
    if (!list.children.length) list.replaceChildren(note(t("common.loading")));
  });
  await Promise.all(PARTS.map((part) => renderPart(part)));
}

async function renderPart(part) {
  let section;
  try {
    section = (await api.getManager(part))[part];
  } catch (error) {
    section = { items: [], error: error.message };
  }
  sections[part] = section;
  document.getElementById(`mgr-${part}-count`).textContent = section.error
    ? ""
    : String(section.items.length);
  drawPart(part);
}

// 지금 페이지의 줄만 그린다. 폴링으로 줄 수가 줄어 보던 페이지가 사라지면 마지막 페이지로
function drawPart(part) {
  const section = sections[part];
  const list = document.getElementById(`mgr-${part}`);
  const total = pageCount(section.items.length);
  pages[part] = Math.min(pages[part], total - 1);
  const start = pages[part] * PAGE_SIZE;
  const rows = section.items.slice(start, start + PAGE_SIZE).map(ROW_BUILDERS[part]);
  if (section.error) rows.unshift(note(t("manager.partFailed", { error: section.error }), "mgr-error"));
  else if (!rows.length) rows.push(note(EMPTY[part]()));
  else if (part === "automations") rows.unshift(automationHead());
  list.replaceChildren(...rows);
  drawPager(part, total);
}

export function pageCount(length) {
  return Math.max(1, Math.ceil(length / PAGE_SIZE));
}

// 이전 · 페이지 번호 · 다음. 한 페이지로 끝나면 숨긴다
function drawPager(part, total) {
  const pager = document.getElementById(`mgr-${part}-pager`);
  pager.hidden = total <= 1;
  if (pager.hidden) return pager.replaceChildren();
  const current = pages[part];
  const go = (index) => {
    pages[part] = index;
    drawPart(part);
  };
  const buttons = [pagerButton(t("manager.pagePrev"), current === 0, () => go(current - 1))];
  for (let index = 0; index < total; index += 1) {
    const number = pagerButton(String(index + 1), false, () => go(index));
    if (index === current) {
      number.className += " on";
      number.setAttribute?.("aria-current", "page");
    }
    buttons.push(number);
  }
  buttons.push(pagerButton(t("manager.pageNext"), current === total - 1, () => go(current + 1)));
  pager.replaceChildren(...buttons);
}

function pagerButton(text, disabled, onClick) {
  const button = el("button", "mgr-page", text);
  button.type = "button";
  button.disabled = disabled;
  button.addEventListener("click", onClick);
  return button;
}

// 키를 문자열 그대로 둔다 — 사전 점검(tests/test_language.py)이 코드에서 키를 찾는다
const EMPTY = {
  automations: () => t("manager.empty.automations"),
  helpers: () => t("manager.empty.helpers"),
  decisions: () => t("manager.empty.decisions"),
};

const ROW_BUILDERS = {
  automations: automationRow,
  helpers: helperRow,
  decisions: decisionRow,
};

// ── 줄 하나: 왼쪽 위 이름·아래 설명, 오른쪽 위 주 값·아래 보조 값 ─────────────────

function row({ title, sub, aside, asideSub, hint, tone }) {
  const item = el("li", `mgr-row${tone ? ` ${tone}` : ""}`);
  if (hint) item.title = hint;
  const main = el("div", "mgr-main");
  main.append(el("span", "mgr-title", title), el("span", "mgr-sub", sub || ""));
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
  return row({
    title: item.name,
    sub: item.doing || t("common.unknown"),
    aside: status,
    asideSub: el("span", "mgr-sub", [percent, moved].filter(Boolean).join(" · ")),
  });
}

function decisionRow(item) {
  const confirm = item.state === "confirm";
  const chip = el(
    "span",
    `mgr-chip ${confirm ? "confirm" : "waiting"}`,
    confirm ? t("manager.stateConfirm") : t("manager.stateDecision")
  );
  const extra = [
    item.since ? t("manager.sinceAgo", { age: formatAge(item.since) }) : "",
    item.held ? t("manager.held") : "",
  ].filter(Boolean);
  const line = row({
    title: `#${item.id} ${item.title}`,
    sub: item.detail || "",
    aside: chip,
    asideSub: el("span", "mgr-sub", extra.join(" · ")),
    tone: `mgr-click${item.held ? " off" : ""}`,
  });
  line.tabIndex = 0;
  line.addEventListener?.("click", () => openDecision(item));
  line.addEventListener?.("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      openDecision(item);
    }
  });
  return line;
}

// ── 결정 대기 팝업 — 지금까지 한 일 / 결정(확인)할 것 ────────────────────────────
// 매니저 DB 와 연결 세션의 마지막 답에 기록된 글만 옮긴다. 요약·추천을 화면이 지어내지 않는다

export function decisionSections(item) {
  const popup = item.popup || {};
  const confirm = item.state === "confirm";
  const done = [{ text: popup.detail }];
  if (popup.plan) {
    done.push({ label: t("manager.popupPlan", { status: popup.plan_status || "-" }), text: popup.plan });
  }
  if (confirm && popup.reason) done.push({ label: t("manager.popupResult"), text: popup.reason });
  const decide = [{ text: popup.next_step }];
  if (popup.open_target) decide.push({ label: t("manager.popupOutput"), text: popup.open_target });
  if (popup.reply_tail) {
    const head = popup.reply_from === "dashboard_head";
    decide.push({
      label: head ? t("manager.popupReplyHead") : t("manager.popupReply"),
      text: popup.reply_tail,
      quote: true,
    });
  }
  const sections = [
    { title: t("manager.popupDone"), parts: done },
    { title: confirm ? t("manager.popupConfirm") : t("manager.popupDecide"), parts: decide },
  ];
  if (popup.source_ref) sections.push({ title: t("manager.popupSource"), parts: [{ text: popup.source_ref }] });
  return sections;
}

function openDecision(item) {
  const dialog = document.getElementById("mgr-decision-modal");
  const body = document.getElementById("mgr-decision-body");
  const head = el("div", "dlg-head");
  head.append(el("p", "dlg-title", `#${item.id} ${item.title}`));
  const nodes = [head];
  for (const section of decisionSections(item)) {
    const box = el("section", "mgr-pop-sec");
    box.append(el("h3", "mgr-pop-title", section.title));
    const filled = section.parts.filter((part) => part.text);
    if (!filled.length) box.append(el("p", "mgr-pop-none", t("manager.popupNone")));
    for (const part of filled) {
      if (part.label) box.append(el("p", "mgr-pop-label", part.label));
      const text = el(part.quote ? "blockquote" : "p", part.quote ? "mgr-pop-quote" : "mgr-pop-text");
      text.append(...linkify(part.text).map(notePart));
      box.append(text);
    }
    nodes.push(box);
  }
  body.replaceChildren(...nodes);
  if (!dialog.open) dialog.showModal();
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
