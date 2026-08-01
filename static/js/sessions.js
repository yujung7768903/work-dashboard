// 활성 세션 영역. 이 영역만 폴링해 편집 중인 입력을 건드리지 않음
import * as api from "./api.js";

const POLL_INTERVAL_MS = 2000;
const WORKING = "working";
const ACTIVE = "active";
const NO_WORKSPACE = "―";
const UNCLASSIFIED_LABEL = "분류 전";
const ROLE_LABELS = { user: "나", assistant: "클로드" };
const OVERVIEW_TAB = "overview";
const SESSION_TAB = "session";
const TABS = [
  [OVERVIEW_TAB, "개요"],
  [SESSION_TAB, "세션"],
];
// 개요의 시각 목록. 실제 순서는 값으로 정렬하므로 여기 순서는 라벨 짝짓기용일 뿐
const TIME_FIELDS = [
  ["created_at", "생성"],
  ["updated_at", "수정"],
  ["completed_at", "완료"],
];

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
  item.addEventListener("click", () => openDetail({ session }));
  return item;
}

// 세션 줄·사용량 레일의 세션 카드·보드의 할일이 모두 이 팝업 하나를 쓴다.
// 어디서 열었느냐는 처음 켜지는 탭만 바꾼다 — 세션은 세션 탭, 할일은 개요 탭
export function openDetail(target) {
  // 폴링이 목록을 다시 그려도 팝업은 별도 요소라 안 건드린다. 대화는 열 때 한 번만 읽음
  const dialog = document.getElementById("session-modal");
  const body = document.getElementById("session-modal-body");
  body.textContent = "불러오는 중";
  if (!dialog.open) dialog.showModal();
  loadContext(target)
    .then((context) => body.replaceChildren(...tabbed(context, dialog)))
    .catch((error) => {
      body.textContent = error.message;
    });
}

// 두 갈래 입력을 같은 모양으로 맞춘다 — 이후 렌더는 어디서 열렸는지 모른다
async function loadContext(target) {
  const [workspaces, categories] = await Promise.all([
    api.getWorkspaces(),
    api.getCategories(),
  ]);
  const common = { workspaces, categories };
  if (target.session) {
    const detail = await api.getSession(target.session.id);
    // 분류 직후처럼 방금 만들어진 할일을 보여줘야 할 때만 개요로 열린다
    return { ...detail, ...common, tab: target.tab ?? SESSION_TAB };
  }
  const { todo, sessions } = await api.getTodo(target.todo.id);
  // 할일에서 열면 세션 탭은 그 할일을 마지막으로 잡은 세션을 보여준다
  const detail = sessions.length ? await api.getSession(sessions[0].id) : null;
  return {
    session: detail?.session ?? null,
    messages: detail?.messages ?? [],
    todos: [todo],
    ...common,
    tab: OVERVIEW_TAB,
  };
}

function tabbed(context, dialog) {
  const panes = {
    [OVERVIEW_TAB]: overviewPane(context.todos),
    [SESSION_TAB]: sessionPane(context, dialog),
  };
  Object.entries(panes).forEach(([key, pane]) => {
    pane.hidden = key !== context.tab;
  });
  return [tabBar(panes, context.tab), ...Object.values(panes)];
}

function tabBar(panes, active) {
  const bar = element("div", "dlg-tabs");
  TABS.forEach(([key, label]) => {
    const button = element("button", null, label);
    button.type = "button";
    button.classList.toggle("active", key === active);
    button.addEventListener("click", () => {
      Array.from(bar.children).forEach((node) => node.classList.remove("active"));
      button.classList.add("active");
      Object.entries(panes).forEach(([paneKey, pane]) => {
        pane.hidden = paneKey !== key;
      });
    });
    bar.appendChild(button);
  });
  return bar;
}

function overviewPane(todos) {
  const pane = element("div", "dlg-pane");
  if (!todos?.length) {
    pane.appendChild(element("p", "muted", "연결된 할일이 없습니다."));
    return pane;
  }
  todos.forEach((todo) => pane.appendChild(todoBlock(todo)));
  return pane;
}

// 제목이 요약 안 된 자동 생성 할일 표시. 보드 줄과 팝업 개요가 같은 표시를 쓴다
export function rawTitleMark() {
  const mark = element("span", "raw-title", "요약 안 됨");
  mark.title = "제목이 지시 첫 문장 그대로다. 요약이 붙으면 자동으로 바뀌고, 안 붙으면 직접 고치면 된다";
  return mark;
}

function todoBlock(todo) {
  const block = element("div", "dlg-section");
  const title = element("p", "dlg-title", todo.title);
  if (todo.needs_title) title.append(rawTitleMark());
  block.append(title, timeList(todo));
  if (todo.subtasks?.length) {
    block.append(element("p", "label", "하위 할일"), subtaskList(todo.subtasks));
  }
  block.append(
    element("p", "label", "note"),
    element("p", todo.note ? "note-body" : "muted", todo.note || "(없음)")
  );
  return block;
}

function subtaskList(subtasks) {
  const list = element("ul", "dlg-subtasks");
  subtasks.forEach((subtask) => {
    const item = document.createElement("li");
    item.append(
      element("span", "dlg-badge", subtask.status),
      element("span", "text", subtask.title)
    );
    list.appendChild(item);
  });
  return list;
}

// 완료 시각이 없는 할일도 있어 빈 값은 빼고, 남은 것만 최근 순으로 세운다
function timeList(todo) {
  const list = element("ul", "time-list");
  TIME_FIELDS.filter(([key]) => todo[key])
    .map(([key, label]) => ({ label, iso: todo[key] }))
    .sort((a, b) => Date.parse(b.iso) - Date.parse(a.iso))
    .forEach(({ label, iso }) => {
      const item = document.createElement("li");
      item.append(
        element("span", "dlg-badge", label),
        element("span", "when", formatWhen(iso)),
        element("span", "age", formatAge(iso))
      );
      list.appendChild(item);
    });
  return list;
}

function formatWhen(iso) {
  const ms = Date.parse(iso);
  if (Number.isNaN(ms)) return iso;
  return new Date(ms).toLocaleString("ko-KR", { dateStyle: "short", timeStyle: "short" });
}

function sessionPane(context, dialog) {
  const pane = element("div", "dlg-pane");
  if (!context.session) {
    pane.appendChild(element("p", "muted", "이 할일을 잡은 세션이 없습니다."));
    return pane;
  }
  pane.append(
    headBlock(context.session, context.categories),
    classifyRow(context.session, context.workspaces, context.categories, dialog),
    logSection(context.messages)
  );
  return pane;
}

function headBlock(session, categories) {
  const head = element("div", "dlg-head");
  const title = element("p", "dlg-title", session.workspace_name || UNCLASSIFIED_LABEL);
  const category = categories.find((item) => item.id === session.category_id);
  if (category) {
    const pill = element("span", "session-cat", category.name);
    // 색은 보드 라벨과 같은 --cat 규약. 없으면 CSS 기본 회색
    if (category.color) pill.style.setProperty("--cat", category.color);
    title.append(pill);
  }

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
      // 제목 요약은 서버가 뒷일로 돌리므로 이 응답은 바로 온다 (제목은 나중에 바뀐다)
      status.textContent = "분류 중…";
      save.disabled = true;
      const result = await api.classifySession(session.id, fields);
      save.disabled = false;
      await renderSessions();
      // 할일이 자동으로 생겼으면 닫지 않고 개요 탭으로 넘겨 무엇이 만들어졌는지 보여준다
      if (result?.created_todo) {
        openDetail({ session, tab: OVERVIEW_TAB });
        return;
      }
      dialog.close();
    } catch (error) {
      save.disabled = false;
      status.textContent = error.message;
    }
  });
  row.append(select, save, status);
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
