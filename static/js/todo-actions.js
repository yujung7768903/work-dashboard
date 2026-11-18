// 할일 상세 팝업의 동작 줄 — 시작(세션 띄우기)·라벨 켜고 끄기·삭제. 보드 할일 케밥에 있던 것을
// 보드가 없어진 뒤(사용자 결정 11-18) 할일 상세로 옮겼다. 트리·매니저·사용량 어디서 열어도 같은 팝업이다
import * as api from "./api.js";
import { fromKorean, t } from "./i18n.js";

/**
 * todo: /api/todos/<id> 의 todo (labels 포함). onChange: 라벨·시작 뒤 다시 그릴 것. onDeleted: 지운 뒤 할 것
 */
export function todoActions(todo, { onChange = () => {}, onDeleted = () => {} } = {}) {
  const row = element("div", "todo-actions");
  const start = element("button", null, t("todo.start"));
  start.type = "button";
  start.title = t("todo.startHint");
  start.addEventListener("click", async () => {
    start.disabled = true;
    try {
      const result = await startFlow(todo);
      if (result?.message) alert(fromKorean(result.message));
      await onChange();
    } finally {
      start.disabled = false;
    }
  });
  const remove = element("button", "todo-delete", t("todo.delete"));
  remove.type = "button";
  remove.addEventListener("click", async () => {
    // 물어보는 동안 팝업은 그대로 둔다 — 무엇을 지우는지 보면서 답해야 한다
    if (!confirm(t("todo.confirmDelete", { title: todo.title }))) return;
    await api.deleteTodo(todo.id);
    await onDeleted();
  });
  const labels = element("span", "todo-labels");
  row.append(start, labels, remove);
  fillLabels(labels, todo, onChange);
  return row;
}

// 위치를 모르면 서버가 reason.noCwd 로 막는다 — 그때만 폴더를 물어 다시 보낸다
async function startFlow(todo) {
  try {
    return await api.startTodo(todo.id);
  } catch (error) {
    if (error.message !== t("reason.noCwd")) {
      alert(error.message);
      return null;
    }
  }
  // 폴더 선택기는 모듈을 들이는 순간 팝업 요소를 잡는다 — 팝업만 검사하는 체크가 DOM 없이 돌 수 있게 쓸 때 들인다
  const { pickDirectory } = await import("./browse.js");
  const cwd = await pickDirectory();
  if (!cwd) return null;
  try {
    return await api.startTodo(todo.id, cwd);
  } catch (error) {
    alert(error.message);
    return null;
  }
}

// 라벨은 여러 개가 붙는다 — 누를 때마다 하나씩 켜고 끈다(자율 수행 후보는 'auto' 라벨로 고른다)
async function fillLabels(box, todo, onChange) {
  let all;
  try {
    all = await api.getLabels();
  } catch {
    return;
  }
  if (!Array.isArray(all)) return;
  if (!all.length) {
    box.appendChild(element("span", "muted", t("todo.noLabels")));
    return;
  }
  const attached = new Set((todo.labels ?? []).map((label) => label.id));
  all.forEach((label) => {
    const chip = element("button", "todo-label", label.name);
    chip.type = "button";
    chip.setAttribute("aria-pressed", String(attached.has(label.id)));
    if (label.color) chip.style.setProperty("--cat", label.color);
    chip.addEventListener("click", async () => {
      const next = attached.has(label.id) ? [...attached].filter((id) => id !== label.id) : [...attached, label.id];
      chip.disabled = true;
      try {
        await api.updateTodo(todo.id, { label_ids: next });
        if (attached.has(label.id)) attached.delete(label.id);
        else attached.add(label.id);
        chip.setAttribute("aria-pressed", String(attached.has(label.id)));
        await onChange();
      } finally {
        chip.disabled = false;
      }
    });
    box.appendChild(chip);
  });
}

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}
