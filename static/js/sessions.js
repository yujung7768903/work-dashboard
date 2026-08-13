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
const WORKTREE_TAB = "worktree";
const TABS = [
  [OVERVIEW_TAB, "개요"],
  [SESSION_TAB, "세션"],
  [WORKTREE_TAB, "워크트리"],
];
// 워크트리 상태 → (배지 글자, 설명). 병합·삭제된 워크트리도 이름과 상태로 남는다
const WORKTREE_STATES = {
  create: ["생성", "만들어졌지만 아직 작업이 없음"],
  working: ["작업중", "기준 브랜치에 아직 없는 작업이 있음"],
  merged: ["병합", "기준 브랜치에 병합돼 끝남"],
  deleted: ["삭제", "병합하지 않고 버림"],
};
// 개요 History 의 이벤트. 실제 순서는 시각으로 정렬하므로 여기 순서는 라벨 짝짓기용일 뿐
const TIME_FIELDS = [
  ["created_at", "생성"],
  ["updated_at", "수정"],
  ["completed_at", "완료"],
];
// 워크트리 History 의 이벤트. 끝난 시각은 하나만 채워진다 —
// 병합됐으면 merged_at, 병합 없이 지웠으면 deleted_at
const WORKTREE_TIME_FIELDS = [
  ["created_at", "생성"],
  ["merged_at", "병합"],
  ["deleted_at", "삭제"],
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

// 경과 시간 표기. usage.js 에도 같은 규칙의 구현이 따로 있다. autorun.js 는 이걸 그대로 쓴다
export function formatAge(iso) {
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
  const { todo, sessions, worktrees } = await api.getTodo(target.todo.id);
  // 할일에서 열면 세션 탭은 그 할일을 마지막으로 잡은 세션을 보여준다
  const detail = sessions.length ? await api.getSession(sessions[0].id) : null;
  return {
    session: detail?.session ?? null,
    messages: detail?.messages ?? [],
    todos: [todo],
    worktrees,
    ...common,
    tab: OVERVIEW_TAB,
    // 할일에서 열면 세션 탭 머리도 개요와 같은 할일 표기를 쓴다
    fromTodo: true,
  };
}

function tabbed(context, dialog) {
  const panes = {
    [OVERVIEW_TAB]: overviewPane(context.todos),
    [SESSION_TAB]: sessionPane(context, dialog),
    [WORKTREE_TAB]: worktreePane(context.worktrees),
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
  // 할일 번호를 제목 앞에 붙인다 — dash.py 명령에 넣을 id 를 팝업에서 바로 읽게
  const title = element("p", "dlg-title", `#${todo.id} | ${todo.title}`);
  if (todo.needs_title) title.append(rawTitleMark());
  block.append(title, historySection(events(todo, TIME_FIELDS)));
  block.append(...textField("착수 조건", todo.precondition));
  // 하위 할일은 보드 카드에서 펼쳐 보므로 여기서는 안 그린다
  block.append(...textField("note", todo.note));
  return block;
}

// note·착수 조건 둘 다 여러 줄이 오는 글이라 같은 라벨+본문 짝을 쓴다
function textField(label, value) {
  return [
    element("p", "label", label),
    element("p", value ? "note-body" : "muted", value || "(없음)"),
  ];
}

// 채워진 시각만 최근 순으로. 완료 시각 없는 할일, 아직 끝나지 않은 워크트리가 있어 빈 값은 뺀다
function events(source, fields) {
  return fields
    .filter(([key]) => source[key])
    .map(([key, label]) => ({ label, iso: source[key] }))
    .sort((a, b) => Date.parse(b.iso) - Date.parse(a.iso));
}

// 시각 + 이벤트 한 줄짜리 로그. 개요(생성·수정·완료)와 워크트리(생성·병합·삭제)가 같은 모양을 쓴다
function historySection(rows) {
  const block = element("div", "dlg-log");
  block.appendChild(element("p", "label", "History"));
  const list = element("ul", "log-list");
  rows.forEach(({ label, iso }) => {
    const item = document.createElement("li");
    item.append(
      element("span", "when", formatStamp(iso)),
      element("span", "text", label),
      element("span", "age", formatAge(iso))
    );
    list.appendChild(item);
  });
  block.appendChild(list);
  return block;
}

// 로그 파일과 같은 표기(로컬 시각). toLocaleString 은 '26. 8. 5. 오후 7:29' 라 로그와 안 맞는다
function formatStamp(iso) {
  const ms = Date.parse(iso);
  if (Number.isNaN(ms)) return iso;
  const at = new Date(ms);
  const pad = (value) => String(value).padStart(2, "0");
  return (
    `${at.getFullYear()}-${pad(at.getMonth() + 1)}-${pad(at.getDate())}` +
    ` ${pad(at.getHours())}:${pad(at.getMinutes())}:${pad(at.getSeconds())}`
  );
}

// 이 할일이 썼던 워크트리. 지금 살아 있는 것만이 아니라 병합·삭제로 끝난 것까지 남는다
function worktreePane(rows) {
  const pane = element("div", "dlg-pane");
  if (!rows?.length) {
    pane.appendChild(element("p", "muted", "이 할일에 붙은 워크트리가 없습니다."));
    return pane;
  }
  rows.forEach((row) => pane.appendChild(worktreeBlock(row)));
  return pane;
}

function worktreeBlock(row) {
  const block = element("div", "dlg-section");
  const head = element("p", "dlg-wt-head");
  const name = element("span", "title", row.name);
  // 이름 칸은 좁으므로 브랜치·경로는 툴팁으로
  name.title = [row.branch, row.path].filter(Boolean).join("\n");
  head.append(name, stateBadge(row.state));
  block.append(head, historySection(events(row, WORKTREE_TIME_FIELDS)), commitSection(row));
  return block;
}

function stateBadge(state) {
  const [label, hint] = WORKTREE_STATES[state] ?? [state, ""];
  const badge = element("span", `dlg-badge wt-state ${state}`, label);
  badge.title = hint;
  return badge;
}

// 기준 브랜치와의 커밋 차이. 보드 워크트리 탭과 같은 ↑↓ 표기
function divergence(row) {
  const box = element("span", "wt-div");
  box.append(
    count("ahead", row.ahead, `${row.base} 에 없는 커밋 ${row.ahead}개`),
    count("behind", row.behind, `${row.base} 보다 뒤처진 커밋 ${row.behind}개`)
  );
  return box;
}

function count(kind, value, title) {
  const node = element("span", kind);
  if (!value) return node;
  node.textContent = `${kind === "ahead" ? "↑" : "↓"}${value}`;
  node.title = title;
  return node;
}

function commitSection(row) {
  const block = element("div", "dlg-log");
  // 커밋 차이는 섹션 이름 오른쪽 — 이 목록이 기준 브랜치와 무엇이 다른지를 세는 값이다
  const heading = element("p", "label", "Commit");
  heading.appendChild(divergence(row));
  block.appendChild(heading);
  if (!row.commits.length) {
    // 병합 없이 지운 워크트리는 커밋이 브랜치와 함께 사라져 되짚을 자국이 없다.
    // 아직 살아 있는 워크트리면 그냥 커밋을 안 한 것이라 말이 달라야 한다
    const reason =
      row.state === "deleted"
        ? "병합 없이 지운 워크트리라 커밋도 브랜치와 함께 사라졌습니다."
        : "아직 커밋이 없습니다.";
    block.appendChild(element("p", "muted", reason));
    return block;
  }
  // git log 가 최신 순으로 주므로 그대로 쓴다 — History 와 같은 방향
  const list = element("ul", "log-list");
  row.commits.forEach((commit) => {
    const item = document.createElement("li");
    const subject = element("span", "text", commit.subject);
    subject.title = commit.subject; // 한 줄에 안 들어가면 잘리므로 전문은 툴팁으로
    item.append(
      element("span", "when", formatStamp(commit.at)),
      element("code", null, commit.hash),
      subject
    );
    list.appendChild(item);
  });
  block.appendChild(list);
  return block;
}

function sessionPane(context, dialog) {
  const pane = element("div", "dlg-pane");
  if (!context.session) {
    pane.appendChild(element("p", "muted", "이 할일을 잡은 세션이 없습니다."));
    return pane;
  }
  pane.append(
    headBlock(context.session, context.categories, context.fromTodo ? context.todos[0] : null),
    classifyRow(context.session, context.workspaces, context.categories, dialog),
    logSection(context.messages)
  );
  return pane;
}

function headBlock(session, categories, todo) {
  const head = element("div", "dlg-head");
  // 할일에서 열었으면 개요 탭과 같은 "#id | 제목". 세션 줄에서 열었으면 워크스페이스+카테고리
  const title = element(
    "p",
    "dlg-title",
    todo ? `#${todo.id} | ${todo.title}` : session.workspace_name || UNCLASSIFIED_LABEL
  );
  const category = todo ? null : categories.find((item) => item.id === session.category_id);
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
