// 응답을 기다리는 동안 빈 칸 대신 세우는 도는 원. 목록 위 패널들의 높이가 그때그때
// 달라 화면 아래까지 남은 높이는 CSS 가 알 수 없어 여기서 재서 --loading-room 으로 넘긴다
import { t } from "./i18n.js";

export function loadingSpinner(container) {
  const spinner = document.createElement("div");
  spinner.className = "loading-spin";
  spinner.setAttribute("role", "status");
  spinner.setAttribute("aria-label", t("common.loading"));
  const room = Math.max(0, innerHeight - container.getBoundingClientRect().top);
  spinner.style.setProperty("--loading-room", `${room}px`);
  return spinner;
}
