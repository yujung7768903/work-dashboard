// 카테고리 관리. 색·이모지를 여기서 바꾸고, 각 줄에서 워크스페이스를 바로 만들 수 있음
import * as api from "./api.js";
import { run } from "./main.js";

// 이모지 피커 격자. CSS 가 8열이므로 8의 배수로 두면 줄이 맞음
const EMOJI_CHOICES = [
  "💻", "🖥️", "⌨️", "📱", "🧩", "⚙️", "🛠️", "🔧",
  "🚨", "⚠️", "🔥", "⚡", "🐛", "🩹", "🔍", "🧪",
  "📋", "📝", "📄", "📊", "📈", "🗂️", "🗓️", "⏱️",
  "🚀", "✅", "🎯", "📌", "🔖", "💡", "🧠", "🤖",
  "🔐", "🌐", "🗄️", "☁️", "📦", "🔁", "📮", "💬",
];
let openPickerId = null;

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
    emojiPicker(category),
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

function emojiPicker(category) {
  const wrapper = document.createElement("div");
  wrapper.className = "emoji-pick";
  const toggle = document.createElement("button");
  toggle.textContent = category.emoji;
  toggle.title = "이모지 선택";
  toggle.addEventListener("click", (event) => {
    event.stopPropagation();
    openPickerId = openPickerId === category.id ? null : category.id;
    run(renderCategories);
  });
  wrapper.appendChild(toggle);
  if (openPickerId === category.id) wrapper.appendChild(emojiGrid(category));
  return wrapper;
}

// 지우기는 두지 않는다. 카테고리는 항상 이모지를 갖는다
function emojiGrid(category) {
  const grid = document.createElement("div");
  grid.className = "emoji-grid";
  EMOJI_CHOICES.forEach((emoji) => grid.appendChild(emojiCell(category, emoji)));
  return grid;
}

function emojiCell(category, emoji) {
  const button = document.createElement("button");
  button.textContent = emoji;
  button.addEventListener("click", (event) => {
    event.stopPropagation();
    run(async () => {
      openPickerId = null;
      await api.updateCategory(category.id, { emoji });
      await renderCategories();
    });
  });
  return button;
}

function moveButton(index, categories, offset) {
  const target = index + offset;
  const button = document.createElement("button");
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
  button.textContent = "×";
  button.addEventListener("click", () =>
    run(async () => {
      await api.deleteCategory(category.id);
      await renderCategories();
    })
  );
  return button;
}

// 격자 밖을 누르면 닫기
document.addEventListener("click", () => {
  if (openPickerId === null) return;
  openPickerId = null;
  run(renderCategories);
});

document.getElementById("category-add").addEventListener("submit", (event) => {
  event.preventDefault();
  const input = document.getElementById("category-name");
  run(async () => {
    await api.createCategory(input.value);
    input.value = "";
    await renderCategories();
  });
});
