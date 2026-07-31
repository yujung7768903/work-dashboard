// 활성 세션 영역. 이 영역만 폴링해 편집 중인 입력을 건드리지 않음
import * as api from "./api.js";

const POLL_INTERVAL_MS = 2000;
const WORKING = "working";
const NO_WORKSPACE = "―";
const UNCLASSIFIED_LABEL = "분류 전";

let timer = null;
// 사용자가 펼친 '대기 중'은 폴링이 접지 않도록 모듈에 남긴다
let showIdle = false;

export async function renderSessions(onPick) {
  const payload = await api.getSessions();
  const working = payload.sessions.filter((s) => s.state === WORKING);
  const idle = payload.sessions.filter((s) => s.state !== WORKING);

  document.getElementById("session-count").textContent =
    `돌고 있는 세션 ${working.length}`;
  const warn = document.getElementById("session-warn");
  warn.hidden = !payload.unclassified_count;
  warn.textContent = payload.unclassified_count
    ? `분류 전 ${payload.unclassified_count}건 ⚠`
    : "";

  const list = document.getElementById("session-list");
  list.innerHTML = "";
  const shown = showIdle ? [...working, ...idle] : working;
  shown.forEach((session) => list.appendChild(sessionRow(session, onPick)));
  if (idle.length) list.appendChild(idleToggle(idle.length, onPick));
}

// 경과 시간 표기. usage.js 에도 같은 규칙의 구현이 따로 있다
function formatAge(iso) {
  if (!iso) return "";
  const ms = Date.parse(iso);
  if (Number.isNaN(ms)) return "";
  const sec = Math.max(0, Math.floor((Date.now() - ms) / 1000));
  if (sec < 60) return `${sec}s`;
  if (sec < 3600) return `${Math.floor(sec / 60)}m`;
  if (sec < 86400) return `${Math.floor(sec / 3600)}h`;
  return `${Math.floor(sec / 86400)}d`;
}

function idleToggle(count, onPick) {
  const item = document.createElement("li");
  item.className = "more";
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = showIdle ? "대기 중 숨기기" : `대기 중 ${count}개 보기`;
  button.addEventListener("click", () => {
    showIdle = !showIdle;
    renderSessions(onPick).catch(() => {});
  });
  item.appendChild(button);
  return item;
}

function sessionRow(session, onPick) {
  const item = document.createElement("li");
  item.className = session.state === WORKING ? "working" : "idle";

  const mark = document.createElement("span");
  mark.textContent = session.state === WORKING ? "●" : "○";

  const scope = document.createElement("span");
  scope.className = "scope";
  scope.textContent = session.workspace_name || NO_WORKSPACE;

  const category = document.createElement("span");
  category.textContent = `(${session.category_name || UNCLASSIFIED_LABEL})`;

  const prompt = document.createElement("span");
  prompt.className = "prompt";
  prompt.textContent = session.last_prompt || "";

  const age = document.createElement("span");
  age.className = "age";
  age.textContent = formatAge(session.last_seen_at);

  item.append(mark, scope, category, prompt, age);
  if (session.workspace_id && onPick) {
    item.addEventListener("click", () => onPick(session.workspace_id));
  }
  return item;
}

export function startSessionPolling(onPick) {
  if (timer) clearInterval(timer);
  // 폴링 실패는 삼킨다 — 2초마다 배너를 덮어쓰면 다른 조작의 에러가 지워짐
  const tick = () => renderSessions(onPick).catch(() => {});
  tick();
  timer = setInterval(tick, POLL_INTERVAL_MS);
}
