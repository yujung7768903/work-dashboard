// 로컬 폴더 선택기. 할일 케밥의 "시작" 이 위치를 못 정했을 때만 연다.
// 브라우저는 서버 파일시스템의 실제 경로를 못 준다(File System Access API 는 핸들만
// 주고 절대경로를 감춘다) — 그래서 서버가 /api/browse 로 목록을 내려주고, 여기서는
// 그 목록을 빵부스러기(breadcrumb)로 내려가게 한다. Figma "다른 이름으로 저장"
// 다이얼로그처럼 — 위로 한 칸씩 누르는 대신 지나온 폴더 이름을 바로 눌러 되돌아간다.
import * as api from "./api.js";
import { t } from "./i18n.js";

const FOLDER_SVG = `<svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
  <path d="M2 5.2h3.6l1.1 1.4H14v6.1a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1z"
        fill="none" stroke="currentColor" stroke-width="1.3"
        stroke-linejoin="round" stroke-linecap="round"/>
</svg>`;

let resolveFn = null;

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
  renderCrumbs(data.path);
  renderList(data);
  const select = document.getElementById("dir-browse-select");
  select.disabled = !data.is_git_repo;
  select.onclick = () => dialog().close(data.path);
}

// "/home/user/work" → [home, user, work] 빵부스러기. 마지막(지금 폴더)은 누를 수
// 없게 막아 "여기가 지금 있는 곳" 을 보여준다 — 나머지는 눌러 그 조상으로 곧장 간다
function renderCrumbs(path) {
  const parts = path.split("/").filter(Boolean);
  const crumb = (label, target, disabled) => {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = label;
    button.disabled = disabled;
    if (!disabled) button.addEventListener("click", () => load(target));
    return button;
  };
  const rows = parts.map((part, index) =>
    crumb(part, "/" + parts.slice(0, index + 1).join("/"), index === parts.length - 1)
  );
  document
    .getElementById("dir-browse-crumbs")
    .replaceChildren(crumb("/", "/", path === "/"), ...rows);
}

function renderList(data) {
  const list = document.getElementById("dir-browse-list");
  if (!data.entries.length) {
    const empty = document.createElement("p");
    empty.className = "dir-browse-empty";
    empty.textContent = t("board.dirBrowseEmpty");
    list.replaceChildren(empty);
    return;
  }
  list.replaceChildren(...data.entries.map(entryRow));
}

function entryRow(entry) {
  const row = document.createElement("button");
  row.type = "button";
  row.className = "dir-browse-entry";
  const icon = document.createElement("span");
  icon.className = "dir-browse-icon";
  icon.innerHTML = FOLDER_SVG;
  const name = document.createElement("span");
  name.className = "dir-browse-name";
  name.textContent = entry.name;
  row.append(icon, name);
  if (entry.is_git_repo) {
    const badge = document.createElement("span");
    badge.className = "dir-browse-badge";
    badge.textContent = "git";
    row.appendChild(badge);
  }
  row.addEventListener("click", () => load(entry.path));
  return row;
}

// ESC·X 버튼도 close 이벤트로 온다 — 그때는 select 가 안 지나가 returnValue 가 비어 있다
dialog().addEventListener("close", () => {
  resolveFn?.(dialog().returnValue || null);
  resolveFn = null;
});
