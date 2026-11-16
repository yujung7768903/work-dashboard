// 할일 트리 Map. 카드는 HTML, 카드 사이 곡선은 SVG 로 같은 판(world) 위에 그리고, 판 전체를
// translate·scale 해 이동·확대한다. 트리 메뉴의 Map·오른쪽 패널, 매니저 탭 팝업이 같이 쓴다.
// 배치(좌표 계산)는 tree-layout.js 가 맡고 여기는 그리기·조작만 한다
import * as api from "./api.js";
import { t } from "./i18n.js";
import { openDetail } from "./sessions.js";
import { CARD_H, CARD_W, LANE_PAD, layoutForest, pathKeys } from "./tree-layout.js";

const SVG_NS = "http://www.w3.org/2000/svg";
const DONE = "done";
const REVIEW = "review";
// 카드의 상태 고르기. 순서가 곧 일이 흘러가는 순서다
export const STATUS_ORDER = ["todo", "doing", REVIEW, DONE];
export const STATUS_LABEL = {
  todo: t("usage.statusTodo"),
  doing: t("usage.statusDoing"),
  [REVIEW]: t("tree.statusReview"),
  [DONE]: t("common.done"),
};
const WAITING_LABEL = {
  permission: t("tree.waitingPermission"),
  input: t("tree.waitingInput"),
};
// 확대 범위. 너무 작으면 글자가 점이 되고, 너무 크면 카드 한 장이 화면을 덮는다
const MIN_ZOOM = 0.25;
const MAX_ZOOM = 2;
// 처음 맞출 때는 이보다 작게 줄이지 않는다 — 다 보이게 하려다 글자를 못 읽게 되면 안 된다
// (55% 로 맞췄더니 카드 글자가 9px 아래로 내려가 읽히지 않았다).
// 다 안 들어가면 왼쪽 위부터 보이고 나머지는 끌거나 축소해서 본다
const MIN_FIT = 0.8;
const PAD = 32;
const GRID = 20; // 점 격자 간격. 확대에 맞춰 같이 커진다
const WHEEL_SPEED = 0.0015;
const BUTTON_STEP = 1.2;

/**
 * host 안에 Map 하나를 만든다.
 * options.onChange: 카드에서 무언가를 바꾼 뒤 부른다. 부르는 쪽이 다시 받아 render 한다
 * options.focusId: 강조할 할일. 그 카드와 루트까지의 길을 칠하고 처음에 그 카드로 간다
 */
export function createTreeMap(host, options = {}) {
  const viewport = element("div", "tm-viewport");
  const world = element("div", "tm-world");
  const edgeLayer = document.createElementNS(SVG_NS, "svg");
  edgeLayer.classList.add("tm-edges");
  const cardLayer = element("div", "tm-cards");
  const zoomLabel = element("span", "tm-zoom-value", "100%");
  world.append(edgeLayer, cardLayer);
  viewport.append(world, zoomControls());
  host.replaceChildren(viewport);

  let view = null; // { x, y, k } — 처음 그릴 때 정해지고 그 뒤로는 다시 그려도 유지된다
  let lastTrees = [];
  let hideDone = false;
  // 방금 완료로 바꾼 카드. 완료 숨김이어도 이 화면을 보는 동안은 흐려진 채 남는다
  const keep = new Set();
  let layout = null;

  attachPanZoom();

  function render(trees, { hideDone: hide = hideDone } = {}) {
    lastTrees = trees;
    hideDone = hide;
    layout = layoutForest(trees, { hideDone, keep });
    world.style.width = `${layout.width}px`;
    world.style.height = `${layout.height}px`;
    edgeLayer.setAttribute("width", layout.width);
    edgeLayer.setAttribute("height", layout.height);
    const onPath = options.focusId != null ? pathKeys(layout, options.focusId) : new Set();
    edgeLayer.replaceChildren(...layout.edges.map((edge) => edgeElement(edge, onPath)));
    cardLayer.replaceChildren(
      ...layout.lanes.map(laneElement),
      ...layout.cards.map((card) => cardElement(card, onPath))
    );
    if (!view) view = options.focusId != null ? focusView() : fitView();
    applyView();
  }

  // ── 시점 ────────────────────────────────────────────────────────────────

  function fitView() {
    const { width, height } = viewportSize();
    if (!layout.width) return { x: PAD, y: PAD, k: 1 };
    const scale = Math.min(
      (width - PAD * 2) / layout.width,
      (height - PAD * 2) / layout.height,
      1
    );
    const k = clamp(scale, MIN_FIT, 1);
    const x = layout.width * k < width - PAD * 2 ? (width - layout.width * k) / 2 : PAD;
    const y = layout.height * k < height - PAD * 2 ? (height - layout.height * k) / 2 : PAD;
    return { x, y, k };
  }

  function focusView() {
    const card = layout.cards.find((item) => item.kind === "todo" && item.data.id === options.focusId);
    if (!card) return fitView();
    const { width, height } = viewportSize();
    const k = 1;
    return {
      x: width / 2 - (card.x + CARD_W / 2) * k,
      y: height / 2 - (card.y + CARD_H / 2) * k,
      k,
    };
  }

  function viewportSize() {
    const rect = viewport.getBoundingClientRect();
    return { width: rect.width || 800, height: rect.height || 600 };
  }

  function applyView() {
    world.style.transform = `translate(${view.x}px, ${view.y}px) scale(${view.k})`;
    viewport.style.backgroundSize = `${GRID * view.k}px ${GRID * view.k}px`;
    viewport.style.backgroundPosition = `${view.x}px ${view.y}px`;
    zoomLabel.textContent = `${Math.round(view.k * 100)}%`;
  }

  function zoomAt(factor, px, py) {
    const k = clamp(view.k * factor, MIN_ZOOM, MAX_ZOOM);
    view = { x: px - ((px - view.x) * k) / view.k, y: py - ((py - view.y) * k) / view.k, k };
    applyView();
  }

  function zoomCenter(factor) {
    const { width, height } = viewportSize();
    zoomAt(factor, width / 2, height / 2);
  }

  // 판을 끌면 이동, 휠·핀치는 커서 자리를 중심으로 확대. 카드·버튼 위에서는 판이 움직이지 않는다
  function attachPanZoom() {
    let drag = null;
    viewport.addEventListener("pointerdown", (event) => {
      if (event.button !== 0 || event.target.closest(".tm-card, .tm-zoom")) return;
      drag = { id: event.pointerId, x: event.clientX, y: event.clientY, view: { ...view } };
      viewport.setPointerCapture(event.pointerId);
      viewport.classList.add("tm-dragging");
    });
    viewport.addEventListener("pointermove", (event) => {
      if (!drag || event.pointerId !== drag.id) return;
      view = { ...drag.view, x: drag.view.x + event.clientX - drag.x, y: drag.view.y + event.clientY - drag.y };
      applyView();
    });
    const release = (event) => {
      if (!drag || event.pointerId !== drag.id) return;
      drag = null;
      viewport.classList.remove("tm-dragging");
    };
    viewport.addEventListener("pointerup", release);
    viewport.addEventListener("pointercancel", release);
    viewport.addEventListener(
      "wheel",
      (event) => {
        if (!view) return;
        event.preventDefault();
        const rect = viewport.getBoundingClientRect();
        zoomAt(Math.exp(-event.deltaY * WHEEL_SPEED), event.clientX - rect.left, event.clientY - rect.top);
      },
      { passive: false }
    );
  }

  function zoomControls() {
    const box = element("div", "tm-zoom");
    box.append(
      iconButton("tm-zoom-out", t("tree.zoomOut"), "M4 8h8", () => zoomCenter(1 / BUTTON_STEP)),
      zoomLabel,
      iconButton("tm-zoom-in", t("tree.zoomIn"), "M8 4v8M4 8h8", () => zoomCenter(BUTTON_STEP)),
      iconButton("tm-fit", t("tree.fit"), "M3 6V3h3M10 3h3v3M13 10v3h-3M6 13H3v-3", () => {
        view = fitView();
        applyView();
      })
    );
    return box;
  }

  // ── 연결선 ──────────────────────────────────────────────────────────────

  // 부모 오른쪽 가운데 → 자식 왼쪽 가운데. 두 끝에서 수평으로 나가는 곡선이라 열이 깊어도 겹치지 않는다
  function edgeElement(edge, onPath) {
    const x1 = edge.from.x + CARD_W;
    const y1 = edge.from.y + CARD_H / 2;
    const x2 = edge.to.x;
    const y2 = edge.to.y + CARD_H / 2;
    const bend = (x2 - x1) / 2;
    const group = document.createElementNS(SVG_NS, "g");
    group.classList.add("tm-edge");
    if (edge.to.data.status === DONE) group.classList.add("tm-edge-done");
    if (onPath.has(edge.to.key)) group.classList.add("tm-edge-path");
    const path = document.createElementNS(SVG_NS, "path");
    path.setAttribute("d", `M${x1} ${y1} C${x1 + bend} ${y1} ${x2 - bend} ${y2} ${x2} ${y2}`);
    group.append(path, port(x1, y1), port(x2, y2));
    return group;
  }

  function port(cx, cy) {
    const dot = document.createElementNS(SVG_NS, "circle");
    dot.setAttribute("cx", cx);
    dot.setAttribute("cy", cy);
    dot.setAttribute("r", 3.5);
    return dot;
  }

  // ── 트리 구획 ───────────────────────────────────────────────────────────

  // 한 판에 트리가 여럿이면 어디까지가 한 트리인지 옅은 면으로 묶는다. 루트가 가지 가운데에
  // 서서 화면 밖에 있을 때도 위쪽 이름표로 지금 어느 트리를 보는지 안다
  function laneElement(lane) {
    const node = element("div", "tm-lane");
    node.style.left = `${-LANE_PAD}px`;
    node.style.top = `${lane.top}px`;
    node.style.width = `${layout.width + LANE_PAD * 2}px`;
    node.style.height = `${lane.bottom - lane.top}px`;
    if (lane.tree.workspace.category_color) node.style.setProperty("--cat", lane.tree.workspace.category_color);
    node.appendChild(element("span", "tm-lane-name", lane.tree.workspace.name));
    return node;
  }

  // ── 카드 ────────────────────────────────────────────────────────────────

  function cardElement(card, onPath) {
    const node = card.kind === "root" ? rootCard(card.tree) : todoCard(card.data);
    node.style.left = `${card.x}px`;
    node.style.top = `${card.y}px`;
    node.style.width = `${CARD_W}px`;
    node.style.height = `${CARD_H}px`;
    if (onPath.has(card.key)) node.classList.add("tm-on-path");
    if (card.kind === "todo" && card.data.id === options.focusId) node.classList.add("tm-focus");
    return node;
  }

  // 루트 = 워크스페이스. 트리 전체의 진행률과 상태별 개수를 싣는다
  function rootCard(tree) {
    const card = element("div", "tm-card tm-root");
    if (tree.workspace.category_color) card.style.setProperty("--cat", tree.workspace.category_color);
    if (tree.complete) card.dataset.status = DONE;
    const head = element("div", "tm-head");
    head.append(element("span", "tm-cat", tree.workspace.category_name ?? t("common.unassigned")));
    if (tree.waiting) head.appendChild(waitingBadge(t("tree.treeWaiting", { count: tree.waiting })));
    const title = element("div", "tm-title", tree.workspace.name);
    title.title = tree.workspace.name;
    const foot = element("div", "tm-foot");
    foot.append(progress(tree.progress), countsLine(tree.counts), addButton(card, foot, { workspace_id: tree.workspace.id }));
    card.append(head, title, foot);
    return card;
  }

  function todoCard(todo) {
    const card = element("div", "tm-card");
    card.dataset.status = todo.status;
    if (todo.waiting) card.dataset.waiting = todo.waiting;
    const head = element("div", "tm-head");
    head.append(statusSelect(todo), element("span", "tm-id", `#${todo.id}`));
    if (todo.autorun_locked) head.appendChild(element("span", "tm-flag", t("common.review")));
    if (todo.waiting) {
      const badge = waitingBadge(WAITING_LABEL[todo.waiting] ?? todo.waiting);
      badge.title = t("tree.waitingHint");
      head.appendChild(badge);
    }
    const title = element("button", "tm-title", todo.title);
    title.type = "button";
    title.title = `${todo.title} — ${t("tree.openDetail")}`;
    title.addEventListener("click", () => showDetail(todo.id));
    const foot = element("div", "tm-foot");
    if (todo.progress.total) foot.appendChild(progress(todo.progress));
    else foot.appendChild(element("span", "tm-spacer"));
    if (todo.status === REVIEW && !todo.autorun_locked) foot.appendChild(completeButton(todo));
    foot.appendChild(addButton(card, foot, { parent_id: todo.id }));
    card.append(head, title, foot);
    return card;
  }

  function statusSelect(todo) {
    const select = element("select", "tm-status");
    select.title = todo.autorun_locked ? t("board.reviewLockedHint") : t("tree.changeStatus");
    select.setAttribute("aria-label", t("tree.changeStatus"));
    select.disabled = Boolean(todo.autorun_locked);
    STATUS_ORDER.forEach((status) => {
      const option = element("option", null, STATUS_LABEL[status]);
      option.value = status;
      option.selected = status === todo.status;
      select.appendChild(option);
    });
    select.addEventListener("change", () => changeStatus(todo.id, select.value));
    return select;
  }

  // 확인 대기 카드에만. 사람이 확인을 마쳤다는 표시라 한 번 누르면 끝난다
  function completeButton(todo) {
    const button = element("button", "tm-complete", t("tree.complete"));
    button.type = "button";
    button.title = t("tree.completeHint");
    button.addEventListener("click", () => {
      button.disabled = true;
      changeStatus(todo.id, DONE);
    });
    return button;
  }

  async function changeStatus(todoId, status) {
    if (status === DONE) keep.add(todoId);
    try {
      await api.updateTodo(todoId, { status });
    } finally {
      // 실패해도 다시 받는다 — 고른 값이 화면에만 남아 저장된 것처럼 보이면 안 된다
      await refresh();
    }
  }

  // 꼬리 줄의 +. 누르면 그 줄이 입력칸으로 바뀌고 Enter 로 바로 아래에 할일이 생긴다
  function addButton(card, foot, target) {
    const button = element("button", "icon-btn tm-add");
    button.type = "button";
    button.title = t("tree.addChild");
    button.setAttribute("aria-label", t("tree.addChild"));
    button.appendChild(glyph("M8 3.5v9M3.5 8h9"));
    button.addEventListener("click", () => openAdd(card, foot, target));
    return button;
  }

  function openAdd(card, foot, target) {
    const form = element("form", "tm-add-form");
    const input = element("input");
    input.placeholder = t("tree.addPlaceholder");
    input.setAttribute("aria-label", t("tree.addChild"));
    form.appendChild(input);
    card.replaceChild(form, foot);
    input.focus();
    const close = () => form.isConnected && card.replaceChild(foot, form);
    input.addEventListener("keydown", (event) => {
      if (event.key === "Escape") close();
    });
    input.addEventListener("blur", () => {
      if (!input.value.trim()) close();
    });
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const title = input.value.trim();
      if (!title) return;
      input.disabled = true;
      try {
        await api.createTodo({ title, ...target });
      } finally {
        await refresh();
      }
    });
  }

  function showDetail(todoId) {
    openDetail({ todo: { id: todoId } });
    // 팝업에서 제목·상태를 고치면 카드도 따라가야 한다
    document.getElementById("session-modal")?.addEventListener("close", () => refresh(), { once: true });
  }

  async function refresh() {
    if (options.onChange) await options.onChange();
    else render(lastTrees);
  }

  return {
    render,
    // 탭을 다시 열거나 패널 대상이 바뀌면 시점을 새로 잡는다
    resetView() {
      view = null;
      keep.clear();
    },
  };
}

// ── 작은 조각 ─────────────────────────────────────────────────────────────

function progress({ done, total }) {
  const box = element("span", "tm-progress");
  box.title = t("tree.progressHint", { done, total });
  const bar = element("span", "tm-bar");
  const fill = element("i");
  fill.style.width = `${total ? Math.round((done / total) * 100) : 0}%`;
  bar.appendChild(fill);
  box.append(bar, element("span", "tm-num", `${done}/${total}`));
  return box;
}

// 루트 꼬리 줄의 상태별 개수. 0 건은 빼고, 완료는 진행률이 이미 말하므로 뺀다
function countsLine(counts) {
  const line = element("span", "tm-counts");
  STATUS_ORDER.filter((status) => status !== DONE && counts[status]).forEach((status) => {
    const chip = element("span", "tm-count", String(counts[status]));
    chip.dataset.status = status;
    chip.title = STATUS_LABEL[status];
    line.appendChild(chip);
  });
  return line;
}

function waitingBadge(text) {
  return element("span", "tm-waiting", text);
}

function iconButton(className, label, d, onClick) {
  const button = element("button", `icon-btn ${className}`);
  button.type = "button";
  button.title = label;
  button.setAttribute("aria-label", label);
  button.appendChild(glyph(d));
  button.addEventListener("click", onClick);
  return button;
}

function glyph(d) {
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("viewBox", "0 0 16 16");
  svg.setAttribute("width", "16");
  svg.setAttribute("height", "16");
  svg.setAttribute("aria-hidden", "true");
  const path = document.createElementNS(SVG_NS, "path");
  path.setAttribute("d", d);
  path.setAttribute("fill", "none");
  path.setAttribute("stroke", "currentColor");
  path.setAttribute("stroke-width", "1.5");
  path.setAttribute("stroke-linecap", "round");
  path.setAttribute("stroke-linejoin", "round");
  svg.appendChild(path);
  return svg;
}

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

function clamp(value, low, high) {
  return Math.min(high, Math.max(low, value));
}
