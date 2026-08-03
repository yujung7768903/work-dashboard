// 보드 탭 렌더. 카테고리 라벨 필터, 빠른 추가, 상태 토글, 완료 워크스페이스 이동
import * as api from "./api.js";
import { attachDragHandlers } from "./dnd.js";
import { renderBoardTab, run } from "./main.js";
import { startAutorunPolling } from "./autorun.js";
import { openDetail, rawTitleMark, startSessionPolling } from "./sessions.js";
import { focusWorkspace, menuItem } from "./workspace.js";

const STATUS_CYCLE = { todo: "doing", doing: "done", done: "todo" };
const GROUP_BY_WORKSPACE = "workspace";
const UNASSIGNED_KIND = "unassigned";
const UNASSIGNED_LABEL = "미분류";
const DONE = "done";
const TODO = "todo";
const ALL_CATEGORIES = { id: null, name: "전체" };
const NO_COMPLETED = "완료된 워크스페이스가 없습니다.";

// null 이면 전체. 카테고리 라벨을 누르면 그 카테고리 워크스페이스만 남음
let activeCategoryId = null;
// 케밥 메뉴가 열린 할일. 한 번에 하나만 열림
let openMenuTodoId = null;
// 그 케밥 메뉴가 라벨 목록으로 들어가 있는 할일. 메뉴를 닫으면 첫 화면으로 돌아온다
let labelMenuTodoId = null;
// 하위 할일을 펼쳐 둔 할일. 기본은 접힘이고, 재렌더에도 펼친 것만 유지된다
const expandedTodoIds = new Set();
// 설정 탭에서 만든 라벨 전체. 케밥 메뉴가 켜고 끌 목록으로 쓴다
let allLabels = [];

function showDone() {
  return document.getElementById("show-done").checked;
}

// 두 하위 탭이 함께 쓰는 위쪽 — 다음에 할 일·세션 패널·빠른 추가·카테고리 라벨.
// 하위 탭을 바꿔도 이 영역은 그대로 남아야 하므로 목록 렌더와 따로 둔다
export async function renderShared() {
  const [next, categories, labels] = await Promise.all([
    api.getNext(),
    api.getCategories(),
    api.getLabels(),
  ]);
  // 케밥 메뉴가 라벨 목록을 그리려면 있어야 한다. 메뉴를 열 때 따로 부르면
  // 메뉴가 한 박자 늦게 채워지므로 보드를 그릴 때 같이 받아 둔다
  allLabels = labels;
  renderNext(next);
  renderQuickCategories(categories);
  renderCategoryFilter(categories);
  startAutorunPolling();
  startSessionPolling();
}

// 고른 카테고리 라벨. 워크트리 탭도 같은 필터를 따른다
export function currentCategoryId() {
  return activeCategoryId;
}

export async function renderBoard() {
  const [tree] = await Promise.all([api.getTree(GROUP_BY_WORKSPACE), renderShared()]);
  const visible = tree.groups.filter(inActiveCategory);
  renderGroups(visible.filter((group) => !isComplete(group)));
  renderCompleted(visible.filter(isComplete));
  attachDragHandlers(renderBoard);
}

// 할일이 하나라도 있고 전부 done 이면 카드째 완료 영역으로 내려감
function isComplete(group) {
  return group.total_count > 0 && group.done_count === group.total_count;
}

// 미분류는 카테고리가 없으므로 필터를 걸면 숨김
function inActiveCategory(group) {
  return activeCategoryId === null || group.category_id === activeCategoryId;
}

function renderNext(next) {
  const target = document.getElementById("next-text");
  if (!next) {
    target.textContent = "없음";
    return;
  }
  const scope = next.workspace ? next.workspace.name : UNASSIGNED_LABEL;
  target.textContent = `${scope} / ${next.todo.title}`;
}

function renderQuickCategories(categories) {
  const select = document.getElementById("quick-category");
  const rendered = categories
    .map((category) => `<option value="${category.id}">${category.name}</option>`)
    .join("");
  if (select.innerHTML !== rendered) select.innerHTML = rendered;
}

// 목록이 그대로면 라벨을 다시 만들지 않는다. 통째로 새로 그리면 누른 라벨이
// 지워졌다 되살아나면서 한 번 깜빡인다
function renderCategoryFilter(categories) {
  const container = document.getElementById("category-filter");
  const signature = categories.map((c) => `${c.id}:${c.name}:${c.color}`).join("|");
  if (container.dataset.signature !== signature) {
    container.dataset.signature = signature;
    container.innerHTML = "";
    container.append(
      filterPill(ALL_CATEGORIES),
      ...categories.map((category) => filterPill(category))
    );
  }
  syncActivePills(container);
}

// 선택 표시만 다시 칠한다. 라벨을 누른 즉시 부르므로 보드 새로고침을 기다리지 않는다
function syncActivePills(container) {
  const active = String(activeCategoryId ?? "");
  container.querySelectorAll(".cat-pill").forEach((pill) => {
    pill.classList.toggle("active", pill.dataset.categoryId === active);
  });
}

function filterPill(category) {
  const pill = document.createElement("button");
  pill.className = "cat-pill";
  pill.textContent = category.name;
  // 색이 없으면 CSS 의 중립 회색 기본값을 씀 (전체 라벨)
  // 글자색은 CSS 의 --on-cat 기본값(흰색)에 맡긴다 — 고른 라벨은 전부 흰 글씨
  if (category.color) pill.style.setProperty("--cat", category.color);
  pill.dataset.categoryId = category.id ?? "";
  pill.addEventListener("click", () => {
    activeCategoryId = category.id;
    syncActivePills(pill.parentElement);
    // 라벨은 공통 영역이라 지금 열려 있는 하위 탭을 다시 그린다
    run(renderBoardTab);
  });
  return pill;
}

function renderGroups(groups) {
  const container = document.getElementById("groups");
  container.innerHTML = "";
  groups.forEach((group) => container.appendChild(groupElement(group)));
}

function renderCompleted(groups) {
  const container = document.getElementById("done-groups");
  container.innerHTML = "";
  if (!groups.length) {
    container.textContent = NO_COMPLETED;
    return;
  }
  // 완료 영역에서는 '완료 항목 표시' 와 무관하게 끝낸 할일을 보여줌
  groups.forEach((group) => container.appendChild(groupElement(group, true)));
}

function groupElement(group, alwaysShowDone = false) {
  const details = document.createElement("details");
  details.open = true;
  details.className = `group ${group.kind}`;
  details.dataset.groupId = group.id ?? "";
  details.dataset.kind = group.kind;
  // 카드 상단 배경색. 미분류는 색이 없어 CSS 기본값(옅은 회색)이 남음
  if (group.category_color) details.style.setProperty("--cat", group.category_color);
  if (group.kind !== UNASSIGNED_KIND) details.draggable = true;

  const summary = document.createElement("summary");
  const meta = [group.category_name, `${group.done_count}/${group.total_count}`]
    .filter(Boolean)
    .join("  ");
  const name = document.createElement("span");
  name.className = "group-name";
  name.textContent = group.name;
  const metaNode = document.createElement("span");
  metaNode.className = "group-meta";
  metaNode.textContent = meta;
  summary.append(name, metaNode);
  // 미분류는 위 빠른 추가 폼이 담당하므로 워크스페이스 카드에만 붙인다
  if (group.kind === GROUP_BY_WORKSPACE) summary.appendChild(groupAddButton(group));
  details.appendChild(summary);

  group.todos
    .filter((todo) => alwaysShowDone || showDone() || todo.status !== DONE)
    .forEach((todo) => {
      details.appendChild(todoElement(todo));
      if (expandedTodoIds.has(todo.id)) details.appendChild(subtaskList(todo));
    });
  return details;
}

// 카드에서 그 워크스페이스로 바로 할일 추가. 카테고리는 서버가 워크스페이스에서 가져온다
function groupAddButton(group) {
  const button = document.createElement("button");
  button.className = "group-add";
  button.innerHTML = PLUS_SVG;
  button.title = `${group.name} 에 할일 추가`;
  button.addEventListener("click", (event) => {
    // summary 클릭은 카드를 접으므로 기본 동작까지 막는다
    event.preventDefault();
    event.stopPropagation();
    const value = prompt(`"${group.name}" 에 추가할 할일 제목`);
    if (!value) return;
    run(async () => {
      await api.createTodo({ title: value, workspace_id: group.id });
      await renderBoard();
    });
  });
  return button;
}

function todoElement(todo) {
  const row = document.createElement("div");
  row.className = `todo ${todo.status}`;
  row.dataset.todoId = todo.id;
  row.draggable = true;

  const statusButton = document.createElement("button");
  statusButton.textContent = todo.status;
  statusButton.title = "상태 순환 (todo → doing → done)";
  statusButton.addEventListener("click", (event) => {
    // 행 전체가 팝업을 여는 클릭이라 버튼은 거기까지 올라가지 않게 막는다
    event.stopPropagation();
    run(async () => {
      await api.updateTodo(todo.id, { status: STATUS_CYCLE[todo.status] });
      await renderBoard();
    });
  });

  const title = document.createElement("span");
  title.className = "title";
  title.textContent = todo.title;
  if (todo.needs_title) title.append(rawTitleMark());

  row.append(statusButton, subtaskToggle(todo), title, labelStrip(todo), todoMenu(todo));
  // 세션 줄과 같은 팝업. 할일에서 열면 개요 탭이 먼저 보인다
  row.addEventListener("click", () => openDetail({ todo }));
  return row;
}

// 제목과 케밥 사이 세 번째 칸. 붙은 라벨이 없으면 빈 칸으로 남아 제목이 그만큼 넓게 쓴다
function labelStrip(todo) {
  const strip = document.createElement("span");
  strip.className = "todo-labels";
  (todo.labels || []).forEach((label) => {
    const pill = document.createElement("span");
    pill.className = "todo-label";
    pill.style.setProperty("--cat", label.color);
    pill.textContent = label.name;
    strip.appendChild(pill);
  });
  return strip;
}

// 사이드바 메뉴와 같은 16 격자 · currentColor 스트로크 아이콘. 펼치면 CSS 로 90도 돌린다
// 워크트리 탭의 커밋 토글도 같은 아이콘을 쓴다
export const CHEVRON_SVG = `<svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
  <path d="M6 3.5 10.5 8 6 12.5" fill="none" stroke="currentColor"
        stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
</svg>`;

// 사이드바 아이콘과 같은 격자·스트로크. 글자 + 는 폰트마다 글리프가 위아래로 치우쳐
// 세로 가운데를 맞춰도 어긋나 보이므로 도형으로 그린다
const PLUS_SVG = `<svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
  <path d="M8 3.5v9M3.5 8h9" fill="none" stroke="currentColor"
        stroke-width="1.5" stroke-linecap="round"/>
</svg>`;

// 상태 배지와 제목 사이의 펼침 아이콘. 하위가 없는 줄도 빈 자리를 남겨 제목 세로줄을 맞춘다
function subtaskToggle(todo) {
  const button = document.createElement("button");
  button.className = "subtask-toggle";
  button.innerHTML = CHEVRON_SVG;
  if (!todo.subtasks.length) {
    button.classList.add("empty");
    return button;
  }
  const open = expandedTodoIds.has(todo.id);
  const done = todo.subtasks.filter((subtask) => subtask.status === DONE).length;
  button.classList.toggle("open", open);
  button.title = `하위 할일 ${done}/${todo.subtasks.length}`;
  button.addEventListener("click", (event) => {
    // 행 전체가 상세 팝업을 여는 클릭이라 화살표는 거기까지 올라가지 않게 막는다
    event.stopPropagation();
    if (open) expandedTodoIds.delete(todo.id);
    else expandedTodoIds.add(todo.id);
    run(renderBoard);
  });
  return button;
}

// 하위 추가·삭제는 오른쪽 케밥 메뉴 안으로. 워크스페이스 카드와 같은 ws-menu 스타일 재사용
function todoMenu(todo) {
  const wrapper = document.createElement("div");
  wrapper.className = "ws-menu";
  const toggle = document.createElement("button");
  toggle.textContent = "⋮";
  toggle.title = "라벨 수정 · 하위 할일 추가 · 삭제";
  toggle.addEventListener("click", (event) => {
    event.stopPropagation();
    openMenuTodoId = openMenuTodoId === todo.id ? null : todo.id;
    labelMenuTodoId = null;
    run(renderBoard);
  });
  wrapper.appendChild(toggle);
  if (openMenuTodoId === todo.id) wrapper.appendChild(todoMenuItems(todo));
  return wrapper;
}

function todoMenuItems(todo) {
  const items = document.createElement("div");
  items.className = "ws-menu-items";
  if (labelMenuTodoId === todo.id) {
    items.append(
      menuItem("← 라벨 수정", () => {
        labelMenuTodoId = null;
        run(renderBoard);
      }),
      ...labelToggles(todo)
    );
    return items;
  }
  items.append(
    menuItem("라벨 수정", () => {
      labelMenuTodoId = todo.id;
      run(renderBoard);
    }),
    menuItem("하위 할일 추가", () =>
      run(async () => {
        openMenuTodoId = null;
        const value = prompt("하위 할일 제목");
        if (value) await api.createSubtask(todo.id, value);
        await renderBoard();
      })
    ),
    menuItem("삭제", () =>
      run(async () => {
        openMenuTodoId = null;
        if (confirm(`"${todo.title}" 삭제할까요? 하위 할일도 함께 사라집니다.`)) {
          await api.deleteTodo(todo.id);
        }
        await renderBoard();
      })
    )
  );
  return items;
}

// 라벨은 여러 개가 붙으므로 한 번 누를 때마다 하나씩 켜고 끈다. 메뉴는 닫지 않는다 —
// 두 개를 붙이려고 케밥을 두 번 여는 건 번거롭다
function labelToggles(todo) {
  if (!allLabels.length) return [emptyLabelHint()];
  const attached = new Set((todo.labels || []).map((label) => label.id));
  return allLabels.map((label) =>
    // 안 붙은 라벨은 체크 자리를 줄바꿈 없는 공백으로 비운다. 점 같은 기호를 넣으면
    // 이름의 일부처럼(".feature") 읽히고, 보통 공백은 nowrap 이 접어 세로줄이 어긋난다
    menuItem(`${attached.has(label.id) ? "✓" : "\u00a0"} ${label.name}`, () =>
      run(async () => {
        const next = attached.has(label.id)
          ? [...attached].filter((id) => id !== label.id)
          : [...attached, label.id];
        await api.updateTodo(todo.id, { label_ids: next });
        await renderBoard();
      })
    )
  );
}

// 라벨을 아직 하나도 안 만들었으면 빈 메뉴가 열려 고장처럼 보인다. 어디서 만드는지 알려준다
function emptyLabelHint() {
  const hint = document.createElement("button");
  hint.textContent = "설정 탭에서 먼저 만드세요";
  hint.disabled = true;
  return hint;
}

function subtaskList(todo) {
  const list = document.createElement("ul");
  list.className = "subtasks";
  todo.subtasks.forEach((subtask) => {
    const item = document.createElement("li");
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = subtask.status === DONE;
    checkbox.addEventListener("change", () =>
      run(async () => {
        await api.updateSubtask(subtask.id, {
          status: checkbox.checked ? DONE : TODO,
        });
        await renderBoard();
      })
    );
    item.append(checkbox, document.createTextNode(` ${subtask.title}`));
    list.appendChild(item);
  });
  return list;
}

document.getElementById("quick-add").addEventListener("submit", (event) => {
  event.preventDefault();
  const title = document.getElementById("quick-title");
  const categoryId = Number(document.getElementById("quick-category").value);
  run(async () => {
    await api.createTodo({ title: title.value, category_id: categoryId });
    title.value = "";
    await renderBoard();
  });
});

document.getElementById("board-controls").addEventListener("change", () => run(renderBoard));

// 항목 밖을 누르면 열린 케밥 메뉴 닫기
document.addEventListener("click", () => {
  if (openMenuTodoId === null) return;
  openMenuTodoId = null;
  labelMenuTodoId = null;
  run(renderBoard);
});
