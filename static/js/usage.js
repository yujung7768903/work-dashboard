// 사용량 탭. /usage 와 같은 한도 창을 미터로, 추이를 차트로 그린다
import * as api from "./api.js";
import { columnChart, compact, percentLineChart, thousands } from "./chart.js";

const POLL_INTERVAL_MS = 60_000; // 5시간 창은 전력으로 써도 분당 0.3%대로 움직인다. 1분이면 충분
const PCT_SERIES = [
  { key: "five_hour_pct", name: "5시간", cls: "series-1" },
  { key: "seven_day_pct", name: "주간", cls: "series-2" },
];
const BREAKDOWN_LABELS = [
  ["output_tokens", "출력"],
  ["cache_write_tokens", "캐시 쓰기"],
  ["cache_read_tokens", "캐시 읽기"],
  ["input_tokens", "입력"],
];
const LEVEL_MARKS = { ok: "●", warn: "▲", critical: "■" };
const MIN_TREND_POINTS = 2;
const SECONDS_PER_MINUTE = 60;
const MINUTES_PER_HOUR = 60;
const PERCENT_FULL = 100;
const MS_PER_SECOND = 1000;
const DATE_SLICE = 5; // "2026-07-30" → "07-30"
const UNKNOWN = "알 수 없음";

let timer = null;

export async function renderUsage() {
  paint(await api.getUsage());
  startPolling();
}

function paint(payload) {
  renderHeader(payload);
  renderMeters(payload);
  renderPctTrend(payload);
  renderTokenTrend(payload.tokens);
  renderTable(payload.tokens);
}

function renderHeader(payload) {
  document.getElementById("usage-plan").textContent = `플랜 ${payload.plan || UNKNOWN}`;
  document.getElementById("usage-updated").textContent = payload.snapshot_ts
    ? `${new Date(payload.snapshot_ts).toLocaleTimeString("ko-KR")} 기준`
    : "한도 정보 없음";

  const badge = document.getElementById("usage-stale");
  badge.hidden = !payload.stale || !payload.windows.length;
  badge.textContent = `⚠ ${ageText(payload.stale_seconds)} 전 값`;

  document.getElementById("usage-note").textContent = payload.windows.length
    ? `statusline 이 그려질 때만 갱신됨 · 사이드카에 없는 창: ${payload.missing_windows.join(", ")}`
    : `한도 정보를 읽을 수 없음 — ${payload.limit_source}`;
}

function renderMeters(payload) {
  // 지금 중요한 단 하나의 숫자는 5시간 창이다. 히어로는 한 화면에 하나만 둔다
  const [first] = payload.windows;
  const hero = document.getElementById("usage-hero");
  hero.textContent = first ? `${first.used_percentage}%` : "―";
  hero.className = first ? `usage-hero ${first.level}` : "usage-hero";
  document.getElementById("usage-hero-label").textContent = first ? first.title : "한도 정보 없음";

  const box = document.getElementById("usage-meters");
  box.innerHTML = "";
  payload.windows.forEach((window) => box.appendChild(meterRow(window)));
}

function meterRow(window) {
  const row = document.createElement("div");
  row.className = "meter-row";

  const head = document.createElement("div");
  head.className = "meter-head";
  const title = document.createElement("span");
  title.textContent = window.title;
  const value = document.createElement("span");
  value.className = "meter-value";
  // 아이콘과 숫자를 같이 둔다. 심각도를 색만으로 전달하지 않는다
  value.textContent = `${LEVEL_MARKS[window.level] || LEVEL_MARKS.ok} ${window.used_percentage}%`;
  head.append(title, value);

  const track = document.createElement("div");
  track.className = "meter-track";
  const fill = document.createElement("div");
  fill.className = `meter-fill ${window.level}`;
  fill.style.width = `${Math.min(window.used_percentage, PERCENT_FULL)}%`;
  track.appendChild(fill);

  const reset = document.createElement("div");
  reset.className = "meter-reset";
  reset.textContent = resetText(window.resets_at);

  row.append(head, track, reset);
  return row;
}

function renderPctTrend(payload) {
  const box = document.getElementById("usage-pct-chart");
  box.innerHTML = "";
  const points = payload.pct_samples.map((sample) => ({
    label: clockText(sample.bucket_ts),
    values: { five_hour_pct: sample.five_hour_pct, seven_day_pct: sample.seven_day_pct },
  }));
  if (points.length < MIN_TREND_POINTS) {
    // %의 이력은 어디에도 남지 않아서 이 대시보드가 모으기 시작한 시점부터 그려진다
    box.appendChild(
      emptyState("한도 %는 이력이 남지 않아 지금부터 모읍니다. 몇 분 뒤 추이가 그려집니다.")
    );
    return;
  }
  box.append(legend(PCT_SERIES), percentLineChart({ points, series: PCT_SERIES }));
}

function renderTokenTrend(tokens) {
  const box = document.getElementById("usage-token-chart");
  box.innerHTML = "";
  if (!tokens.available) {
    box.appendChild(emptyState(`토큰 기록이 없습니다 — ${tokens.source}`));
    return;
  }
  const points = tokens.days.map((day) => ({
    label: day.date.slice(DATE_SLICE),
    value: day.total,
    // 요약줄은 압축 표기라, 상세에는 정확한 수를 둔다
    detail: `${thousands(day.total)} · 정가환산 $${day.cost_usd}`,
  }));
  box.appendChild(columnChart({ points, unit: " 토큰" }));
}

function renderTable(tokens) {
  const box = document.getElementById("usage-table");
  box.innerHTML = "";
  if (!tokens.available) return;
  const table = document.createElement("table");
  table.className = "usage-table";
  table.appendChild(
    tableRow("th", [
      "날짜",
      "합계",
      ...tokens.models,
      ...BREAKDOWN_LABELS.map(([, label]) => label),
      "정가환산",
    ])
  );
  tokens.days.forEach((day) => {
    table.appendChild(
      tableRow("td", [
        day.date,
        thousands(day.total),
        ...tokens.models.map((model) => compact(day.by_model[model] || 0)),
        ...BREAKDOWN_LABELS.map(([field]) => compact(day.breakdown[field] || 0)),
        `$${day.cost_usd}`,
      ])
    );
  });
  box.appendChild(table);
}

function tableRow(cell, values) {
  const line = document.createElement("tr");
  values.forEach((value) => {
    const node = document.createElement(cell);
    node.textContent = value;
    line.appendChild(node);
  });
  return line;
}

function legend(series) {
  const box = document.createElement("div");
  box.className = "chart-legend";
  series.forEach(({ name, cls }) => {
    const item = document.createElement("span");
    const swatch = document.createElement("i");
    swatch.className = `swatch ${cls}`;
    const label = document.createElement("span");
    label.textContent = name;
    item.append(swatch, label);
    box.appendChild(item);
  });
  return box;
}

function emptyState(message) {
  const box = document.createElement("p");
  box.className = "chart-empty";
  box.textContent = message;
  return box;
}

function clockText(epochMs) {
  return new Date(epochMs).toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" });
}

function resetText(epochSeconds) {
  if (!epochSeconds) return "초기화 시각 미확인";
  const target = new Date(epochSeconds * MS_PER_SECOND);
  const remaining = Math.max(0, Math.round((target - Date.now()) / MS_PER_SECOND));
  const stamp = target.toLocaleString("ko-KR", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
  return `${stamp} 초기화 · ${ageText(remaining)} 남음`;
}

function ageText(seconds) {
  if (seconds === null || seconds === undefined) return UNKNOWN;
  if (seconds < SECONDS_PER_MINUTE) return `${seconds}초`;
  const minutes = Math.floor(seconds / SECONDS_PER_MINUTE);
  if (minutes < MINUTES_PER_HOUR) return `${minutes}분`;
  return `${Math.floor(minutes / MINUTES_PER_HOUR)}시간 ${minutes % MINUTES_PER_HOUR}분`;
}

function startPolling() {
  if (timer) clearInterval(timer);
  // 가려져 있으면 건너뛴다. 폴링 실패는 삼킨다 — 1분마다 배너를 덮어쓸 이유가 없다
  timer = setInterval(() => {
    if (document.getElementById("tab-usage").hidden) return;
    api.getUsage().then(paint).catch(() => {});
  }, POLL_INTERVAL_MS);
}
