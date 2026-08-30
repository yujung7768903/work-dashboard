// 보드의 워크트리 하위 탭. 워크스페이스마다 저장소 하나, 그 아래 브랜치·워크트리 행
import * as api from "./api.js";
import { CHEVRON_SVG, currentCategoryId } from "./board.js";
import { fromKorean, t } from "./i18n.js";
import { run } from "./main.js";
import { openDetail } from "./sessions.js";
import { loadingSpinner } from "./spinner.js";
import { menuItem } from "./workspace.js";

const GROUP_BY_WORKSPACE = "workspace";
const GROUP_BY_PROJECT = "project";
// 기기마다 다른 취향이라 서버가 아니라 브라우저에 남긴다 (layout.js 의 1열/2열·레일 접기와 같은 방식)
const VIEW_KEY = "worktree-view";

const NO_REPO = {
  [GROUP_BY_WORKSPACE]: t("worktree.noRepo"),
  [GROUP_BY_PROJECT]: t("worktree.noRepoProject"),
};
const NO_MATCH = t("worktree.noMatch");
// 줄마다 배지를 다는 대신 섹션으로 가른다 — 워크스페이스 카드가 배경·목적·목표를
// 라벨로 나누는 것과 같은 방식
const SECTIONS = [
  ["base", t("worktree.sectionBase")],
  ["worktree", t("common.worktree")],
  ["branch", t("worktree.sectionBranch")],
];

// 펼쳐 둔 행. 저장소가 달라도 브랜치 이름은 겹칠 수 있어 저장소까지 함께 키로 쓴다
const expandedRows = new Set();

// 케밥 메뉴가 열려 있는 행 키. 한 번에 하나만 연다
let openMenuKey = null;

const rowKey = (repo, branch) => `${repo} ${branch}`;

// 마지막으로 받아 둔 응답. 한 번 부르는 데 git·lsof 로 0.4 초가 걸리므로,
// 서버 데이터가 그대로인 조작(커밋 토글·라벨 전환)은 이걸로 다시 그린다
let cached = null;

// 지금 뷰 모드. 저장해 둔 값이 없으면 워크스페이스별(기존 기본)
let groupBy = localStorage.getItem(VIEW_KEY) === GROUP_BY_PROJECT
  ? GROUP_BY_PROJECT
  : GROUP_BY_WORKSPACE;

export async function renderWorktrees() {
  // 들고 있는 게 있으면 먼저 그려 두고, 새로 받아 한 번 더 그린다.
  // 없으면 빈 칸 대신 도는 원을 세운다 — 한 번 받는 데 0.4 초가 걸린다
  if (cached) draw(cached);
  else drawLoading();
  cached = (await api.getWorktrees(groupBy)).groups;
  draw(cached);
}

function drawLoading() {
  syncViewButtons();
  const container = document.getElementById("worktree-list");
  container.innerHTML = "";
  container.appendChild(loadingSpinner(container));
}

function draw(groups) {
  syncViewButtons();
  const container = document.getElementById("worktree-list");
  container.innerHTML = "";
  // 카테고리 라벨은 할일 탭과 같은 것을 쓴다 — 고른 라벨의 워크스페이스만 남는다.
  // 프로젝트별은 워크스페이스에 안 걸린 저장소까지 보여주는 게 목적이라 이 필터를 안 탄다
  const visible = groupBy === GROUP_BY_PROJECT ? groups : groups.filter(inActiveCategory);
  if (!visible.length) {
    container.textContent = groups.length ? NO_MATCH : NO_REPO[groupBy];
    return;
  }
  visible.forEach((group) => container.appendChild(groupElement(group)));
}

function syncViewButtons() {
  document.querySelectorAll("#worktree-view button").forEach((button) => {
    button.classList.toggle("active", button.dataset.view === groupBy);
  });
}

function inActiveCategory(group) {
  const active = currentCategoryId();
  return active === null || group.category_id === active;
}

document.getElementById("worktree-view").addEventListener("click", (event) => {
  const view = event.target.closest("button")?.dataset.view;
  if (!view || view === groupBy) return;
  groupBy = view;
  localStorage.setItem(VIEW_KEY, view);
  // 뷰가 바뀌면 그룹 자체가 달라져 캐시로는 그릴 수 없다
  cached = null;
  run(renderWorktrees);
});

// 보드 카드와 같은 .group 껍데기. 상단 배경도 그 워크스페이스의 카테고리 색
function groupElement(group) {
  const details = document.createElement("details");
  details.open = true;
  details.className = "group";
  if (group.category_color) details.style.setProperty("--cat", group.category_color);

  const summary = document.createElement("summary");
  const name = document.createElement("span");
  name.textContent = group.name;
  const meta = document.createElement("span");
  meta.className = "group-meta";
  meta.textContent = [
    group.category_name,
    t("worktree.groupMeta", { count: group.rows.length, base: group.base }),
    group.hidden_branches ? t("worktree.hiddenBranches", { count: group.hidden_branches }) : "",
  ]
    .filter(Boolean)
    .join("  ");
  meta.title = group.repo;
  summary.append(name, meta);
  details.appendChild(summary);

  SECTIONS.forEach(([kind, label]) => {
    const rows = group.rows.filter((row) => sectionOf(row) === kind);
    if (rows.length) details.appendChild(sectionElement(group, label, rows));
  });
  return details;
}

function sectionOf(row) {
  if (row.is_base) return "base";
  return row.path ? "worktree" : "branch";
}

function sectionElement(group, label, rows) {
  const section = document.createElement("div");
  section.className = "wt-section";
  const heading = document.createElement("p");
  heading.className = "label";
  heading.textContent = label;
  section.appendChild(heading);
  rows.forEach((row) => {
    section.appendChild(rowElement(group, row));
    if (expandedRows.has(rowKey(group.repo, row.branch))) {
      section.appendChild(commitList(row));
    }
  });
  return section;
}

// 표의 한 줄 — 이름 / 요약 / 커밋 변화 / 포트 네 칸. 칸 나누기는 CSS 격자가 맡는다
function rowElement(group, row) {
  const element = document.createElement("div");
  element.className = "wt-row";

  const name = document.createElement("span");
  name.className = "wt-name";
  // 칸이 좁으면 이름이 잘리므로 툴팁에 전체 이름을, 워크트리면 그 경로까지 담는다
  name.title = [row.branch, row.path].filter(Boolean).join("\n");
  const title = document.createElement("span");
  title.className = "title";
  title.textContent = row.branch;
  name.append(commitToggle(group, row), title);

  const summary = document.createElement("span");
  summary.className = "wt-summary";
  summary.textContent = row.summary;
  summary.title = row.summary;

  const ports = document.createElement("span");
  ports.className = "wt-ports";
  ports.append(...portLinks(row));

  element.append(name, summary, divergence(row), ports, actionCell(group, row));
  // 클릭은 이름 칸까지만 — 줄 전체를 누를 수 있으면 요약·포트 칸의 빈 공간까지 팝업이
  // 열려 무엇을 누르는 칸인지 알 수 없다. 연결된 할일이 없는 줄은 아예 안 눌린다
  if (row.todo_id) {
    name.classList.add("linked");
    name.addEventListener("click", () => openDetail({ todo: { id: row.todo_id } }));
  }
  return element;
}

// 다섯째 칸 — 워크트리 행에만 케밥 메뉴. 디폴트·브랜치 행은 지울 워크트리가 없어 빈 칸
function actionCell(group, row) {
  if (!row.path) return document.createElement("span");
  return rowMenu(group, row);
}

// 서버 실행·재실행·중지, 적용(병합)·삭제(버림). 할일 카드의 ws-menu 재사용
function rowMenu(group, row) {
  const key = rowKey(group.repo, row.branch);
  const wrapper = document.createElement("div");
  wrapper.className = "ws-menu";
  const toggle = document.createElement("button");
  // kebab: 보드 케밥과 같은 보정을 받는다 (app.css 의 .kebab 참고)
  toggle.className = "kebab";
  toggle.textContent = "⋮";
  toggle.title = t("worktree.rowMenu");
  toggle.addEventListener("click", (event) => {
    event.stopPropagation();
    openMenuKey = openMenuKey === key ? null : key;
    draw(cached);
  });
  wrapper.appendChild(toggle);
  if (openMenuKey === key) wrapper.appendChild(rowMenuItems(group, row));
  return wrapper;
}

function rowMenuItems(group, row) {
  const items = document.createElement("div");
  items.className = "ws-menu-items";
  items.append(
    ...serveItems(group, row),
    menuItem(t("worktree.apply"), () =>
      runRowAction(() => api.applyWorktree(group.repo, row.branch),
        t("worktree.confirmApply",
          { branch: row.branch, base: group.base })
      )
    ),
    menuItem(t("worktree.discard"), () =>
      runRowAction(() => api.discardWorktree(group.repo, row.branch),
        t("worktree.confirmDiscard",
          { branch: row.branch })
      )
    )
  );
  return items;
}

// 실행·재실행·중지 셋을 항상 보여준다. 지금 안 떠 있으면 재실행은 실행과 같고
// 중지는 죽일 게 없어 아무 일도 일어나지 않는다 — 상태에 따라 항목이 사라지면
// 눌러 보기 전에 무엇을 할 수 있는 메뉴인지 알 수 없다
function serveItems(group, row) {
  const item = (label, action, confirmMessage) =>
    menuItem(label, () =>
      runRowAction(() => api.controlWorktree(group.repo, row.branch, action), confirmMessage)
    );
  // 실행만 확인창이 없다. 나머지 둘은 남의 화면을 끊을 수 있다 —
  // 다른 세션이 그 포트를 보고 있을 수 있어 되묻는다
  const target = servingPorts(row) || `"${row.branch}"`;
  return [
    item(t("worktree.serveStart"), "start"),
    item(t("worktree.serveRestart"), "restart", t("worktree.confirmRestart", { target })),
    item(t("worktree.serveStop"), "stop", t("worktree.confirmStop", { target })),
  ];
}

// 그 줄이 지금 듣고 있는 포트 ":9081, :9082". 떠 있는 게 없으면 빈 문자열
function servingPorts(row) {
  const ports = row.processes.flatMap((process) => process.ports);
  return ports.length ? `:${ports.join(", :")}` : "";
}

// 메뉴 항목 다섯 개가 확인창 → API 호출 → 목록 다시 받기로 흐름이 같다.
// 확인창이 없는 항목(실행)은 confirmMessage 를 넘기지 않는다
function runRowAction(call, confirmMessage) {
  return run(async () => {
    openMenuKey = null;
    if (confirmMessage && !confirm(confirmMessage)) {
      draw(cached);
      return;
    }
    const result = await call();
    // 병합·삭제로 커밋·워크트리 목록 자체가 바뀌어 캐시로는 다시 그릴 수 없다
    cached = null;
    await renderWorktrees();
    // 알림은 목록을 다시 그린 **뒤에**. alert 는 화면을 멈추므로 먼저 띄우면
    // 확인을 누른 다음에야 포트 배지가 붙어 한 박자 늦게 보인다.
    // 병합이 끊은 세션, 서버 실행·중지 결과가 다 message 로 온다 —
    // 실행은 몇 초 걸리고 끝나도 배지만 조용히 붙어 완료 여부를 알 수 없다
    // 서버가 한국어로 적어 준 문장이라 사전에서 되짚어 지금 언어로 옮긴다
    const notice = result?.message;
    if (notice) alert(fromKorean(notice));
  });
}

// 앞섬·뒤처짐이 각자 칸을 지킨다. 한쪽이 0 이면 칸만 비워 다른 쪽이 밀리지 않는다
function divergence(row) {
  const box = document.createElement("span");
  box.className = "wt-div";
  box.append(
    count("ahead", row.ahead, t("worktree.ahead", { count: row.ahead })),
    count("behind", row.behind, t("worktree.behind", { count: row.behind }))
  );
  return box;
}

function count(kind, value, title) {
  const node = document.createElement("span");
  node.className = kind;
  if (!value) return node;
  node.textContent = `${kind === "ahead" ? "↑" : "↓"}${value}`;
  node.title = title;
  return node;
}

function portLinks(row) {
  return row.processes.flatMap((process) =>
    process.ports.map((port) => portLink(port, process))
  );
}

// 포트를 누르면 그 워크트리가 띄운 서버가 새 탭에서 열린다
function portLink(port, process) {
  const link = document.createElement("a");
  link.className = "wt-port";
  link.textContent = `:${port}`;
  link.href = `http://localhost:${port}`;
  link.target = "_blank";
  link.rel = "noopener";
  link.title = t("worktree.portLink", {
    command: process.command,
    pid: process.pid,
  });
  // 줄 클릭은 할일 상세를 여니, 포트 배지는 그 클릭이 거기까지 올라가지 않게 막는다
  link.addEventListener("click", (event) => event.stopPropagation());
  return link;
}

// 커밋이 없는 줄도 자리를 비워 브랜치 세로줄을 맞춘다
function commitToggle(group, row) {
  const button = document.createElement("button");
  button.className = "row-toggle";
  button.innerHTML = CHEVRON_SVG;
  if (!row.commits.length) {
    button.classList.add("empty");
    return button;
  }
  const key = rowKey(group.repo, row.branch);
  const open = expandedRows.has(key);
  button.classList.toggle("open", open);
  button.title = t("worktree.commitToggle", {
    base: group.base,
    count: row.commits.length,
  });
  button.addEventListener("click", (event) => {
    // 줄 클릭은 할일 상세를 여니, 셰브런은 그 클릭이 거기까지 올라가지 않게 막는다
    event.stopPropagation();
    if (open) expandedRows.delete(key);
    else expandedRows.add(key);
    // 커밋은 이미 받아 둔 응답에 들어 있다 — 서버에 다시 묻지 않는다
    draw(cached);
  });
  return button;
}

function commitList(row) {
  const list = document.createElement("ul");
  list.className = "wt-commits";
  row.commits.forEach((commit) => {
    const item = document.createElement("li");
    const hash = document.createElement("code");
    hash.textContent = commit.hash;
    const when = document.createElement("span");
    when.className = "wt-when";
    when.textContent = commit.at.slice(5, 10); // '2026-08-01T…' → '08-01'
    item.append(hash, document.createTextNode(` ${commit.subject} `), when);
    list.appendChild(item);
  });
  return list;
}

// 메뉴 밖을 누르면 열린 케밥 메뉴 닫기
document.addEventListener("click", () => {
  if (openMenuKey === null) return;
  openMenuKey = null;
  draw(cached);
});
