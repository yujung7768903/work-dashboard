// 선행 대기 — 다른 매니저 할일이 먼저 끝나야 할 수 있는 할일(매니저 task update --after). 사용자 결정을 기다리는
// 결정 대기와 다른 칩으로 보이고, 사전 조건 할일(제목·상태)을 줄로 늘어놓아 누르면 그 할일 팝업을 연다.
// 매니저 탭(manager.js)과 할일 상세(sessions.js)가 같이 쓴다. 팝업을 여는 manager.js 는 sessions.js 를 들이므로
// 여기서는 누를 때 동적으로 들인다 — 정적으로 들이면 서로를 들이는 고리가 생긴다
import { t } from "./i18n.js";

// 사전 조건 할일 상태 → (칩 색, 문구). 끝난 것(done·invalid)만 풀린 것이다 — 확인 대기는 아직이다.
// 키를 문자열 그대로 둔다 — 사전 점검(tests/test_language.py)이 코드에서 키를 찾는다
const STATUS = {
  open: ["waiting", () => t("prereq.status.open")],
  confirm: ["confirm", () => t("prereq.status.confirm")],
  done: ["ok", () => t("prereq.status.done")],
  invalid: ["", () => t("prereq.status.invalid")],
};
const MISSING = ["failed", () => t("prereq.status.missing")];

/** 선행 대기 칩 — 결정 대기(waiting)와 다른 색 */
export function prereqChip() {
  return element("span", "mgr-chip prereq", t("manager.statePrereq"));
}

/** 끝나지 않은 사전 조건을 한 줄로 — '#168 · #169 끝나야 함' */
export function prereqSummary(prereqs) {
  const left = (prereqs || []).filter((item) => !item.finished).map((item) => `#${item.id}`);
  return left.length ? t("prereq.waitingOn", { ids: left.join(" · ") }) : "";
}

/** 사전 조건 할일 목록. 줄을 누르면 그 매니저 할일 팝업을 연다 */
export function prereqList(prereqs) {
  const list = element("ul", "prereq-list");
  for (const item of prereqs || []) {
    const [tone, label] = item.status ? STATUS[item.status] ?? ["", () => item.status] : MISSING;
    const line = element("li", `prereq-item${item.finished ? " finished" : ""}`);
    const button = element("button", "prereq-open");
    button.type = "button";
    button.title = t("prereq.open");
    button.append(element("span", "prereq-title", `#${item.id} ${item.title ?? t("prereq.missingTitle")}`));
    button.append(element("span", `mgr-chip ${tone}`.trim(), label()));
    button.addEventListener("click", (event) => {
      event.stopPropagation?.();
      openTask(item.id);
    });
    line.append(button);
    list.append(line);
  }
  return list;
}

async function openTask(id) {
  try {
    const manager = await import("./manager.js");
    await manager.openManagerTask(id);
  } catch (error) {
    globalThis.alert?.(t("prereq.openFailed", { error: error.message }));
  }
}

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}
