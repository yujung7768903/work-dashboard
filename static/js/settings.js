// 설정 탭. 카테고리(소속·하나)와 라벨(성격·여러 개)을 같은 모양의 줄로 관리한다.
// 언어는 화면 전체에 걸려 있어 여기가 아니라 상단 우측 아이콘에 있다 (language.js)
// 두 목록은 이름·색·순서·삭제가 똑같아 줄 만드는 코드를 공유하고, 다른 점만 설정으로 넘긴다
import * as api from "./api.js";
import { renderGtasks } from "./gtasks.js";
import { t } from "./i18n.js";
import { run } from "./main.js";

const CATEGORIES = {
  listId: "category-list",
  formId: "category-add",
  inputId: "category-name",
  colorTitle: t("settings.categoryColor"),
  load: api.getCategories,
  create: api.createCategory,
  update: api.updateCategory,
  remove: api.deleteCategory,
  reorderKind: "categories",
  extra: addWorkspaceButton,
};

const LABELS = {
  listId: "label-list",
  formId: "label-add",
  inputId: "label-name",
  colorTitle: t("settings.labelColor"),
  load: api.getLabels,
  create: api.createLabel,
  update: api.updateLabel,
  remove: api.deleteLabel,
  reorderKind: "labels",
};

export async function renderSettings() {
  await Promise.all([renderList(CATEGORIES), renderList(LABELS), renderGtasks()]);
}

async function renderList(config) {
  const items = await config.load();
  const list = document.getElementById(config.listId);
  list.innerHTML = "";
  items.forEach((item, index) => list.appendChild(row(config, item, index, items)));
}

function row(config, item, index, items) {
  const line = document.createElement("li");
  line.append(
    colorInput(config, item),
    nameInput(config, item),
    moveButton(config, index, items, -1),
    moveButton(config, index, items, 1)
  );
  if (config.extra) line.appendChild(config.extra(item));
  line.appendChild(removeButton(config, item));
  return line;
}

function nameInput(config, item) {
  const input = document.createElement("input");
  input.value = item.name;
  input.addEventListener("blur", () =>
    run(async () => {
      if (input.value === item.name) return;
      await config.update(item.id, { name: input.value });
      await renderList(config);
    })
  );
  return input;
}

function colorInput(config, item) {
  const input = document.createElement("input");
  input.type = "color";
  input.value = item.color;
  input.title = config.colorTitle;
  // change: 색을 고르는 중이 아니라 확정했을 때만 저장
  input.addEventListener("change", () =>
    run(async () => {
      await config.update(item.id, { color: input.value });
      await renderList(config);
    })
  );
  return input;
}

function moveButton(config, index, items, offset) {
  const target = index + offset;
  const button = document.createElement("button");
  button.className = "icon-btn";
  button.textContent = offset < 0 ? "↑" : "↓";
  button.disabled = target < 0 || target >= items.length;
  button.addEventListener("click", () =>
    run(async () => {
      const ids = items.map((entry) => entry.id);
      const [moved] = ids.splice(index, 1);
      ids.splice(target, 0, moved);
      await api.reorder(config.reorderKind, ids);
      await renderList(config);
    })
  );
  return button;
}

function addWorkspaceButton(category) {
  const button = document.createElement("button");
  button.textContent = t("settings.addWorkspace");
  button.addEventListener("click", () =>
    run(async () => {
      const name = prompt(t("settings.workspaceNamePrompt", { category: category.name }));
      if (!name) return;
      await api.createWorkspace({ category_id: category.id, name });
      alert(t("settings.workspaceCreated"));
    })
  );
  return button;
}

function removeButton(config, item) {
  const button = document.createElement("button");
  button.className = "icon-btn";
  button.textContent = "×";
  button.addEventListener("click", () =>
    run(async () => {
      await deleteWithConfirm(config, item.id);
      await renderList(config);
    })
  );
  return button;
}

// 붙은 게 없으면 서버가 바로 지운다. 딸린 게 있을 때만 되묻고 force 로 재요청
async function deleteWithConfirm(config, id) {
  try {
    await config.remove(id);
  } catch (error) {
    if (!error.confirm) throw error;
    if (!confirm(error.message)) return;
    await config.remove(id, true);
  }
}

[CATEGORIES, LABELS].forEach((config) => {
  document.getElementById(config.formId).addEventListener("submit", (event) => {
    event.preventDefault();
    const input = document.getElementById(config.inputId);
    run(async () => {
      await config.create(input.value);
      input.value = "";
      await renderList(config);
    });
  });
});
