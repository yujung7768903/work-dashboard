// 상단 우측 밝기 메뉴. 언어 메뉴와 같은 자리·같은 모양이다.
// 고른 값은 이 기기에만 남긴다 — 같은 대시보드를 아이패드는 어둡게, 데스크톱은 밝게 보는
// 일이 흔해 서버에 저장하는 언어와 달리 기기마다 달라야 한다.
// 붙이는 곳은 <html data-theme> 하나이고, 첫 칠 전 index.html 의 스크립트가 같은 값을 넣는다
import { t } from "./i18n.js";

const KEY = "theme";
const DARK_SCREEN = "(prefers-color-scheme: dark)";
const CHECK = "✓";
const BLANK = " "; // 고른 것 표시 자리. 보통 공백은 nowrap 이 접어 세로줄이 어긋난다

// 레일 메뉴와 같은 16 격자 · currentColor 스트로크
const ICONS = {
  light: `<svg viewBox="0 0 16 16" width="20" height="20" aria-hidden="true">
    <circle cx="8" cy="8" r="3.2" fill="none" stroke="currentColor" stroke-width="1.5"/>
    <path d="M8 1.4v1.4M8 13.2v1.4M1.4 8h1.4M13.2 8h1.4M3.3 3.3l1 1M11.7 11.7l1 1M12.7 3.3l-1 1M4.3 11.7l-1 1"
          fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
  </svg>`,
  dark: `<svg viewBox="0 0 16 16" width="20" height="20" aria-hidden="true">
    <path d="M13.4 9.8A5.7 5.7 0 0 1 6.2 2.6a5.8 5.8 0 1 0 7.2 7.2z"
          fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/>
  </svg>`,
};

// 목록 순서 = 화면에 보이는 순서. 문구는 부를 때 만든다 — 최상단에서 굳히면 사전이
// 늦게 들어온 자리에서 키가 그대로 보인다
const choices = () => ({
  system: t("theme.system"),
  light: t("theme.light"),
  dark: t("theme.dark"),
});

let open = false;

export function renderThemeMenu() {
  document.documentElement.dataset.theme = brightness();
  const box = document.getElementById("theme-menu");
  if (!box) return;
  box.innerHTML = "";
  box.appendChild(toggle());
  if (open) box.appendChild(items());
}

// 고른 값. 모르는 값(손으로 고친 저장소)은 기기 설정으로 떨어진다
function chosen() {
  const value = localStorage.getItem(KEY);
  return value in choices() ? value : "system";
}

// 실제로 칠할 밝기. 기기 설정을 따를 때만 화면 설정을 읽는다
function brightness() {
  const value = chosen();
  if (value !== "system") return value;
  return matchMedia(DARK_SCREEN).matches ? "dark" : "light";
}

function toggle() {
  const button = document.createElement("button");
  button.type = "button";
  // 지금 화면 밝기를 아이콘으로 보여 준다 — 기기 설정을 따르는 중에도 무엇이 켜져 있는지 보인다
  button.innerHTML = ICONS[brightness()];
  button.title = t("settings.theme");
  button.setAttribute("aria-label", t("settings.theme"));
  button.setAttribute("aria-haspopup", "menu");
  button.setAttribute("aria-expanded", String(open));
  button.addEventListener("click", (event) => {
    event.stopPropagation();
    open = !open;
    renderThemeMenu();
  });
  return button;
}

function items() {
  const list = document.createElement("div");
  list.className = "ws-menu-items";
  list.setAttribute("role", "menu");
  const now = chosen();
  Object.entries(choices()).forEach(([value, label]) => {
    const button = document.createElement("button");
    button.type = "button";
    button.setAttribute("role", "menuitem");
    button.setAttribute("aria-current", String(value === now));
    button.textContent = `${value === now ? CHECK : BLANK} ${label}`;
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      open = false;
      // 색은 CSS 변수로만 갈리므로 언어와 달리 새로고침 없이 그 자리에서 바뀐다
      localStorage.setItem(KEY, value);
      renderThemeMenu();
    });
    list.appendChild(button);
  });
  return list;
}

function close() {
  if (!open) return;
  open = false;
  renderThemeMenu();
}

// 밖을 누르거나 Esc 면 닫는다. 언어·케밥 메뉴와 같은 규칙
document.addEventListener("click", close);
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") close();
});

// 기기 설정을 따르는 중에 그 설정이 바뀌면 화면도 따라간다
matchMedia(DARK_SCREEN).addEventListener("change", () => {
  if (chosen() === "system") renderThemeMenu();
});
