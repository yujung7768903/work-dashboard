// 로컬 폴더 선택기. 할일 케밥의 "시작" 이 위치를 못 정했을 때만 연다.
// 브라우저는 서버 파일시스템의 실제 경로를 못 준다(File System Access API 는 핸들만
// 주고 절대경로를 감춘다) — 그래서 서버가 /api/browse 로 목록을 내려주고, 여기서는
// 그 목록을 폴더 트리처럼 클릭해 내려가게만 한다.
import * as api from "./api.js";

let resolveFn = null;
let currentParent = null;

const dialog = () => document.getElementById("dir-browse-modal");

/** 경로 하나를 고를 때까지 기다린다. 취소하면 null */
export function pickDirectory() {
  return new Promise((resolve) => {
    resolveFn = resolve;
    load(null);
    if (!dialog().open) dialog().showModal();
  });
}

async function load(path) {
  const data = await api.browseDir(path);
  currentParent = data.parent;
  render(data);
}

function render(data) {
  document.getElementById("dir-browse-path").textContent = data.path;
  document.getElementById("dir-browse-up").disabled = !data.parent;
  const select = document.getElementById("dir-browse-select");
  select.disabled = !data.is_git_repo;
  select.onclick = () => dialog().close(data.path);
  const list = document.getElementById("dir-browse-list");
  list.replaceChildren(
    ...data.entries.map((entry) => {
      const row = document.createElement("button");
      row.type = "button";
      row.className = "dir-browse-entry";
      row.textContent = entry.is_git_repo ? `${entry.name} (git)` : entry.name;
      row.addEventListener("click", () => load(entry.path));
      return row;
    })
  );
}

document.getElementById("dir-browse-up").addEventListener("click", () => {
  if (currentParent) load(currentParent);
});

// ESC·X 버튼도 close 이벤트로 온다 — 그때는 select 가 안 지나가 returnValue 가 비어 있다
dialog().addEventListener("close", () => {
  resolveFn?.(dialog().returnValue || null);
  resolveFn = null;
});
