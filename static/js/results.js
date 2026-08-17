// 결과물(Result) 메뉴. Claude Artifact 처럼 카드 그리드 + 날짜 필터 + 페이징.
// 코드 이외 산출물(Figma·블로그·Jira 댓글·배포 등)을 워크스페이스와 무관하게 한곳에서 본다
import * as api from "./api.js";
import { t } from "./i18n.js";
import { run } from "./main.js";
import { openDetail } from "./sessions.js";
import { menuItem } from "./workspace.js";

// data-preset="" 는 필터 없음(전체). custom 은 날짜 입력 뒤 적용 버튼을 눌러야 조회된다
const MODE_ALL = "all";
const MODE_CUSTOM = "custom";

let mode = MODE_ALL;
let customFrom = "";
let customTo = "";
let page = 1;
// 케밥 메뉴를 열고 닫을 때 서버를 다시 부르지 않으려고 마지막 응답을 들고 있는다
let cached = null;
let openMenuId = null;

export async function renderResultsTab() {
  const payload = await api.getResults(filterQuery());
  cached = payload;
  openMenuId = null;
  draw(payload);
}

function filterQuery() {
  const query = { page: String(page) };
  if (mode === MODE_CUSTOM) {
    if (customFrom) query.date_from = customFrom;
    if (customTo) query.date_to = customTo;
  } else if (mode !== MODE_ALL) {
    query.preset = mode;
  }
  return query;
}

function draw(payload) {
  syncFilterButtons();
  const list = document.getElementById("results-list");
  list.innerHTML = "";
  if (!payload.items.length) {
    list.textContent = t("result.none");
  } else {
    payload.items.forEach((item) => list.appendChild(resultCard(item)));
  }
  drawPager(payload);
}

function syncFilterButtons() {
  document.querySelectorAll("#results-filter button").forEach((button) => {
    const preset = button.dataset.preset || MODE_ALL;
    button.classList.toggle("active", preset === mode);
  });
}

function drawPager(payload) {
  const pager = document.getElementById("results-pager");
  const totalPages = Math.max(1, Math.ceil(payload.total / payload.page_size));
  pager.hidden = payload.total <= payload.page_size;
  document.getElementById("results-page-label").textContent = t("result.pagerLabel", {
    page: payload.page,
    total: totalPages,
  });
  document.getElementById("results-prev").disabled = payload.page <= 1;
  document.getElementById("results-next").disabled = payload.page >= totalPages;
}

document.getElementById("results-filter").addEventListener("click", (event) => {
  const preset = event.target.closest("button")?.dataset.preset;
  if (preset === undefined) return;
  document.getElementById("results-range").hidden = preset !== MODE_CUSTOM;
  if (preset === MODE_CUSTOM) {
    mode = MODE_CUSTOM;
    syncFilterButtons();
    return; // 날짜 두 값을 받아야 하므로 적용 버튼을 기다린다
  }
  mode = preset || MODE_ALL;
  page = 1;
  run(renderResultsTab);
});

document.getElementById("results-range-apply").addEventListener("click", () => {
  customFrom = document.getElementById("results-date-from").value;
  customTo = document.getElementById("results-date-to").value;
  mode = MODE_CUSTOM;
  page = 1;
  run(renderResultsTab);
});

document.getElementById("results-prev").addEventListener("click", () => {
  if (page <= 1) return;
  page -= 1;
  run(renderResultsTab);
});
document.getElementById("results-next").addEventListener("click", () => {
  page += 1;
  run(renderResultsTab);
});

function resultCard(item) {
  const card = document.createElement("div");
  card.className = "rs-card";
  card.append(cardHead(item), todoLine(item));
  if (item.session_cwd) card.appendChild(element("p", "rs-cwd", item.session_cwd));
  if (item.summary) card.appendChild(element("p", "note-body", item.summary));
  if (item.links.length) card.appendChild(linkList(item.links));
  return card;
}

function cardHead(item) {
  const head = document.createElement("div");
  head.className = "rs-head";
  const text = document.createElement("div");
  text.className = "rs-head-text";
  text.append(element("span", "rs-kind", item.kind), element("span", "rs-when", relativeOrDate(item.updated_at)));
  head.append(text, menu(item));
  return head;
}

// 연결된 할일 — 워크트리 탭의 연결 줄과 같은 규칙으로 클릭하면 그 할일 팝업이 열린다
function todoLine(item) {
  const line = element("p", "rs-todo", `#${item.todo_id} | ${item.todo_title}`);
  line.addEventListener("click", () => openDetail({ todo: { id: item.todo_id } }));
  return line;
}

function linkList(links) {
  const list = document.createElement("ul");
  list.className = "rs-links";
  links.forEach((link) => {
    const item = document.createElement("li");
    const anchor = document.createElement("a");
    anchor.href = link.url;
    anchor.target = "_blank";
    anchor.rel = "noopener";
    anchor.textContent = link.label || link.url;
    item.appendChild(anchor);
    list.appendChild(item);
  });
  return list;
}

function menu(item) {
  const wrapper = document.createElement("div");
  wrapper.className = "ws-menu";
  const toggle = document.createElement("button");
  toggle.type = "button";
  toggle.textContent = "⋮";
  toggle.title = t("worktree.rowMenu");
  toggle.addEventListener("click", (event) => {
    event.stopPropagation();
    openMenuId = openMenuId === item.id ? null : item.id;
    draw(cached);
  });
  wrapper.appendChild(toggle);
  if (openMenuId === item.id) wrapper.appendChild(menuItems(item));
  return wrapper;
}

function menuItems(item) {
  const items = document.createElement("div");
  items.className = "ws-menu-items";
  items.appendChild(
    menuItem(t("common.delete"), () =>
      run(async () => {
        openMenuId = null;
        if (!confirm(t("result.confirmDelete", { kind: item.kind }))) {
          draw(cached);
          return;
        }
        await api.deleteResult(item.id);
        await renderResultsTab();
      })
    )
  );
  return items;
}

// 오늘(UTC 날짜 기준, 서버 필터와 같은 기준)이면 상대 시간, 아니면 YYYY-MM-DD
function relativeOrDate(iso) {
  const ms = Date.parse(iso);
  if (Number.isNaN(ms)) return "";
  const at = new Date(ms);
  const nowDate = new Date();
  const sameDay =
    at.getUTCFullYear() === nowDate.getUTCFullYear() &&
    at.getUTCMonth() === nowDate.getUTCMonth() &&
    at.getUTCDate() === nowDate.getUTCDate();
  if (!sameDay) return isoDate(at);
  const sec = Math.max(0, Math.floor((Date.now() - ms) / 1000));
  if (sec < 60) return t("result.justNow");
  if (sec < 3600) return t("result.minutesAgo", { count: Math.floor(sec / 60) });
  return t("result.hoursAgo", { count: Math.floor(sec / 3600) });
}

function isoDate(date) {
  const pad = (value) => String(value).padStart(2, "0");
  return `${date.getUTCFullYear()}-${pad(date.getUTCMonth() + 1)}-${pad(date.getUTCDate())}`;
}

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

// 카드 밖을 누르면 열린 케밥 메뉴 닫기
document.addEventListener("click", () => {
  if (openMenuId === null) return;
  openMenuId = null;
  if (cached) draw(cached);
});
