// 사용량 탭. 왼쪽은 한도·토큰 모니터링, 오른쪽 레일은 지금 무엇을 하고 있는지.
// 모든 숫자는 실측이며, 못 가져온 창은 값을 만들지 않고 "미수집"으로 남긴다.
import * as api from "./api.js";
import {
  PCT_TICKS,
  compact,
  donutChart,
  percentLineChart,
  stackedColumnChart,
  thousands,
} from "./chart.js";
import { language, t } from "./i18n.js";
import { openDetail } from "./sessions.js";

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
const UNCLASSIFIED_LABEL = t("session.unclassified");
const UNKNOWN = t("common.unknown");
// 날짜·시각 표기도 고른 언어를 따른다. ko 는 지역까지 붙여 기존 표기를 그대로 둔다
const LOCALE = language() === "ko" ? "ko-KR" : language();

// 사이드카(rate-limits.json)에는 five_hour·seven_day 만 남는다.
// Fable 세션 창은 그 파일에 없어 자리만 두고 미수집으로 표시한다.
const LIMIT_CARDS = [
  { key: "five_hour", label: t("usage.cardFiveHour"), sample: "five_hour_pct" },
  { key: "seven_day", label: t("usage.cardSevenDay"), sample: "seven_day_pct" },
  { key: "fable_session", label: t("usage.cardFable"), sample: null },
];
// 5시간 창만 시각 축에 올린다. 주간 창은 7일 내내 쌓이기만 해서 24시간 구간에서는
// 거의 평평한 선이 되고, 5시간 톱니와 축을 나눠 쓰면 둘 다 읽히지 않는다 —
// 주간은 주차끼리 견주는 게 맞아 renderWeekly 로 뺐다
const PCT_SERIES = [
  { key: "five_hour_pct", name: t("usage.seriesFiveHour"), tipName: t("usage.seriesFiveHourTip"), cls: "u-c-five" },
];
// 주차 막대. 시리즈 하나뿐이라 쌓이지 않고 그냥 막대가 된다
const WEEK_PCT_SERIES = [{ key: "peak_pct", name: t("usage.seriesPeak"), cls: "u-c-seven" }];
// 닫힌 주차를 최근부터 부르는 이름. 표에서 밀려나면 "N주 전"
const WEEK_NAMES = [null, t("usage.weekLast")];
const WEEK_CURRENT = t("usage.weekCurrent");
const PLAN_UNKNOWN = t("usage.planUnknown");
// Fable 이 빠져 있어 폴백(=Haiku)으로 떨어지면서 두 모델이 같은 회색이 되던 것을 갈랐다.
// 폴백은 "기타" 몫으로 남긴다 — 이름을 모르는 모델까지 색을 배정할 수는 없다
const MODEL_CLASS = {
  Opus: "u-c-opus",
  Sonnet: "u-c-sonnet",
  Haiku: "u-c-haiku",
  Fable: "u-c-fable",
};
const FALLBACK_CLASS = "u-c-other";
const BREAKDOWN_ROWS = [
  ["output_tokens", t("usage.output")],
  ["cache_write_tokens", t("usage.cacheWrite")],
  ["cache_read_tokens", t("usage.cacheRead")],
];
const LEVEL_CLASS = { warn: "u-warn", critical: "u-crit" };
// 휴일 판정용. 음력 명절(설·추석)·부처님오신날·대체공휴일은 이 표로 잡히지 않는다 —
// 달력 자료를 붙이지 않는 한 계산할 수 없어 양력 고정일과 주말만 본다
const FIXED_HOLIDAYS = new Set([
  "01-01", "03-01", "05-05", "06-06", "08-15", "10-03", "10-09", "12-25",
]);
const WEEKEND_DAYS = new Set([0, 6]);
const STATUS_LABEL = { todo: t("usage.statusTodo"), doing: t("usage.statusDoing"), done: t("common.done") };

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
  renderWeekly(usage.weekly);
  renderWeeklyTokens(usage.weekly);
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
    const age = durationText(usage.stale_seconds);
    top.appendChild(tag("span", "u-stale", t("usage.stale", { age })));
  }
  // 경로만 적어두면 "왜 비었는지" 를 모른다. 한도 %는 상태줄 페이로드로만 오므로,
  // 채우는 방법을 같이 알려준다 (README "상태줄" 참고)
  if (!usage.windows.length) {
    top.appendChild(
      tag("p", "u-caption", t("usage.limitUnavailable", { source: usage.limit_source }))
    );
    top.appendChild(tag("p", "u-caption", t("usage.limitHowTo")));
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
  // 제목은 서버가 준 문구(한국어 고정)가 아니라 화면 사전에서 가져온다 — 창을 가르는
  // 것은 key 이고, 서버 title 을 쓰면 이 카드만 언어를 안 따라간다
  head.append(tag("span", "u-lim-label", spec.label), arrowMark());
  card.appendChild(head);

  // 값 줄 · 게이지 · 하단 줄 세 단으로 고정한다. 수집 안 된 창도 같은 세 단을
  // 그리고 안을 비워야 카드 세 장의 각 요소가 같은 높이에 앉는다
  if (!found) {
    const note = tag("p", "u-reset");
    note.append(
      tag("span", "u-flag", t("usage.notCollected")),
      document.createTextNode(` ${t("usage.windowMissing")}`)
    );
    card.append(
      valueRow(tag("p", "u-lim-value u-lim-empty", "―"), null),
      trackBar(0, null),
      note
    );
    return card;
  }

  const pct = found.used_percentage;
  const value = tag("p", "u-lim-value", String(Math.round(pct)));
  value.appendChild(tag("small", null, "%"));
  card.append(
    valueRow(value, deltaOf(usage.pct_samples, spec.sample)),
    trackBar(pct, LEVEL_CLASS[found.level]),
    resetLine(found.resets_at)
  );
  return card;
}

// 게이지. 수집 전이면 빈 트랙만 남겨 자리를 지킨다
function trackBar(pct, levelClass) {
  const track = tag("div", "u-track");
  const fill = tag("i", levelClass || null);
  fill.style.width = `${Math.min(pct, PERCENT_FULL)}%`;
  track.appendChild(fill);
  return track;
}

function deltaOf(samples, field) {
  if (!field || !samples || samples.length < MIN_TREND_POINTS) return null;
  const last = samples[samples.length - 1][field];
  const prev = samples[samples.length - 2][field];
  if (typeof last !== "number" || typeof prev !== "number") return null;
  const diff = Math.round(last - prev);
  // 주간 %는 5분 사이에 1% 넘게 움직이는 일이 드물다. 그때 자리를 비우면 값이 안 잡힌
  // 건지 안 변한 건지 구분이 안 되므로, 변화 없음은 회색 – 로 남긴다
  if (diff === 0) return { dir: "flat", text: "–" };
  return { dir: diff > 0 ? "up" : "down", text: `${Math.abs(diff)}%` };
}

// 값과 델타를 한 줄에 놓는다. 델타가 없어도 자리를 남겨 카드 높이를 맞춘다
function valueRow(value, delta) {
  const row = tag("div", "u-lim-row");
  row.append(value, deltaMark(delta));
  return row;
}

// 값 오른쪽에 붙는 증감 표시. 방향 기호와 수치만 두고 설명 문구는 넣지 않는다
function deltaMark(delta) {
  const mark = tag("span", delta ? `u-delta ${delta.dir}` : "u-delta u-delta-empty");
  // 빈 span 은 베이스라인이 없어 옆의 값을 1px 밀어올린다. 폭 없는 문자로 지표를 맞춤
  if (!delta) {
    mark.textContent = "​";
    return mark;
  }
  if (delta.dir !== "flat") {
    mark.appendChild(document.createTextNode(delta.dir === "up" ? "▲" : "▼"));
  }
  mark.appendChild(tag("b", null, delta.text));
  return mark;
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
    line.textContent = t("usage.resetUnknown");
    return line;
  }
  line.append(
    document.createTextNode(`${t("usage.resetIn")} `),
    tag("b", null, remainingText(epochSeconds)),
    document.createTextNode(` · ${resetStamp(epochSeconds)}`)
  );
  return line;
}

// ── 3행: 일별 토큰 ─────────────────────────────────────────────────────────
function renderDaily(tokens) {
  const box = slot("u-daily", "u-card");
  if (!box) return;
  const models = activeModels(tokens);
  const days = tokens.days || [];
  if (!tokens.available || !models.length) {
    box.append(headRow(t("usage.dailyTokens")), emptyState(noTokenText(tokens)));
    return;
  }
  box.appendChild(
    headRow(t("usage.dailyTokens"), t("usage.lastDays", { days: days.length }), [
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
    detail: t("usage.listPriceValue", { cost: day.cost_usd }),
  }));
  box.appendChild(stackedColumnChart({ points, series, label: t("usage.dailyTokens") }));

  const details = document.createElement("details");
  details.appendChild(tag("summary", null, t("usage.asTable")));
  details.appendChild(dayTable(tokens, models));
  box.appendChild(details);
}

function dayTable(tokens, models) {
  const table = document.createElement("table");
  table.appendChild(tableRow("th", [t("usage.date"), t("common.total"), ...models, t("usage.listPrice")]));
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

// ── 3행: 오늘 토큰 ─────────────────────────────────────────────────────────
function renderToday(tokens) {
  const box = slot("u-today", "u-card");
  if (!box) return;
  const days = tokens.days || [];
  const today = days[days.length - 1];
  box.appendChild(headRow(t("usage.todayTokens"), today ? today.date.slice(DATE_SLICE) : ""));
  if (!tokens.available || !today) {
    box.appendChild(emptyState(noTokenText(tokens)));
    return;
  }

  box.appendChild(bigNumber(today.total));
  const change = dayOverDay(days);
  if (change) box.appendChild(deltaLine(change, t("usage.vsYesterday")));

  const rows = tag("div", "u-rows");
  BREAKDOWN_ROWS.forEach(([field, label]) => {
    rows.appendChild(labelledRow(label, compact(today.breakdown?.[field] || 0)));
  });
  rows.appendChild(labelledRow(t("usage.listPrice"), `$${today.cost_usd}`));
  box.append(rows, tag("p", "u-caption", t("usage.listPriceNote")));
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

// ── 2행: 5시간 세션 추이 ──────────────────────────────────────────────────
function renderTrend(usage) {
  const box = slot("u-trend", "u-card");
  if (!box) return;
  const samples = usage.pct_samples || [];
  if (samples.length < MIN_TREND_POINTS) {
    // 한도 %는 어디에도 이력이 남지 않아 이 대시보드가 모으기 시작한 시점부터 그려진다
    box.append(
      headRow(t("usage.trendTitle")),
      emptyState(t("usage.trendEmpty"))
    );
    return;
  }
  box.appendChild(
    headRow(t("usage.trendTitle"), t("usage.lastHours", { hours: TREND_HOURS }), [
      legendRow(PCT_SERIES),
    ])
  );
  const points = samples.map((sample) => ({
    label: clockText(sample.bucket_ts),
    values: { five_hour_pct: sample.five_hour_pct, seven_day_pct: sample.seven_day_pct },
  }));
  box.append(
    percentLineChart({ points, series: PCT_SERIES, label: t("usage.trendChartLabel") }),
    tag(
      "p",
      "u-caption",
      t("usage.trendCaption", { count: samples.length })
    )
  );
}

// ── 4행: 주간 한도 주차 비교 ───────────────────────────────────────────────
// 주간 창은 7일 내내 누적만 하다 초기화되므로 시각 축에서는 읽을 게 없다. 창 하나를
// 한 칸으로 접어 주차끼리 견준다 — 값은 초기화 직전에 도달한 최고 사용률이다
function renderWeekly(weekly) {
  const box = slot("u-weekly", "u-card");
  if (!box) return;
  const tracks = weekly?.tracks || [];
  if (!tracks.length) {
    box.append(
      headRow(t("usage.weeklyTitle")),
      emptyState(t("usage.weeklyEmpty"))
    );
    return;
  }
  box.appendChild(
    headRow(t("usage.weeklyTitle"), t("usage.weeklySub"), [legendRow(WEEK_PCT_SERIES)])
  );
  tracks.forEach((track) => box.appendChild(weekTrack(track)));
  // 낮은 주차가 "적게 썼다" 로 읽히면 안 된다. 안 보고 있었을 수도 있다는 걸 밝힌다
  if (tracks.some((track) => track.weeks.some((week) => week.peak_is_floor))) {
    box.appendChild(tag("p", "u-caption", t("usage.floorNote")));
  }
  if (weekly.multi_account) {
    // 계정 이름은 어디에도 없다. 초기화 시각이 유일한 식별자라 그걸로 가른다
    box.appendChild(
      tag("p", "u-caption", t("usage.multiAccountNote"))
    );
  }
  const details = document.createElement("details");
  details.appendChild(tag("summary", null, t("usage.asTable")));
  details.appendChild(weekTable(tracks));
  box.appendChild(details);
}

function weekTrack(track) {
  const wrap = tag("div", "u-week-track");
  const weeks = track.weeks;
  const labels = weekLabels(weeks);
  const title = t("usage.trackTitle", { at: trackLabel(weeks[weeks.length - 1].reset_at) });
  // 플랜은 지금 로그인한 계정 것만 설정 파일에 있다. 아직 그 계정으로 들어온 적이 없는
  // 트랙은 알 수 없으므로, 빈 자리로 두지 않고 모른다는 사실을 적는다
  const head = tag("div", "u-week-head");
  head.append(
    tag("h3", "u-week-title", title),
    tag("span", track.plan ? "u-flag u-week-plan" : "u-flag", track.plan || PLAN_UNKNOWN)
  );
  wrap.appendChild(head);
  wrap.appendChild(
    stackedColumnChart({
      points: weeks.map((week, index) => ({
        label: labels[index],
        values: { peak_pct: week.peak_pct },
        detail: weekFoot(week),
      })),
      series: WEEK_PCT_SERIES,
      ticks: PCT_TICKS,
      format: (value) => `${Math.round(value)}%`,
      label: t("usage.weekChartLabel", { title }),
    })
  );
  return wrap;
}

// 창 열이 첫 칸이다. 계정이 둘이면 "이번 주" 행이 둘 나오는데, 그 열이 없으면
// 어느 계정의 주차인지 표에서 가릴 수 없다
function weekTable(tracks) {
  const table = document.createElement("table");
  table.appendChild(
    tableRow("th", [t("usage.colWindow"), t("usage.colWeek"), t("usage.colSpan"), t("usage.colPeak"), t("usage.colSamples")])
  );
  tracks.forEach((track) => {
    const labels = weekLabels(track.weeks);
    const window = trackLabel(track.weeks[track.weeks.length - 1].reset_at);
    track.weeks
      .map((week, index) => ({ week, label: labels[index] }))
      .reverse()
      .forEach(({ week, label }) => {
        table.appendChild(
          tableRow("td", [
            window,
            label,
            weekSpan(week),
            peakText(week),
            sampleText(week),
          ])
        );
      });
  });
  const box = tag("div", "u-table-box");
  box.appendChild(table);
  return box;
}

// ── 4행: 주차별 토큰 ───────────────────────────────────────────────────────
// %는 소급되지 않지만 토큰은 cost 로그에 남아 있어, 한도 %를 모으기 전 주차도 값이 나온다
function renderWeeklyTokens(weekly) {
  const box = slot("u-weekly-tokens", "u-card");
  if (!box) return;
  const weeks = weekly?.token_weeks || [];
  if (!weeks.length) {
    box.append(
      headRow(t("usage.weeklyTokens")),
      emptyState(
        weekly?.token_available
          ? t("usage.weeklyTokensEmpty")
          : t("usage.noTokenSource", { source: weekly?.token_source || "" })
      )
    );
    return;
  }
  // 1칸 카드라 막대를 세우면 620 폭 viewBox 가 절반으로 줄어 축 라벨이 읽히지 않는다.
  // 이 자리의 문법은 오늘 토큰과 같은 큰 수 + 행 목록이다
  const labels = weekLabels(weeks);
  const rows = weeks.map((week, index) => ({ week, label: labels[index] }));
  const latest = rows[rows.length - 1];
  box.appendChild(headRow(t("usage.weeklyTokens"), latest.label));
  box.appendChild(bigNumber(latest.week.tokens));
  const change = weekOverWeek(weeks);
  if (change) box.appendChild(deltaLine(change, t("usage.vsLastWeek")));

  const list = tag("div", "u-rows");
  rows
    .slice(0, -1)
    .reverse()
    .forEach(({ week, label }) => list.appendChild(labelledRow(label, compact(week.tokens))));
  list.appendChild(labelledRow(t("usage.listPrice"), `$${latest.week.cost_usd}`));
  box.appendChild(list);
  box.appendChild(
    tag(
      "p",
      "u-caption",
      weekly.token_shared
        ? t("usage.weekBoundaryShared")
        : t("usage.weekBoundaryReset")
    )
  );
}

// 진행 중 주차와 바로 앞 주차의 비율. 일별과 같은 규칙 — 0 이면 줄을 빼고 분모가 0 이면 만들지 않는다
function weekOverWeek(weeks) {
  if (weeks.length < MIN_TREND_POINTS) return null;
  const current = weeks[weeks.length - 1].tokens;
  const previous = weeks[weeks.length - 2].tokens;
  if (!previous) return null;
  const ratio = Math.round(((current - previous) / previous) * PERCENT_FULL);
  if (ratio === 0) return null;
  return { dir: ratio > 0 ? "up" : "down", text: `${Math.abs(ratio)}%` };
}

// 진행 중인 주차는 "이번 주", 닫힌 주차는 최근에서 거슬러 "지난주 / 2주 전"
export function weekLabels(weeks) {
  let back = 0;
  return weeks
    .slice()
    .reverse()
    .map((week) =>
      week.in_progress ? WEEK_CURRENT : WEEK_NAMES[++back] || t("usage.weeksAgo", { count: back })
    )
    .reverse();
}

// 툴팁 꼬리말. 진행 중 주차는 값이 아직 자라는 중이라 그 사실을 붙인다
function weekFoot(week) {
  const progress = week.in_progress ? ` · ${t("usage.inProgress")}` : "";
  const blind = week.peak_is_floor ? ` · ${t("usage.notSeenFor", { span: blindText(week) })}` : "";
  return `${weekSpan(week)}${progress}${blind}`;
}

// 표본은 상태줄이 그려질 때만 쌓인다. 창이 닫히기 전 마지막 관측 이후를 못 봤으면
// 그 사이 얼마가 더 올랐는지 알 수 없으므로, 최고치를 정확한 값처럼 보이면 안 된다
function blindText(week) {
  const hours = Math.round(week.blind_seconds / 3600);
  return hours >= 24
    ? t("usage.days", { days: Math.round(hours / 24) })
    : t("usage.hours", { hours });
}

function peakText(week) {
  return `${week.peak_is_floor ? "≥" : ""}${Math.round(week.peak_pct)}%`;
}

function sampleText(week) {
  const count = t("usage.sampleCount", { count: week.samples });
  return week.peak_is_floor ? `${count} · ${t("usage.gapOf", { span: blindText(week) })}` : count;
}

// 주 경계는 자정이 아니라 초기화 시각이다. 날짜만 적으면 하루가 겹쳐 보인다
function weekSpan(week) {
  return `${resetStamp(week.starts_at)} → ${resetStamp(week.reset_at)}`;
}

// 계정 식별자 겸 주 경계. "화 04:00"
// ko-KR 은 요일만 뽑으면 "(화)" 로 괄호를 붙인다 — 뒤에 시각이 이어지므로 괄호를 뗀다
function trackLabel(epochSeconds) {
  return new Date(epochSeconds * MS_PER_SECOND)
    .toLocaleString(LOCALE, {
      weekday: "short",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    })
    .replace(/[()]/g, "")
    .trim();
}

// ── 2행: 모델 구성 ─────────────────────────────────────────────────────────
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
    box.append(headRow(t("usage.modelMix")), emptyState(noTokenText(tokens)));
    return;
  }
  box.appendChild(headRow(t("usage.modelMix"), t("usage.days", { days: days.length })));

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
      centerLabel: t("usage.daysTotal", { days: days.length }),
    }),
    legend
  );
  box.appendChild(wrap);
}

// ── 우측 레일: 다음에 할일 ─────────────────────────────────────────────────
function renderNext(next, categories) {
  const box = slot("u-next");
  if (!box) return;
  box.appendChild(railHead(t("usage.nextTodo"), boardLink()));
  if (!next?.todo) {
    box.appendChild(railCard(tag("p", "u-caption", t("usage.noNextTodo"))));
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
  button.textContent = t("usage.toBoard");
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

  box.appendChild(railHead(t("usage.runningSessions"), folded ? expandToggle(payload) : null));
  if (!all.length) {
    box.appendChild(railCard(tag("p", "u-caption", t("usage.noRunningSessions"))));
    return;
  }

  shown.forEach((session) => {
    const item = tag("div", `u-rail-card u-sess-item ${session.state}`);
    item.appendChild(tag("div", "u-sess-mark"));
    const body = tag("div", "u-sess-body");
    const scope = tag("div", "u-sess-scope", session.workspace_name || UNCLASSIFIED_LABEL);
    // 카테고리·경과시간은 없어도 빈 칸으로 둔다. 조건부로 빼면 줄마다 열이 어긋난다
    scope.append(
      tag("span", "u-sess-cat", session.category_name || ""),
      tag("span", "u-sess-ago", agoText(session.last_seen_at) || "")
    );
    body.append(scope, tag("p", "u-sess-prompt", session.last_prompt || t("usage.noPrompt")));
    item.appendChild(body);
    item.addEventListener("click", () => openDetail({ session }));
    box.appendChild(item);
  });
  if (folded && !sessionsExpanded) {
    box.appendChild(tag("p", "u-caption", t("usage.moreSessions", { count: folded })));
  }
  if (payload.unclassified_count) {
    box.appendChild(
      tag("p", "u-sess-warn", t("session.unclassifiedCount", { count: payload.unclassified_count }))
    );
  }
}

// 접힌 세션을 그 자리에서 펼친다. 같은 payload 로 다시 그리므로 재조회는 없다
function expandToggle(payload) {
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = sessionsExpanded ? t("usage.collapse") : t("usage.expand");
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
  return tokens.available
    ? t("usage.noTokens")
    : t("usage.noTokenSource", { source: tokens.source });
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
  return new Date(epochMs).toLocaleTimeString(LOCALE, { hour: "2-digit", minute: "2-digit" });
}

function stampText(epochMs) {
  return epochMs ? t("usage.asOf", { at: clockText(epochMs) }) : t("usage.noLimitInfo");
}

function resetStamp(epochSeconds) {
  return new Date(epochSeconds * MS_PER_SECOND).toLocaleString(LOCALE, {
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
  if (seconds < SECONDS_PER_MINUTE) return t("duration.seconds", { count: seconds });
  const minutes = Math.floor(seconds / SECONDS_PER_MINUTE);
  if (minutes < MINUTES_PER_HOUR) return t("duration.minutes", { count: minutes });
  const hours = Math.floor(minutes / MINUTES_PER_HOUR);
  if (hours < HOURS_PER_DAY) {
    return t("duration.hoursMinutes", { hours, minutes: minutes % MINUTES_PER_HOUR });
  }
  return t("duration.daysHours", {
    days: Math.floor(hours / HOURS_PER_DAY),
    hours: hours % HOURS_PER_DAY,
  });
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
