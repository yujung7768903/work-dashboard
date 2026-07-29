// 활성 세션 영역. 이 영역만 폴링해 편집 중인 입력을 건드리지 않음
import * as api from "./api.js";

const POLL_INTERVAL_MS = 2000;
const WORKING = "working";
const NO_WORKSPACE = "―";
const UNCLASSIFIED_LABEL = "분류 전";

let timer = null;

export async function renderSessions(onPick) {
  const payload = await api.getSessions();
  document.getElementById("session-count").textContent =
    `돌고 있는 세션 ${payload.sessions.length}`;
  const warn = document.getElementById("session-warn");
  warn.hidden = !payload.unclassified_count;
  warn.textContent = payload.unclassified_count
    ? `분류 전 ${payload.unclassified_count}건 ⚠`
    : "";

  const list = document.getElementById("session-list");
  list.innerHTML = "";
  payload.sessions.forEach((session) =>
    list.appendChild(sessionRow(session, onPick))
  );
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

  item.append(mark, scope, category, prompt);
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
