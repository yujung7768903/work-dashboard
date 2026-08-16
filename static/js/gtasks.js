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
  const toggle = document.getElementById("gtasks-toggle");
  // 링크가 없으면 아직 카테고리를 안 맞춘 것이다 — 목록 대신 안내를 남긴다
  const linked = panel.categories.filter((row) => row.linked);
  // 맞추기 전에는 켤 것이 없다. 스위치를 보여주면 누를 수 없는 것을 누르게 된다
  document.getElementById("gtasks-switch").hidden = !panel.connected || !linked.length;
  toggle.checked = enabled;
  paintWarning(panel.reason);
  const card = document.getElementById("gtasks-card");
  card.classList.toggle("off", !enabled);
  card.innerHTML = "";
  if (!panel.connected) {
    card.append(note(t("gtasks.intro")), connectButton(panel));
    return;
  }
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
  // 자율 수행 줄과 같은 모양 — 주기와 마지막 수행을 한 줄에 둔다.
  // 주기는 상수로 적지 않는다. 아무것도 등록 안 한 사람에게는 거짓말이 된다
  const when = document.createElement("span");
  when.textContent = [
    panel.every_sec
      ? t("gtasks.every", { minutes: Math.round(panel.every_sec / 60) })
      : t("gtasks.noSchedule"),
    panel.state.last_sync_at
      ? t("gtasks.lastSync", { when: stamp(panel.state.last_sync_at) })
      : t("gtasks.neverSynced"),
  ].join(" | ");
  const now = document.createElement("button");
  now.textContent = t("gtasks.syncNow");
  now.disabled = !panel.state.enabled;
  now.addEventListener("click", () => busy(now, async () => paint((await api.syncGtasks()).panel)));
  // 맞추기를 마치면 이 팝업으로 돌아올 길이 없었다 — 폰에만 있는 목록을 영영 못 가져온다
  const more = document.createElement("button");
  more.textContent = t("gtasks.addCategories");
  more.addEventListener("click", () => busy(more, openPlan));
  foot.append(when, more, disconnectButton(), now);
  return foot;
}

function disconnectButton() {
  const button = document.createElement("button");
  button.textContent = t("gtasks.disconnect");
  button.addEventListener("click", () => {
    // 양쪽 데이터는 그대로라 되돌리기 쉽지만, 눌러서 끊길 줄 몰랐던 상황은 만들지 않는다
    if (!globalThis.confirm?.(t("gtasks.confirmDisconnect"))) return;
    return busy(button, async () => paint(await api.disconnectGtasks()));
  });
  return button;
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
  const boxes = fillPlan(plan.items);
  const chosen = await askPlan();
  if (!chosen) return;
  // 잠긴 것(이미 맺어 둔 것)은 빼고 새로 고른 것만 보낸다
  const picked = boxes.filter((box) => box.checked && !box.disabled).map((box) => box.value);
  if (!picked.length) return;
  paint((await api.setupGtasks(picked)).panel);
}

// 세 무리로 나눈다. '양쪽에 있음' 은 두 뭉치가 합쳐진다는 뜻이라 건수를 같이 보여준다 —
// 대시보드 '공부'(2개)와 폰의 '공부'(61개)가 별개인 채로 켜지는 사고를 막는 유일한 장치다
// 라벨을 함수로 두는 이유: 사전 검사기가 t("키") 리터럴만 훑어서, 키를 값으로 담아 두면
// '안 쓰는 키'로 잡힌다. 게다가 사전은 첫 렌더 뒤에 채워지므로 지연 호출이 맞다
const PLAN_GROUPS = [
  { label: () => t("gtasks.planBoth"), match: (item) => item.local !== null && item.remote !== null },
  { label: () => t("gtasks.planOnlyLocal"), match: (item) => item.remote === null },
  { label: () => t("gtasks.planOnlyRemote"), match: (item) => item.local === null },
];

function fillPlan(items) {
  const list = document.getElementById("gtasks-plan-list");
  list.innerHTML = "";
  const boxes = [];
  PLAN_GROUPS.forEach((section) => {
    const group = items.filter(section.match);
    if (!group.length) return;
    const head = document.createElement("h4");
    head.textContent = section.label();
    list.appendChild(head);
    group.forEach((item) => {
      const line = document.createElement("label");
      line.className = "gt-pick";
      const box = document.createElement("input");
      box.type = "checkbox";
      box.value = item.name;
      // 이미 맺어 둔 것은 켠 채로 잠근다 — 여기서 다시 보내면 카드에서 꺼 둔 것이 되살아난다
      box.checked = item.linked;
      box.disabled = item.linked;
      boxes.push(box);
      line.append(box, text(item.name), count(item));
      list.appendChild(line);
    });
  });
  return boxes;
}

function count(item) {
  const node = document.createElement("span");
  node.className = "gt-count";
  node.textContent =
    item.local !== null && item.remote !== null
      ? t("gtasks.planPair", { local: item.local, remote: item.remote })
      : t("gtasks.planOne", { n: item.local === null ? item.remote : item.local });
  return node;
}

function askPlan() {
  const dialog = document.getElementById("gtasks-plan");
  return new Promise((resolve) => {
    let go = false;
    document.getElementById("gtasks-plan-go").onclick = () => {
      go = true;
      dialog.close();
    };
    document.getElementById("gtasks-plan-cancel").onclick = () => dialog.close();
    dialog.addEventListener("close", () => resolve(go), { once: true });
    dialog.showModal();
  });
}

// ── 진행 표시 ─────────────────────────────────────────────────────────────

async function onToggle() {
  // 스위치는 카테고리를 맞춘 뒤에만 보인다. 그러니 여기서 다시 확인할 것이 없다 —
  // 합집합 팝업은 '카테고리 맞추기' 한 번뿐이고, 그 뒤로는 껐다 켜는 것이 전부다
  const toggle = document.getElementById("gtasks-toggle");
  await guard(toggle, async () => paint(await api.setGtasks(toggle.checked)));
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
  // 스피너를 카드에 붙이면 버튼 옆에 따로 떠서 무엇이 도는지 안 보인다. 버튼 안에 넣는다
  const label = button.textContent;
  button.disabled = true;
  button.classList.add("busy");
  button.textContent = "";
  button.appendChild(span("gt-spin"));
  button.appendChild(text(label));
  try {
    await action();
  } catch (error) {
    // 실패는 api.js 가 이미 알렸다. 여기서는 다시 누를 수 있게 되돌리기만 한다
  } finally {
    // 반드시 되돌린다. 취소하고 돌아온 자리에서 버튼이 죽어 있으면 다시 시도할 길이 없다
    button.disabled = false;
    button.classList.remove("busy");
    button.textContent = label;
  }
}

function text(value) {
  const node = document.createElement("span");
  node.textContent = value;
  return node;
}
