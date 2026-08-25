// 자율 수행 탭. 위에서부터 설정 → 후보 → 실행이고, 실행은 상태별로 끊어 그린다.
// 보드에서 떼어낸 이유 — 결과가 한 목록에 섞이면 사람이 처리할 것(요청·검토 대기)을
// 찾을 수 없고, 후보가 왜 안 도는지도 알 수 없다
import * as api from "./api.js";
import { pickDirectory } from "./browse.js";
import { fromKorean, t } from "./i18n.js";
import { formatAge, openDetail } from "./sessions.js";

const POLL_INTERVAL_MS = 5000;
// 크론 주기는 crontab 이 정하고 이 값은 화면 표시용 상수다 — README "크론" 참고
const TICK_LABEL = t("autorun.cycle");
const NO_TICK = t("autorun.noRun");
const NO_WORKSPACE = t("common.unassigned");
const RUNNING_LABEL = t("autorun.running");
const NO_CANDIDATE = t("autorun.noCandidate");
const NO_RUN = t("autorun.noRunYet");
// review = 잡은 끝났고 사람이 diff 를 보고 병합을 판정할 차례. 진행 중(클로드가 아직
// 돌고 있음)과 섞이면 목록에서 무엇을 봐야 하는지 알 수 없어 배지를 따로 둔다
// requested = 세션이 실패한 게 아니라 판단(기획 공백·방향 미정·정보 부족)을 요청하고
// 스스로 멈춘 것. 사유는 autorun-request 로 남긴 텍스트라 배지 마우스오버로 보여준다
const OUTCOME_LABELS = {
  done: t("common.done"), review: t("common.review"), failed: t("autorun.outcomeFailed"),
  blocked: t("autorun.outcomeBlocked"), requested: t("autorun.outcomeRequested"),
};
const REVIEW = "review";
const REQUESTED = "requested";
const REVIEW_HINT = t("autorun.reviewHint");
const TOGGLE_HINT = t("autorun.toggleHint");
const TOGGLE_GROUP_HINT = t("autorun.groupToggle");
const PRECONDITION = "precondition";
// 작업 위치를 모르는 후보. 이 칩만 눌러서 그 자리에서 풀 수 있다
const CWD = "cwd";

// 후보 한 건이 지금 못 도는 이유. 서버 autorun.BLOCKER_* 와 같은 이름을 쓴다.
// 이미 돈 것(검토 대기·판단 보류·막힘)과 남이 잡은 것은 서버가 후보에서 빼므로 여기 없다 —
// 그 넷은 아래 실행 목록과 세션 목록이 제 구획으로 보여준다.
// 칩에는 짧은 쪽(…Chip)을 적고 왜 그런지는 툴팁(…Hint)으로 — 목록이 문장으로 넘치면 못 읽는다
// 키를 조립하지 않고 하나씩 적는다 — tests/test_language.py 가 코드에 적힌 키만 찾는다
const BLOCKER_CHIPS = {
  ready: t("autorun.blocker.ready"),
  cwd: t("autorun.blocker.cwd"),
  precondition: t("autorun.blocker.precondition"),
};
const BLOCKER_HINTS = {
  ready: t("autorun.blockerHint.ready"),
  cwd: t("autorun.blockerHint.cwd"),
  precondition: t("autorun.blockerHint.precondition"),
};

// 실행 목록의 구획. 사람이 손댈 것부터 위에 온다.
// 첫 칸은 접힘 여부를 기억할 키다 — 라벨은 언어에 따라 바뀌므로 키로 쓸 수 없다
const RUN_GROUPS = [
  ["attention", t("autorun.groupAttention"),
    (run) => run.outcome === REQUESTED || run.outcome === REVIEW],
  ["running", RUNNING_LABEL, (run) => !run.outcome],
  ["failed", t("autorun.groupFailed"),
    (run) => run.outcome === "blocked" || run.outcome === "failed"],
  ["done", t("common.done"), (run) => run.outcome === "done"],
];
// 접혀서 시작하는 구획. 사람이 손댈 것(확인 필요·진행 중)은 펴 두고, 이미 끝난 것만 접는다.
// 폴링이 5초마다 다시 그리므로 화면 밖(모듈)에 들고 있어야 접은 것이 도로 펴지지 않는다
const collapsed = new Set(["failed", "done"]);

// 헤더행의 칸 이름. 데이터 줄과 같은 격자를 쓰므로 순서가 곧 칸 순서다.
// 데이터 칸의 클래스(.wt·.age…)를 붙이지 않는다 — 그 색·글자 크기까지 따라와
// 이름 줄이 칸마다 다른 크기로 흩어진다
const COLUMNS = [
  t("autorun.colWorkspace"),
  t("autorun.colTodo"),
  t("autorun.colWorktree"),
  t("autorun.colPort"),
  t("autorun.colStatus"),
  t("autorun.colStarted"),
  t("autorun.colEnded"),
  t("autorun.colAge"),
];

let timer = null;
let bound = false;
// 끌고 있는 줄. 폴링이 그 사이 목록을 새로 그리면 끌던 노드가 사라진다
let dragging = null;
// 마지막으로 받은 응답. 접기·펴기가 서버를 다시 부르지 않고 이걸로 다시 그린다
let last = null;

export async function renderAutorun() {
  const payload = await api.getAutorun();
  // 끌고 있는 동안 다시 그리면 잡고 있던 줄이 사라져 드롭이 취소된다
  if (dragging) return;
  last = payload;
  paint(payload.state, payload.runs, payload.candidates ?? []);
}

// 접기·펴기처럼 화면 상태만 바뀌는 것은 받아 둔 응답으로 다시 그린다.
// 서버를 다시 부르면 왕복(100ms 안팎)만큼 손이 멈춘 것처럼 느려진다
function repaint() {
  if (!last) return;
  paint(last.state, last.runs, last.candidates ?? []);
}

function paint(state, runs, candidates) {
  document.getElementById("autorun-toggle").checked = Boolean(state.enabled);
  // 주기만으로는 크론이 실제로 돌고 있는지 알 수 없다. 마지막 tick 이 5분을 한참
  // 넘겼으면 크론이 죽은 것이다 — 목록의 실행 이력과 달리 tick 은 여기서만 보인다.
  // 후보별 사유와 달리 전역 사유(사용률·워킹트리 더러움)는 이 줄에만 있다.
  // 사유가 없으면 붙이지 않는다 — 이 열을 받기 전 DB 는 NULL 이다.
  // 사유는 서버가 한국어로 적어 둔 문장이라 사전에서 되짚어 지금 언어로 옮긴다
  const reason = state.last_tick_reason
    ? ` · ${fromKorean(state.last_tick_reason)}`
    : "";
  document.getElementById("autorun-cycle").textContent = state.last_tick_at
    ? `${TICK_LABEL} | ${t("autorun.lastRun", { age: formatAge(state.last_tick_at) })}${reason}`
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
  candidates.forEach((candidate) => list.appendChild(candidateRow(candidate)));
  bindCandidateDrag(list);
}

function candidateRow(candidate) {
  const item = document.createElement("li");
  item.className = candidate.blocker === "ready" ? "ready" : "held";
  item.dataset.todoId = String(candidate.todo_id);
  const scope = element("span", "scope", candidate.workspace_name || NO_WORKSPACE);
  const title = element("span", "prompt", candidate.title);
  item.append(dragHandle(item), scope, title, blockerChip(candidate));
  // 세션 줄·보드 카드와 같은 팝업. 착수 조건 체크리스트는 개요 탭에 있다
  item.addEventListener("click", () => openDetail({ todo: { id: candidate.todo_id } }));
  return item;
}

// 줄 전체가 아니라 핸들만 잡히게 한다 — 줄이 곧 드래그 대상이면 팝업을 열려던
// 클릭이 조금만 흔들려도 드래그로 새고, 제목의 글자 선택도 안 된다
function dragHandle(item) {
  const handle = element("span", "ar-grip");
  handle.title = t("autorun.dragHandle");
  handle.setAttribute("aria-hidden", "true");
  handle.addEventListener("mousedown", () => {
    item.draggable = true;
  });
  handle.addEventListener("mouseup", () => {
    item.draggable = false;
  });
  // 핸들을 눌렀다 떼면 클릭으로도 읽혀 팝업이 뜬다. 끌려던 것이지 열려던 게 아니다
  handle.addEventListener("click", (event) => event.stopPropagation());
  return handle;
}

// 끌어서 순서 바꾸기. 삽입선은 대상 줄의 위·아래 테두리로 그린다 — 어디에 놓이는지
// 보이지 않으면 사람이 한 칸씩 시험해 보는 수밖에 없다.
// 보드의 dnd.js 를 쓰지 않는 이유 — 그쪽은 카드 위에 통째로 떨어뜨리는 방식이고
// 워크스페이스 묶음을 전제한다. 후보 목록은 여러 워크스페이스가 한 줄로 섞인 평면이다
function bindCandidateDrag(list) {
  if (list.dataset.dragBound) return;
  list.dataset.dragBound = "1";
  list.addEventListener("dragstart", (event) => {
    dragging = event.target.closest("li");
    if (dragging) dragging.classList.add("dragging");
  });
  list.addEventListener("dragover", (event) => {
    const over = event.target.closest("li");
    if (!dragging || !over || over === dragging) return;
    event.preventDefault(); // 이걸 안 하면 브라우저가 드롭을 아예 안 받는다
    markDropLine(list, over, event.clientY);
  });
  list.addEventListener("dragend", () => finishDrag(list));
  list.addEventListener("drop", (event) => {
    event.preventDefault();
    const ids = droppedOrder(list);
    finishDrag(list);
    // 저장에 실패해도 다시 그린다 — 화면이 서버가 아는 순서로 되돌아간다.
    // main.js 의 run() 을 안 쓰는 이유: main.js 가 이 모듈을 부르므로 순환이 된다
    if (ids) api.reorder("autorun", ids).catch(() => {}).then(renderAutorun);
  });
}

// 커서가 줄 중앙보다 위면 그 줄 앞, 아래면 뒤. 한 번에 한 줄만 표시한다
function markDropLine(list, over, clientY) {
  const box = over.getBoundingClientRect();
  const after = clientY > box.top + box.height / 2;
  clearDropLines(list);
  over.classList.add(after ? "drop-after" : "drop-before");
}

function droppedOrder(list) {
  const marked = list.querySelector(".drop-before, .drop-after");
  if (!dragging || !marked) return null;
  const rows = [...list.children].filter((row) => row !== dragging);
  const at = rows.indexOf(marked) + (marked.classList.contains("drop-after") ? 1 : 0);
  rows.splice(at, 0, dragging);
  return rows.map((row) => Number(row.dataset.todoId));
}

function finishDrag(list) {
  clearDropLines(list);
  if (dragging) {
    dragging.classList.remove("dragging");
    dragging.draggable = false;
  }
  dragging = null;
}

function clearDropLines(list) {
  list
    .querySelectorAll(".drop-before, .drop-after")
    .forEach((row) => row.classList.remove("drop-before", "drop-after"));
}

// 위치 미정만 누를 수 있는 칩이다 — 나머지 사유는 이 자리에서 풀 것이 없다.
// 워크스페이스가 없는 할일은 위치를 적어 둘 곳이 없어 글자로만 남긴다
function blockerChip(candidate) {
  const pickable = candidate.blocker === CWD && Boolean(candidate.workspace_id);
  const chip = element(
    pickable ? "button" : "span",
    `badge blocker-${candidate.blocker}`,
    chipText(candidate)
  );
  chip.title = BLOCKER_HINTS[candidate.blocker] ?? candidate.blocker;
  if (pickable) bindCwdPick(chip, candidate);
  return chip;
}

// 보드 케밥의 "시작" 이 쓰는 폴더 선택기를 그대로 연다 — 묻는 것이 같으면 묻는 화면도 같아야 한다.
// 여기서 세션을 띄우지 않는 이유 — 고른 경로는 워크스페이스에 남으므로 다음 tick 이
// 제 순서대로 시작한다. 지금 띄우면 자율 실행 기록 밖에서 도는 세션이 하나 더 생긴다
function bindCwdPick(chip, candidate) {
  chip.type = "button";
  chip.addEventListener("click", async (event) => {
    // 줄 클릭은 상세 팝업이라 여기서 멈춘다 — 경로를 고르려고 눌렀는데 팝업이 뜨면 안 된다
    event.stopPropagation();
    const cwd = await pickDirectory();
    if (!cwd) return;
    // 실패하면 api.js 가 이미 알렸다. 목록은 그대로 두고 되돌린다
    await api.updateWorkspace(candidate.workspace_id, { cwd }).then(renderAutorun, () => {});
  });
}

// 조건 미충족이면 몇 개 중 몇 개인지까지 적는다 — 무엇을 풀어야 도는지가 그 숫자다
function chipText(candidate) {
  if (candidate.blocker !== PRECONDITION || !candidate.precondition) {
    return BLOCKER_CHIPS[candidate.blocker] ?? candidate.blocker;
  }
  const { met, total, manual } = candidate.precondition;
  const counted = t("autorun.conditionCount", { met, total });
  return manual ? `${counted} · ${t("autorun.conditionManual", { manual })}` : counted;
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
  RUN_GROUPS.forEach(([key, label, belongs]) => {
    const rows = runs.filter(belongs);
    if (rows.length) list.appendChild(groupPanel(key, label, rows));
  });
}

// 상태마다 판 하나. 판을 펼치면 그 안에 칸 이름 줄과 실행 줄이 들어간다 —
// 목록 맨 위에 칸 이름을 한 번만 두면 접힌 구획을 지나 멀리 떨어져 짝이 안 보인다
function groupPanel(key, label, rows) {
  const panel = document.createElement("li");
  const open = !collapsed.has(key);
  panel.className = open ? "ar-group" : "ar-group collapsed";
  panel.append(groupHead(key, label, rows.length, open));
  // 접힌 판은 줄을 아예 안 그린다 — 숨겨 두면 목록이 길어질수록 그리는 값만 늘어난다
  if (open) {
    const body = element("ul", "ar-group-rows");
    body.appendChild(headRow());
    rows.forEach((run) => body.appendChild(runRow(run)));
    panel.appendChild(body);
  }
  return panel;
}

function headRow() {
  const item = document.createElement("li");
  item.className = "head";
  item.append(...COLUMNS.map((label) => element("span", "", label)));
  return item;
}

function groupHead(key, label, count, open) {
  const head = element("div", "ar-group-head");
  head.setAttribute("role", "button");
  head.setAttribute("aria-expanded", open ? "true" : "false");
  head.tabIndex = 0;
  head.title = TOGGLE_GROUP_HINT;
  // 꺾쇠는 CSS 가 그린다 (세션 패널과 같은 방식) — 글꼴마다 모양이 다른 ▾ 문자를 쓰지 않는다
  head.append(
    element("span", "mark"),
    element("span", "text", label),
    element("span", "count", `${count}`),
  );
  const toggle = () => {
    if (collapsed.has(key)) collapsed.delete(key);
    else collapsed.add(key);
    repaint();
  };
  head.addEventListener("click", toggle);
  head.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault(); // 스페이스로 화면이 굴러가면 접은 판을 놓친다
    toggle();
  });
  return head;
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
  const started = element("span", "when", formatClock(run.started_at));
  // 안 끝난 실행은 종료가 비어 있다. 자리는 남겨 둔다 — 칸이 없으면 뒤 칸이 당겨 온다
  const ended = element("span", "when", formatClock(run.ended_at));
  const age = element("span", "age", formatAge(run.started_at));
  item.append(scope, title, worktree, ports, outcome, started, ended, age);
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

// 시작·종료는 절대 시각으로 적는다 — 둘 다 "몇 분 전"이면 그 사이가 얼마인지 못 읽는다.
// 오늘 것은 시:분만, 날이 넘어간 것에만 날짜를 붙인다 (경과 칸이 어제인지 알려 준다)
function formatClock(iso) {
  if (!iso) return "";
  const ms = Date.parse(iso);
  if (Number.isNaN(ms)) return "";
  const at = new Date(ms);
  const pad = (value) => String(value).padStart(2, "0");
  const clock = `${pad(at.getHours())}:${pad(at.getMinutes())}`;
  if (at.toDateString() === new Date().toDateString()) return clock;
  return `${pad(at.getMonth() + 1)}-${pad(at.getDate())} ${clock}`;
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
