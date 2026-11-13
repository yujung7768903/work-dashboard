// 할일 우선순위 표시 — '{이 할일 우선순위}/{열린 할일 중 최고}', 정하지 않았으면 '-'.
// 보드 할일 줄(board.js)과 매니저 탭 결정 대기(manager.js)가 같은 모양을 쓴다. 분모는 부르는 쪽이
// 자기 목록 기준으로 넘긴다 — 보드는 대시보드 할일, 매니저 탭은 매니저 DB 의 열린 할일
import { t } from "./i18n.js";

export function priorityText(priority, max) {
  if (priority == null) return "-";
  return `${priority}/${max ?? "-"}`;
}

export function priorityBadge(priority, max) {
  const node = document.createElement("span");
  node.className = "todo-priority";
  node.textContent = priorityText(priority, max);
  node.title =
    priority == null
      ? t("board.priorityNone")
      : t("board.priorityHint", { priority, max: max ?? "-" });
  return node;
}
