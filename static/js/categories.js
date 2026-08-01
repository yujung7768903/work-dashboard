// 카테고리 관리. 색을 여기서 바꾸고, 각 줄에서 워크스페이스를 바로 만들 수 있음
import * as api from "./api.js";
import { run } from "./main.js";

export async function renderCategories() {
  const categories = await api.getCategories();
  const list = document.getElementById("category-list");
  list.innerHTML = "";
  categories.forEach((category, index) =>
    list.appendChild(categoryRow(category, index, categories))
  );
}

function categoryRow(category, index, categories) {
  const item = document.createElement("li");

  const name = document.createElement("input");
  name.value = category.name;
  name.addEventListener("blur", () =>
    run(async () => {
      if (name.value === category.name) return;
      await api.updateCategory(category.id, { name: name.value });
      await renderCategories();
    })
  );

  item.append(
    colorInput(category),
    name,
    moveButton(index, categories, -1),
    moveButton(index, categories, 1),
    addWorkspaceButton(category),
    removeButton(category)
  );
  return item;
}

function colorInput(category) {
  const input = document.createElement("input");
  input.type = "color";
  input.value = category.color;
  input.title = "카드 상단 배경색";
  // change: 색을 고르는 중이 아니라 확정했을 때만 저장
  input.addEventListener("change", () =>
    run(async () => {
      await api.updateCategory(category.id, { color: input.value });
      await renderCategories();
    })
  );
  return input;
}

function moveButton(index, categories, offset) {
  const target = index + offset;
  const button = document.createElement("button");
  button.className = "icon-btn";
  button.textContent = offset < 0 ? "↑" : "↓";
  button.disabled = target < 0 || target >= categories.length;
  button.addEventListener("click", () =>
    run(async () => {
      const ids = categories.map((item) => item.id);
      const [moved] = ids.splice(index, 1);
      ids.splice(target, 0, moved);
      await api.reorder("categories", ids);
      await renderCategories();
    })
  );
  return button;
}

function addWorkspaceButton(category) {
  const button = document.createElement("button");
  button.textContent = "워크스페이스 추가";
  button.addEventListener("click", () =>
    run(async () => {
      const name = prompt(`"${category.name}" 에 만들 워크스페이스 이름`);
      if (!name) return;
      await api.createWorkspace({ category_id: category.id, name });
      alert("생성됨. 워크스페이스 탭에서 배경·목적·목표를 채우세요.");
    })
  );
  return button;
}

function removeButton(category) {
  const button = document.createElement("button");
  button.className = "icon-btn";
  button.textContent = "×";
  button.addEventListener("click", () =>
    run(async () => {
      await api.deleteCategory(category.id);
      await renderCategories();
    })
  );
  return button;
}

document.getElementById("category-add").addEventListener("submit", (event) => {
  event.preventDefault();
  const input = document.getElementById("category-name");
  run(async () => {
    await api.createCategory(input.value);
    input.value = "";
    await renderCategories();
  });
});
