// 칸반 뷰. 상태를 컬럼으로 세우고, 컬럼 안에는 할일 하나가 카드 하나다. 어느
// 워크스페이스의 할일인지는 카드 위 작은 줄로 얹는다 — 워크스페이스를 카드로 감싸면
// 이름줄이 자리를 먹고 카드가 커져 목록을 훑기 어렵다.
// 목록 뷰와 같은 /api/tree 를 쓰므로 서버에 새 엔드포인트를 두지 않는다
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
  // 워크스페이스 순서를 그대로 따라 펼친다 — 같은 워크스페이스 할일이 붙어 있게 된다
  const cards = groups.flatMap((group) =>
    group.todos.filter((todo) => todo.status === column.status).map((todo) => ({ group, todo }))
  );

  const element = document.createElement("section");
  element.className = "kanban-col";
  // 상태를 클래스로 붙이면 할일 줄 스타일(.todo·.done)이 컬럼에 걸린다 — 속성으로 둔다
  element.dataset.status = column.status;
  element.appendChild(columnHead(column, cards.length));
  if (!cards.length) element.appendChild(emptyNote());
  cards.forEach((card) => element.appendChild(cardElement(card)));
  return element;
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

function cardElement({ group, todo }) {
  const card = document.createElement("article");
  card.className = `kanban-card ${group.kind}`;
  // 카드 왼쪽 색띠와 워크스페이스 이름 색이 그 카테고리 색. 미분류는 CSS 기본값(회색)
  if (group.category_color) card.style.setProperty("--cat", group.category_color);

  const workspace = document.createElement("span");
  workspace.className = "kanban-ws";
  workspace.textContent =
    group.kind === UNASSIGNED_KIND ? t("common.unassigned") : group.name;
  // 상태 버튼·라벨·상세 팝업까지 목록 뷰와 같은 줄을 쓴다 (static/js/board.js)
  card.append(workspace, todoElement(todo));
  return card;
}
