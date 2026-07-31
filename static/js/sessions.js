// 활성 세션 영역. 이 영역만 폴링해 편집 중인 입력을 건드리지 않음
import * as api from "./api.js";
import { focusWorkspace } from "./workspace.js";

const POLL_INTERVAL_MS = 2000;
const WORKING = "working";
const ACTIVE = "active";
const NO_WORKSPACE = "―";
const UNCLASSIFIED_LABEL = "분류 전";
const ROLE_LABELS = { user: "나", assistant: "클로드" };

let timer = null;
// 사용자가 펼친 '대기 중'은 폴링이 접지 않도록 모듈에 남긴다
let showIdle = false;

export async function renderSessions() {
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
  shown.forEach((session) => list.appendChild(sessionRow(session)));
  if (idle.length) list.appendChild(idleToggle(idle.length));
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

function idleToggle(count) {
  const item = document.createElement("li");
  item.className = "more";
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = showIdle ? "대기 중 숨기기" : `대기 중 ${count}개 보기`;
  button.addEventListener("click", () => {
    showIdle = !showIdle;
    renderSessions().catch(() => {});
  });
  item.appendChild(button);
  return item;
}

function sessionRow(session) {
  const item = document.createElement("li");
  item.className = session.state === WORKING ? "working" : "idle";

  const mark = element("span", null, session.state === WORKING ? "●" : "○");
  const scope = element("span", "scope", session.workspace_name || NO_WORKSPACE);
  const category = element("span", null, `(${session.category_name || UNCLASSIFIED_LABEL})`);
  const prompt = element("span", "prompt", session.last_prompt || "");

  const age = element("span", "age", formatAge(session.last_seen_at));

  item.append(mark, scope, category, prompt, age);
  item.addEventListener("click", () => openSessionDetail(session));
  return item;
}

// 보드의 세션 줄과 사용량 레일의 세션 카드가 같은 팝업을 쓴다
export function openSessionDetail(session) {
  // 폴링이 목록을 다시 그려도 팝업은 별도 요소라 안 건드린다. 대화는 열 때 한 번만 읽음
  const dialog = document.getElementById("session-modal");
  const body = document.getElementById("session-modal-body");
  body.textContent = "불러오는 중";
  if (!dialog.open) dialog.showModal();
  Promise.all([api.getSession(session.id), api.getWorkspaces(), api.getCategories()])
    .then(([detail, workspaces, categories]) =>
      body.replaceChildren(
        headBlock(detail.session),
        classifyRow(detail.session, workspaces, categories, dialog),
        logSection(detail.messages)
      )
    )
    .catch((error) => {
      body.textContent = error.message;
    });
}

function headBlock(session) {
  const head = element("div", "dlg-head");
  const title = element("p", "dlg-title", session.workspace_name || UNCLASSIFIED_LABEL);
  title.append(element("span", "dlg-meta", ` ${session.category_name || ""}`.trimEnd()));

  const idRow = element("div", "session-id");
  const code = element("code", null, session.claude_session_id);
  const copy = element("button", "copy", "복사");
  copy.addEventListener("click", () => {
    navigator.clipboard.writeText(session.claude_session_id);
    copy.textContent = "복사됨";
  });
  idRow.append(code, copy);

  head.append(title, idRow, element("p", "session-meta", metaLine(session)));
  return head;
}

function metaLine(session) {
  return [session.cwd || "위치 모름", session.git_branch || "브랜치 없음", session.state].join(
    " · "
  );
}

function classifyRow(session, workspaces, categories, dialog) {
  const row = element("div", "session-classify");
  const select = targetSelect(session, workspaces, categories);
  const status = element("p", "session-status", "");

  const save = element("button", null, "분류 저장");
  save.addEventListener("click", async () => {
    const fields = classifyFields(select.value);
    if (!fields) {
      status.textContent = "워크스페이스나 카테고리를 고르세요";
      return;
    }
    try {
      await api.classifySession(session.id, fields);
      dialog.close();
      await renderSessions();
    } catch (error) {
      status.textContent = error.message;
    }
  });
  row.append(select, save);

  if (session.workspace_id) {
    const open = element("button", null, "워크스페이스 열기");
    open.addEventListener("click", () => {
      dialog.close();
      focusWorkspace(session.workspace_id);
      document.querySelector('#tabs button[data-tab="workspace"]').click();
    });
    row.append(open);
  }
  row.append(status);
  return row;
}

function classifyFields(value) {
  const [kind, id] = value.split(":");
  if (kind === "w") return { workspace_id: Number(id) };
  if (kind === "c") return { category_id: Number(id) };
  return null;
}

function targetSelect(session, workspaces, categories) {
  const select = element("select", "session-target");
  const placeholder = new Option("분류 선택", "");
  placeholder.disabled = true;
  placeholder.selected = true;
  select.add(placeholder);

  const names = new Map(categories.map((category) => [category.id, category.name]));
  const workspaceGroup = optgroup("워크스페이스");
  workspaces
    .filter((workspace) => workspace.status === ACTIVE)
    .forEach((workspace) =>
      workspaceGroup.appendChild(
        new Option(
          `${workspace.name} (${names.get(workspace.category_id) ?? "?"})`,
          `w:${workspace.id}`,
          false,
          session.workspace_id === workspace.id
        )
      )
    );

  // 워크스페이스 없이 카테고리만 정하는 세션이 있어 두 갈래를 한 select 에 둔다
  const categoryGroup = optgroup("카테고리만");
  categories.forEach((category) =>
    categoryGroup.appendChild(
      new Option(
        category.name,
        `c:${category.id}`,
        false,
        !session.workspace_id && session.category_id === category.id
      )
    )
  );

  select.append(workspaceGroup, categoryGroup);
  return select;
}

function logSection(messages) {
  const section = element("div", "dlg-section");
  section.appendChild(element("p", "label", "최근 대화"));
  if (!messages.length) {
    section.appendChild(element("p", "muted", "최근 대화를 찾지 못함"));
    return section;
  }
  const list = element("ul", "session-log");
  messages.forEach((message) => {
    const item = element("li", message.role);
    item.title = message.text; // 목록에서는 몇 줄만 보이므로 전문은 툴팁으로
    item.append(
      element("span", "dlg-badge", ROLE_LABELS[message.role] ?? message.role),
      element("span", "text", message.text)
    );
    list.appendChild(item);
  });
  section.appendChild(list);
  return section;
}

function optgroup(label) {
  const group = document.createElement("optgroup");
  group.label = label;
  return group;
}

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

export function startSessionPolling() {
  if (timer) clearInterval(timer);
  // 폴링 실패는 삼킨다 — 2초마다 배너를 덮어쓰면 다른 조작의 에러가 지워짐
  const tick = () => renderSessions().catch(() => {});
  tick();
  timer = setInterval(tick, POLL_INTERVAL_MS);
}
