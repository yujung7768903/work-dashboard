// 매니저 탭 — 휴대폰 '예약 작업' 목록처럼 한 줄에 하나씩, 보기 전용.
// 세 칸(자동화·보조 세션·결정 대기)은 서버에서 따로 받는다. 보조 세션 목록은 claude agents 를
// 부르느라 수 초 걸려, 한 번에 받으면 나머지 두 칸까지 그만큼 늦게 뜬다 (app/services/manager_panel.py)
import * as api from "./api.js";
import { language, t } from "./i18n.js";
import { formatAge } from "./sessions.js";

const PARTS = ["automations", "helpers", "decisions"];
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
  const list = document.getElementById(`mgr-${part}`);
  let section;
  try {
    section = (await api.getManager(part))[part];
  } catch (error) {
    section = { items: [], error: error.message };
  }
  const rows = section.items.map(ROW_BUILDERS[part]);
  document.getElementById(`mgr-${part}-count`).textContent = section.error
    ? ""
    : String(section.items.length);
  if (section.error) rows.unshift(note(t("manager.partFailed", { error: section.error }), "mgr-error"));
  else if (!rows.length) rows.push(note(EMPTY[part]()));
  list.replaceChildren(...rows);
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

function automationRow(item) {
  const sub = [cycleText(item.cycle, item.expr), item.desc].filter(Boolean).join(" · ");
  return row({
    title: automationName(item),
    sub,
    aside: el("span", "mgr-next", nextText(item)),
    asideSub: lastBadge(item.last),
    hint: [item.command, item.last?.detail].filter(Boolean).join("\n"),
    tone: item.off_duty ? "off" : "",
  });
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
  return row({
    title: `#${item.id} ${item.title}`,
    sub: item.detail || "",
    aside: chip,
    asideSub: el("span", "mgr-sub", extra.join(" · ")),
    hint: item.detail || "",
    tone: item.held ? "off" : "",
  });
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

export function cycleText(cycle, expr) {
  if (!cycle) return expr || "";
  if (cycle.reboot) return t("manager.onReboot");
  if (cycle.raw) return cycle.raw;
  if (cycle.every_days != null) {
    if (cycle.manual) return t("manager.cycleManual");
    const runner = cycleText(cycle.runner);
    return cycle.every_days === 1
      ? t("manager.cycleDailyCheck", { runner })
      : t("manager.cycleEveryDays", { count: cycle.every_days, runner });
  }
  const days = daysText(cycle.days);
  const time = timeText(cycle.time);
  if (days === null || time === null) return expr || "";
  return days ? `${days} · ${time}` : time;
}

function daysText(days) {
  switch (days?.kind) {
    case "every":
      return "";
    case "weekdays":
      return t("manager.daysWeekdays");
    case "dow":
      return t("manager.daysWeekly", { days: days.values.map(weekdayName).join(", ") });
    case "dom":
      return t("manager.daysMonthly", { days: days.values.join(", ") });
    default:
      return null;
  }
}

function timeText(time) {
  const hours = time?.hours ? t("manager.hourRange", { from: time.hours[0], to: time.hours[1] }) : "";
  const join = (text) => (hours ? `${hours} ${text}` : text);
  switch (time?.kind) {
    case "interval":
      return join(t("manager.everyMinutes", { count: time.minutes }));
    case "hourly":
      return join(t("manager.hourlyAt", { minute: String(time.minute).padStart(2, "0") }));
    case "at":
      return time.times.join(", ");
    default:
      return null;
  }
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
