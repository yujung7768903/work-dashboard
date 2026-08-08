// 워크스페이스 카드 그리드. 수정을 누른 카드만 입력 가능
import * as api from "./api.js";
import { run } from "./main.js";

const CONTEXT_FIELDS = [
  ["background", "배경"],
  ["purpose", "목적"],
  ["goal", "목표"],
  ["considerations", "추가 고려사항"],
];
const WORKSPACE_STATUSES = ["active", "paused", "done"];
const EMPTY_LABEL = "(미입력)";
const GROUP_BY_WORKSPACE = "workspace";

let editingId = null;
let focusId = null;
let openMenuId = null;

// 보드 세션 줄에서 넘어올 때 강조할 카드 지정
export function focusWorkspace(workspaceId) {
  focusId = workspaceId;
}

export async function renderWorkspaceTab() {
  const [workspaces, categories, tree] = await Promise.all([
    api.getWorkspaces(),
    api.getCategories(),
    api.getTree(GROUP_BY_WORKSPACE),
  ]);
  renderCategoryOptions(categories);
  const list = document.getElementById("workspace-list");
  list.innerHTML = "";
  if (!workspaces.length) {
    list.textContent = "워크스페이스가 없습니다. 위에서 바로 만들 수 있습니다.";
    return;
  }
  const counts = countsByWorkspace(tree);
  workspaces.forEach((workspace) => {
    const card =
      workspace.id === editingId
        ? editCard(workspace, categories)
        : readCard(workspace, categories, counts);
    if (workspace.id === focusId) card.classList.add("focused");
    list.appendChild(card);
  });
  focusId = null;
}

function countsByWorkspace(tree) {
  const counts = {};
  tree.groups
    .filter((group) => group.kind === GROUP_BY_WORKSPACE)
    .forEach((group) => {
      counts[group.id] = `${group.done_count}/${group.total_count}`;
    });
  return counts;
}

function renderCategoryOptions(categories) {
  const select = document.getElementById("workspace-new-category");
  const rendered = optionsHtml(categories, null);
  if (select.innerHTML !== rendered) select.innerHTML = rendered;
}

function optionsHtml(items, selectedId) {
  return items
    .map(
      (item) =>
        `<option value="${item.id}"${item.id === selectedId ? " selected" : ""}>` +
        `${item.name}</option>`
    )
    .join("");
}

function readCard(workspace, categories, counts) {
  const category = categories.find((item) => item.id === workspace.category_id);
  const card = document.createElement("div");
  card.className = "ws-card";
  // 보드 카드와 같은 카테고리 색을 상단에 깖. 못 찾으면 CSS 기본값(옅은 회색)
  if (category?.color) card.style.setProperty("--cat", category.color);
  const jira = workspace.jira_id ? ` · ${workspace.jira_id}` : "";
  const progress = counts[workspace.id] ? ` · 할일 ${counts[workspace.id]}` : "";

  const head = document.createElement("div");
  head.className = "ws-head";
  const title = document.createElement("div");
  const name = document.createElement("div");
  name.className = "ws-title";
  name.textContent = workspace.name;
  const meta = document.createElement("div");
  meta.className = "ws-meta";
  meta.textContent = `${category?.name ?? "?"} · ${workspace.status}${jira}${progress}`;
  title.append(name, meta);
  head.append(title, menu(workspace));
  card.appendChild(head);

  CONTEXT_FIELDS.forEach(([key, label]) => {
    card.appendChild(readRow(label, workspace[key]));
  });
  return card;
}

function readRow(label, text) {
  const row = document.createElement("div");
  row.className = "ws-row";
  const caption = document.createElement("div");
  caption.className = "label";
  caption.textContent = label;
  const value = document.createElement("div");
  value.className = text ? "value" : "value empty";
  value.textContent = text || EMPTY_LABEL;
  row.append(caption, value);
  return row;
}

function menu(workspace) {
  const wrapper = document.createElement("div");
  wrapper.className = "ws-menu";
  const toggle = document.createElement("button");
  toggle.textContent = "…";
  toggle.title = "수정 · 삭제";
  toggle.addEventListener("click", (event) => {
    event.stopPropagation();
    openMenuId = openMenuId === workspace.id ? null : workspace.id;
    run(renderWorkspaceTab);
  });
  wrapper.appendChild(toggle);
  if (openMenuId === workspace.id) {
    wrapper.appendChild(menuItems(workspace));
  }
  return wrapper;
}

function menuItems(workspace) {
  const items = document.createElement("div");
  items.className = "ws-menu-items";
  items.append(
    menuItem("수정", () => {
      editingId = workspace.id;
      openMenuId = null;
      run(renderWorkspaceTab);
    }),
    menuItem("삭제", () =>
      run(async () => {
        openMenuId = null;
        if (!confirm("삭제하면 소속 할일은 미분류로 내려갑니다. 진행할까요?")) {
          await renderWorkspaceTab();
          return;
        }
        await api.deleteWorkspace(workspace.id);
        if (editingId === workspace.id) editingId = null;
        await renderWorkspaceTab();
      })
    )
  );
  return items;
}

// 보드의 할일 케밥 메뉴도 같은 항목 버튼을 씀
export function menuItem(label, onClick) {
  const button = document.createElement("button");
  button.textContent = label;
  button.addEventListener("click", (event) => {
    event.stopPropagation();
    onClick();
  });
  return button;
}

function editCard(workspace, categories) {
  const card = document.createElement("div");
  card.className = "ws-card";
  const inputs = {};

  inputs.name = textInput(workspace.name);
  card.appendChild(labeled("이름", inputs.name));

  inputs.category_id = document.createElement("select");
  inputs.category_id.innerHTML = optionsHtml(categories, workspace.category_id);
  card.appendChild(labeled("카테고리", inputs.category_id));

  inputs.status = document.createElement("select");
  inputs.status.innerHTML = WORKSPACE_STATUSES.map(
    (value) =>
      `<option value="${value}"${value === workspace.status ? " selected" : ""}>` +
      `${value}</option>`
  ).join("");
  card.appendChild(labeled("상태", inputs.status));

  inputs.jira_id = textInput(workspace.jira_id ?? "");
  card.appendChild(labeled("Jira ID", inputs.jira_id));

  CONTEXT_FIELDS.forEach(([key, label]) => {
    inputs[key] = document.createElement("textarea");
    inputs[key].value = workspace[key] ?? "";
    card.appendChild(labeled(label, inputs[key]));
  });

  card.appendChild(editActions(workspace, inputs));
  return card;
}

function textInput(value) {
  const input = document.createElement("input");
  input.value = value;
  return input;
}

function labeled(label, control) {
  const row = document.createElement("div");
  row.className = "ws-row";
  const caption = document.createElement("div");
  caption.className = "label";
  caption.textContent = label;
  row.append(caption, control);
  return row;
}

function editActions(workspace, inputs) {
  const actions = document.createElement("div");
  actions.className = "ws-actions";

  const save = document.createElement("button");
  save.textContent = "저장";
  save.addEventListener("click", () =>
    run(async () => {
      await api.updateWorkspace(workspace.id, collect(inputs));
      editingId = null;
      await renderWorkspaceTab();
    })
  );

  const cancel = document.createElement("button");
  cancel.textContent = "취소";
  cancel.addEventListener("click", () => {
    editingId = null;
    run(renderWorkspaceTab);
  });

  actions.append(save, cancel);
  return actions;
}

function collect(inputs) {
  const fields = {
    name: inputs.name.value,
    category_id: Number(inputs.category_id.value),
    status: inputs.status.value,
    jira_id: inputs.jira_id.value || null,
  };
  CONTEXT_FIELDS.forEach(([key]) => {
    fields[key] = inputs[key].value;
  });
  return fields;
}

// 카드 밖을 누르면 열린 메뉴 닫기
document.addEventListener("click", () => {
  if (openMenuId === null) return;
  openMenuId = null;
  run(renderWorkspaceTab);
});

document.getElementById("workspace-add").addEventListener("submit", (event) => {
  event.preventDefault();
  const name = document.getElementById("workspace-new-name");
  const categoryId = Number(document.getElementById("workspace-new-category").value);
  run(async () => {
    const created = await api.createWorkspace({
      category_id: categoryId,
      name: name.value,
    });
    name.value = "";
    focusId = created.id;
    await renderWorkspaceTab();
  });
});
