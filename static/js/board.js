// 보드 탭 렌더. 카테고리 라벨 필터, 빠른 추가, 상태 토글, 완료 워크스페이스 이동
import * as api from "./api.js";
import { attachDragHandlers } from "./dnd.js";
import { run } from "./main.js";
import { startSessionPolling } from "./sessions.js";

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

function showDone() {
  return document.getElementById("show-done").checked;
}

export async function renderBoard() {
  const [tree, next, categories] = await Promise.all([
    api.getTree(GROUP_BY_WORKSPACE),
    api.getNext(),
    api.getCategories(),
  ]);
  renderNext(next);
  renderQuickCategories(categories);
  renderCategoryFilter(categories);
  const visible = tree.groups.filter(inActiveCategory);
  renderGroups(visible.filter((group) => !isComplete(group)));
  renderCompleted(visible.filter(isComplete));
  attachDragHandlers(renderBoard);
  startSessionPolling();
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

function renderCategoryFilter(categories) {
  const container = document.getElementById("category-filter");
  container.innerHTML = "";
  container.append(
    filterPill(ALL_CATEGORIES),
    ...categories.map((category) => filterPill(category))
  );
}

// 선택된 라벨은 카테고리 색을 그대로 채우므로 글자를 흰·검 중 대비가 큰 쪽으로 고른다.
// 경계값(0.179)에서도 양쪽 다 4.5:1 을 넘겨서 어떤 색을 골라도 읽을 수 있다
function inkOn(hex) {
  const channel = (index) => {
    const value = parseInt(hex.slice(1 + index * 2, 3 + index * 2), 16) / 255;
    return value <= 0.03928 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
  };
  const luminance = 0.2126 * channel(0) + 0.7152 * channel(1) + 0.0722 * channel(2);
  return luminance < 0.179 ? "#fff" : "#14181d";
}

function filterPill(category) {
  const pill = document.createElement("button");
  pill.className = "cat-pill";
  pill.textContent = category.name;
  // 색이 없으면 CSS 의 중립 회색 기본값을 씀 (전체 라벨)
  if (category.color) {
    pill.style.setProperty("--cat", category.color);
    pill.style.setProperty("--on-cat", inkOn(category.color));
  }
  pill.classList.toggle("active", activeCategoryId === category.id);
  pill.addEventListener("click", () => {
    activeCategoryId = category.id;
    run(renderBoard);
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
  name.textContent = group.name;
  const metaNode = document.createElement("span");
  metaNode.className = "group-meta";
  metaNode.textContent = meta;
  summary.append(name, metaNode);
  details.appendChild(summary);

  group.todos
    .filter((todo) => alwaysShowDone || showDone() || todo.status !== DONE)
    .forEach((todo) => {
      details.appendChild(todoElement(todo));
      if (todo.subtasks.length) details.appendChild(subtaskList(todo));
    });
  return details;
}

function todoElement(todo) {
  const row = document.createElement("div");
  row.className = `todo ${todo.status}`;
  row.dataset.todoId = todo.id;
  row.draggable = true;

  const statusButton = document.createElement("button");
  statusButton.textContent = todo.status;
  statusButton.title = "상태 순환 (todo → doing → done)";
  statusButton.addEventListener("click", () =>
    run(async () => {
      await api.updateTodo(todo.id, { status: STATUS_CYCLE[todo.status] });
      await renderBoard();
    })
  );

  const title = document.createElement("span");
  title.className = "title";
  title.textContent = todo.title;

  const addSubtask = document.createElement("button");
  addSubtask.textContent = "+하위";
  addSubtask.addEventListener("click", () =>
    run(async () => {
      const value = prompt("하위 할일 제목");
      if (!value) return;
      await api.createSubtask(todo.id, value);
      await renderBoard();
    })
  );

  const remove = document.createElement("button");
  remove.textContent = "×";
  remove.addEventListener("click", () =>
    run(async () => {
      if (!confirm(`"${todo.title}" 삭제할까요? 하위 할일도 함께 사라집니다.`)) return;
      await api.deleteTodo(todo.id);
      await renderBoard();
    })
  );

  row.append(statusButton, title, addSubtask, remove);
  return row;
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
