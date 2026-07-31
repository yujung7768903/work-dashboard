// SVG 차트. 라이브러리는 넣지 않는다 — 이 대시보드에 필요한 형태가 두 개뿐이다.
// viewBox 를 컬럼 폭(약 480px)에 맞춰 축 글자가 축소되지 않게 한다.
const NS = "http://www.w3.org/2000/svg";
const WIDTH = 480;
const HEIGHT = 180;
const PAD = { top: 14, right: 14, bottom: 26, left: 46 };
const PLOT = {
  x: PAD.left,
  y: PAD.top,
  width: WIDTH - PAD.left - PAD.right,
  height: HEIGHT - PAD.top - PAD.bottom,
};
const COLUMN_MAX_WIDTH = 24;
const COLUMN_RADIUS = 4;
const COLUMN_GAP = 2; // 이웃한 기둥을 가르는 건 선이 아니라 표면색 간격
const LINE_WIDTH = 2;
const MARKER_RADIUS = 4;
const RING_WIDTH = 2;
const TICK_COUNT = 4;
const TICK_STEPS = [1, 2, 2.5, 5, 10];
const AXIS_FONT = 10;
const MAX_X_LABELS = 7;
const PERCENT_MAX = 100;
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

// 단일 시리즈 세로 막대. 시리즈가 하나라 범례를 두지 않는다 — 제목이 무엇인지 말한다
export function columnChart({ points, format = compact, unit = "" }) {
  const max = Math.max(...points.map((point) => point.value), 0);
  const ticks = niceTicks(max);
  const top = ticks[ticks.length - 1] || 1;
  const svg = frame();
  gridAndTicks(svg, ticks, format);

  const band = PLOT.width / Math.max(points.length, 1);
  const barWidth = Math.min(COLUMN_MAX_WIDTH, Math.max(band - COLUMN_GAP, 1));
  points.forEach((point, index) => {
    const height = (point.value / top) * PLOT.height;
    const x = PLOT.x + band * index + (band - barWidth) / 2;
    if (height > 0) {
      // 색은 클래스로 준다. 프레젠테이션 속성에는 var() 가 먹지 않는다
      svg.appendChild(
        el("path", {
          d: topRounded(x, PLOT.y + PLOT.height - height, barWidth, height),
          class: "series-1",
        })
      );
    }
    const summary = `${point.label} · ${format(point.value)}${unit}`;
    svg.appendChild(hitArea(PLOT.x + band * index, band, summary, point.detail));
  });
  xLabels(svg, points.map((point) => point.label), band);
  return figure(svg);
}

// 여러 시리즈 꺾은선. y 를 0–100% 로 고정해 축이 날짜마다 흔들리지 않게 한다
export function percentLineChart({ points, series }) {
  const svg = frame();
  gridAndTicks(svg, niceTicks(PERCENT_MAX), (value) => `${value}%`);
  const step = points.length > 1 ? PLOT.width / (points.length - 1) : 0;
  const positionX = (index) =>
    points.length > 1 ? PLOT.x + step * index : PLOT.x + PLOT.width / 2;
  const positionY = (value) =>
    PLOT.y + PLOT.height - (Math.min(value, PERCENT_MAX) / PERCENT_MAX) * PLOT.height;

  series.forEach(({ key, cls }) => {
    const drawable = points
      .map((point, index) => ({ index, value: point.values[key] }))
      .filter((item) => typeof item.value === "number");
    if (!drawable.length) return;
    svg.appendChild(
      el("path", {
        d: drawable
          .map(
            (item, order) =>
              `${order ? "L" : "M"}${positionX(item.index)} ${positionY(item.value)}`
          )
          .join(" "),
        "stroke-width": LINE_WIDTH,
        "stroke-linejoin": "round",
        "stroke-linecap": "round",
        class: `chart-line ${cls}`,
      })
    );
    // 끝점만 찍는다. 점마다 찍으면 읽히지 않는다. 링은 표면색이라 선과 겹쳐도 살아남는다
    const last = drawable[drawable.length - 1];
    svg.appendChild(
      el("circle", {
        cx: positionX(last.index),
        cy: positionY(last.value),
        r: MARKER_RADIUS,
        "stroke-width": RING_WIDTH,
        class: `chart-dot ${cls}`,
      })
    );
  });

  points.forEach((point, index) => {
    const parts = series
      .filter(({ key }) => typeof point.values[key] === "number")
      .map(({ key, name }) => `${name} ${point.values[key].toFixed(1)}%`);
    if (!parts.length) return;
    const band = step || PLOT.width;
    svg.appendChild(hitArea(positionX(index) - band / 2, band, point.label, parts.join(" · ")));
  });
  xLabels(svg, points.map((point) => point.label), step || PLOT.width);
  return figure(svg);
}

function frame() {
  return el("svg", {
    viewBox: `0 0 ${WIDTH} ${HEIGHT}`,
    width: "100%",
    role: "img",
    class: "chart-svg",
  });
}

function gridAndTicks(svg, ticks, format) {
  const top = ticks[ticks.length - 1] || 1;
  ticks.forEach((value) => {
    const y = PLOT.y + PLOT.height - (value / top) * PLOT.height;
    svg.appendChild(
      el("line", {
        x1: PLOT.x,
        y1: y,
        x2: PLOT.x + PLOT.width,
        y2: y,
        class: value === 0 ? "chart-baseline" : "chart-grid",
      })
    );
    svg.appendChild(
      text(format(value), {
        x: PLOT.x - 6,
        y: y + AXIS_FONT / 3,
        "text-anchor": "end",
      })
    );
  });
}

function xLabels(svg, labels, band) {
  // 겹칠 만큼 촘촘하면 건너뛴다. 겹쳐 찍는 것보다 비는 편이 읽힌다
  const stride = Math.ceil(labels.length / MAX_X_LABELS);
  labels.forEach((label, index) => {
    if (index % stride) return;
    svg.appendChild(
      text(label, {
        x: PLOT.x + band * index + band / 2,
        y: HEIGHT - PAD.bottom + AXIS_FONT + 4,
        "text-anchor": "middle",
      })
    );
  });
}

function hitArea(x, width, title, detail) {
  // 마크보다 넉넉한 투명 사각형이 hover 대상. 얇은 선·작은 점은 그 자체로 집기 어렵다
  const rect = el("rect", {
    x,
    y: PLOT.y,
    width: Math.max(width, 1),
    height: PLOT.height,
    fill: "transparent",
  });
  const tip = el("title");
  tip.textContent = detail ? `${title}\n${detail}` : title;
  rect.appendChild(tip);
  return rect;
}

function figure(svg) {
  const box = document.createElement("div");
  box.className = "chart";
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
  const node = el("text", { "font-size": AXIS_FONT, class: "chart-tick", ...attrs });
  node.textContent = content;
  return node;
}

function el(name, attrs = {}) {
  const node = document.createElementNS(NS, name);
  Object.entries(attrs).forEach(([key, value]) => node.setAttribute(key, String(value)));
  return node;
}
