// 탭 전환과 에러 표시. 각 탭 내용은 해당 모듈이 그림
// (이 모듈은 boot.js 가 언어를 확정한 뒤에 들어온다 — 아래 TITLES 가 그때 번역된다)
import { renderBoard, renderShared } from "./board.js";
import { t } from "./i18n.js";
import { renderSettings } from "./settings.js";
import { renderUsage } from "./usage.js";
import { renderWorkspaceTab } from "./workspace.js";
import { renderWorktrees } from "./worktrees.js";

// 보드 안의 하위 탭. 할일과 워크트리는 같은 워크스페이스를 다른 눈으로 보는 화면이라
// 레일 항목을 늘리지 않고 보드 안에서 가른다. 카테고리 라벨까지의 위쪽은 둘이 함께 쓴다
// (renderBoard 는 자기가 renderShared 를 부르므로 여기서 또 부르지 않는다)
const SUBRENDERERS = { todos: renderBoard, worktrees: renderWorktreeSubtab };
let activeSubtab = "todos";

async function renderWorktreeSubtab() {
  await renderShared();
  await renderWorktrees();
}

export function renderBoardTab() {
  document.querySelectorAll("#board-tabs button").forEach((button) => {
    button.classList.toggle("active", button.dataset.subtab === activeSubtab);
  });
  Object.keys(SUBRENDERERS).forEach((key) => {
    document.getElementById(`board-${key}`).hidden = key !== activeSubtab;
  });
  return SUBRENDERERS[activeSubtab]();
}

const RENDERERS = {
  board: renderBoardTab,
  workspace: renderWorkspaceTab,
  settings: renderSettings,
  usage: renderUsage,
};

// 사이드바 최상단과 일치시킨다 — 한도부터 확인하고 들어오는 흐름
const DEFAULT_TAB = "usage";

// 상단 바 제목. 레일 메뉴 라벨과 같은 말을 쓴다
const TITLES = {
  board: t("nav.board"),
  workspace: t("nav.workspace"),
  settings: t("nav.settings"),
  usage: t("nav.usage"),
};

export function showError(message) {
  const box = document.getElementById("error");
  box.textContent = message;
  box.hidden = !message;
}

export async function run(action) {
  try {
    showError("");
    await action();
  } catch (error) {
    showError(error.message);
  }
}

// 주소창의 /board 같은 경로가 곧 탭 이름. 모르는 경로는 기본 탭으로 떨어진다
function tabFromPath() {
  const name = location.pathname.replace(/^\/|\/$/g, "");
  return name in RENDERERS ? name : DEFAULT_TAB;
}

function showTab(name, push = true) {
  // 같은 탭을 다시 눌러도 기록을 쌓지 않는다. 뒤로 가기가 헛돌면 안 된다
  if (push && tabFromPath() !== name) history.pushState({}, "", `/${name}`);
  document.querySelectorAll("#tabs button").forEach((button) => {
    button.classList.toggle("active", button.dataset.tab === name);
  });
  Object.keys(RENDERERS).forEach((key) => {
    document.getElementById(`tab-${key}`).hidden = key !== name;
  });
  document.getElementById("page-title").textContent = TITLES[name];
  run(RENDERERS[name]);
}

// 메뉴 버튼 안에 아이콘 svg 가 있어 event.target 이 버튼이 아닐 수 있다
document.getElementById("tabs").addEventListener("click", (event) => {
  const tab = event.target.closest("button")?.dataset.tab;
  if (tab) showTab(tab);
});

// 하위 탭도 아이콘 svg 를 품고 있어 event.target 이 버튼이 아닐 수 있다
document.getElementById("board-tabs").addEventListener("click", (event) => {
  const subtab = event.target.closest("button")?.dataset.subtab;
  if (!subtab || subtab === activeSubtab) return;
  activeSubtab = subtab;
  run(renderBoardTab);
});

// 뒤로/앞으로 가기는 주소만 바뀌므로 화면을 따라가게 한다
window.addEventListener("popstate", () => showTab(tabFromPath(), false));

// 첫 진입. / 로 들어와도 주소를 기본 탭 경로로 맞춰 새로고침이 제자리로 돌아오게 한다
const initialTab = tabFromPath();
history.replaceState({}, "", `/${initialTab}`);
showTab(initialTab, false);
