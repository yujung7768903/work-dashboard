// 상단 우측 언어 메뉴. 지구본 아이콘을 누르면 목록이 열린다 —
// 설정 탭 안에 두면 언어를 못 읽는 사람이 그 탭 이름부터 찾아야 한다.
// 이름은 국기가 아니라 그 언어의 원어 표기로 적는다 (국기는 언어가 아니라 나라다)
import * as api from "./api.js";
import { LANGUAGES, language, t } from "./i18n.js";
import { run } from "./main.js";

// 레일 메뉴와 같은 16 격자 · currentColor 스트로크
const GLOBE_SVG = `<svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true">
  <circle cx="8" cy="8" r="5.6" fill="none" stroke="currentColor" stroke-width="1.5"/>
  <path d="M2.4 8h11.2M8 2.4c1.7 1.6 2.6 3.5 2.6 5.6S9.7 12 8 13.6C6.3 12 5.4 10.1 5.4 8S6.3 4 8 2.4z"
        fill="none" stroke="currentColor" stroke-width="1.5"
        stroke-linecap="round" stroke-linejoin="round"/>
</svg>`;
const CHECK = "✓";
const BLANK = " "; // 고른 것 표시 자리. 보통 공백은 nowrap 이 접어 세로줄이 어긋난다

let open = false;

export function renderLanguageMenu() {
  const box = document.getElementById("lang-menu");
  if (!box) return;
  box.innerHTML = "";
  box.appendChild(toggle());
  if (open) box.appendChild(items());
}

function toggle() {
  const button = document.createElement("button");
  button.type = "button";
  button.innerHTML = GLOBE_SVG;
  button.title = t("settings.language");
  button.setAttribute("aria-label", t("settings.language"));
  button.setAttribute("aria-haspopup", "menu");
  button.setAttribute("aria-expanded", String(open));
  button.addEventListener("click", (event) => {
    event.stopPropagation();
    open = !open;
    renderLanguageMenu();
  });
  return button;
}

function items() {
  const list = document.createElement("div");
  list.className = "ws-menu-items";
  list.setAttribute("role", "menu");
  LANGUAGES.forEach((item) => {
    const chosen = item.code === language();
    const button = document.createElement("button");
    button.type = "button";
    button.setAttribute("role", "menuitem");
    button.setAttribute("aria-current", String(chosen));
    button.lang = item.code;
    button.textContent = `${chosen ? CHECK : BLANK} ${item.label}`;
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      open = false;
      if (chosen) return renderLanguageMenu();
      // 화면을 다시 띄운다 — 모듈 최상단에서 t() 로 만든 상수까지 다시 만들어야 하는데,
      // 그것들을 되돌리는 코드보다 새로고침 한 줄이 확실하다
      run(async () => {
        await api.updateSettings({ language: item.code });
        location.reload();
      });
    });
    list.appendChild(button);
  });
  return list;
}

function close() {
  if (!open) return;
  open = false;
  renderLanguageMenu();
}

// 밖을 누르거나 Esc 면 닫는다. 보드·워크스페이스 케밥 메뉴와 같은 규칙
document.addEventListener("click", close);
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") close();
});
