// SVG 차트. 라이브러리는 넣지 않는다 — 이 대시보드에 필요한 형태가 셋뿐이다.
// 색은 반드시 CSS 클래스로 준다. getComputedStyle 로 변수를 읽어 SVG 속성에 넣으면
// 테마가 바뀔 때 갱신되지 않는다.
const NS = "http://www.w3.org/2000/svg";
const WIDTH = 620;
const BAR = { height: 190, pad: { top: 12, right: 10, bottom: 22, left: 46 } };
// 오른쪽 여백은 끝점 라벨 자리. 두 선이 같은 계열이라 색만으로는 어느 선인지 알 수 없다
const LINE = { height: 178, pad: { top: 12, right: 88, bottom: 22, left: 40 } };
const COLUMN_MAX_WIDTH = 22;
const COLUMN_RADIUS = 4;
const SEGMENT_GAP = 2; // 세그먼트를 가르는 건 선이 아니라 표면색 간격
const MIN_SEGMENT = 0.8;
const LINE_WIDTH = 2;
const MARKER_RADIUS = 4;
const RING_WIDTH = 2;
const END_LABEL_GAP = 10;
const TICK_COUNT = 4;
const TICK_STEPS = [1, 2, 2.5, 5, 10];
const AXIS_FONT = 10;
const MAX_X_LABELS = 7;
const PERCENT_MAX = 100;
const PCT_TICKS = [0, 25, 50, 75, 100];
const DONUT_SIZE = 128;
const DONUT_THICKNESS = 17;
const DONUT_ARC_GAP = 2; // 조각 사이도 선이 아니라 간격으로 가른다
const DONUT_MIN_ARC = 0.5;
const DONUT_TOTAL_FONT = 19;
const COMPACT_UNITS = [
  [1e9, "B"],
  [1e6, "M"],
  [1e3, "K"],
];

export function compact(value) {
  for (const [size, suffix] of COMPACT_UNITS) {
    // 축 눈금에서 "200.0M" 의 .0 은 잡음이라 떼어낸다
    if (Math.abs(value) >= size) {
      return `${(value / size).toFixed(1).replace(/\.0$/, "")}${suffix}`;
    }
  }
  return String(Math.round(value));
}

export function thousands(value) {
  return Math.round(value).toLocaleString("ko-KR");
}

// 모델별 누적 세로 막대. point = { label, values: {키: 수}, detail }
export function stackedColumnChart({ points, series, format = compact }) {
  const plot = plotOf(BAR);
  const totals = points.map((point) => sumOf(point.values, series));
  const ticks = niceTicks(Math.max(...totals, 0));
  const top = ticks[ticks.length - 1] || 1;
  const svg = frame(BAR.height);
  gridAndTicks(svg, plot, ticks, (value) => (value === 0 ? "0" : format(value)));

  const band = plot.width / Math.max(points.length, 1);
  const barWidth = Math.min(COLUMN_MAX_WIDTH, Math.max(band - SEGMENT_GAP * 2, 1));
  points.forEach((point, index) => {
    const x = plot.x + band * index + (band - barWidth) / 2;
    const stack = series.filter(({ key }) => (point.values[key] || 0) > 0);
    let cursor = plot.y + plot.height;
    stack.forEach(({ key, cls }, order) => {
      const raw = (point.values[key] / top) * plot.height;
      const isTop = order === stack.length - 1;
      const gap = isTop ? 0 : SEGMENT_GAP;
      const height = Math.max(raw - gap, MIN_SEGMENT);
      cursor -= raw;
      svg.appendChild(
        el("path", {
          d: isTop
            ? topRounded(x, cursor, barWidth, height)
            : `M${x} ${cursor + gap} h${barWidth} v${height} h${-barWidth} Z`,
          class: `u-bar ${cls}`,
        })
      );
    });
    svg.appendChild(hitArea(plot, plot.x + band * index, band, point.label, point.detail));
  });
  xLabels(svg, points.map((point) => point.label), (i) => plot.x + band * i + band / 2, BAR);
  return figure(svg);
}

// 여러 시리즈 꺾은선. y 를 0–100% 로 고정해 축이 표본마다 흔들리지 않게 한다
export function percentLineChart({ points, series }) {
  const plot = plotOf(LINE);
  const svg = frame(LINE.height);
  gridAndTicks(svg, plot, PCT_TICKS, (value) => `${value}%`);
  const step = points.length > 1 ? plot.width / (points.length - 1) : 0;
  const positionX = (index) =>
    points.length > 1 ? plot.x + step * index : plot.x + plot.width / 2;
  const positionY = (value) =>
    plot.y + plot.height - (Math.min(value, PERCENT_MAX) / PERCENT_MAX) * plot.height;

  series.forEach(({ key, name, cls }) => {
    const drawable = points
      .map((point, index) => ({ index, value: point.values[key] }))
      .filter((item) => typeof item.value === "number");
    if (!drawable.length) return;
    const path = drawable
      .map((item, order) => `${order ? "L" : "M"}${positionX(item.index)} ${positionY(item.value)}`)
      .join(" ");
    const last = drawable[drawable.length - 1];
    svg.appendChild(
      el("path", {
        d: `${path} L${positionX(last.index)} ${positionY(0)} L${positionX(drawable[0].index)} ${positionY(0)} Z`,
        class: `u-area ${cls}`,
      })
    );
    svg.appendChild(
      el("path", {
        d: path,
        "stroke-width": LINE_WIDTH,
        "stroke-linejoin": "round",
        "stroke-linecap": "round",
        class: `u-line ${cls}`,
      })
    );
    // 끝점만 찍는다. 점마다 찍으면 읽히지 않는다. 링은 표면색이라 선과 겹쳐도 살아남는다
    svg.appendChild(
      el("circle", {
        cx: positionX(last.index),
        cy: positionY(last.value),
        r: MARKER_RADIUS,
        "stroke-width": RING_WIDTH,
        class: `u-dot ${cls}`,
      })
    );
    // 끝점 직접 라벨. 글자는 시리즈 색을 입지 않고 잉크 토큰을 쓴다
    svg.appendChild(
      text(`${name} ${Math.round(last.value)}%`, {
        x: positionX(last.index) + END_LABEL_GAP,
        y: positionY(last.value) + 4,
        class: "u-end-label",
        "font-size": null,
      })
    );
  });

  points.forEach((point, index) => {
    const parts = series
      .filter(({ key }) => typeof point.values[key] === "number")
      .map(({ key, name }) => `${name} ${point.values[key].toFixed(1)}%`);
    if (!parts.length) return;
    const band = step || plot.width;
    svg.appendChild(
      hitArea(plot, positionX(index) - band / 2, band, point.label, parts.join(" · "))
    );
  });
  xLabels(svg, points.map((point) => point.label), positionX, LINE);
  return figure(svg);
}

// 도넛. slice = { value, cls }. 가운데에 합계를 둔다
export function donutChart({ slices, centerValue, centerLabel }) {
  const radius = (DONUT_SIZE - DONUT_THICKNESS) / 2;
  const middle = DONUT_SIZE / 2;
  const circumference = 2 * Math.PI * radius;
  const sum = slices.reduce((acc, slice) => acc + slice.value, 0) || 1;
  const svg = el("svg", {
    viewBox: `0 0 ${DONUT_SIZE} ${DONUT_SIZE}`,
    width: DONUT_SIZE,
    height: DONUT_SIZE,
    role: "img",
  });
  let offset = 0;
  slices.forEach((slice) => {
    const length = (slice.value / sum) * circumference;
    const drawn = Math.max(length - DONUT_ARC_GAP, DONUT_MIN_ARC);
    svg.appendChild(
      el("circle", {
        cx: middle,
        cy: middle,
        r: radius,
        "stroke-width": DONUT_THICKNESS,
        "stroke-dasharray": `${drawn} ${circumference - drawn}`,
        "stroke-dashoffset": -offset,
        transform: `rotate(-90 ${middle} ${middle})`,
        class: `u-arc ${slice.cls}`,
      })
    );
    offset += length;
  });
  svg.appendChild(
    text(centerValue, {
      x: middle,
      y: middle - 1,
      "text-anchor": "middle",
      "font-size": DONUT_TOTAL_FONT,
      "font-weight": 700,
      class: "u-donut-total",
    })
  );
  svg.appendChild(
    text(centerLabel, { x: middle, y: middle + 15, "text-anchor": "middle" })
  );
  return svg;
}

function sumOf(values, series) {
  return series.reduce((acc, { key }) => acc + (values[key] || 0), 0);
}

function plotOf({ height, pad }) {
  return {
    x: pad.left,
    y: pad.top,
    width: WIDTH - pad.left - pad.right,
    height: height - pad.top - pad.bottom,
  };
}

function frame(height) {
  return el("svg", { viewBox: `0 0 ${WIDTH} ${height}`, width: "100%", role: "img" });
}

function gridAndTicks(svg, plot, ticks, format) {
  const top = ticks[ticks.length - 1] || 1;
  ticks.forEach((value) => {
    const y = plot.y + plot.height - (value / top) * plot.height;
    svg.appendChild(
      el("line", { x1: plot.x, y1: y, x2: plot.x + plot.width, y2: y, class: "u-grid" })
    );
    svg.appendChild(
      text(format(value), { x: plot.x - 7, y: y + AXIS_FONT / 3, "text-anchor": "end" })
    );
  });
}

function xLabels(svg, labels, centerX, spec) {
  // 겹칠 만큼 촘촘하면 건너뛴다. 겹쳐 찍는 것보다 비는 편이 읽힌다
  const stride = Math.ceil(labels.length / MAX_X_LABELS) || 1;
  labels.forEach((label, index) => {
    if (index % stride) return;
    svg.appendChild(
      text(label, {
        x: centerX(index),
        y: spec.height - spec.pad.bottom + AXIS_FONT + 4,
        "text-anchor": "middle",
      })
    );
  });
}

function hitArea(plot, x, width, title, detail) {
  // 마크보다 넉넉한 투명 사각형이 hover 대상. 얇은 선·작은 점은 그 자체로 집기 어렵다
  const rect = el("rect", {
    x,
    y: plot.y,
    width: Math.max(width, 1),
    height: plot.height,
    fill: "transparent",
  });
  const tip = el("title");
  tip.textContent = detail ? `${title}\n${detail}` : title;
  rect.appendChild(tip);
  return rect;
}

function figure(svg) {
  const box = document.createElement("div");
  box.className = "u-chart";
  box.appendChild(svg);
  return box;
}

function topRounded(x, y, width, height) {
  // 데이터 끝만 둥글고 기준선 쪽은 각지게 — 기준선이 흐려지지 않는다
  const radius = Math.min(COLUMN_RADIUS, width / 2, height);
  return (
    `M${x} ${y + height} L${x} ${y + radius} Q${x} ${y} ${x + radius} ${y}` +
    ` L${x + width - radius} ${y} Q${x + width} ${y} ${x + width} ${y + radius}` +
    ` L${x + width} ${y + height} Z`
  );
}

function niceTicks(max) {
  if (max <= 0) return [0, 1];
  const rough = max / TICK_COUNT;
  const magnitude = 10 ** Math.floor(Math.log10(rough));
  const step =
    TICK_STEPS.map((factor) => factor * magnitude).find((candidate) => candidate >= rough) ??
    magnitude * 10;
  // 맨 위 눈금이 최대값 이상이어야 한다. 아니면 그 값의 마크가 플롯 위로 넘쳐난다
  const ticks = [];
  for (let value = 0; ; value += step) {
    ticks.push(value);
    if (value >= max) return ticks;
  }
}

function text(content, attrs) {
  // 축 글자는 시리즈 색을 입지 않는다. 색은 마크가 갖고 글자는 잉크 토큰을 쓴다
  const node = el("text", { "font-size": AXIS_FONT, class: "u-tick", ...attrs });
  node.textContent = content;
  return node;
}

function el(name, attrs = {}) {
  const node = document.createElementNS(NS, name);
  Object.entries(attrs).forEach(([key, value]) => {
    if (value !== null) node.setAttribute(key, String(value));
  });
  return node;
}
