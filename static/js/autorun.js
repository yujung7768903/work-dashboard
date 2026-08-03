// 자율 수행 패널. 켜짐 여부와 최근 실행한 할일을 보여준다. 세션 패널과 같은 폴링 방식
import * as api from "./api.js";
import { formatAge } from "./sessions.js";

const POLL_INTERVAL_MS = 5000;
// 크론 주기는 crontab 이 정하고 이 값은 화면 표시용 상수다 — README "크론" 참고
const TICK_LABEL = "5분마다";
const NO_WORKSPACE = "미분류";
const RUNNING_LABEL = "진행 중";
const OUTCOME_LABELS = { done: "완료", failed: "실패", blocked: "막힘" };

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
  const outcome = element(
    "span",
    `badge outcome-${run.outcome || "running"}`,
    run.outcome ? (OUTCOME_LABELS[run.outcome] ?? run.outcome) : RUNNING_LABEL
  );
  const age = element("span", "age", formatAge(run.started_at));
  item.append(scope, title, outcome, age);
  return item;
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
