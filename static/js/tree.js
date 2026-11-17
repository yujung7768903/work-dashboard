// 트리 메뉴. 워크스페이스 하나가 트리 하나(루트)이고 맥락·할일이 상위 연결로 깊이 제한 없이 매달린다.
// 상위는 여럿일 수 있고(왜 생겼나 — 계기·목적·배경), 선행은 따로다(무엇을 먼저).
// 트리별 — 트리 1개가 1행 요약. 펼치면 각 상위 밑에 하위가 다 보이고(상위가 둘이면 두 곳에) 줄마다 다시 펼친다.
//          행을 누르면 오른쪽 패널에 그 트리만 Map 으로.
// 할일별 — 진행 중 할일 1개가 1행. 줄 아래 작게 그 할일이 걸린 트리. 줄을 누르면 카드가 있는 트리를,
//          트리 이름을 누르면 그 트리를 오른쪽 패널에 그 카드가 가운데 오게 띄운다 (고르는 규칙은 tree-todos.js).
//          지금 떠 있는 보조 세션이 잡은 할일은 줄 왼쪽에 막대를 붙인다
// 트리별·할일별 목록은 가장 최근에 작업하거나 고친 것이 위다(tree-todos.js activeAt). 맵 배치는 그대로
// Map  — 진행 중인 트리 전부를 한 판에. 카드는 한 번만 그리고 다른 상위·선행은 선을 더 긋는다.
// 제안(자동·재구성이 만든 연결)은 점선 + 확인·거절. 위쪽 '제안' 버튼이 전부 모아 보여 준다.
// 보드(카테고리>워크스페이스>할일)는 그대로 두고 같은 데이터를 다른 눈으로 본다
import * as api from "./api.js";
import { t } from "./i18n.js";
import { resultView } from "./result-card.js";
import { cornerBadge, createTreeMap, metaLine, parentLabel, proposalLabel, STATUS_LABEL, STATUS_ORDER } from "./tree-map.js";
import { isVisible } from "./tree-layout.js";
import { helperStatusText } from "./manager.js";
import { doingTodos, holdersByTodo, latestFirst, panelTrees, treeIdOf, UNASSIGNED_TREE } from "./tree-todos.js";

const VIEW_KEY = "tree-view";
const HIDE_KEY = "tree-hide-done";
const PANEL_KEY = "tree-panel-width";
const VIEW_LIST = "list";
const VIEW_TODOS = "todos";
const VIEW_MAP = "map";
const VIEWS = [VIEW_LIST, VIEW_TODOS, VIEW_MAP];
const DONE = "done";
const REVIEW = "review";
// 트리를 펼쳤을 때 처음부터 열려 있는 깊이. 그 아래는 줄마다 펼친다(깊이 제한은 없다)
const OPEN_DEPTH = 2;
const PROPOSED = "proposed";
const CONFIRMED = "confirmed";
const REJECTED = "rejected";
const CONTEXT = "context";
const HELPERS_PART = "helpers";
const HOLDER_HELPER = "helper";
// 패널 폭의 한계. 목록 쪽도 이름·진행률이 읽힐 만큼은 남아야 한다
const PANEL_MIN = 360;
const LIST_MIN = 320;
const PANEL_DEFAULT_RATIO = 0.55;
const KEY_STEP = 24;
// 이 폭 아래에서는 패널이 목록 밑으로 내려간다(tree.css 와 같은 값) — 할일을 누르면 패널까지 내려 준다
const STACKED = "(max-width: 900px)";

// 기기마다 다른 취향이라 서버가 아니라 브라우저에 남긴다 (보드의 todo-view 와 같은 방식)
let view = VIEWS.includes(readStore(VIEW_KEY)) ? readStore(VIEW_KEY) : VIEW_LIST;
let hideDone = readStore(HIDE_KEY) !== "false";
let trees = [];
let links = [];
let proposalCount = 0;
let nodeByKey = new Map();
const expanded = new Set();
// 줄 펼침을 사람이 바꾼 것. key 는 트리부터 그 줄까지의 경로 — 상위가 둘이면 같은 할일도 줄이 둘이다
const toggled = new Map();
let showProposals = false;
let mapView = null;
let panelMap = null;
// 오른쪽 패널에 띄운 트리(워크스페이스 id)와 강조할 할일.
// 할일별에서 열면 home(카드가 있는 트리)과 center(카드를 가운데)가 붙는다
let panel = null;
// 할일 id → 그 할일을 지금 잡은 보조 세션들 (tree-todos.js holdersByTodo). 할일별에서만 받는다
let holders = new Map();
let holdersTicket = 0;

export async function renderTreeTab() {
  bindControls();
  await reload();
}

async function reload() {
  const payload = await api.getTodoTrees();
  trees = payload.trees;
  links = payload.links ?? [];
  proposalCount = payload.proposals ?? 0;
  nodeByKey = indexNodes(trees);
  draw();
  if (view === VIEW_TODOS) loadHolders();
  if (showProposals) await drawProposals();
}

// 할일별 줄 왼쪽 막대의 재료 — 매니저 탭 보조 세션 목록과 같은 칸(/manager?part=helpers = manager.py 보조 --json,
// 지금 떠 있는 보조 세션과 각 세션이 가장 최근에 연결한 할일). 1초 남짓 걸려 목록을 먼저 그리고 뒤에 얹는다.
// 메인 매니저는 대시보드 훅에서 빠져(매니저 hooks/unless_main.py) 할일을 잡지 않는다 — 막대는 보조 세션만이다
async function loadHolders() {
  const ticket = ++holdersTicket;
  let found;
  try {
    found = holdersByTodo((await api.getManager(HELPERS_PART))[HELPERS_PART]?.items);
  } catch {
    // 매니저가 없거나 받기에 실패하면 막대 없이 — 목록은 그대로 쓸 수 있어야 한다
    found = new Map();
  }
  if (ticket !== holdersTicket) return;
  holders = found;
  if (view !== VIEW_TODOS) return;
  drawSummary();
  drawTodoList();
}

function indexNodes(list) {
  const found = new Map();
  const walk = (nodes) =>
    nodes.forEach((node) => {
      found.set(node.key, node);
      walk(node.children);
    });
  list.forEach((tree) => walk(tree.children));
  return found;
}

function draw() {
  syncControls();
  drawSummary();
  const isMap = view === VIEW_MAP;
  byId("tree-list-pane").hidden = isMap;
  byId("tree-map").hidden = !isMap;
  const showPanel = !isMap && panel != null && treeOf(panel.treeId) != null;
  byId("tree-proposals").hidden = !showProposals;
  byId("tree-panel").hidden = !showPanel;
  byId("tree-splitter").hidden = !showPanel;
  if (isMap) {
    // 숨겨진 칸에서 처음 그리면 크기를 0 으로 재서 맞춤이 틀어진다 — 보인 다음에 그린다
    mapView ??= createTreeMap(byId("tree-map"), { onChange: reload });
    mapView.render(trees, { hideDone, links });
    return;
  }
  if (view === VIEW_TODOS) drawTodoList();
  else drawList();
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
    if (view === VIEW_TODOS) loadHolders();
  });
  byId("tree-hide-done").addEventListener("click", () => {
    hideDone = !hideDone;
    writeStore(HIDE_KEY, String(hideDone));
    draw();
  });
  byId("tree-refresh").addEventListener("click", () => reload());
  byId("tree-proposals-toggle").addEventListener("click", async () => {
    showProposals = !showProposals;
    draw();
    if (showProposals) await drawProposals();
  });
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
  const toggle = byId("tree-proposals-toggle");
  toggle.textContent = t("tree.proposals", { count: proposalCount });
  toggle.setAttribute("aria-pressed", String(showProposals));
  toggle.disabled = !proposalCount && !showProposals;
}

// 판 위 한 줄 — 지금 사람이 봐야 할 것이 몇 개인지
function drawSummary() {
  const legend = byId("tree-legend");
  legend.hidden = true;
  if (view === VIEW_TODOS) {
    const rows = doingTodos(trees);
    const waiting = rows.filter((row) => row.node.waiting).length;
    byId("tree-summary").textContent = t("tree.todoSummary", { count: rows.length, waiting });
    // 막대의 뜻 — 막대가 하나라도 있을 때만
    const held = rows.filter((row) => holders.has(row.node.id)).length;
    legend.hidden = !held;
    byId("tree-legend-text").textContent = t("tree.todoHeldLegend", { count: held });
    return;
  }
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
  const id = treeIdOf(tree);
  const treeName = tree.workspace.name ?? t("common.unassigned");
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
  name.append(element("span", "tree-row-title", treeName));
  name.title = treeName;
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
  if (open) block.appendChild(kidsList(tree, tree.children, 1, null, String(id)));
  return block;
}

// 그 노드 밑에 매달 줄 — 주 상위로 붙은 하위 + 이 노드를 다른 상위로 둔 하위(extra_children)
function kidsOf(node) {
  const extra = (node.extra_children ?? []).map((key) => nodeByKey.get(key)).filter(Boolean);
  return [...node.children, ...extra];
}

// 펼친 줄. 깊이 제한 없이 줄마다 펼친다. 상위가 둘인 할일은 두 상위 밑에 다 나온다 — 그 줄에서
// 지금 매달린 상위를 뺀 나머지를 '다른 상위 N개' 로 알린다. 이 줄의 연결이 제안이면 점선 + 확인·거절.
// results 는 바로 위 할일의 세션 결과물 — 하위 할일 다음에 줄로 붙는다(맵과 달리 접지 않는다)
function kidsList(tree, nodes, depth, parentKey, path, results = []) {
  const list = element("ul", "tree-kids");
  latestFirst(nodes)
    .filter((node) => isVisible(node, { hideDone }))
    .forEach((node) => {
      const here = `${path}>${node.key}`;
      const kids = kidsOf(node).filter((kid) => isVisible(kid, { hideDone }));
      const outputs = node.results ?? [];
      const via = parentKey ? node.parents.find((parent) => parent.key === parentKey) : null;
      // 주 상위가 아닌 자리(다른 상위 밑)는 같은 가지가 두 번 펼쳐지지 않게 처음엔 닫아 둔다
      const fresh = via && !via.primary ? false : depth < OPEN_DEPTH;
      const open = toggled.has(here) ? toggled.get(here) : fresh;
      const item = element("li");
      const row = element("div", "tree-kid-row");
      row.style.setProperty("--depth", depth);
      if (via?.state === PROPOSED) row.classList.add("proposed");
      row.append(kidToggle(here, open, kids.length + outputs.length), kidLine(node, parentKey));
      if (via?.state === PROPOSED) row.appendChild(decideBox(via));
      item.appendChild(row);
      if (open && kids.length + outputs.length) {
        item.appendChild(kidsList(tree, kids, depth + 1, node.key, here, outputs));
      }
      list.appendChild(item);
    });
  results.forEach((result) => list.appendChild(resultRow(result, depth)));
  return list;
}

// 결과물 한 줄 — 배지(로고 + 종류) · 제목 · 동작. 누르면 새 탭으로 열거나(파일은) 담긴 폴더를 연다
function resultRow(result, depth) {
  const view = resultView(result);
  const item = element("li");
  const row = element("div", "tree-kid-row");
  row.style.setProperty("--depth", depth);
  const spacer = element("span", "icon-btn tree-kid-toggle");
  spacer.setAttribute("aria-hidden", "true");
  const line = view.href ? element("a", "tree-result") : element("button", "tree-result");
  line.dataset.kind = view.kind;
  line.title = view.tip;
  if (view.href) {
    line.href = view.href;
    line.target = "_blank";
    line.rel = "noopener noreferrer";
  } else {
    line.type = "button";
    line.disabled = view.missing;
    if (view.missing) line.dataset.missing = "";
    line.addEventListener("click", () => api.openResultFolder(view.folder).catch(() => {}));
  }
  line.append(
    cornerBadge({ logo: view.kind, text: view.kindLabel, className: "tm-result-badge" }),
    element("span", "tree-result-title", view.line)
  );
  if (view.actions) line.appendChild(element("span", "tm-result-action", view.actions));
  row.append(spacer, line);
  item.appendChild(row);
  return item;
}

function kidLine(node, parentKey) {
  const line = element("button", "tree-kid");
  line.type = "button";
  line.dataset.status = node.status;
  if (node.kind === CONTEXT) line.dataset.kind = CONTEXT;
  if (panel?.focusKey === node.key) line.classList.add("active");
  const label = node.kind === CONTEXT ? t("tree.context") : STATUS_LABEL[node.status] ?? node.status;
  line.appendChild(element("span", "tree-kid-status", label));
  if (node.kind !== CONTEXT) line.appendChild(element("span", "tree-kid-id", `#${node.id}`));
  line.append(element("span", "tree-kid-title", node.title), metaLine(node, true, { shownUnder: parentKey }));
  if (node.waiting) line.appendChild(element("span", "tm-waiting", waitingText(node.waiting)));
  if (node.progress.total) {
    line.appendChild(element("span", "tree-kid-num", `${node.progress.done}/${node.progress.total}`));
  }
  const via = parentKey ? node.parents.find((parent) => parent.key === parentKey) : null;
  line.title = via?.evidence ? `${node.title}\n${parentLabel(via)} — ${via.evidence}` : node.title;
  // 패널은 그 할일의 카드가 있는 트리(자기 워크스페이스)를 연다 — 다른 트리의 상위 밑에서 눌러도
  line.addEventListener("click", () =>
    openPanel(node.workspace_id ?? UNASSIGNED_TREE, node.kind === CONTEXT ? null : node.id, node.key)
  );
  return line;
}

function kidToggle(here, open, count) {
  const toggle = element("button", "icon-btn tree-expand tree-kid-toggle");
  toggle.type = "button";
  toggle.title = t("tree.expandNode");
  toggle.setAttribute("aria-label", t("tree.expandNode"));
  toggle.setAttribute("aria-expanded", String(open && count > 0));
  toggle.disabled = !count;
  toggle.appendChild(chevron());
  toggle.addEventListener("click", (event) => {
    event.stopPropagation();
    toggled.set(here, !open);
    drawList();
  });
  return toggle;
}

// 제안 연결 줄의 확인·거절. 근거 문장은 묶음 제목(툴팁)에
function decideBox(link) {
  const box = element("span", "tree-decide");
  box.title = link.evidence ?? "";
  box.append(
    element("span", "tree-decide-label", parentLabel(link)),
    decideButton(link.edge_id, CONFIRMED, t("tree.accept"), "tree-accept"),
    decideButton(link.edge_id, REJECTED, t("tree.reject"), "tree-reject")
  );
  return box;
}

function decideButton(edgeId, state, label, className) {
  const button = element("button", `tree-decide-btn ${className}`, label);
  button.type = "button";
  button.addEventListener("click", async (event) => {
    event.stopPropagation();
    button.disabled = true;
    try {
      await api.updateEdge(edgeId, { state });
    } finally {
      await reload();
    }
  });
  return button;
}

// ── 할일별 ───────────────────────────────────────────────────────────────
// 줄 = #번호 · 제목 · 사람 대기 · 하위 진행률, 그 아래 작게 걸린 트리. 상태는 전부 진행중이라 칩을 뺀다.
// 지금 떠 있는 보조 세션이 잡은 할일은 왼쪽 막대(트리별 행의 카테고리 막대와 같은 모양) + 툴팁에 세션

function drawTodoList() {
  const list = byId("tree-list");
  const rows = doingTodos(trees);
  if (!rows.length) {
    list.replaceChildren(element("p", "tree-empty", t("tree.todoEmpty")));
    return;
  }
  const box = element("ul", "tree-todo-list");
  box.replaceChildren(...rows.map(todoRow));
  list.replaceChildren(box);
}

function todoRow({ node, home, trees: member }) {
  const item = element("li", "tree-todo");
  // 지금 패널이 이 할일을 어느 트리에서 보여 주는지 — 줄과 그 트리 이름을 같이 칠한다
  const shownIn = panel?.focusKey === node.key ? panel.treeId : null;
  if (shownIn != null) item.classList.add("active");
  const held = holders.get(node.id);
  if (held) item.dataset.holder = HOLDER_HELPER;
  const row = element("div", "tree-todo-row");
  row.tabIndex = 0;
  row.setAttribute("role", "button");
  const who = held?.map((holder) => `${holder.label} · ${helperStatusText(holder.status)}`).join(", ");
  row.title = [node.title, who && t("tree.todoHeldBy", { who }), t("tree.todoOpenHint")].filter(Boolean).join("\n");

  const head = element("div", "tree-todo-head");
  head.append(element("span", "tree-kid-id", `#${node.id}`), element("span", "tree-todo-title", node.title));
  if (node.waiting) head.appendChild(element("span", "tm-waiting", waitingText(node.waiting)));
  if (node.progress.total) {
    const num = element("span", "tree-kid-num", `${node.progress.done}/${node.progress.total}`);
    num.title = t("tree.progressHint", node.progress);
    head.appendChild(num);
  }

  const where = element("div", "tree-todo-trees");
  member.forEach((tree, index) => {
    // 자기 트리 다음, 다른 상위로 걸린 트리 앞에 한 번 '연결' 을 적어 둘을 가른다
    if (index === 1) where.appendChild(element("span", "tree-todo-linked", t("tree.todoLinked")));
    where.appendChild(treeChip(node, home, tree, shownIn));
  });

  const choose = () => openTodo(node, home, home);
  row.addEventListener("click", choose);
  row.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      choose();
    }
  });
  row.append(head, where);
  item.appendChild(row);
  return item;
}

// 트리 이름 하나. 카테고리 색 점 + 이름. 누르면 그 트리에서 이 할일을 보인다
function treeChip(node, home, tree, shownIn) {
  const name = tree.name ?? t("common.unassigned");
  const chip = element("button", "tree-todo-tree");
  chip.type = "button";
  if (tree.color) chip.style.setProperty("--cat", tree.color);
  if (tree.proposed) chip.dataset.proposed = "";
  chip.setAttribute("aria-pressed", String(shownIn === tree.id));
  chip.append(element("span", "tree-todo-dot"), element("span", "tree-todo-tree-name", name));
  const parents = tree.via.map((parent) => (parent.id != null ? `#${parent.id} ${parent.title}` : parent.title));
  chip.title = tree.home
    ? t("tree.todoHomeTree", { name })
    : `${tree.proposed ? t("tree.todoProposedTree", { name }) : t("tree.todoLinkedTree", { name })}\n${parents.join("\n")}`;
  chip.addEventListener("click", (event) => {
    event.stopPropagation();
    openTodo(node, home, tree.id);
  });
  // 줄의 Enter·Space 처리가 이 버튼의 누름을 막지 않게
  chip.addEventListener("keydown", (event) => event.stopPropagation());
  return chip;
}

function openTodo(node, home, treeId) {
  openPanel(treeId, node.id, node.key, { home, center: true });
  if (window.matchMedia?.(STACKED).matches) byId("tree-panel").scrollIntoView({ block: "start", behavior: "smooth" });
}

// ── 제안 모음 ─────────────────────────────────────────────────────────────
// 자동·재구성이 만든 확인 대기 연결 전부. 관련처럼 트리에 자리가 없는 제안도 여기서 본다

async function drawProposals() {
  const box = byId("tree-proposals");
  const { proposals } = await api.getProposals();
  if (!proposals.length) {
    box.replaceChildren(element("p", "tree-empty", t("tree.noProposals")));
    return;
  }
  const list = element("ul", "tree-proposal-list");
  proposals.forEach((link) => {
    const item = element("li", "tree-proposal");
    const pair = element("span", "tree-proposal-pair");
    pair.append(
      element("span", "tree-proposal-node", nodeText(link.from, link.from_title)),
      element("span", "tree-proposal-arrow", "→"),
      element("span", "tree-proposal-node", nodeText(link.to, link.to_title))
    );
    pair.title = pair.textContent;
    const why = element("span", "tree-proposal-why", link.evidence ?? "");
    why.title = link.evidence ?? "";
    item.append(
      element("span", "tree-proposal-kind", proposalLabel(link)),
      pair,
      why,
      decideButton(link.id, CONFIRMED, t("tree.accept"), "tree-accept"),
      decideButton(link.id, REJECTED, t("tree.reject"), "tree-reject")
    );
    list.appendChild(item);
  });
  box.replaceChildren(list);
}

function nodeText(key, title) {
  if (/^t\d+$/.test(key)) return `#${key.slice(1)} ${title ?? ""}`;
  if (/^c\d+$/.test(key)) return `${t("tree.context")} · ${title ?? ""}`;
  return title ?? key;
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

function openPanel(treeId, focusId, focusKey = null, { home = null, center = false } = {}) {
  const changed =
    panel?.treeId !== treeId || panel?.focusId !== focusId || panel?.home !== home || panel?.center !== center;
  panel = { treeId, focusId, focusKey: focusKey ?? (focusId != null ? `t${focusId}` : null), home, center };
  // 다른 트리·다른 할일을 고르면 그 대상으로 시점을 새로 잡는다
  if (changed) panelMap = null;
  draw();
}

// 할일별에서 다른 트리를 고르면 그 트리 + 카드가 있는 트리의 가지를 함께 그린다(tree-todos.js panelTrees)
function drawPanel() {
  const shown = panelTrees(trees, panel);
  byId("tree-panel-title").textContent = shown[0].workspace.name ?? t("common.unassigned");
  applyPanelWidth();
  // 그 할일의 상위는 끝났어도 남긴다 — 다른 트리에서 카드로 긋는 선의 시작점이다
  const keepIds = (nodeByKey.get(panel.focusKey)?.parents ?? [])
    .filter((parent) => /^t\d+$/.test(parent.key))
    .map((parent) => Number(parent.key.slice(1)));
  panelMap ??= createTreeMap(byId("tree-panel-map"), {
    onChange: reload,
    focusId: panel.focusId,
    center: panel.center ? "card" : null,
    keepIds,
  });
  panelMap.render(shown, { hideDone, links });
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

function treeOf(treeId) {
  return trees.find((tree) => treeIdOf(tree) === treeId) ?? null;
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
