// 할일 탭의 상태별 뷰. 상태를 컬럼으로 세우고, 컬럼 안에는 할일 하나가 카드 하나다.
// 어느 워크스페이스의 할일인지는 카드 위 작은 줄로 얹는다 — 워크스페이스를 카드로 감싸면
// 이름줄이 자리를 먹고 카드가 커져 목록을 훑기 어렵다.
// 데이터·카테고리 필터·다시 그리기는 board.js 가 맡고, 이 모듈은 그리기만 한다
import { todoElement } from "./board.js";
import { t } from "./i18n.js";

const UNASSIGNED_KIND = "unassigned";
const REVIEW = "review";
// 컬럼은 할일 줄이 쓰는 상태 표기와 같은 넷 — 검토 대기까지 한 칸으로 둔다
const COLUMNS = [
  { key: "todo", label: t("usage.statusTodo") },
  { key: "doing", label: t("usage.statusDoing") },
  { key: REVIEW, label: t("common.review") },
  { key: "done", label: t("common.done") },
];

export function drawKanban(groups) {
  const board = document.getElementById("kanban");
  board.innerHTML = "";
  COLUMNS.forEach((column) => board.appendChild(columnElement(column, groups)));
}

// 검토 대기는 status 가 아니라 자율 수행 기록이 남긴 것이고, 그 할일의 status 는 done 이다.
// 상태보다 이쪽이 먼저다 — 확인 전에 완료로 섞이면 검토를 놓친다 (static/js/board.js)
function columnOf(todo) {
  return todo.autorun_locked ? REVIEW : todo.status;
}

function columnElement(column, groups) {
  // 워크스페이스 순서를 그대로 따라 펼친다 — 같은 워크스페이스 할일이 붙어 있게 된다
  const cards = groups.flatMap((group) =>
    group.todos
      .filter((todo) => columnOf(todo) === column.key)
      .map((todo) => ({ group, todo }))
  );

  const element = document.createElement("section");
  element.className = "kanban-col";
  // 상태를 클래스로 붙이면 할일 줄 스타일(.todo·.done)이 컬럼에 걸린다 — 속성으로 둔다
  element.dataset.status = column.key;
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
  // 라벨·케밥·상세 팝업까지 워크스페이스별 뷰와 같은 줄을 쓴다. 상태 칩만 뺀다 —
  // 컬럼이 이미 그 상태를 말하므로 카드마다 되풀이할 값이 없다 (static/js/board.js)
  card.append(workspace, todoElement(todo, { withStatus: false }));
  return card;
}
