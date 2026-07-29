// 드래그 재정렬·이동. 렌더 직후 attachDragHandlers 로 리스너를 붙임
import * as api from "./api.js";
import { currentGroupBy } from "./board.js";
import { run } from "./main.js";

const GROUP_BY_WORKSPACE = "workspace";
const UNASSIGNED_KIND = "unassigned";
const DROP_CLASS = "drop-target";
const DRAG_GROUP = "group";
const DRAG_TODO = "todo";

let dragged = null;

export function attachDragHandlers(refresh) {
  document.querySelectorAll(".group").forEach((group) => {
    attachGroupHandlers(group, refresh);
    group.querySelectorAll(".todo").forEach(attachTodoHandlers);
  });
}

function attachGroupHandlers(group, refresh) {
  group.addEventListener("dragstart", (event) => {
    if (event.target !== group) return;
    dragged = { type: DRAG_GROUP, element: group };
    event.stopPropagation();
  });
  group.addEventListener("dragover", (event) => {
    event.preventDefault();
    group.classList.add(DROP_CLASS);
  });
  group.addEventListener("dragleave", () => group.classList.remove(DROP_CLASS));
  group.addEventListener("drop", (event) => {
    event.preventDefault();
    event.stopPropagation();
    group.classList.remove(DROP_CLASS);
    const payload = dragged;
    dragged = null;
    if (!payload) return;
    run(async () => {
      if (payload.type === DRAG_GROUP) await dropGroup(payload.element, group);
      else await dropTodo(payload.element, group);
      await refresh();
    });
  });
}

function attachTodoHandlers(todo) {
  todo.addEventListener("dragstart", (event) => {
    dragged = { type: DRAG_TODO, element: todo };
    event.stopPropagation();
  });
}

async function dropGroup(source, target) {
  if (source === target) return;
  if (currentGroupBy() !== GROUP_BY_WORKSPACE) {
    throw new Error("워크스페이스 기준 그룹핑에서만 순위를 바꿀 수 있습니다");
  }
  if (source.dataset.kind === UNASSIGNED_KIND || target.dataset.kind === UNASSIGNED_KIND) {
    throw new Error("미분류 그룹은 순위를 바꿀 수 없습니다");
  }
  const all = await api.getWorkspaces();
  await api.reorder("workspaces", movedOrder(all, source, target));
}

async function dropTodo(todoElement, group) {
  const todoId = Number(todoElement.dataset.todoId);
  const sourceGroup = todoElement.closest(".group");
  if (sourceGroup === group) {
    const ids = [...group.querySelectorAll(".todo")].map((node) =>
      Number(node.dataset.todoId)
    );
    await api.reorder("todos", ids, scopeOf(group));
    return;
  }
  if (currentGroupBy() !== GROUP_BY_WORKSPACE) {
    throw new Error("카테고리 기준에서는 그룹 간 이동을 할 수 없습니다");
  }
  await api.updateTodo(todoId, { workspace_id: scopeOf(group) });
}

function movedOrder(all, source, target) {
  // 화면에 없는(빈) 워크스페이스도 포함해야 서버 재정렬 검증을 통과함
  const ids = all.map((item) => item.id);
  const sourceId = Number(source.dataset.groupId);
  const targetId = Number(target.dataset.groupId);
  const [moved] = ids.splice(ids.indexOf(sourceId), 1);
  ids.splice(ids.indexOf(targetId), 0, moved);
  return ids;
}

function scopeOf(group) {
  return group.dataset.kind === UNASSIGNED_KIND ? null : Number(group.dataset.groupId);
}
