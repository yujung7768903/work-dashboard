// SVG 차트. 라이브러리는 넣지 않는다 — 이 대시보드에 필요한 형태가 셋뿐이다.
// 색은 반드시 CSS 클래스로 준다. getComputedStyle 로 변수를 읽어 SVG 속성에 넣으면
// 테마가 바뀔 때 갱신되지 않는다.
import { t } from "./i18n.js";

const NS = "http://www.w3.org/2000/svg";
const WIDTH = 620;
// 플롯 여백도 CSS 와 같은 4px 격자 위에 둔다. left 는 축 라벨 폭이 정하는 값
const BAR = { height: 192, pad: { top: 12, right: 8, bottom: 24, left: 48 } };
// 오른쪽 여백은 끝점 라벨 자리. 두 선이 같은 계열이라 색만으로는 어느 선인지 알 수 없다
const LINE = { height: 176, pad: { top: 12, right: 88, bottom: 24, left: 40 } };
const COLUMN_MAX_WIDTH = 22;
const COLUMN_RADIUS = 4;
const SEGMENT_GAP = 2; // 세그먼트를 가르는 건 선이 아니라 표면색 간격
const MIN_SEGMENT = 0.8;
const LINE_WIDTH = 2;
const MARKER_RADIUS = 4;
const RING_WIDTH = 2;
const END_LABEL_GAP = 8;
const TICK_COUNT = 4;
const TICK_STEPS = [1, 2, 2.5, 5, 10];
const AXIS_FONT = 9; // css --fs-micro. 좌표 계산에 쓰이므로 CSS 가 아니라 여기서 정한다
// 라벨 폭 어림값. 숫자·하이픈만 오는 축이라 자당 0.6em 이면 실제보다 조금 넉넉하다
const LABEL_CHAR_EM = 0.6;
const LABEL_MIN_GAP = 6;
const CJK_START = 0x2e80; // 이보다 크면 전각으로 본다 (한글·한자·전각 기호)
const END_LABEL_MIN_GAP = 12; // 끝점 라벨 두 줄이 겹치지 않는 최소 간격
const CURSOR_DASH = "3 3";
const TIP_GAP = 12; // 기준선과 툴팁 사이. 0 이면 툴팁이 선을 덮어 어디를 짚었는지 흐려진다
const TOTAL_LABEL = t("common.total");
const PERCENT_MAX = 100;
// 한도 %는 축 상한이 100 이어야 한다. 최대값에 맞춰 늘리면 87% 막대가 꽉 찬 것처럼 보인다
export const PCT_TICKS = [0, 25, 50, 75, 100];
const DONUT_SIZE = 128;
const DONUT_THICKNESS = 16;
const DONUT_ARC_GAP = 2; // 조각 사이도 선이 아니라 간격으로 가른다
const DONUT_MIN_ARC = 0.5;
const DONUT_TOTAL_FONT = 20; // css --fs-title
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
// 툴팁도 축과 같은 압축 표기를 쓴다 — 억 단위 자릿수는 눈으로 읽히지 않는다.
// 정확한 수가 필요하면 "표로 보기" 를 펼친다
// ticks 를 주면 축을 그 눈금에 고정한다 — 상한이 정해진 값(%)에 필요하다
export function stackedColumnChart({ points, series, format = compact, label, ticks: fixed }) {
  const plot = plotOf(BAR);
  const totals = points.map((point) => sumOf(point.values, series));
  const ticks = fixed || niceTicks(Math.max(...totals, 0));
  const top = ticks[ticks.length - 1] || 1;
  const svg = frame(BAR.height, label);
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
  });
  // 휴일 라벨만 색을 달리 한다 — 막대 색은 모델 몫이라 건드리지 않는다
  xLabels(
    svg,
    points.map((point) => ({ text: point.label, cls: point.holiday ? "u-holiday" : null })),
    (i) => plot.x + band * i + band / 2,
    BAR
  );

  // 막대 위에는 초점 마크를 찍지 않는다 — 기준선이 이미 어느 막대인지 가리킨다
  const slots = points.map((point, index) => ({
    x: plot.x + band * index + band / 2,
    title: point.label,
    rows: [
      { name: TOTAL_LABEL, value: format(sumOf(point.values, series)), total: true },
      ...series
        .filter(({ key }) => (point.values[key] || 0) > 0)
        .map(({ key, name, cls }) => ({ cls, name: name || key, value: format(point.values[key]) })),
    ],
    foot: point.detail,
  }));
  return figure(svg, { plot, slots });
}

// 여러 시리즈 꺾은선. y 를 0–100% 로 고정해 축이 표본마다 흔들리지 않게 한다
export function percentLineChart({ points, series, label }) {
  const plot = plotOf(LINE);
  const svg = frame(LINE.height, label);
  gridAndTicks(svg, plot, PCT_TICKS, (value) => `${value}%`);
  const step = points.length > 1 ? plot.width / (points.length - 1) : 0;
  const positionX = (index) =>
    points.length > 1 ? plot.x + step * index : plot.x + plot.width / 2;
  const positionY = (value) =>
    plot.y + plot.height - (Math.min(value, PERCENT_MAX) / PERCENT_MAX) * plot.height;

  const ends = [];
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
    // 끝점 직접 라벨. 글자는 시리즈 색을 입지 않고 잉크 토큰을 쓴다.
    // 두 창의 %가 붙으면 라벨끼리 겹치므로 자리는 나중에 한꺼번에 벌린다
    ends.push({
      text: `${name} ${Math.round(last.value)}%`,
      x: positionX(last.index) + END_LABEL_GAP,
      y: positionY(last.value) + 4,
    });
  });

  spreadEnds(ends, plot).forEach((end) => {
    svg.appendChild(
      text(end.text, { x: end.x, y: end.y, class: "u-end-label", "font-size": null })
    );
  });
  xLabels(svg, points.map((point) => ({ text: point.label })), positionX, LINE);

  // 값이 없는 표본은 슬롯을 만들지 않는다 — 빈 툴팁이 뜨는 자리가 생긴다
  const slots = points
    .map((point, index) => {
      const filled = series.filter(({ key }) => typeof point.values[key] === "number");
      return {
        x: positionX(index),
        title: point.label,
        rows: filled.map(({ key, name, tipName, cls }) => ({
          cls,
          // 끝점 라벨은 좁아서 짧은 name 을 쓴다. 툴팁에는 자리가 있어 풀어 쓴다
          name: tipName || name,
          value: `${point.values[key].toFixed(1)}%`,
        })),
        marks: filled.map(({ key, cls }) => ({ y: positionY(point.values[key]), cls })),
      };
    })
    .filter((slot) => slot.rows.length);
  return figure(svg, { plot, slots });
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

function frame(height, label) {
  return el("svg", {
    viewBox: `0 0 ${WIDTH} ${height}`,
    width: "100%",
    role: "img",
    "aria-label": label ?? null,
  });
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

// labels = [{ text, cls }]. 자리가 되면 전부 찍고, 겹칠 때만 건너뛴다 —
// 개수를 고정해 두면 14일치처럼 다 들어가는 축에서도 절반이 빈다
function xLabels(svg, labels, centerX, spec) {
  const stride = labelStride(labels, spec, centerX);
  labels.forEach((label, index) => {
    if (index % stride) return;
    svg.appendChild(
      text(label.text, {
        x: centerX(index),
        y: spec.height - spec.pad.bottom + AXIS_FONT + 4,
        "text-anchor": "middle",
        // null 을 넘기면 el 이 속성을 건너뛰어 text() 의 기본 class 까지 사라진다
        class: label.cls ? `u-tick ${label.cls}` : "u-tick",
      })
    );
  });
}

export function labelStride(labels, spec, centerX) {
  if (labels.length < 2) return 1;
  const widest = Math.max(...labels.map((label) => textEm(label.text)));
  const need = widest * AXIS_FONT + LABEL_MIN_GAP;
  const step = Math.abs(centerX(1) - centerX(0)) || need;
  return Math.max(1, Math.ceil(need / step));
}

// 끝점 라벨을 위에서부터 최소 간격만큼 벌린다. 두 창의 %가 1~2%p 차이면
// 라벨이 겹쳐 둘 다 못 읽는다 — 값에서 조금 밀려도 읽히는 쪽이 낫다.
// 아래로만 밀고 플롯 바닥에 닿으면 그만큼 전체를 위로 당긴다
export function spreadEnds(ends, plot) {
  const sorted = [...ends].sort((a, b) => a.y - b.y);
  sorted.forEach((end, index) => {
    if (!index) return;
    end.y = Math.max(end.y, sorted[index - 1].y + END_LABEL_MIN_GAP);
  });
  const bottom = plot.y + plot.height;
  const over = sorted.length ? sorted[sorted.length - 1].y - bottom : 0;
  if (over > 0) sorted.forEach((end) => (end.y -= over));
  return sorted;
}

// 글자 폭 어림값(em). 한글은 전각이라 숫자와 같은 폭으로 세면 라벨이 서로 닿는다
function textEm(text) {
  return [...text].reduce(
    (sum, char) => sum + (char.charCodeAt(0) > CJK_START ? 1 : LABEL_CHAR_EM),
    0
  );
}

function figure(svg, hover) {
  const box = document.createElement("div");
  box.className = "u-chart";
  box.appendChild(svg);
  if (hover?.slots.length) attachHover(box, svg, hover);
  return box;
}

// 와탭식 호버. 표본마다 투명 사각형을 두는 대신 차트 전체가 pointermove 를 받아
// 가장 가까운 표본으로 기준선·초점·툴팁을 옮긴다. 사각형을 나눠 두면 경계마다
// leave/enter 가 번갈아 들어와 툴팁이 깜빡인다
function attachHover(box, svg, { plot, slots }) {
  const cursor = el("line", {
    y1: plot.y,
    y2: plot.y + plot.height,
    "stroke-dasharray": CURSOR_DASH,
    class: "u-cursor",
  });
  const marks = el("g");
  const layer = el("g", { class: "u-hover", "aria-hidden": "true" });
  layer.append(cursor, marks);
  svg.appendChild(layer);

  const tip = document.createElement("div");
  tip.className = "u-tip";
  box.appendChild(tip);

  const move = (event) => {
    const rect = svg.getBoundingClientRect();
    if (!rect.width) return;
    // svg 는 width:100% 라 viewBox 단위와 화면 px 의 배율이 폭마다 다르다
    const scale = rect.width / WIDTH;
    const slot = nearestSlot(slots, (event.clientX - rect.left) / scale);
    cursor.setAttribute("x1", slot.x);
    cursor.setAttribute("x2", slot.x);
    marks.replaceChildren(
      ...(slot.marks || []).map(({ y, cls }) =>
        el("circle", {
          cx: slot.x,
          cy: y,
          r: MARKER_RADIUS,
          "stroke-width": RING_WIDTH,
          class: `u-dot ${cls}`,
        })
      )
    );
    fillTip(tip, slot);
    box.classList.add("u-hovering");
    placeTip(tip, box, slot.x * scale, event.clientY - rect.top);
  };
  const leave = () => box.classList.remove("u-hovering");
  box.addEventListener("pointermove", move);
  box.addEventListener("pointerleave", leave);
  box.addEventListener("pointercancel", leave);
}

// 커서 x(화면 px)에 가장 가까운 슬롯. 표본이 촘촘해도 짚은 값은 하나여야 한다
export function nearestSlot(slots, x) {
  return slots.reduce((best, slot) => (Math.abs(slot.x - x) < Math.abs(best.x - x) ? slot : best));
}

function fillTip(tip, slot) {
  const nodes = [htmlTag("p", "u-tip-head", slot.title)];
  slot.rows.forEach((row) => {
    const line = htmlTag("div", row.total ? "u-tip-row u-tip-total" : "u-tip-row");
    const name = htmlTag("span", "u-tip-name", row.name);
    // 합계는 시리즈가 아니라 그 표본 전체라 색 점을 달지 않는다
    if (!row.total) name.prepend(htmlTag("i", `u-swatch ${row.cls}`));
    line.append(name, htmlTag("b", null, row.value));
    nodes.push(line);
  });
  if (slot.foot) nodes.push(htmlTag("p", "u-tip-foot", slot.foot));
  tip.replaceChildren(...nodes);
}

// 툴팁은 기준선 오른쪽이 기본. 카드 밖으로 넘칠 자리에서는 왼쪽으로 넘긴다.
// visibility 로만 숨기므로 offsetWidth 는 숨은 상태에서도 잰다
export function placeTip(tip, box, x, y) {
  const width = tip.offsetWidth;
  const height = tip.offsetHeight;
  const flipped = x + TIP_GAP + width > box.clientWidth;
  tip.style.left = `${Math.max(0, flipped ? x - TIP_GAP - width : x + TIP_GAP)}px`;
  tip.style.top = `${Math.max(0, Math.min(y - height / 2, box.clientHeight - height))}px`;
}

function htmlTag(name, className, textContent) {
  const node = document.createElement(name);
  if (className) node.className = className;
  if (textContent !== undefined && textContent !== null) node.textContent = textContent;
  return node;
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
