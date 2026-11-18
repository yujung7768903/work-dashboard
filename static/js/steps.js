// 진행 단계 — 매니저 할일이 어느 단계에서 멈췄고 사용자가 무엇을 하면 넘어가는지(manager.py task update --step).
// 사전 조건 목록(prereq.js)과 같은 줄 모양으로 늘어놓고, 멈춘 단계(current)를 강조해 그 줄에 '넘어가려면'을 붙인다.
// slot(답하는 상자)을 주면 멈춘 단계 줄 바로 아래에 넣는다 — 무엇을 보내야 넘어가는지 읽고 바로 쓰게.
// 매니저 탭 팝업(manager.js)과 할일 상세 결정·직접 할 일·선행 대기 카드(decision-answer.js·task-report.js·sessions.js)가 같이 쓴다
import { t } from "./i18n.js";

// 단계 상태 → (칩 색, 문구). 키를 문자열 그대로 둔다 — 사전 점검(tests/test_language.py)이 코드에서 키를 찾는다
const STATUS = {
  done: ["ok", () => t("steps.status.done")],
  current: ["waiting", () => t("steps.status.current")],
  todo: ["", () => t("steps.status.todo")],
};

/** 멈춘 단계 — 없으면 null */
export function currentStep(steps) {
  return (steps || []).find((step) => step.status === "current") ?? null;
}

/** 단계 목록. active 가 거짓이면(닫힌 할일) 멈춘 단계를 강조하지 않는다 — 이미 지난 일이다.
 *  slot 을 주면 멈춘 단계 줄 안, 넘어가는 조건 아래에 넣는다(멈춘 단계가 없으면 넣지 않는다 — 부른 쪽이 따로 둔다) */
export function stepList(steps, { active = true, slot = null } = {}) {
  const list = element("ol", "prereq-list step-list");
  (steps || []).forEach((step, index) => {
    const stuck = active && step.status === "current";
    const line = element("li", `prereq-item step-item step-${step.status}${stuck ? " stuck" : ""}`);
    const head = element("div", "step-line");
    head.append(element("span", "step-no", String(index + 1)), element("span", "prereq-title step-name", step.name));
    // 닫힌 할일은 끝난 단계에만 칩을 단다 — 멈춘·남은 단계의 '멈춤'·'남음'은 이제 사실이 아니다
    if (active || step.status === "done") {
      const [tone, label] = STATUS[step.status] ?? STATUS.todo;
      head.append(element("span", `mgr-chip ${tone}`.trim(), label()));
    }
    line.append(head);
    // 단계 행(할일 통합 뒤)은 끝난 단계에 누가·언제·결과 한 줄이 있다 — 어디까지 왔는지를 이 줄로 읽는다
    const meta = stepMeta(step);
    if (meta) line.append(element("p", "step-meta", meta));
    if (stuck && step.unblock) {
      const how = element("p", "step-unblock");
      how.append(element("span", "dec-label", t("steps.unblock")), document.createTextNode(step.unblock));
      line.append(how);
    }
    if (stuck && slot) line.append(slot);
    list.append(line);
  });
  return list;
}

/** '누가 · 언제 · 결과' — 있는 것만. 예전 진행 단계(JSON)에는 없어서 빈 문자열 */
export function stepMeta(step) {
  if (step.status !== "done") return "";
  return [step.by, shortTime(step.at), step.result].filter(Boolean).join(" · ");
}

// '11-18 14:05' — 단계는 며칠 안에 끝나므로 연도는 뺀다. 못 읽으면 원문 그대로
function shortTime(text) {
  if (!text) return "";
  const when = new Date(text);
  if (Number.isNaN(when.getTime())) return text;
  const pad = (n) => String(n).padStart(2, "0");
  return `${pad(when.getMonth() + 1)}-${pad(when.getDate())} ${pad(when.getHours())}:${pad(when.getMinutes())}`;
}

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}
