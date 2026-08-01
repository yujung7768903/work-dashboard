// 탭 전환과 에러 표시. 각 탭 내용은 해당 모듈이 그림
import { renderBoard } from "./board.js";
import { renderCategories } from "./categories.js";
import { renderUsage } from "./usage.js";
import { renderWorkspaceTab } from "./workspace.js";
import { renderWorktrees } from "./worktrees.js";

// 보드 안의 하위 탭. 할일과 워크트리는 같은 워크스페이스를 다른 눈으로 보는 화면이라
// 레일 항목을 늘리지 않고 보드 안에서 가른다
const SUBRENDERERS = { todos: renderBoard, worktrees: renderWorktrees };
let activeSubtab = "todos";

function renderBoardTab() {
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
  categories: renderCategories,
  usage: renderUsage,
};

// 상단 바 제목. 레일 메뉴 라벨과 같은 말을 쓴다
const TITLES = {
  board: "보드",
  workspace: "워크스페이스",
  categories: "카테고리",
  usage: "사용량",
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

function showTab(name) {
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

// 사이드바 최상단과 일치시킨다 — 한도부터 확인하고 들어오는 흐름
showTab("usage");
