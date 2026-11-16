// 트리 메뉴. 워크스페이스 하나가 트리 하나(루트)이고 할일이 깊이 제한 없이 매달린다.
// List — 트리 1개가 1행 요약, 토글로 2단계까지 펼친다. 행을 누르면 오른쪽 패널에 그 트리만 Map 으로.
// Map  — 진행 중인 트리 전부를 한 판에 왼→오 노드 그래프로.
// 보드(카테고리>워크스페이스>할일)는 그대로 두고 같은 데이터를 다른 눈으로 본다
import * as api from "./api.js";
import { t } from "./i18n.js";
import { createTreeMap, STATUS_LABEL, STATUS_ORDER } from "./tree-map.js";
import { isVisible } from "./tree-layout.js";

const VIEW_KEY = "tree-view";
const HIDE_KEY = "tree-hide-done";
const PANEL_KEY = "tree-panel-width";
const VIEW_LIST = "list";
const VIEW_MAP = "map";
const DONE = "done";
const REVIEW = "review";
const LIST_DEPTH = 2; // 목록에서 펼치는 깊이. 그 아래는 패널의 Map 에서 본다
// 패널 폭의 한계. 목록 쪽도 이름·진행률이 읽힐 만큼은 남아야 한다
const PANEL_MIN = 360;
const LIST_MIN = 320;
const PANEL_DEFAULT_RATIO = 0.55;
const KEY_STEP = 24;

// 기기마다 다른 취향이라 서버가 아니라 브라우저에 남긴다 (보드의 todo-view 와 같은 방식)
let view = readStore(VIEW_KEY) === VIEW_MAP ? VIEW_MAP : VIEW_LIST;
let hideDone = readStore(HIDE_KEY) !== "false";
let trees = [];
const expanded = new Set();
let mapView = null;
let panelMap = null;
// 오른쪽 패널에 띄운 트리(워크스페이스 id)와 강조할 할일
let panel = null;

export async function renderTreeTab() {
  bindControls();
  await reload();
}

async function reload() {
  trees = (await api.getTodoTrees()).trees;
  draw();
}

function draw() {
  syncControls();
  drawSummary();
  const isMap = view === VIEW_MAP;
  byId("tree-list-pane").hidden = isMap;
  byId("tree-map").hidden = !isMap;
  const showPanel = !isMap && panel != null && treeOf(panel.treeId) != null;
  byId("tree-panel").hidden = !showPanel;
  byId("tree-splitter").hidden = !showPanel;
  if (isMap) {
    // 숨겨진 칸에서 처음 그리면 크기를 0 으로 재서 맞춤이 틀어진다 — 보인 다음에 그린다
    mapView ??= createTreeMap(byId("tree-map"), { onChange: reload });
    mapView.render(trees, { hideDone });
    return;
  }
  drawList();
  if (showPanel) drawPanel();
}

// ── 위쪽 조작 줄 ──────────────────────────────────────────────────────────

let bound = false;
function bindControls() {
  if (bound) return;
  bound = true;
  byId("tree-view").addEventListener("click", (event) => {
    const next = event.target.closest("button")?.dataset.view;
    if (!next || next === view) return;
    view = next;
    writeStore(VIEW_KEY, view);
    draw();
  });
  byId("tree-hide-done").addEventListener("click", () => {
    hideDone = !hideDone;
    writeStore(HIDE_KEY, String(hideDone));
    draw();
  });
  byId("tree-refresh").addEventListener("click", () => reload());
  byId("tree-panel-close").addEventListener("click", () => {
    panel = null;
    draw();
  });
  bindSplitter();
}

function syncControls() {
  byId("tree-view")
    .querySelectorAll("button")
    .forEach((button) => button.classList.toggle("active", button.dataset.view === view));
  byId("tree-hide-done").setAttribute("aria-pressed", String(hideDone));
}

// 판 위 한 줄 — 지금 사람이 봐야 할 것이 몇 개인지
function drawSummary() {
  const open = trees.filter((tree) => !tree.complete);
  const review = open.reduce((sum, tree) => sum + (tree.counts[REVIEW] || 0), 0);
  const waiting = open.reduce((sum, tree) => sum + tree.waiting, 0);
  byId("tree-summary").textContent = t("tree.summary", { trees: open.length, review, waiting });
}

// ── List ─────────────────────────────────────────────────────────────────

function drawList() {
  const list = byId("tree-list");
  const shown = trees.filter((tree) => !(hideDone && tree.complete));
  if (!shown.length) {
    list.replaceChildren(element("p", "tree-empty", t("tree.empty")));
    return;
  }
  list.replaceChildren(...shown.map(rowBlock));
}

function rowBlock(tree) {
  const block = element("div", "tree-block");
  const id = tree.workspace.id;
  const row = element("div", "tree-row");
  row.tabIndex = 0;
  row.setAttribute("role", "button");
  if (tree.complete) row.dataset.status = DONE;
  if (panel?.treeId === id) row.classList.add("active");
  if (tree.workspace.category_color) row.style.setProperty("--cat", tree.workspace.category_color);

  const open = expanded.has(id);
  const toggle = element("button", "icon-btn tree-expand");
  toggle.type = "button";
  toggle.title = t("tree.expand");
  toggle.setAttribute("aria-label", t("tree.expand"));
  toggle.setAttribute("aria-expanded", String(open));
  toggle.disabled = !tree.children.length;
  toggle.appendChild(chevron());
  toggle.addEventListener("click", (event) => {
    event.stopPropagation();
    if (open) expanded.delete(id);
    else expanded.add(id);
    drawList();
  });

  const name = element("span", "tree-row-name");
  name.append(element("span", "tree-row-title", tree.workspace.name));
  name.title = tree.workspace.name;
  const category = element("span", "tree-row-cat", tree.workspace.category_name ?? "");

  row.append(toggle, name, category, progressCell(tree.progress), countsCell(tree), waitingCell(tree));
  const choose = () => openPanel(id, null);
  row.addEventListener("click", choose);
  row.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      choose();
    }
  });
  block.appendChild(row);
  if (open) block.appendChild(kidsList(tree, tree.children, 1));
  return block;
}

// 펼친 줄. 2단계까지만 — 그보다 깊은 가지는 숫자로만 알리고 패널의 Map 에서 본다
function kidsList(tree, nodes, depth) {
  const list = element("ul", "tree-kids");
  nodes
    .filter((node) => isVisible(node, { hideDone }))
    .forEach((node) => {
      const item = element("li");
      const line = element("button", "tree-kid");
      line.type = "button";
      line.dataset.status = node.status;
      line.style.setProperty("--depth", depth);
      if (panel?.focusId === node.id) line.classList.add("active");
      const status = element("span", "tree-kid-status", STATUS_LABEL[node.status] ?? node.status);
      const title = element("span", "tree-kid-title", node.title);
      line.append(status, element("span", "tree-kid-id", `#${node.id}`), title);
      if (node.waiting) line.appendChild(element("span", "tm-waiting", waitingText(node.waiting)));
      if (node.progress.total) {
        line.appendChild(element("span", "tree-kid-num", `${node.progress.done}/${node.progress.total}`));
      }
      line.title = node.title;
      line.addEventListener("click", () => openPanel(tree.workspace.id, node.id));
      item.appendChild(line);
      if (depth < LIST_DEPTH && node.children.length) {
        item.appendChild(kidsList(tree, node.children, depth + 1));
      }
      list.appendChild(item);
    });
  return list;
}

function progressCell({ done, total }) {
  const cell = element("span", "tree-row-progress");
  cell.title = t("tree.progressHint", { done, total });
  const bar = element("span", "tm-bar");
  const fill = element("i");
  fill.style.width = `${total ? Math.round((done / total) * 100) : 0}%`;
  bar.appendChild(fill);
  cell.append(bar, element("span", "tm-num", `${done}/${total}`));
  return cell;
}

// 상태별 개수. 0 건은 비워 두어 남은 칩만 눈에 들어오게 한다
function countsCell(tree) {
  const cell = element("span", "tree-row-counts");
  STATUS_ORDER.forEach((status) => {
    const count = tree.counts[status] || 0;
    if (!count) return;
    const chip = element("span", "tree-count", `${STATUS_LABEL[status]} ${count}`);
    chip.dataset.status = status;
    cell.appendChild(chip);
  });
  return cell;
}

function waitingCell(tree) {
  const cell = element("span", "tree-row-flag");
  if (tree.waiting) cell.appendChild(element("span", "tm-waiting", t("tree.treeWaiting", { count: tree.waiting })));
  return cell;
}

// ── 오른쪽 패널 ───────────────────────────────────────────────────────────

function openPanel(treeId, focusId) {
  const changed = panel?.treeId !== treeId || panel?.focusId !== focusId;
  panel = { treeId, focusId };
  // 다른 트리·다른 할일을 고르면 그 대상으로 시점을 새로 잡는다
  if (changed) panelMap = null;
  draw();
}

function drawPanel() {
  const tree = treeOf(panel.treeId);
  byId("tree-panel-title").textContent = tree.workspace.name;
  applyPanelWidth();
  panelMap ??= createTreeMap(byId("tree-panel-map"), { onChange: reload, focusId: panel.focusId });
  panelMap.render([tree], { hideDone });
}

// 목록과 패널 사이 경계를 끌어 패널 폭을 정한다. 키보드 ←→ 로도 움직인다
function bindSplitter() {
  const splitter = byId("tree-splitter");
  let drag = null;
  splitter.addEventListener("pointerdown", (event) => {
    drag = { id: event.pointerId };
    splitter.setPointerCapture(event.pointerId);
    splitter.classList.add("dragging");
  });
  splitter.addEventListener("pointermove", (event) => {
    if (!drag || drag.id !== event.pointerId) return;
    const stage = byId("tree-stage").getBoundingClientRect();
    setPanelWidth(stage.right - event.clientX);
  });
  const release = (event) => {
    if (!drag || drag.id !== event.pointerId) return;
    drag = null;
    splitter.classList.remove("dragging");
    writeStore(PANEL_KEY, String(currentPanelWidth()));
  };
  splitter.addEventListener("pointerup", release);
  splitter.addEventListener("pointercancel", release);
  splitter.addEventListener("keydown", (event) => {
    const delta = { ArrowLeft: KEY_STEP, ArrowRight: -KEY_STEP }[event.key];
    if (!delta) return;
    event.preventDefault();
    setPanelWidth(currentPanelWidth() + delta);
    writeStore(PANEL_KEY, String(currentPanelWidth()));
  });
  // 두 번 누르면 기본 폭으로
  splitter.addEventListener("dblclick", () => {
    removeStore(PANEL_KEY);
    applyPanelWidth();
  });
}

function applyPanelWidth() {
  const saved = Number(readStore(PANEL_KEY));
  const stage = byId("tree-stage").getBoundingClientRect().width || 1200;
  setPanelWidth(saved > 0 ? saved : stage * PANEL_DEFAULT_RATIO);
}

function setPanelWidth(width) {
  const stage = byId("tree-stage").getBoundingClientRect().width || 1200;
  const clamped = Math.round(Math.max(PANEL_MIN, Math.min(width, stage - LIST_MIN)));
  byId("tree-stage").style.setProperty("--tree-panel-w", `${clamped}px`);
  byId("tree-splitter").setAttribute("aria-valuenow", String(clamped));
}

function currentPanelWidth() {
  return byId("tree-panel").getBoundingClientRect().width;
}

// ── 조각 ─────────────────────────────────────────────────────────────────

function waitingText(kind) {
  return kind === "permission" ? t("tree.waitingPermission") : t("tree.waitingInput");
}

function treeOf(workspaceId) {
  return trees.find((tree) => tree.workspace.id === workspaceId) ?? null;
}

function chevron() {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 16 16");
  svg.setAttribute("width", "16");
  svg.setAttribute("height", "16");
  svg.setAttribute("aria-hidden", "true");
  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  path.setAttribute("d", "M6 4l4 4-4 4");
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

function byId(id) {
  return document.getElementById(id);
}

// 사파리 사생활 보호 창처럼 저장소가 막혀도 화면은 떠야 한다
function readStore(key) {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function writeStore(key, value) {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* 기억 못 해도 지금 화면은 그대로 쓴다 */
  }
}

function removeStore(key) {
  try {
    localStorage.removeItem(key);
  } catch {
    /* 위와 같음 */
  }
}
