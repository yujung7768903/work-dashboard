// 화면 취향 두 가지 — 보드 카드의 열 수와 좌측 레일 접힘. 둘 다 CSS 만 바뀌므로
// 다시 그리지 않는다. 기기마다 다른 값이라 설정(언어)과 달리 서버에 두지 않고 브라우저에 남긴다
import { t } from "./i18n.js";

const COLUMNS_KEY = "board-columns";
const SIDE_KEY = "side-collapsed";
const COLLAPSED = "side-collapsed";
// 처음 열었을 때의 기본 열 수. app.css 의 2컬럼 기준과 같은 값이라야 화면이 안 바뀐 채 시작한다
const WIDE_SCREEN = "(min-width: 1240px)";

function applyColumns(columns) {
  document.body.dataset.boardColumns = columns;
  document.querySelectorAll("#view-columns button").forEach((button) => {
    button.classList.toggle("active", button.dataset.columns === columns);
  });
}

function applySide(collapsed) {
  document.body.classList.toggle(COLLAPSED, collapsed);
  const button = document.getElementById("side-toggle");
  const label = collapsed ? t("nav.expandSide") : t("nav.collapseSide");
  button.title = label;
  button.setAttribute("aria-label", label);
  button.setAttribute("aria-expanded", String(!collapsed));
}

document.getElementById("view-columns").addEventListener("click", (event) => {
  // 버튼 안에 아이콘 svg 가 있어 event.target 이 버튼이 아닐 수 있다
  const columns = event.target.closest("button")?.dataset.columns;
  if (!columns) return;
  localStorage.setItem(COLUMNS_KEY, columns);
  applyColumns(columns);
});

document.getElementById("side-toggle").addEventListener("click", () => {
  const collapsed = !document.body.classList.contains(COLLAPSED);
  localStorage.setItem(SIDE_KEY, String(collapsed));
  applySide(collapsed);
});

applyColumns(
  localStorage.getItem(COLUMNS_KEY) ?? (matchMedia(WIDE_SCREEN).matches ? "2" : "1")
);
applySide(localStorage.getItem(SIDE_KEY) === "true");
