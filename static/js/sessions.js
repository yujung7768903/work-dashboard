// 활성 세션 영역. 이 영역만 폴링해 편집 중인 입력을 건드리지 않음
import * as api from "./api.js";

const POLL_INTERVAL_MS = 2000;
const WORKING = "working";
const ACTIVE = "active";
const NO_WORKSPACE = "―";
const UNCLASSIFIED_LABEL = "분류 전";
const ROLE_LABELS = { user: "나", assistant: "클로드" };

let timer = null;
let pickWorkspace = null;

export async function renderSessions(onPick) {
  if (onPick) pickWorkspace = onPick;
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
  payload.sessions.forEach((session) => list.appendChild(sessionRow(session)));
}

function sessionRow(session) {
  const item = document.createElement("li");
  item.className = session.state === WORKING ? "working" : "idle";

  const mark = element("span", null, session.state === WORKING ? "●" : "○");
  const scope = element("span", "scope", session.workspace_name || NO_WORKSPACE);
  const category = element("span", null, `(${session.category_name || UNCLASSIFIED_LABEL})`);
  const prompt = element("span", "prompt", session.last_prompt || "");

  item.append(mark, scope, category, prompt);
  item.addEventListener("click", () => openDetail(session));
  return item;
}

function openDetail(session) {
  // 폴링이 목록을 다시 그려도 팝업은 별도 요소라 안 건드린다. 대화는 열 때 한 번만 읽음
  const dialog = document.getElementById("session-modal");
  const body = document.getElementById("session-modal-body");
  body.textContent = "불러오는 중";
  if (!dialog.open) dialog.showModal();
  Promise.all([api.getSession(session.id), api.getWorkspaces(), api.getCategories()])
    .then(([detail, workspaces, categories]) =>
      body.replaceChildren(
        element("p", "session-id", detail.session.claude_session_id),
        element("p", "session-meta", metaLine(detail.session)),
        classifyRow(detail.session, workspaces, categories, dialog),
        messageList(detail.messages)
      )
    )
    .catch((error) => {
      body.textContent = error.message;
    });
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

  if (session.workspace_id && pickWorkspace) {
    const open = element("button", null, "워크스페이스 열기");
    open.addEventListener("click", () => {
      dialog.close();
      pickWorkspace(session.workspace_id);
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

function messageList(messages) {
  const list = element("ul", "session-log");
  if (!messages.length) {
    list.appendChild(element("li", "session-meta", "최근 대화를 찾지 못함"));
    return list;
  }
  messages.forEach((message) => {
    const item = element("li", message.role);
    item.append(
      element("span", "role", ROLE_LABELS[message.role] ?? message.role),
      element("span", "text", message.text)
    );
    list.appendChild(item);
  });
  return list;
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

export function startSessionPolling(onPick) {
  if (timer) clearInterval(timer);
  // 폴링 실패는 삼킨다 — 2초마다 배너를 덮어쓰면 다른 조작의 에러가 지워짐
  const tick = () => renderSessions(onPick).catch(() => {});
  tick();
  timer = setInterval(tick, POLL_INTERVAL_MS);
}
