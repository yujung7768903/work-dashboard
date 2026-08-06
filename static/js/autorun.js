// 자율 수행 탭. 위에서부터 설정 → 후보 → 실행이고, 실행은 상태별로 끊어 그린다.
// 보드에서 떼어낸 이유 — 결과가 한 목록에 섞이면 사람이 처리할 것(요청·검토 대기)을
// 찾을 수 없고, 후보가 왜 안 도는지도 알 수 없다
import * as api from "./api.js";
import { formatAge, openDetail } from "./sessions.js";

const POLL_INTERVAL_MS = 5000;
// 크론 주기는 crontab 이 정하고 이 값은 화면 표시용 상수다 — README "크론" 참고
const TICK_LABEL = "5분마다";
const NO_TICK = "마지막 수행 없음";
const NO_WORKSPACE = "미분류";
const RUNNING_LABEL = "진행 중";
const NO_CANDIDATE = "auto 라벨이 붙은 할일이 없습니다.";
const NO_RUN = "아직 실행 기록이 없습니다.";
// review = 잡은 끝났고 사람이 diff 를 보고 병합을 판정할 차례. 진행 중(클로드가 아직
// 돌고 있음)과 섞이면 목록에서 무엇을 봐야 하는지 알 수 없어 배지를 따로 둔다
// requested = 세션이 실패한 게 아니라 판단(기획 공백·방향 미정·정보 부족)을 요청하고
// 스스로 멈춘 것. 사유는 autorun-request 로 남긴 텍스트라 배지 마우스오버로 보여준다
const OUTCOME_LABELS = {
  done: "완료", review: "검토 대기", failed: "실패", blocked: "막힘", requested: "요청",
};
const REVIEW = "review";
const REQUESTED = "requested";
const REVIEW_HINT = "변경을 확인·병합했으면 눌러 완료로 내린다";
const TOGGLE_HINT = "자율 수행 켜기·끄기";
const PRECONDITION = "precondition";

// 후보 한 건이 지금 못 도는 이유. 서버 autorun.BLOCKER_* 와 같은 이름을 쓴다.
// 칩에는 — 앞까지만 적고 뒷말은 툴팁으로 — 목록이 사유 문장으로 넘치면 못 읽는다
const BLOCKER_LABELS = {
  ready: "시작 가능",
  blocked: "막힘 — 원인을 보고 그 기록을 지워야 다시 돈다",
  requested: "요청 대기 — 사람이 결정을 남겨야 다시 돈다",
  review: "검토 대기 — 확인 버튼을 눌러야 다시 돈다",
  claimed: "다른 세션이 잡음 — 그 세션이 끝나면 풀린다",
  precondition: "착수 조건 미충족",
};

// 실행 목록의 구획. 사람이 손댈 것부터 위에 온다
const RUN_GROUPS = [
  ["확인 필요", (run) => run.outcome === REQUESTED || run.outcome === REVIEW],
  [RUNNING_LABEL, (run) => !run.outcome],
  ["막힘·실패", (run) => run.outcome === "blocked" || run.outcome === "failed"],
  ["완료", (run) => run.outcome === "done"],
];

let timer = null;
let bound = false;

export async function renderAutorun() {
  const { state, runs, candidates } = await api.getAutorun();
  paint(state, runs, candidates ?? []);
}

function paint(state, runs, candidates) {
  document.getElementById("autorun-toggle").checked = Boolean(state.enabled);
  // 주기만으로는 크론이 실제로 돌고 있는지 알 수 없다. 마지막 tick 이 5분을 한참
  // 넘겼으면 크론이 죽은 것이다 — 목록의 실행 이력과 달리 tick 은 여기서만 보인다.
  // 후보별 사유와 달리 전역 사유(사용률·워킹트리 더러움)는 이 줄에만 있다.
  // 사유가 없으면 붙이지 않는다 — 이 열을 받기 전 DB 는 NULL 이다
  const reason = state.last_tick_reason ? ` · ${state.last_tick_reason}` : "";
  document.getElementById("autorun-cycle").textContent = state.last_tick_at
    ? `${TICK_LABEL} | 마지막 수행 ${formatAge(state.last_tick_at)} 전${reason}`
    : `${TICK_LABEL} | ${NO_TICK}`;

  paintCandidates(candidates);
  paintRuns(runs);
}

function paintCandidates(candidates) {
  const list = document.getElementById("autorun-candidates");
  list.innerHTML = "";
  if (!candidates.length) {
    list.appendChild(emptyRow(NO_CANDIDATE));
    return;
  }
  candidates.forEach((candidate, index) =>
    list.appendChild(candidateRow(candidate, index)),
  );
}

function candidateRow(candidate, index) {
  const item = document.createElement("li");
  item.className = candidate.blocker === "ready" ? "ready" : "held";
  const rank = element("span", "rank", `${index + 1}`);
  const scope = element("span", "scope", candidate.workspace_name || NO_WORKSPACE);
  const title = element("span", "prompt", candidate.title);
  item.append(rank, scope, title, blockerChip(candidate));
  // 세션 줄·보드 카드와 같은 팝업. 착수 조건 체크리스트는 개요 탭에 있다
  item.addEventListener("click", () => openDetail({ todo: { id: candidate.todo_id } }));
  return item;
}

function blockerChip(candidate) {
  const chip = element("span", `badge blocker-${candidate.blocker}`, chipText(candidate));
  chip.title = BLOCKER_LABELS[candidate.blocker] ?? candidate.blocker;
  return chip;
}

// 조건 미충족이면 몇 개 중 몇 개인지까지 적는다 — 무엇을 풀어야 도는지가 그 숫자다
function chipText(candidate) {
  const label = BLOCKER_LABELS[candidate.blocker] ?? candidate.blocker;
  if (candidate.blocker !== PRECONDITION || !candidate.precondition) {
    return label.split(" — ")[0];
  }
  const { met, total, manual } = candidate.precondition;
  return `착수 조건 ${met}/${total}${manual ? ` · 사람 확인 ${manual}` : ""}`;
}

// 스위치를 켜고 끄면 autorun_state 가 바뀐다 — CLI 의 dash.py autorun on|off 와 같은 곳
function bindToggle() {
  // 탭에 들어올 때마다 폴링이 다시 시작한다. 두 번 붙으면 한 번 눌러 두 번 나간다
  if (bound) return;
  bound = true;
  const label = document.getElementById("autorun-switch");
  const toggle = document.getElementById("autorun-toggle");
  label.addEventListener("click", (event) => event.stopPropagation());
  toggle.addEventListener("change", () => {
    label.title = TOGGLE_HINT;
    api
      .setAutorun(toggle.checked)
      .then(({ state, runs, candidates }) => paint(state, runs, candidates ?? []))
      .catch((error) => {
        // 서버가 안 받았으면 스위치도 원래대로 — 켠 줄 알고 자리를 뜨면 안 된다
        toggle.checked = !toggle.checked;
        label.title = error.message;
      });
  });
}

function paintRuns(runs) {
  const list = document.getElementById("autorun-list");
  list.innerHTML = "";
  if (!runs.length) {
    list.appendChild(emptyRow(NO_RUN));
    return;
  }
  RUN_GROUPS.forEach(([label, belongs]) => {
    const rows = runs.filter(belongs);
    if (!rows.length) return;
    list.appendChild(groupRow(label, rows.length));
    rows.forEach((run) => list.appendChild(runRow(run)));
  });
}

function groupRow(label, count) {
  const item = document.createElement("li");
  item.className = "group";
  item.append(element("span", "text", label), element("span", "count", `${count}`));
  return item;
}

function emptyRow(text) {
  const item = document.createElement("li");
  item.className = "empty";
  item.append(element("span", "text", text));
  return item;
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
  const link = element("a", "wt-port", `:${port}`);
  link.href = `http://localhost:${port}`;
  link.target = "_blank";
  link.rel = "noopener";
  // 줄 클릭은 상세 팝업이라 여기서 멈춘다 — 서버를 보려고 눌렀는데 팝업이 뜨면 안 된다
  link.addEventListener("click", (event) => event.stopPropagation());
  return link;
}

// 검토 대기만 누를 수 있는 버튼이다 — 다른 결과는 사람이 내릴 것이 없다
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

export function stopAutorunPolling() {
  // 탭을 떠나면 멈춘다 — 안 멈추면 다른 탭을 보는 내내 5초마다 요청이 나간다
  if (timer) clearInterval(timer);
  timer = null;
}
