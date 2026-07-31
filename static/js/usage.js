// 사용량 탭. 왼쪽은 한도·토큰 모니터링, 오른쪽 레일은 지금 무엇을 하고 있는지.
// 모든 숫자는 실측이며, 못 가져온 창은 값을 만들지 않고 "미수집"으로 남긴다.
import * as api from "./api.js";
import { compact, donutChart, percentLineChart, stackedColumnChart, thousands } from "./chart.js";

const POLL_INTERVAL_MS = 60_000; // 5시간 창은 전력으로 써도 분당 0.3%대로 움직인다
const MIN_TREND_POINTS = 2;
const RAIL_SESSION_LIMIT = 6; // 레일이 본문보다 길어지면 카드 배치가 무너진다
const PERCENT_FULL = 100;
const MS_PER_SECOND = 1000;
const SECONDS_PER_MINUTE = 60;
const MINUTES_PER_HOUR = 60;
const HOURS_PER_DAY = 24;
const DATE_SLICE = 5; // "2026-07-31" → "07-31"
const TREND_HOURS = 24;
const WORKING = "working";
const UNCLASSIFIED_LABEL = "분류 전";
const UNKNOWN = "알 수 없음";

// 사이드카(rate-limits.json)에는 five_hour·seven_day 만 남는다.
// Fable 세션 창은 그 파일에 없어 자리만 두고 미수집으로 표시한다.
const LIMIT_CARDS = [
  { key: "five_hour", label: "현재 세션 · 5시간 창", sample: "five_hour_pct" },
  { key: "seven_day", label: "이번 주 · 전체 모델", sample: "seven_day_pct" },
  { key: "fable_session", label: "Fable 세션 창", sample: null },
];
// tipName 은 툴팁 전용 긴 이름. 사이드카에는 이 두 창만 남아 모델별 %는 만들 수 없다 —
// 주간 창이 전체 모델 합산이라 그게 사실상 총 사용률이다
const PCT_SERIES = [
  { key: "seven_day_pct", name: "주간", tipName: "주간 · 전체 모델", cls: "u-c-seven" },
  { key: "five_hour_pct", name: "5시간", tipName: "현재 세션 · 5시간", cls: "u-c-five" },
];
const MODEL_CLASS = { Opus: "u-c-opus", Sonnet: "u-c-sonnet", Haiku: "u-c-haiku" };
const FALLBACK_CLASS = "u-c-haiku";
const BREAKDOWN_ROWS = [
  ["output_tokens", "출력"],
  ["cache_write_tokens", "캐시 쓰기"],
  ["cache_read_tokens", "캐시 읽기"],
];
const LEVEL_CLASS = { warn: "u-warn", critical: "u-crit" };
// 휴일 판정용. 음력 명절(설·추석)·부처님오신날·대체공휴일은 이 표로 잡히지 않는다 —
// 달력 자료를 붙이지 않는 한 계산할 수 없어 양력 고정일과 주말만 본다
const FIXED_HOLIDAYS = new Set([
  "01-01", "03-01", "05-05", "06-06", "08-15", "10-03", "10-09", "12-25",
]);
const WEEKEND_DAYS = new Set([0, 6]);
const STATUS_LABEL = { todo: "대기", doing: "진행중", done: "완료" };

let timer = null;
// 전체보기로 펼친 상태. 모듈 변수라 60초 폴링이 다시 그려도 접히지 않는다
let sessionsExpanded = false;

export async function renderUsage() {
  paint(await load());
  startPolling();
}

async function load() {
  const [usage, next, sessions, categories] = await Promise.all([
    api.getUsage(),
    api.getNext(),
    api.getSessions(),
    api.getCategories(),
  ]);
  return { usage, next, sessions, categories };
}

function paint({ usage, next, sessions, categories }) {
  renderTop(usage);
  renderLimits(usage);
  renderDaily(usage.tokens);
  renderToday(usage.tokens);
  renderTrend(usage);
  renderShare(usage.tokens);
  renderNext(next, categories);
  renderSessions(sessions);
}

// 슬롯은 index.html 이 만든다. 아직 없으면 조용히 넘어간다
function slot(id, className) {
  const box = document.getElementById(id);
  if (!box) return null;
  box.innerHTML = "";
  if (className) box.className = className;
  return box;
}

// ── 상단 스트립: 플랜·기준 시각·stale ──────────────────────────────────────
function renderTop(usage) {
  const shell = document.querySelector("#tab-usage .u-shell");
  if (!shell) return;
  let top = document.getElementById("u-top");
  if (!top) {
    top = tag("div", "u-top");
    top.id = "u-top";
    shell.parentNode.insertBefore(top, shell);
  }
  top.innerHTML = "";

  const plan = tag("span", "u-plan");
  plan.append(tag("i"), tag("span", null, usage.plan || UNKNOWN));
  top.append(plan, tag("span", "u-stamp", stampText(usage.snapshot_ts)));
  if (usage.stale) {
    top.appendChild(tag("span", "u-stale", `⚠ ${durationText(usage.stale_seconds)} 전 값`));
  }
  if (!usage.windows.length) {
    top.appendChild(tag("p", "u-caption", `한도 정보를 읽을 수 없음 — ${usage.limit_source}`));
  }
}

// ── 1행: 한도 카드 3장 ─────────────────────────────────────────────────────
function renderLimits(usage) {
  const box = slot("u-limits");
  if (!box) return;
  LIMIT_CARDS.forEach((spec) => box.appendChild(limitCard(spec, usage)));
}

function limitCard(spec, usage) {
  const found = usage.windows.find((window) => window.key === spec.key);
  const card = tag("div", found ? "u-card" : "u-card u-dim");
  const head = tag("div", "u-lim-head");
  head.append(tag("span", "u-lim-label", found ? found.title : spec.label), arrowMark());
  card.appendChild(head);

  if (!found) {
    const flagLine = tag("p", "u-reset");
    flagLine.appendChild(tag("span", "u-flag", "미수집"));
    card.append(
      tag("p", "u-lim-value u-lim-empty", "―"),
      flagLine,
      tag("p", "u-caption", "사이드카에 이 창이 없음")
    );
    return card;
  }

  const pct = found.used_percentage;
  const value = tag("p", "u-lim-value", String(Math.round(pct)));
  value.appendChild(tag("small", null, "%"));
  card.appendChild(value);

  // 델타는 표본이 두 개 이상일 때만. 계산이 안 되면 줄 자체를 뺀다
  const delta = deltaOf(usage.pct_samples, spec.sample);
  if (delta) card.appendChild(deltaLine(delta, "이전 표본 대비"));

  const track = tag("div", "u-track");
  const fill = tag("i", LEVEL_CLASS[found.level] || null);
  fill.style.width = `${Math.min(pct, PERCENT_FULL)}%`;
  track.appendChild(fill);
  card.appendChild(track);
  card.appendChild(resetLine(found.resets_at));
  return card;
}

function deltaOf(samples, field) {
  if (!field || !samples || samples.length < MIN_TREND_POINTS) return null;
  const last = samples[samples.length - 1][field];
  const prev = samples[samples.length - 2][field];
  if (typeof last !== "number" || typeof prev !== "number") return null;
  const diff = Math.round(last - prev);
  // 폴링이 1분 간격이라 직전 표본과 같은 값인 게 정상이다. 그때 "변화 없음" 한 줄을
  // 띄우면 카드마다 의미 없는 문구가 남으므로 아예 뺀다
  if (diff === 0) return null;
  return { dir: diff > 0 ? "up" : "down", text: `${Math.abs(diff)}%p` };
}

function deltaLine(delta, suffix) {
  const line = tag("p", `u-delta ${delta.dir}`);
  line.append(
    document.createTextNode(delta.dir === "up" ? "▲ " : "▼ "),
    tag("b", null, delta.text),
    document.createTextNode(` ${suffix}`)
  );
  return line;
}

function resetLine(epochSeconds) {
  const line = tag("p", "u-reset");
  if (!epochSeconds) {
    line.textContent = "초기화 시각 미확인";
    return line;
  }
  line.append(
    document.createTextNode("초기화까지 "),
    tag("b", null, remainingText(epochSeconds)),
    document.createTextNode(` · ${resetStamp(epochSeconds)}`)
  );
  return line;
}

// ── 2행: 일별 토큰 ─────────────────────────────────────────────────────────
function renderDaily(tokens) {
  const box = slot("u-daily", "u-card");
  if (!box) return;
  const models = activeModels(tokens);
  const days = tokens.days || [];
  if (!tokens.available || !models.length) {
    box.append(headRow("일별 토큰"), emptyState(noTokenText(tokens)));
    return;
  }
  box.appendChild(
    headRow("일별 토큰", `최근 ${days.length}일`, [
      legendRow(models.map((model) => ({ name: model, cls: classOf(model) }))),
    ])
  );

  // name 은 툴팁·범례에 쓰인다. 모델 이름 자체가 라벨이라 키와 같다
  const series = models.map((model) => ({ key: model, name: model, cls: classOf(model) }));
  const points = tokens.days.map((day) => ({
    label: day.date.slice(DATE_SLICE),
    holiday: isHoliday(day.date),
    values: day.by_model || {},
    // 툴팁이 합계·모델별 토큰을 정확한 수로 보여주므로 여기 남는 건 비용뿐
    detail: `정가환산 $${day.cost_usd}`,
  }));
  box.appendChild(stackedColumnChart({ points, series, label: "일별 토큰" }));

  const details = document.createElement("details");
  details.appendChild(tag("summary", null, "표로 보기"));
  details.appendChild(dayTable(tokens, models));
  box.appendChild(details);
}

function dayTable(tokens, models) {
  const table = document.createElement("table");
  table.appendChild(tableRow("th", ["날짜", "합계", ...models, "정가환산"]));
  tokens.days
    .filter((day) => day.total > 0)
    .slice()
    .reverse()
    .forEach((day) => {
      table.appendChild(
        tableRow("td", [
          day.date.slice(DATE_SLICE),
          thousands(day.total),
          ...models.map((model) => compact(day.by_model?.[model] || 0)),
          `$${day.cost_usd}`,
        ])
      );
    });
  const box = tag("div", "u-table-box");
  box.appendChild(table);
  return box;
}

// ── 2행: 오늘 토큰 ─────────────────────────────────────────────────────────
function renderToday(tokens) {
  const box = slot("u-today", "u-card");
  if (!box) return;
  const days = tokens.days || [];
  const today = days[days.length - 1];
  box.appendChild(headRow("오늘 토큰", today ? today.date.slice(DATE_SLICE) : ""));
  if (!tokens.available || !today) {
    box.appendChild(emptyState(noTokenText(tokens)));
    return;
  }

  box.appendChild(bigNumber(today.total));
  const change = dayOverDay(days);
  if (change) box.appendChild(deltaLine(change, "어제 대비"));

  const rows = tag("div", "u-rows");
  BREAKDOWN_ROWS.forEach(([field, label]) => {
    rows.appendChild(labelledRow(label, compact(today.breakdown?.[field] || 0)));
  });
  rows.appendChild(labelledRow("정가환산", `$${today.cost_usd}`));
  box.append(rows, tag("p", "u-caption", "정가환산은 API 정가 기준이며 구독 청구액이 아님"));
}

// 압축 표기의 단위 문자만 작게 — "248.2M" 의 M
function bigNumber(value) {
  const [, digits, unit] = compact(value).match(/^(.*?)([A-Z]?)$/);
  const node = tag("p", "u-today-value", digits);
  if (unit) node.appendChild(tag("small", null, unit));
  return node;
}

function dayOverDay(days) {
  if (days.length < MIN_TREND_POINTS) return null;
  const today = days[days.length - 1].total;
  const yesterday = days[days.length - 2].total;
  if (!yesterday) return null; // 0 으로 나눌 수 없으면 비율을 만들지 않는다
  const ratio = Math.round(((today - yesterday) / yesterday) * PERCENT_FULL);
  if (ratio === 0) return null; // deltaLine 은 증감만 그린다. 0 이면 줄을 빼는 쪽이 맞다
  return { dir: ratio > 0 ? "up" : "down", text: `${Math.abs(ratio)}%` };
}

// ── 3행: 한도 사용률 추이 ──────────────────────────────────────────────────
function renderTrend(usage) {
  const box = slot("u-trend", "u-card");
  if (!box) return;
  const samples = usage.pct_samples || [];
  if (samples.length < MIN_TREND_POINTS) {
    // 한도 %는 어디에도 이력이 남지 않아 이 대시보드가 모으기 시작한 시점부터 그려진다
    box.append(
      headRow("한도 사용률 추이"),
      emptyState("한도 %는 이력이 남지 않아 지금부터 모읍니다. 몇 분 뒤 추이가 그려집니다.")
    );
    return;
  }
  box.appendChild(headRow("한도 사용률 추이", `최근 ${TREND_HOURS}시간`, [legendRow(PCT_SERIES)]));
  const points = samples.map((sample) => ({
    label: clockText(sample.bucket_ts),
    values: { five_hour_pct: sample.five_hour_pct, seven_day_pct: sample.seven_day_pct },
  }));
  box.append(
    percentLineChart({ points, series: PCT_SERIES, label: "한도 사용률 추이" }),
    tag("p", "u-caption", `실측 ${samples.length}개 · 대시보드가 모으기 시작한 뒤부터 쌓임`)
  );
}

// ── 3행: 모델 구성 ─────────────────────────────────────────────────────────
function renderShare(tokens) {
  const box = slot("u-share", "u-card");
  if (!box) return;
  const days = tokens.days || [];
  const shares = activeModels(tokens).map((model) => ({
    model,
    cls: classOf(model),
    value: days.reduce((acc, day) => acc + (day.by_model?.[model] || 0), 0),
  }));
  const sum = shares.reduce((acc, share) => acc + share.value, 0);
  if (!tokens.available || !sum) {
    box.append(headRow("모델 구성"), emptyState(noTokenText(tokens)));
    return;
  }
  box.appendChild(headRow("모델 구성", `${days.length}일`));

  const wrap = tag("div", "u-donut-wrap");
  const legend = tag("div", "u-donut-legend");
  shares.forEach((share) => {
    const row = tag("span");
    row.append(
      tag("i", `u-swatch ${share.cls}`),
      tag("span", null, share.model),
      tag("b", null, `${((share.value / sum) * PERCENT_FULL).toFixed(1)}%`)
    );
    legend.appendChild(row);
  });
  wrap.append(
    donutChart({
      slices: shares,
      centerValue: compact(sum),
      centerLabel: `${days.length}일 합계`,
    }),
    legend
  );
  box.appendChild(wrap);
}

// ── 우측 레일: 다음에 할일 ─────────────────────────────────────────────────
function renderNext(next, categories) {
  const box = slot("u-next");
  if (!box) return;
  box.appendChild(railHead("다음에 할일", boardLink()));
  if (!next?.todo) {
    box.appendChild(railCard(tag("p", "u-caption", "대기 중인 할일이 없음")));
    return;
  }

  const { todo, workspace } = next;
  const item = tag("div", "u-next-item");
  // Jira 키가 없는 워크스페이스도 있다 — 그 자리에는 배지를 두지 않는다
  if (workspace?.jira_id) item.appendChild(tag("div", "u-next-badge", workspace.jira_id));
  const body = tag("div", "u-next-body");
  body.append(tag("p", null, todo.title));
  if (workspace?.name) body.appendChild(tag("small", null, workspace.name));
  item.appendChild(body);

  const meta = tag("div", "u-next-meta");
  meta.appendChild(tag("span", "u-chip", STATUS_LABEL[todo.status] || todo.status));
  const categoryName = nameOf(categories, workspace?.category_id);
  if (categoryName) meta.appendChild(tag("span", "u-chip plain", categoryName));

  const shell = railCard(item);
  shell.appendChild(meta);
  box.appendChild(shell);
}

function boardLink() {
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = "보드로";
  // 탭 전환은 main.js 가 #tabs 클릭으로 처리한다. 그 버튼을 그대로 누른다
  button.addEventListener("click", () => {
    document.querySelector("#tabs [data-tab=board]")?.click();
  });
  return button;
}

// ── 우측 레일: 돌고 있는 세션 ──────────────────────────────────────────────
function renderSessions(payload) {
  const box = slot("u-sessions");
  if (!box) return;
  const all = payload?.sessions || [];
  // 작업중이 먼저. 접힌 상태에서는 앞의 몇 개만 세우고 나머지는 수만 알린다
  const ordered = [...all].sort(
    (a, b) => Number(b.state === WORKING) - Number(a.state === WORKING)
  );
  const folded = Math.max(0, ordered.length - RAIL_SESSION_LIMIT);
  const shown = sessionsExpanded ? ordered : ordered.slice(0, RAIL_SESSION_LIMIT);

  box.appendChild(railHead("돌고 있는 세션", folded ? expandToggle(payload) : null));
  if (!all.length) {
    box.appendChild(railCard(tag("p", "u-caption", "돌고 있는 세션이 없음")));
    return;
  }

  shown.forEach((session) => {
    const item = tag("div", `u-rail-card u-sess-item ${session.state}`);
    item.appendChild(tag("div", "u-sess-mark"));
    const body = tag("div", "u-sess-body");
    const scope = tag("div", "u-sess-scope", session.workspace_name || UNCLASSIFIED_LABEL);
    if (session.category_name) scope.appendChild(tag("span", null, session.category_name));
    const ago = agoText(session.last_seen_at);
    if (ago) scope.appendChild(tag("span", "u-sess-ago", ago));
    body.append(scope, tag("p", "u-sess-prompt", session.last_prompt || "지시 없음"));
    item.appendChild(body);
    box.appendChild(item);
  });
  if (folded && !sessionsExpanded) {
    box.appendChild(tag("p", "u-caption", `그 외 ${folded}건`));
  }
  if (payload.unclassified_count) {
    box.appendChild(tag("p", "u-sess-warn", `분류 전 ${payload.unclassified_count}건 ⚠`));
  }
}

// 접힌 세션을 그 자리에서 펼친다. 같은 payload 로 다시 그리므로 재조회는 없다
function expandToggle(payload) {
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = sessionsExpanded ? "접기" : "전체보기";
  button.setAttribute("aria-expanded", String(sessionsExpanded));
  button.addEventListener("click", () => {
    sessionsExpanded = !sessionsExpanded;
    renderSessions(payload);
  });
  return button;
}

// ── 공통 조각 ──────────────────────────────────────────────────────────────
function tag(name, className, textContent) {
  const node = document.createElement(name);
  if (className) node.className = className;
  if (textContent !== undefined) node.textContent = textContent;
  return node;
}

function headRow(title, sub, extras = []) {
  const head = tag("div", "u-card-head");
  const heading = tag("h2", null, title);
  if (sub) heading.appendChild(tag("span", null, sub));
  head.appendChild(heading);
  extras.forEach((node) => head.appendChild(node));
  return head;
}

function railHead(title, extra) {
  const head = tag("div", "u-rail-head");
  head.appendChild(tag("h2", null, title));
  if (extra) head.appendChild(extra);
  return head;
}

function railCard(child) {
  const card = tag("div", "u-rail-card");
  card.appendChild(child);
  return card;
}

function legendRow(items) {
  const box = tag("div", "u-legend");
  items.forEach(({ name, cls }) => {
    const item = tag("span");
    item.append(tag("i", `u-swatch ${cls}`), tag("span", null, name));
    box.appendChild(item);
  });
  return box;
}

function labelledRow(label, value) {
  const row = tag("div");
  row.append(tag("span", null, label), tag("b", null, value));
  return row;
}

function tableRow(cell, values) {
  const line = document.createElement("tr");
  values.forEach((value, index) => {
    line.appendChild(tag(cell, index ? "u-num" : null, value));
  });
  return line;
}

function arrowMark() {
  const box = tag("span", "u-round");
  box.setAttribute("aria-hidden", "true");
  box.textContent = "→";
  return box;
}

function emptyState(message) {
  return tag("p", "u-empty", message);
}

function noTokenText(tokens) {
  return tokens.available ? "집계할 토큰 기록이 없음" : `토큰 기록이 없음 — ${tokens.source}`;
}

// 값이 한 번도 안 잡힌 모델은 범례에서 뺀다 — 죽은 항목이 색만 차지한다
function activeModels(tokens) {
  const days = tokens.days || [];
  return (tokens.models || []).filter((model) =>
    days.some((day) => (day.by_model?.[model] || 0) > 0)
  );
}

// "2026-07-31" → 주말·공휴일 여부. 로컬 자정으로 만들어 시간대에 따라 요일이 밀리는 걸 막는다
export function isHoliday(isoDate) {
  const [year, month, day] = String(isoDate).split("-").map(Number);
  if (!year || !month || !day) return false;
  if (FIXED_HOLIDAYS.has(String(isoDate).slice(DATE_SLICE))) return true;
  return WEEKEND_DAYS.has(new Date(year, month - 1, day).getDay());
}

function classOf(model) {
  return MODEL_CLASS[model] || FALLBACK_CLASS;
}

function nameOf(categories, id) {
  if (!id || !Array.isArray(categories)) return null;
  return categories.find((category) => category.id === id)?.name || null;
}

function clockText(epochMs) {
  return new Date(epochMs).toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" });
}

function stampText(epochMs) {
  return epochMs ? `${clockText(epochMs)} 기준` : "한도 정보 없음";
}

function resetStamp(epochSeconds) {
  return new Date(epochSeconds * MS_PER_SECOND).toLocaleString("ko-KR", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function remainingText(epochSeconds) {
  return durationText(Math.max(0, epochSeconds - Math.floor(Date.now() / MS_PER_SECOND)));
}

// 초 → "45초" / "12분" / "3시간 20분" / "1일 20시간". 남은 시간과 stale 나이가 같은 규칙을 쓴다
function durationText(seconds) {
  if (seconds === null || seconds === undefined) return UNKNOWN;
  if (seconds < SECONDS_PER_MINUTE) return `${seconds}초`;
  const minutes = Math.floor(seconds / SECONDS_PER_MINUTE);
  if (minutes < MINUTES_PER_HOUR) return `${minutes}분`;
  const hours = Math.floor(minutes / MINUTES_PER_HOUR);
  if (hours < HOURS_PER_DAY) return `${hours}시간 ${minutes % MINUTES_PER_HOUR}분`;
  return `${Math.floor(hours / HOURS_PER_DAY)}일 ${hours % HOURS_PER_DAY}시간`;
}

// ISO8601 UTC → "16s" / "5m" / "3h" / "2d". 세션 카드의 경과 시간 전용 표기라
// durationText(한국어 "3시간 20분")와 규칙이 다르다. 값이 없거나 못 읽으면 null
function agoText(isoText) {
  if (!isoText) return null;
  const stamp = Date.parse(isoText);
  if (Number.isNaN(stamp)) return null;
  const seconds = Math.max(0, Math.floor((Date.now() - stamp) / MS_PER_SECOND));
  if (seconds < SECONDS_PER_MINUTE) return `${seconds}s`;
  const minutes = Math.floor(seconds / SECONDS_PER_MINUTE);
  if (minutes < MINUTES_PER_HOUR) return `${minutes}m`;
  const hours = Math.floor(minutes / MINUTES_PER_HOUR);
  if (hours < HOURS_PER_DAY) return `${hours}h`;
  return `${Math.floor(hours / HOURS_PER_DAY)}d`;
}

function startPolling() {
  if (timer) clearInterval(timer);
  // 가려져 있으면 건너뛴다. 폴링 실패는 삼킨다 — 1분마다 배너를 덮어쓸 이유가 없다
  timer = setInterval(() => {
    if (document.getElementById("tab-usage")?.hidden !== false) return;
    load().then(paint).catch(() => {});
  }, POLL_INTERVAL_MS);
}
