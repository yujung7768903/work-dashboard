// 자율 수행 패널. 켜짐 여부와 최근 실행한 할일을 보여준다. 세션 패널과 같은 폴링 방식
import * as api from "./api.js";
import { formatAge, openDetail } from "./sessions.js";

const POLL_INTERVAL_MS = 5000;
// 크론 주기는 crontab 이 정하고 이 값은 화면 표시용 상수다 — README "크론" 참고
const TICK_LABEL = "5분마다";
const NO_WORKSPACE = "미분류";
const RUNNING_LABEL = "진행 중";
// review = 잡은 끝났고 사람이 diff 를 보고 병합을 판정할 차례. 진행 중(클로드가 아직
// 돌고 있음)과 섞이면 목록에서 무엇을 봐야 하는지 알 수 없어 배지를 따로 둔다
const OUTCOME_LABELS = { done: "완료", review: "확인 필요", failed: "실패", blocked: "막힘" };
const REVIEW = "review";
const REVIEW_HINT = "변경을 확인·병합했으면 눌러 완료로 내린다";

let timer = null;

export async function renderAutorun() {
  const { state, runs } = await api.getAutorun();
  document.getElementById("autorun-dot").classList.toggle("on", Boolean(state.enabled));
  document.getElementById("autorun-cycle").textContent = TICK_LABEL;

  const list = document.getElementById("autorun-list");
  list.innerHTML = "";
  runs.forEach((run) => list.appendChild(runRow(run)));
}

function runRow(run) {
  const item = document.createElement("li");
  const scope = element("span", "scope", run.workspace_name || NO_WORKSPACE);
  const title = element("span", "prompt", run.todo_title);
  const outcome = outcomeBadge(run);
  const age = element("span", "age", formatAge(run.started_at));
  item.append(scope, title, outcome, age);
  // 세션 줄·보드 카드와 같은 팝업. 실행 단위가 할일이라 할일로 열어 개요 탭부터 보여준다
  item.addEventListener("click", () => openDetail({ todo: { id: run.todo_id } }));
  return item;
}

// 확인 필요만 누를 수 있는 버튼이다 — 다른 결과는 사람이 내릴 것이 없다
function outcomeBadge(run) {
  const label = run.outcome
    ? (OUTCOME_LABELS[run.outcome] ?? run.outcome)
    : RUNNING_LABEL;
  const className = `badge outcome-${run.outcome || "running"}`;
  if (run.outcome !== REVIEW) return element("span", className, label);
  const button = element("button", className, label);
  button.type = "button";
  button.title = REVIEW_HINT;
  button.addEventListener("click", (event) => {
    // 줄 클릭은 상세 팝업이라 여기서 멈춘다 — 확인하려고 눌렀는데 팝업이 뜨면 안 된다
    event.stopPropagation();
    api
      .confirmAutorunRun(run.id)
      .then(() => renderAutorun())
      .catch((error) => {
        button.title = error.message;
      });
  });
  return button;
}

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

export function startAutorunPolling() {
  if (timer) clearInterval(timer);
  // 폴링 실패는 삼킨다 — 세션 패널과 같은 규칙
  const tick = () => renderAutorun().catch(() => {});
  tick();
  timer = setInterval(tick, POLL_INTERVAL_MS);
}
