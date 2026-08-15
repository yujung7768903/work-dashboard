// 설정 탭의 구글 태스크 연동. 켜기 전에 카테고리 합집합을 보여주고 확인을 받는다.
// 바로 동기화하면 사용자가 무엇이 폰으로 넘어가는지 모르는 채 수십 건이 올라간다
import * as api from "./api.js";
import { fromKorean, t } from "./i18n.js";

let bound = false;

export async function renderGtasks() {
  bind();
  paint(await api.getGtasks());
}

function bind() {
  // 설정 탭을 다시 그릴 때마다 붙으면 한 번 눌러 여러 번 나간다
  if (bound) return;
  bound = true;
  document.getElementById("gtasks-toggle").addEventListener("change", onToggle);
}

// ── 그리기 ────────────────────────────────────────────────────────────────

function paint(panel) {
  const enabled = Boolean(panel.state.enabled);
  const head = document.getElementById("gtasks-switch");
  const toggle = document.getElementById("gtasks-toggle");
  head.hidden = !panel.connected;
  toggle.checked = enabled;
  paintWarning(panel.reason);
  const card = document.getElementById("gtasks-card");
  card.classList.toggle("off", !enabled);
  card.innerHTML = "";
  if (!panel.connected) {
    card.append(note(t("gtasks.intro")), connectButton(panel));
    return;
  }
  // 링크가 없으면 아직 카테고리를 안 맞춘 것이다 — 목록 대신 안내를 남긴다
  const linked = panel.categories.filter((row) => row.linked);
  if (!linked.length) {
    card.append(note(t("gtasks.intro")), setupButton());
    return;
  }
  linked.forEach((row) => card.appendChild(categoryRow(row, enabled)));
  card.appendChild(footer(panel));
}

async function paintWarning(reason) {
  const warn = document.getElementById("gtasks-warn");
  warn.hidden = !reason;
  // 서버는 한국어로 내려준다. 사전에 같은 문장이 있으면 옮기고 없으면 원문 그대로
  document.getElementById("gtasks-reason").textContent = reason
    ? await fromKorean(reason)
    : "";
}

function note(text) {
  const line = document.createElement("p");
  line.className = "gt-empty";
  line.textContent = text;
  return line;
}

function categoryRow(row, enabled) {
  const line = document.createElement("div");
  line.className = "gt-row";
  const name = document.createElement("span");
  name.className = "name";
  name.textContent = row.name;
  const label = document.createElement("label");
  label.className = "switch";
  const box = document.createElement("input");
  box.type = "checkbox";
  box.checked = row.enabled;
  // 연동을 끄면 값은 그대로 두고 조작만 막는다 — 무엇이 켜져 있었는지 계속 보인다
  box.disabled = !enabled;
  box.addEventListener("change", () => guard(box, () => api.setGtasksCategory(row.id, box.checked)));
  label.append(box, span("track"), span("state"));
  line.append(name, label);
  return line;
}

function span(className) {
  const node = document.createElement("span");
  node.className = className;
  return node;
}

function footer(panel) {
  const foot = document.createElement("div");
  foot.className = "gt-foot";
  const when = document.createElement("span");
  when.textContent = panel.state.last_sync_at
    ? t("gtasks.lastSync", { when: stamp(panel.state.last_sync_at) })
    : t("gtasks.neverSynced");
  const now = document.createElement("button");
  now.textContent = t("gtasks.syncNow");
  now.disabled = !panel.state.enabled;
  now.addEventListener("click", () => busy(now, async () => paint((await api.syncGtasks()).panel)));
  foot.append(when, now);
  return foot;
}

function stamp(text) {
  const moment = new Date(text);
  return Number.isNaN(moment.getTime()) ? text : moment.toLocaleString();
}

// ── 버튼 ──────────────────────────────────────────────────────────────────

function connectButton(panel) {
  const button = document.createElement("button");
  button.textContent = t("gtasks.connect");
  button.addEventListener("click", () => busy(button, () => connect(panel)));
  return button;
}

async function connect(panel) {
  // 자격증명은 구글 콘솔에서 직접 받아야 한다. 이미 받아 둔 게 있으면 다시 묻지 않는다
  const filled = panel.has_client ? {} : await askCredentials(panel.client_id);
  if (!filled) return;
  // 동의 창은 서버가 연다. 승인까지 몇 분이 걸릴 수 있어 그동안 계속 돌려 둔다
  paint(await api.connectGtasks(filled));
}

function askCredentials(knownId) {
  const dialog = document.getElementById("gtasks-auth");
  const guide = document.getElementById("gtasks-auth-guide");
  const form = document.getElementById("gtasks-auth-form");
  const id = document.getElementById("gtasks-client-id");
  const secret = document.getElementById("gtasks-client-secret");
  guide.hidden = false;
  form.hidden = true;
  id.value = knownId || "";
  secret.value = "";
  return new Promise((resolve) => {
    let filled = null;
    // addEventListener 가 아니라 대입이라야 다시 열 때 핸들러가 겹쳐 쌓이지 않는다
    document.getElementById("gtasks-auth-next").onclick = () => step(guide, form);
    document.getElementById("gtasks-auth-back").onclick = () => step(form, guide);
    document.getElementById("gtasks-auth-cancel").onclick = () => dialog.close();
    form.onsubmit = (event) => {
      event.preventDefault();
      filled = { client_id: id.value.trim(), client_secret: secret.value.trim() };
      dialog.close();
    };
    dialog.addEventListener("close", () => resolve(filled), { once: true });
    dialog.showModal();
  });
}

function step(from, to) {
  from.hidden = true;
  to.hidden = false;
}

function setupButton() {
  const button = document.createElement("button");
  button.textContent = t("gtasks.setup");
  button.addEventListener("click", () => busy(button, openPlan));
  return button;
}

async function openPlan() {
  const plan = await api.planGtasks();
  fill("gtasks-plan-local", plan.local);
  fill("gtasks-plan-remote", plan.remote);
  fill("gtasks-plan-union", plan.union);
  const dialog = document.getElementById("gtasks-plan");
  const decision = await ask(dialog);
  if (decision !== "go") return;
  paint((await api.setupGtasks()).panel);
}

function fill(id, names) {
  document.getElementById(id).textContent = names.length ? names.join(", ") : t("gtasks.none");
}

function ask(dialog) {
  return new Promise((resolve) => {
    dialog.addEventListener("close", () => resolve(dialog.returnValue), { once: true });
    dialog.showModal();
  });
}

// ── 진행 표시 ─────────────────────────────────────────────────────────────

async function onToggle() {
  const toggle = document.getElementById("gtasks-toggle");
  // 켜는 길은 카테고리 확인을 거친다. 끄는 것은 되돌리기 쉬워 바로 반영한다
  if (!toggle.checked) {
    await guard(toggle, async () => paint(await api.setGtasks(false)));
    return;
  }
  toggle.checked = false; // 확인을 마쳐야 켜진다 — 미리 켜 두면 취소했을 때 어긋난다
  await openPlan();
}

async function guard(box, action) {
  try {
    await action();
  } catch (error) {
    // 서버가 안 받았으면 스위치도 원래대로 — 켠 줄 알고 자리를 뜨면 안 된다
    box.checked = !box.checked;
  }
}

async function busy(button, action) {
  const card = document.getElementById("gtasks-card");
  const spinner = span("gt-spin");
  button.disabled = true;
  card.appendChild(spinner);
  try {
    await action();
  } catch (error) {
    // 실패는 api.js 가 이미 알렸다. 여기서는 다시 누를 수 있게 되돌리기만 한다
  } finally {
    // 반드시 되돌린다. 취소하고 돌아온 자리에서 버튼이 죽어 있으면 다시 시도할 길이 없다
    button.disabled = false;
    spinner.remove();
  }
}
