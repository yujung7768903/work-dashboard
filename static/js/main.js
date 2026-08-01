// 탭 전환과 에러 표시. 각 탭 내용은 해당 모듈이 그림
import { renderBoard } from "./board.js";
import { renderCategories } from "./categories.js";
import { renderUsage } from "./usage.js";
import { renderWorkspaceTab } from "./workspace.js";

const RENDERERS = {
  board: renderBoard,
  workspace: renderWorkspaceTab,
  categories: renderCategories,
  usage: renderUsage,
};

// 사이드바 최상단과 일치시킨다 — 한도부터 확인하고 들어오는 흐름
const DEFAULT_TAB = "usage";

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

// 뒤로/앞으로 가기는 주소만 바뀌므로 화면을 따라가게 한다
window.addEventListener("popstate", () => showTab(tabFromPath(), false));

// 첫 진입. / 로 들어와도 주소를 기본 탭 경로로 맞춰 새로고침이 제자리로 돌아오게 한다
const initialTab = tabFromPath();
history.replaceState({}, "", `/${initialTab}`);
showTab(initialTab, false);
