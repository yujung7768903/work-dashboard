// 보드 탭 렌더. 그룹핑 전환, 빠른 추가, 상태 토글, 오늘 완료
import * as api from "./api.js";
import { attachDragHandlers } from "./dnd.js";
import { run } from "./main.js";
import { startSessionPolling } from "./sessions.js";
import { focusWorkspace } from "./workspace.js";

const STATUS_CYCLE = { todo: "doing", doing: "done", done: "todo" };
const UNASSIGNED_KIND = "unassigned";
const UNASSIGNED_LABEL = "미분류";
const DONE = "done";
const TODO = "todo";

export function currentGroupBy() {
  return document.querySelector('input[name="group-by"]:checked').value;
}

function showDone() {
  return document.getElementById("show-done").checked;
}

export async function renderBoard() {
  const [tree, next, categories, doneToday] = await Promise.all([
    api.getTree(currentGroupBy()),
    api.getNext(),
    api.getCategories(),
    api.getDoneToday(),
  ]);
  renderNext(next);
  renderCategoryOptions(categories);
  renderGroups(tree.groups);
  renderDoneToday(doneToday);
  attachDragHandlers(renderBoard);
  startSessionPolling(openWorkspace);
}

function openWorkspace(workspaceId) {
  // 세션 줄 클릭 → 워크스페이스 탭에서 해당 카드 강조
  focusWorkspace(workspaceId);
  document.querySelector('#tabs button[data-tab="workspace"]').click();
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

function renderCategoryOptions(categories) {
  const select = document.getElementById("quick-category");
  const rendered = categories
    .map((category) => `<option value="${category.id}">${category.name}</option>`)
    .join("");
  if (select.innerHTML !== rendered) select.innerHTML = rendered;
}

function renderGroups(groups) {
  const container = document.getElementById("groups");
  container.innerHTML = "";
  groups.forEach((group) => container.appendChild(groupElement(group)));
}

function groupElement(group) {
  const details = document.createElement("details");
  details.open = true;
  details.className = `group ${group.kind}`;
  details.dataset.groupId = group.id ?? "";
  details.dataset.kind = group.kind;
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
    .filter((todo) => showDone() || todo.status !== DONE)
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

function renderDoneToday(rows) {
  document.querySelector("#done-today summary").textContent = `오늘 완료 ${rows.length}건`;
  const list = document.getElementById("done-list");
  list.innerHTML = "";
  rows.forEach((row) => {
    const item = document.createElement("li");
    item.textContent = `${row.workspace_name} / ${row.title}`;
    list.appendChild(item);
  });
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
