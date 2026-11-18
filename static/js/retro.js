// 매니저 탭 '회고' — 매니저 개선건을 메인 매니저 대화·알림과 따로 본다 (app/services/retro_panel.py).
// 위: 대기 중인 피드백 — 입력창·터미널 /피드백·세션 회고의 개선 후보가 한 항목씩 쌓이고 상태(대기·반영 중·반영됨·안 함)가 보인다.
// 아래: 날짜별 하루 회고 — 전날 무엇을 회고했고 무엇을 개선했는지 요약, 누르면 그 자리에 상세(근거·바꾼 것·커밋·측정).
// 판정·반영은 매니저 하루 회고(retro.py)가 한다 — 화면은 읽고 쌓기만 한다. 상태 문구도 매니저가 정한 키를 옮긴다
import * as api from "./api.js";
import { t } from "./i18n.js";
import { formatAge } from "./sessions.js";
import { REFRESH_SVG } from "./icons.js";

// 피드백 상태 → 칩 색. 결정 대기(asked)는 사용자가 정한 넷 중 '대기'로 보이고 칩 옆 메모로 사유를 단다.
// 키를 문자열 그대로 둔다 — 사전 점검(tests/test_language.py)이 코드에서 키를 찾는다
const STATUS = {
  pending: ["", () => t("retro.status.pending")],
  asked: ["waiting", () => t("retro.status.pending")],
  doing: ["working", () => t("retro.status.doing")],
  done: ["confirm", () => t("retro.status.done")],
  skip: ["prereq", () => t("retro.status.skip")],
};
const SOURCE = {
  user: () => t("retro.source.user"),
  ui: () => t("retro.source.ui"),
  session: () => t("retro.source.session"),
  candidate: () => t("retro.source.session"),
};
const ACTION = {
  spawn: () => t("retro.action.spawn"),
  ask: () => t("retro.action.ask"),
  skip: () => t("retro.action.skip"),
};
const RETRO_STATUS = {
  failed: ["failed", () => t("retro.failed")],
  running: ["working", () => t("retro.running")],
};

const FEEDBACK_COMMAND = "/피드백";
let bound = false;
const opened = new Set();
const details = new Map();

export async function renderRetro() {
  bind();
  let data;
  try {
    data = await api.getRetro();
  } catch (error) {
    document.getElementById("mgr-retro-feedback").replaceChildren(
      el("li", "mgr-error", t("manager.partFailed", { error: error.message }))
    );
    return;
  }
  drawFeedback(data.feedback || []);
  drawDays(data.retros || []);
}

function bind() {
  if (bound) return;
  bound = true;
  // 명령 이름은 언어와 상관없이 같다 — 사전에는 자리만 두고 여기서 넣는다
  document.getElementById("retro-queue-hint").textContent = t("retro.queueHint", { command: FEEDBACK_COMMAND });
  const refresh = document.getElementById("mgr-retro-refresh");
  refresh.innerHTML = REFRESH_SVG;
  refresh.addEventListener("click", async () => {
    if (refresh.disabled) return;
    refresh.disabled = true;
    try {
      details.clear();
      await renderRetro();
    } finally {
      refresh.disabled = false;
    }
  });
  document.getElementById("retro-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const input = document.getElementById("retro-input");
    const button = document.getElementById("retro-send");
    const text = input.value.trim();
    if (!text || button.disabled) return;
    button.disabled = true;
    const noteLine = document.getElementById("retro-form-note");
    try {
      await api.sendRetroFeedback(text);
      input.value = "";
      noteLine.hidden = false;
      noteLine.className = "retro-form-note";
      noteLine.textContent = t("retro.saved");
      await renderRetro();
    } catch (error) {
      noteLine.hidden = false;
      noteLine.className = "retro-form-note mgr-error";
      noteLine.textContent = t("retro.saveFailed", { error: error.message });
    } finally {
      button.disabled = false;
    }
  });
}

// ── 대기 중인 피드백 ───────────────────────────────────────────────────────

function drawFeedback(items) {
  const active = items.filter((item) => !["done", "skip"].includes(item.status));
  document.getElementById("mgr-retro-count").textContent = String(active.length);
  const list = document.getElementById("mgr-retro-feedback");
  if (!items.length) return list.replaceChildren(el("li", "mgr-empty", t("retro.emptyQueue")));
  list.replaceChildren(...items.map(feedbackRow));
}

function feedbackRow(item) {
  const line = el("li", "mgr-row retro-feedback");
  const main = el("div", "mgr-main");
  main.append(el("span", "mgr-title retro-text", item.text));
  const meta = [SOURCE[item.source]?.() ?? item.source, formatAge(item.created_at)];
  if (item.note) meta.push(item.note);
  main.append(el("span", "mgr-sub", meta.filter(Boolean).join(" · ")));
  const side = el("div", "mgr-side");
  side.append(chip(STATUS, item.status, item.label));
  if (item.commits?.length) side.append(el("span", "mgr-sub", item.commits.join(" ")));
  line.title = item.text;
  line.append(main, side);
  return line;
}

// ── 날짜별 회고 ────────────────────────────────────────────────────────────

function drawDays(retros) {
  document.getElementById("mgr-retro-days-count").textContent = String(retros.length);
  const list = document.getElementById("mgr-retro-days");
  if (!retros.length) return list.replaceChildren(el("li", "mgr-empty", t("retro.emptyDays")));
  const rows = [];
  retros.forEach((retro) => {
    rows.push(dayRow(retro));
    if (opened.has(retro.id)) rows.push(detailRow(retro.id));
  });
  list.replaceChildren(...rows);
}

function dayRow(retro) {
  const line = el("li", "mgr-row mgr-click retro-day");
  line.tabIndex = 0;
  line.setAttribute?.("aria-expanded", String(opened.has(retro.id)));
  const main = el("div", "mgr-main");
  main.append(el("span", "mgr-title", retro.day), el("span", "mgr-sub retro-summary", retro.summary));
  const side = el("div", "mgr-side");
  const counts = retro.counts || {};
  const parts = ["spawn", "ask", "skip"]
    .filter((key) => counts[key])
    .map((key) => `${ACTION[key]()} ${counts[key]}`);
  side.append(
    RETRO_STATUS[retro.status] ? chip(RETRO_STATUS, retro.status) : el("span", "mgr-sub", parts.join(" · ")),
    el("span", "mgr-sub", formatAge(retro.created_at))
  );
  line.append(main, side);
  const toggle = () => {
    if (opened.has(retro.id)) opened.delete(retro.id);
    else opened.add(retro.id);
    const list = document.getElementById("mgr-retro-days");
    const next = line.nextSibling;
    if (next?.classList?.contains("retro-detail")) next.remove();
    if (opened.has(retro.id)) list.insertBefore(detailRow(retro.id), line.nextSibling);
    line.setAttribute?.("aria-expanded", String(opened.has(retro.id)));
  };
  line.addEventListener?.("click", toggle);
  line.addEventListener?.("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      toggle();
    }
  });
  return line;
}

function detailRow(id) {
  const box = el("li", "retro-detail");
  if (details.has(id)) {
    box.append(...detailParts(details.get(id)));
    return box;
  }
  box.append(el("p", "mgr-sub", t("common.loading")));
  api
    .getRetroDetail(id)
    .then((data) => {
      details.set(id, data);
      box.replaceChildren(...detailParts(data));
    })
    .catch((error) => box.replaceChildren(el("p", "mgr-error", t("manager.partFailed", { error: error.message }))));
  return box;
}

function detailParts(data) {
  const detail = data.detail || {};
  const parts = [];
  const items = detail.items || [];
  if (items.length) {
    const list = el("ol", "retro-items");
    items.forEach((item) => list.append(itemBlock(item)));
    parts.push(list);
  }
  const done = (detail.reconciled || []).filter((row) => row.status === "done");
  if (done.length) {
    parts.push(el("h4", "retro-h", t("retro.reflected")));
    const list = el("ul", "retro-plain");
    done.forEach((row) => list.append(el("li", "", [row.text, row.commits?.join(" ")].filter(Boolean).join(" — "))));
    parts.push(list);
  }
  const merges = detail.sources?.merges || [];
  if (merges.length) {
    parts.push(el("h4", "retro-h", t("retro.merges")));
    const list = el("ul", "retro-plain");
    merges.forEach((merge) => list.append(el("li", "", `${merge.hash} ${merge.subject}`)));
    parts.push(list);
  }
  if (!parts.length) parts.push(el("p", "mgr-sub", t("retro.noItems")));
  return parts;
}

function itemBlock(item) {
  const block = el("li", "retro-item");
  const head = el("div", "retro-item-head");
  head.append(el("strong", "", item.title), chip({ x: ["", () => ACTION[item.action]?.() ?? item.action] }, "x"));
  block.append(head);
  // 키를 문자열 그대로 둔다 — 사전 점검(tests/test_language.py)이 코드에서 키를 찾는다
  const fields = [
    [t("retro.evidence"), item.evidence],
    [t("retro.change"), item.change || item.reason],
    [t("retro.result"), item.result],
    [t("retro.measure"), item.measure],
  ];
  const table = el("dl", "retro-fields");
  fields.forEach(([label, value]) => {
    if (!value) return;
    table.append(el("dt", "", label), el("dd", "", value));
  });
  const commits = (item.feedback || []).flatMap((row) => row.commits || []);
  if (commits.length) table.append(el("dt", "", t("retro.commits")), el("dd", "", commits.join(" ")));
  (item.feedback || []).forEach((row) => {
    const dd = el("dd", "retro-fb");
    dd.append(chip(STATUS, row.status, row.label), document.createTextNode(` ${row.text}`));
    table.append(el("dt", "", t("retro.feedbackItem")), dd);
  });
  block.append(table);
  return block;
}

function chip(table, key, fallback) {
  const [tone, label] = table[key] ?? ["", () => fallback || key];
  return el("span", `mgr-chip${tone ? ` ${tone}` : ""}`, label());
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}
