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
const CONTEXT = "context";
const PROPOSED = "proposed";
const CONFIRMED = "confirmed";
const REJECTED = "rejected";
const PARENT = "parent";
const PRECEDES = "precedes";
// 카드 관계 줄에 근거 문서를 몇 개까지 펼치는지. 나머지는 +N 으로 줄이고 제목에 다 적는다
const DOC_CHIPS = 2;
// 다른 트리의 상위처럼 대상이 왼쪽·같은 열에 있어도 곡선이 카드 밖으로 빠졌다 들어오게 하는 최소 휨
const COL_BEND = 48;
const PILL_GAP = 90; // 제안 알약과 하위 카드 사이(선을 따라)
const PILL_STEP = 0.01;
// 화살촉 marker id 는 문서 전체에서 하나여야 한다 — 판이 여럿(트리 맵·패널·매니저 팝업)이라 판마다 붙인다
let mapSeq = 0;
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
  let lastLinks = [];
  const arrowId = `tm-arrow-${(mapSeq += 1)}`;
  let hideDone = false;
  // 방금 완료로 바꾼 카드. 완료 숨김이어도 이 화면을 보는 동안은 흐려진 채 남는다
  const keep = new Set();
  // 강조할 카드는 끝났어도 숨기지 않는다 — 매니저 팝업이 가리키는 카드가 사라지면 연관을 못 본다
  const keepFocus = () => options.focusId != null && keep.add(options.focusId);
  keepFocus();
  let layout = null;

  attachPanZoom();

  // links: /api/todo-trees 의 links — 주 상위 밖의 상위·선행을 선으로 더 긋는다. 안 주면 지난 것을 쓴다
  function render(trees, { hideDone: hide = hideDone, links = lastLinks } = {}) {
    lastTrees = trees;
    lastLinks = links;
    hideDone = hide;
    layout = layoutForest(trees, { hideDone, keep });
    world.style.width = `${layout.width}px`;
    world.style.height = `${layout.height}px`;
    edgeLayer.setAttribute("width", layout.width);
    edgeLayer.setAttribute("height", layout.height);
    const onPath = options.focusId != null ? pathKeys(layout, options.focusId) : new Set();
    const extra = extraLinks(links);
    edgeLayer.replaceChildren(
      arrowDefs(),
      ...layout.edges.map((edge) => edgeElement(edge, onPath)),
      ...extra.map(linkElement)
    );
    cardLayer.replaceChildren(
      ...layout.lanes.map(laneElement),
      ...layout.cards.map((card) => cardElement(card, onPath)),
      ...proposalPills(extra)
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

  // 강조 카드로 갈 때는 루트에서 그 카드까지의 길과 그 카드의 바로 아래 자식을 한 화면에 담는다 —
  // 카드만 가운데 두면 어느 가지의 일인지(루트·부모)가 화면 밖으로 나간다
  function focusView() {
    const card = layout.cards.find((item) => item.kind === "todo" && item.data.id === options.focusId);
    if (!card) return fitView();
    const frame = layout.cards.filter((item) => item.parent === card);
    for (let step = card; step; step = step.parent) frame.push(step);
    const left = Math.min(...frame.map((item) => item.x));
    const top = Math.min(...frame.map((item) => item.y));
    const right = Math.max(...frame.map((item) => item.x + CARD_W));
    const bottom = Math.max(...frame.map((item) => item.y + CARD_H));
    const { width, height } = viewportSize();
    const k = clamp(Math.min((width - PAD * 2) / (right - left), (height - PAD * 2) / (bottom - top), 1), MIN_FIT, 1);
    // 다 안 들어가면 강조 카드가 화면 가운데에 오게 한다
    const centerX = (right - left) * k <= width - PAD * 2 ? (left + right) / 2 : card.x + CARD_W / 2;
    const centerY = (bottom - top) * k <= height - PAD * 2 ? (top + bottom) / 2 : card.y + CARD_H / 2;
    return { x: width / 2 - centerX * k, y: height / 2 - centerY * k, k };
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

  // 부모 오른쪽 가운데 → 자식 왼쪽 가운데. 두 끝에서 수평으로 나가는 곡선이라 열이 깊어도 겹치지 않는다.
  // 주 상위 연결이 제안이면 점선 — 확인·거절 알약은 proposalPills 가 얹는다
  function edgeElement(edge, onPath) {
    const { x1, y1, x2, y2, d } = sideCurve(edge.from, edge.to);
    const group = document.createElementNS(SVG_NS, "g");
    group.classList.add("tm-edge");
    if (edge.to.data.status === DONE) group.classList.add("tm-edge-done");
    if (onPath.has(edge.to.key)) group.classList.add("tm-edge-path");
    if (primaryLink(edge.to)?.state === PROPOSED) group.classList.add("tm-edge-proposed");
    const path = document.createElementNS(SVG_NS, "path");
    path.setAttribute("d", d);
    group.append(path, port(x1, y1), port(x2, y2));
    return group;
  }

  // 양옆으로 나가 들어오는 곡선. 대상이 왼쪽에 있어도(다른 트리의 상위) 끝은 늘 수평으로 붙는다
  function sideCurve(from, to) {
    const x1 = from.x + CARD_W;
    const y1 = from.y + CARD_H / 2;
    const x2 = to.x;
    const y2 = to.y + CARD_H / 2;
    const bend = Math.max(COL_BEND, Math.abs(x2 - x1) / 2);
    const controls = [x1 + bend, y1, x2 - bend, y2];
    return { x1, y1, x2, y2, controls, d: `M${x1} ${y1} C${controls.join(" ")} ${x2} ${y2}` };
  }

  // 선행은 위아래로 잇는 화살표다 — 상위 곡선(좌우)과 방향부터 달라 색을 못 봐도 갈린다
  function verticalCurve(from, to) {
    const down = to.y >= from.y;
    const x1 = from.x + CARD_W / 2;
    const y1 = down ? from.y + CARD_H : from.y;
    const x2 = to.x + CARD_W / 2;
    const y2 = down ? to.y : to.y + CARD_H;
    const bend = Math.max(COL_BEND / 2, Math.abs(y2 - y1) / 2) * (down ? 1 : -1);
    const controls = [x1, y1 + bend, x2, y2 - bend];
    return { x1, y1, x2, y2, controls, d: `M${x1} ${y1} C${controls.join(" ")} ${x2} ${y2}` };
  }

  // 알약 자리. 선 가운데가 아니라 하위(도착) 끝에서 선을 따라 PILL_GAP 만큼 거슬러 간 곳 — 다른 트리에서
  // 길게 오는 선이면 가운데가 화면 밖이라, 확인할 카드 옆에서 바로 보이게 한다. 짧은 선이면 가운데
  function pillPoint({ x1, y1, x2, y2, controls: [c1x, c1y, c2x, c2y] }) {
    const at = (t) => {
      const u = 1 - t;
      const mix = (a, b, c, d) => u ** 3 * a + 3 * u ** 2 * t * b + 3 * u * t ** 2 * c + t ** 3 * d;
      return [mix(x1, c1x, c2x, x2), mix(y1, c1y, c2y, y2)];
    };
    for (let t = 1; t > 0.5; t -= PILL_STEP) {
      const [x, y] = at(t);
      if (Math.hypot(x - x2, y - y2) >= PILL_GAP) return [x, y];
    }
    return at(0.5);
  }

  // 그릴 수 있는 추가 연결 — 다른 상위와 선행. 양 끝 카드가 다 판에 있을 때만
  function extraLinks(links) {
    return (links || [])
      .filter((link) => (link.relation === PARENT && !link.primary) || link.relation === PRECEDES)
      .map((link) => ({ link, from: layout.byKey.get(link.from), to: layout.byKey.get(link.to) }))
      .filter((item) => item.from && item.to);
  }

  function linkElement({ link, from, to }) {
    const precedes = link.relation === PRECEDES;
    const { d } = precedes ? verticalCurve(from, to) : sideCurve(from, to);
    const group = document.createElementNS(SVG_NS, "g");
    group.classList.add("tm-edge", precedes ? "tm-edge-precedes" : "tm-edge-other");
    if (link.state === PROPOSED) group.classList.add("tm-edge-proposed");
    if (to.data.status === DONE && from.data.status === DONE) group.classList.add("tm-edge-done");
    const path = document.createElementNS(SVG_NS, "path");
    path.setAttribute("d", d);
    if (precedes) path.setAttribute("marker-end", `url(#${arrowId})`);
    group.appendChild(path);
    return group;
  }

  function arrowDefs() {
    const defs = document.createElementNS(SVG_NS, "defs");
    const marker = document.createElementNS(SVG_NS, "marker");
    marker.setAttribute("id", arrowId);
    marker.setAttribute("viewBox", "0 0 10 10");
    marker.setAttribute("refX", "9");
    marker.setAttribute("refY", "5");
    marker.setAttribute("markerWidth", "8");
    marker.setAttribute("markerHeight", "8");
    marker.setAttribute("orient", "auto-start-reverse");
    const tip = document.createElementNS(SVG_NS, "path");
    tip.setAttribute("d", "M0 0L10 5L0 10z");
    tip.classList.add("tm-arrow");
    marker.appendChild(tip);
    defs.appendChild(marker);
    return defs;
  }

  // 제안 연결마다 선 한가운데에 '제안 · 기준' 알약과 확인·거절 버튼. 근거 문장은 알약 제목(툴팁)
  function proposalPills(extra) {
    const pills = [];
    layout.edges.forEach((edge) => {
      const link = primaryLink(edge.to);
      if (link?.state !== PROPOSED) return;
      const at = pillPoint(sideCurve(edge.from, edge.to));
      pills.push(proposalPill({ id: link.edge_id, relation: PARENT, basis: link.basis, evidence: link.evidence }, at));
    });
    extra.forEach(({ link, from, to }) => {
      if (link.state !== PROPOSED) return;
      pills.push(proposalPill(link, pillPoint(link.relation === PRECEDES ? verticalCurve(from, to) : sideCurve(from, to))));
    });
    return pills;
  }

  function proposalPill(link, [x, y]) {
    const pill = element("div", "tm-proposal");
    pill.style.left = `${x}px`;
    pill.style.top = `${y}px`;
    const label = element("span", "tm-proposal-label", proposalLabel(link));
    pill.title = link.evidence ? `${proposalLabel(link)} — ${link.evidence}` : proposalLabel(link);
    pill.append(
      label,
      decideButton("tm-accept", t("tree.accept"), "M3.5 8.5l3 3 6-7", link.id, CONFIRMED),
      decideButton("tm-reject", t("tree.reject"), "M4.5 4.5l7 7M11.5 4.5l-7 7", link.id, REJECTED)
    );
    return pill;
  }

  function decideButton(className, label, d, edgeId, state) {
    const button = iconButton(className, label, d, async () => {
      button.disabled = true;
      try {
        await api.updateEdge(edgeId, { state });
      } finally {
        await refresh();
      }
    });
    return button;
  }

  function primaryLink(card) {
    return card.data.parents?.find((parent) => parent.primary) ?? null;
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
    node.appendChild(element("span", "tm-lane-name", lane.tree.workspace.name ?? t("common.unassigned")));
    return node;
  }

  // ── 카드 ────────────────────────────────────────────────────────────────

  function cardElement(card, onPath) {
    const node =
      card.kind === "root" ? rootCard(card.tree) : card.kind === CONTEXT ? contextCard(card.data) : todoCard(card.data);
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
    const name = tree.workspace.name ?? t("common.unassigned");
    const title = element("div", "tm-title", name);
    title.title = name;
    const foot = element("div", "tm-foot");
    foot.append(progress(tree.progress), countsLine(tree.counts));
    // 미분류 트리는 워크스페이스가 없어 여기서 바로 만들 할일의 소속을 정할 수 없다
    if (tree.workspace.id != null) foot.appendChild(addButton(card, foot, { workspace_id: tree.workspace.id }));
    card.append(head, title, element("div", "tm-meta"), foot);
    return card;
  }

  // 맥락 = 할일이 아니라 배경 묶음. 상태를 고르지 않고, 아래 할일 진행률과 + 만 있다
  function contextCard(node) {
    const card = element("div", "tm-card tm-context");
    card.dataset.status = node.status;
    const head = element("div", "tm-head");
    head.appendChild(element("span", "tm-kind", t("tree.context")));
    const title = element("div", "tm-title", node.title);
    title.title = node.note ? `${node.title}\n\n${node.note}` : node.title;
    const foot = element("div", "tm-foot");
    foot.append(progress(node.progress), addButton(card, foot, { context_id: node.id }));
    card.append(head, title, metaLine(node, false), foot);
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
    card.append(head, title, metaLine(todo, true), foot);
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
      keepFocus();
    },
  };
}

// ── 트리 없이 혼자 서는 카드 ──────────────────────────────────────────────
// 매니저 탭 팝업에서 그 일이 트리에 붙어 있지 않을 때 쓴다. 트리 카드와 같은 크기·클래스·상태 색·
// 대기 표시라 같은 일로 읽힌다. 상태는 대시보드 할일이 아니라 바꿀 수 없어 고르기 대신 칩으로 둔다
//   status: 상태 색을 정하는 todo·doing·review·done 중 하나. label: 칩 글자(없으면 그 상태 이름)
//   waiting: permission·input — 그 일을 하는 세션이 사람을 기다릴 때. onOpen: 있으면 제목을 눌러 연다
export function soloCard({ id = null, title, status, label, waiting = null, onOpen = null }) {
  const card = element("div", "tm-card tm-solo");
  card.dataset.status = status;
  if (waiting) card.dataset.waiting = waiting;
  card.style.width = `${CARD_W}px`;
  card.style.height = `${CARD_H}px`;
  const head = element("div", "tm-head");
  head.appendChild(element("span", "tm-state", label ?? STATUS_LABEL[status]));
  if (id != null) head.appendChild(element("span", "tm-id", `#${id}`));
  if (waiting) {
    const badge = waitingBadge(WAITING_LABEL[waiting] ?? waiting);
    badge.title = t("tree.waitingHint");
    head.appendChild(badge);
  }
  const name = element(onOpen ? "button" : "div", "tm-title", title);
  name.title = onOpen ? `${title} — ${t("tree.openDetail")}` : title;
  if (onOpen) {
    name.type = "button";
    name.addEventListener("click", onOpen);
  }
  // 꼬리 줄은 비워 둔다 — 높이를 트리 카드와 맞춰 제목이 같은 자리에 온다
  const foot = element("div", "tm-foot");
  foot.appendChild(element("span", "tm-spacer"));
  card.append(head, name, element("div", "tm-meta"), foot);
  return card;
}

// ── 관계 줄 ───────────────────────────────────────────────────────────────
// 카드(맵)와 목록 줄이 같이 쓴다. 근거 문서는 눌러서 여는 링크, 나머지는 글자 칩이고 자세한 것은 제목(툴팁)에.
// 색 하나로만 구분하지 않는다 — 칩마다 '먼저'·'다른 상위' 같은 글자가 먼저 읽힌다
//   shownUnder: 목록에서 지금 이 줄이 매달린 상위 key. 그 상위를 뺀 나머지를 '다른 상위' 로 센다
export function metaLine(node, withLinks = true, { shownUnder = null } = {}) {
  const line = element("div", "tm-meta");
  docChips(node.docs ?? []).forEach((chip) => line.appendChild(chip));
  if (!withLinks) return line;
  const others = (node.parents ?? []).filter((parent) =>
    shownUnder != null ? parent.key !== shownUnder : !parent.primary
  );
  if (others.length) {
    const chip = element("span", "tm-chip", t("tree.otherParents", { count: others.length }));
    chip.title = others.map((parent) => `${parentLabel(parent)} ${parent.title}`).join("\n");
    line.appendChild(chip);
  }
  const waitingFor = (node.after ?? []).filter((item) => item.status !== DONE);
  if (waitingFor.length) {
    const text =
      waitingFor.length === 1 ? t("tree.afterOne", { id: waitingFor[0].id }) : t("tree.afterMany", { count: waitingFor.length });
    const chip = element("span", "tm-chip tm-chip-after", text);
    chip.title = waitingFor.map((item) => `#${item.id} ${item.title}`).join("\n");
    line.appendChild(chip);
  }
  if (node.related?.length) {
    const chip = element("span", "tm-chip", t("tree.related", { count: node.related.length }));
    chip.title = node.related
      .map((item) => `${item.state === PROPOSED ? `${t("tree.proposed")} · ` : ""}${item.title}${item.evidence ? ` — ${item.evidence}` : ""}`)
      .join("\n");
    line.appendChild(chip);
  }
  return line;
}

function docChips(docs) {
  const shown = docs.slice(0, DOC_CHIPS).map((doc) => {
    // Jira·PR 은 키가 곧 이름이고, Confluence 는 페이지 번호보다 제목이 읽힌다
    const text = doc.kind === "confluence" && doc.title && doc.title !== doc.label ? doc.title : doc.label;
    const link = element("a", "tm-doc", text);
    link.href = doc.url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.title = [doc.title && doc.title !== doc.label ? doc.title : null, doc.url].filter(Boolean).join("\n");
    link.addEventListener("pointerdown", (event) => event.stopPropagation());
    link.addEventListener("click", (event) => event.stopPropagation());
    return link;
  });
  if (docs.length > DOC_CHIPS) {
    const more = element("span", "tm-chip", `+${docs.length - DOC_CHIPS}`);
    more.title = docs.slice(DOC_CHIPS).map((doc) => doc.label).join("\n");
    shown.push(more);
  }
  return shown;
}

// 상위 연결 하나를 사람 말로 — '제안 · 계기' 처럼 상태와 기준
// 사전 키를 글자로 조립하지 않는다 — 안 쓰는 키 검사(tests/test_language.py)가 t("…") 호출에서 키를 찾는다
const BASIS_LABEL = {
  trigger: () => t("tree.basis.trigger"),
  purpose: () => t("tree.basis.purpose"),
  background: () => t("tree.basis.background"),
};
const RELATION_LABEL = {
  parent: () => t("tree.relation.parent"),
  precedes: () => t("tree.relation.precedes"),
  related: () => t("tree.relation.related"),
  evidence: () => t("tree.relation.evidence"),
};

export function parentLabel(parent) {
  const basis = BASIS_LABEL[parent.basis]?.() ?? "";
  return parent.state === PROPOSED ? `${t("tree.proposed")} · ${basis}` : basis;
}

export function proposalLabel(link) {
  const relation = RELATION_LABEL[link.relation]?.() ?? link.relation;
  const basis = link.relation === PARENT && BASIS_LABEL[link.basis] ? ` · ${BASIS_LABEL[link.basis]()}` : "";
  return `${t("tree.proposed")} · ${relation}${basis}`;
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
