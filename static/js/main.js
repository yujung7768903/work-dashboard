// 탭 전환과 에러 표시. 각 탭 내용은 해당 모듈이 그림
import { renderBoard } from "./board.js";
import { renderCategories } from "./categories.js";
import { renderWorkspaceTab } from "./workspace.js";

const RENDERERS = {
  board: renderBoard,
  workspace: renderWorkspaceTab,
  categories: renderCategories,
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
  run(RENDERERS[name]);
}

document.getElementById("tabs").addEventListener("click", (event) => {
  const tab = event.target.dataset?.tab;
  if (tab) showTab(tab);
});

showTab("board");
