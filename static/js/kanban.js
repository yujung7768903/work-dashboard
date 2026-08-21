// 칸반 뷰. 상태를 컬럼으로 세우고, 컬럼 안에 워크스페이스 카드를, 카드 안에 그 상태의
// 할일만 담는다. 목록 뷰와 같은 /api/tree 를 쓰므로 서버에 새 엔드포인트를 두지 않는다
import * as api from "./api.js";
import { currentCategoryId, setTodoRefresh, todoElement } from "./board.js";
import { t } from "./i18n.js";

const GROUP_BY_WORKSPACE = "workspace";
const UNASSIGNED_KIND = "unassigned";
// 컬럼 순서가 곧 상태 진행 순서. 할일 줄의 상태 버튼이 이 순서로 다음 칸으로 옮긴다
const COLUMNS = [
  { status: "todo", label: t("usage.statusTodo") },
  { status: "doing", label: t("usage.statusDoing") },
  { status: "done", label: t("common.done") },
];

export async function renderKanban() {
  // 할일 줄의 상태 버튼·케밥이 목록 대신 이 화면을 다시 그리게 한다 (static/js/board.js)
  setTodoRefresh(renderKanban);
  const tree = await api.getTree(GROUP_BY_WORKSPACE);
  const groups = tree.groups.filter(inActiveCategory);
  const board = document.getElementById("kanban");
  board.innerHTML = "";
  COLUMNS.forEach((column) => board.appendChild(columnElement(column, groups)));
}

// 카테고리 라벨은 목록 뷰와 공유한다 — 라벨을 걸어 둔 채 뷰를 바꿔도 그대로 걸려 있다
function inActiveCategory(group) {
  const active = currentCategoryId();
  return active === null || group.category_id === active;
}

function columnElement(column, groups) {
  // 그 상태의 할일이 없는 워크스페이스는 카드째 빠진다 — 컬럼마다 빈 카드가 늘어서면
  // 정작 할 일이 있는 카드가 아래로 밀린다
  const cards = groups
    .map((group) => ({ group, todos: group.todos.filter(isIn(column)) }))
    .filter((card) => card.todos.length);
  const total = cards.reduce((sum, card) => sum + card.todos.length, 0);

  const element = document.createElement("section");
  element.className = "kanban-col";
  // 상태를 클래스로 붙이면 할일 줄 스타일(.todo·.done)이 컬럼에 걸린다 — 속성으로 둔다
  element.dataset.status = column.status;
  element.appendChild(columnHead(column, total));
  if (!cards.length) element.appendChild(emptyNote());
  cards.forEach((card) => element.appendChild(cardElement(card)));
  return element;
}

function isIn(column) {
  return (todo) => todo.status === column.status;
}

function columnHead(column, total) {
  const head = document.createElement("div");
  head.className = "kanban-head";
  const name = document.createElement("span");
  name.className = "kanban-col-name";
  name.textContent = column.label;
  const count = document.createElement("span");
  count.className = "kanban-count";
  count.textContent = String(total);
  head.append(name, count);
  return head;
}

function emptyNote() {
  const note = document.createElement("p");
  note.className = "kanban-empty";
  note.textContent = t("board.kanbanEmpty");
  return note;
}

function cardElement({ group, todos }) {
  const card = document.createElement("article");
  card.className = `kanban-card ${group.kind}`;
  // 카드 머리 배경은 목록 뷰 카드와 같은 카테고리 색. 미분류는 CSS 기본값(옅은 회색)
  if (group.category_color) card.style.setProperty("--cat", group.category_color);

  const head = document.createElement("header");
  const name = document.createElement("span");
  name.className = "group-name";
  name.textContent =
    group.kind === UNASSIGNED_KIND ? t("common.unassigned") : group.name;
  const meta = document.createElement("span");
  meta.className = "group-meta";
  // 컬럼이 이미 상태를 말하므로 목록 뷰의 done/total 대신 이 컬럼에 든 건수만
  meta.textContent = String(todos.length);
  head.append(name, meta);
  card.appendChild(head);

  // 상태 버튼·라벨·상세 팝업까지 목록 뷰와 같은 줄을 쓴다 (static/js/board.js)
  todos.forEach((todo) => card.appendChild(todoElement(todo)));
  return card;
}
