// 자율 수행 패널. 켜짐 여부와 최근 실행한 할일을 보여준다. 세션 패널과 같은 폴링 방식
import * as api from "./api.js";
import { formatAge, openDetail } from "./sessions.js";

const POLL_INTERVAL_MS = 5000;
// 크론 주기는 crontab 이 정하고 이 값은 화면 표시용 상수다 — README "크론" 참고
const TICK_LABEL = "5분마다";
const NO_TICK = "마지막 수행 없음";
const NO_WORKSPACE = "미분류";
const RUNNING_LABEL = "진행 중";
// review = 잡은 끝났고 사람이 diff 를 보고 병합을 판정할 차례. 진행 중(클로드가 아직
// 돌고 있음)과 섞이면 목록에서 무엇을 봐야 하는지 알 수 없어 배지를 따로 둔다
// requested = 세션이 실패한 게 아니라 판단(기획 공백·방향 미정·정보 부족)을 요청하고
// 스스로 멈춘 것. 사유는 autorun-request 로 남긴 텍스트라 배지 마우스오버로 보여준다
const OUTCOME_LABELS = {
  done: "완료", review: "확인 필요", failed: "실패", blocked: "막힘", requested: "요청",
};
const REVIEW = "review";
const REQUESTED = "requested";
const REVIEW_HINT = "변경을 확인·병합했으면 눌러 완료로 내린다";
const TOGGLE_HINT = "자율 수행 켜기·끄기";

let timer = null;
let bound = false;

export async function renderAutorun() {
  const { state, runs } = await api.getAutorun();
  paint(state, runs);
}

function paint(state, runs) {
  document.getElementById("autorun-toggle").checked = Boolean(state.enabled);
  // 주기만으로는 크론이 실제로 돌고 있는지 알 수 없다. 마지막 tick 이 5분을 한참
  // 넘겼으면 크론이 죽은 것이다 — 목록의 실행 이력과 달리 tick 은 여기서만 보인다
  // 켜져 있는데 아무것도 안 뜨는 이유(후보 없음·사용률·워킹트리 더러움)는 tick 만 안다.
  // 사유가 없으면 붙이지 않는다 — 이 열을 받기 전 DB 는 NULL 이다
  const reason = state.last_tick_reason ? ` · ${state.last_tick_reason}` : "";
  document.getElementById("autorun-cycle").textContent = state.last_tick_at
    ? `${TICK_LABEL} | 마지막 수행 ${formatAge(state.last_tick_at)} 전${reason}`
    : `${TICK_LABEL} | ${NO_TICK}`;

  const list = document.getElementById("autorun-list");
  list.innerHTML = "";
  runs.forEach((run) => list.appendChild(runRow(run)));
}

// 스위치를 켜고 끄면 autorun_state 가 바뀐다 — CLI 의 dash.py autorun on|off 와 같은 곳
function bindToggle() {
  // 보드를 다시 그릴 때마다 폴링이 다시 시작한다. 두 번 붙으면 한 번 눌러 두 번 나간다
  if (bound) return;
  bound = true;
  const label = document.getElementById("autorun-switch");
  const toggle = document.getElementById("autorun-toggle");
  // summary 안이라 막지 않으면 스위치를 누를 때마다 패널이 접혔다 펴진다
  label.addEventListener("click", (event) => event.stopPropagation());
  toggle.addEventListener("change", () => {
    label.title = TOGGLE_HINT;
    api
      .setAutorun(toggle.checked)
      .then(({ state, runs }) => paint(state, runs))
      .catch((error) => {
        // 서버가 안 받았으면 스위치도 원래대로 — 켠 줄 알고 자리를 뜨면 안 된다
        toggle.checked = !toggle.checked;
        label.title = error.message;
      });
  });
}

function runRow(run) {
  const item = document.createElement("li");
  const scope = element("span", "scope", run.workspace_name || NO_WORKSPACE);
  const title = element("span", "prompt", run.todo_title);
  const worktree = element("span", "wt", run.worktree || "");
  worktree.title = run.worktree_path || "";
  const ports = element("span", "ports");
  ports.append(...(run.ports || []).map(portLink));
  const outcome = outcomeBadge(run);
  const age = element("span", "age", formatAge(run.started_at));
  item.append(scope, title, worktree, ports, outcome, age);
  // 세션 줄·보드 카드와 같은 팝업. 실행 단위가 할일이라 할일로 열어 개요 탭부터 보여준다
  item.addEventListener("click", () => openDetail({ todo: { id: run.todo_id } }));
  return item;
}

// 워크트리 탭과 같은 규칙 — 포트를 누르면 그 서버가 새 탭에서 열린다
function portLink(port) {
  const link = element("a", "port", `:${port}`);
  link.href = `http://localhost:${port}`;
  link.target = "_blank";
  link.rel = "noopener";
  // 줄 클릭은 상세 팝업이라 여기서 멈춘다 — 서버를 보려고 눌렀는데 팝업이 뜨면 안 된다
  link.addEventListener("click", (event) => event.stopPropagation());
  return link;
}

// 확인 필요만 누를 수 있는 버튼이다 — 다른 결과는 사람이 내릴 것이 없다
function outcomeBadge(run) {
  const label = run.outcome
    ? (OUTCOME_LABELS[run.outcome] ?? run.outcome)
    : RUNNING_LABEL;
  const className = `badge outcome-${run.outcome || "running"}`;
  if (run.outcome === REQUESTED) {
    const badge = element("span", className, label);
    if (run.requested_note) badge.title = run.requested_note;
    return badge;
  }
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
  bindToggle();
  // 폴링 실패는 삼킨다 — 세션 패널과 같은 규칙
  const tick = () => renderAutorun().catch(() => {});
  tick();
  timer = setInterval(tick, POLL_INTERVAL_MS);
}
