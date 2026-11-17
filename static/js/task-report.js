// 직접 할 일·확인 대기에 응답하기 — 할일 상세 창(개요 제목 아래, 결정 칸 다음)과 매니저 탭 확인 대기 팝업이 같은 상자를 쓴다.
// 결정 카드(decision-answer.js)와 같은 틀이다. 다른 점은 고를 선택지가 없고 기본 동작이 하나라는 것:
//   직접 할 일 — 완료(기본) · 진행 상황 보내기(글이 있을 때)
//   확인 대기 — 확인(기본) · 고칠 것 보내기(글이 있을 때)
// 기본 버튼은 강조색으로 따로 둔다. 확인 대기는 '확인했다'가 거의 모든 경우라 한 번에 끝나야 하고, 글만 보내는 버튼과
// 이름이 같으면 무엇이 닫히는지 헷갈린다. 기본 버튼과 함께 쓴 글은 완료·확인 메모(사용자 말)로 같이 간다.
// 보낸 뒤에는 서버가 뒤에서 매니저 task-ui 를 돌리고 이 상자는 전달 상태를 폴링한다. 상태(answer_state)는 매니저가
// 계산한 값을 그대로 옮긴다 — 화면이 판정하지 않는다
import * as api from "./api.js";
import { folded, labelled } from "./decision-answer.js";
import { fromKorean, t } from "./i18n.js";

// 칸 머리 칩 — 무엇을 기다리는 일인가. 키를 문자열 그대로 둔다 — 사전 점검(tests/test_language.py)이 코드에서 키를 찾는다
const KIND_CHIPS = {
  action: ["waiting", () => t("report.kind.action")],
  confirm: ["confirm", () => t("report.kind.confirm")],
};
const CLOSED_CHIPS = {
  action: ["", () => t("report.kind.doneAction")],
  confirm: ["", () => t("report.kind.doneConfirm")],
};
// 보낸 글의 전달 상태. 칩 색은 결정 카드와 같은 뜻
const STATES = {
  saved: ["", () => t("report.state.saved")],
  sending: ["working", () => t("report.state.sending")],
  relayed: ["working", () => t("report.state.relayed")],
  delivered: ["confirm", () => t("report.state.delivered")],
  failed: ["failed", () => t("report.state.failed")],
  no_session: ["", () => t("report.state.noSession")],
  parked: ["", () => t("report.state.parked")],
};
const POSTING = ["working", () => t("report.state.posting")];
// 보낸 글의 종류(answer_via) → 앞말
const SENT = {
  "ui:progress": (text) => t("report.sent.progress", { text }),
  "ui:done": (text) => t("report.sent.done", { text }),
  "ui:confirm": (text) => t("report.sent.confirm", { text }),
  "ui:fix": (text) => t("report.sent.fix", { text }),
};
// 칩만으로 다음에 무엇이 일어나는지 모르는 상태에만 붙이는 설명
const NOTES = {
  sending: () => t("report.sendingNote"),
  relayed: () => t("decision.relayedNote"),
  parked: () => t("report.parkedNote"),
};
const FIX_VIA = "ui:fix";
const POLL_MS = 2000;
// 매니저 task-ui 는 되살리지 않아 길어야 수십 초다. 결정 카드와 같은 상한으로 둔다 — 그 뒤 상태는 다시 열면 보인다
const POLL_LIMIT = 120;

function posting(item) {
  return Boolean(item.job?.running) && item.answer_state !== "sending";
}

function busy(item) {
  return Boolean(item.job?.running) || item.answer_state === "sending";
}

function closed(item) {
  return item.status === "done";
}

/** 칸 머리 칩 — 열린 것은 무엇을 기다리는지, 닫힌 것은 어떻게 닫혔는지 */
export function reportChip(item) {
  const kind = item.report_kind === "confirm" ? "confirm" : "action";
  const [tone, label] = (closed(item) ? CLOSED_CHIPS : KIND_CHIPS)[kind];
  return element("span", `mgr-chip ${tone}`.trim(), label());
}

/**
 * 직접 할 일·확인 대기 하나. head 면 '#id 제목 + 칩'·내용(배경·끝낸 내용·다음 단계)까지, 아니면(매니저 팝업 — 팝업 머리와
 * 섹션이 이미 보인다) 응답 부분만. alive 가 false 가 되면(창을 닫으면) 폴링을 멈춘다.
 * renderText 는 글 안의 주소·경로를 누를 수 있게 바꾸는 함수(sessions.js notePart + linkify)
 */
export function reportCard(item, { head = true, alive = () => true, renderText = null } = {}) {
  const card = element("div", `dec-card report-card${closed(item) ? " answered" : ""}${head ? "" : " bare"}`);
  const state = { item, feedback: "", polls: 0, timer: null };
  const draw = () => {
    card.className = `dec-card report-card${closed(state.item) ? " answered" : ""}${head ? "" : " bare"}`;
    card.replaceChildren(...cardParts(state, { head, renderText, draw, alive }));
  };
  draw();
  if (busy(item)) poll(state, draw, alive);
  return card;
}

/** 매니저 팝업용 — 줄에는 전달 상태가 없으니 열 때 한 건을 받아 그린다 */
export function reportLoader(id, options) {
  const box = element("div", "dec-loader");
  box.append(element("p", "mgr-pop-none", t("common.loading")));
  api
    .getTaskReport(id)
    .then((item) => box.replaceChildren(reportCard(item, { ...options, head: false })))
    .catch((error) => box.replaceChildren(element("p", "mgr-pop-none", t("report.loadFailed", { error: error.message }))));
  return box;
}

function cardParts(state, { head, renderText, draw, alive }) {
  const { item } = state;
  const parts = [];
  if (head) {
    const line = element("p", "dec-head");
    line.append(element("span", "dec-title", `#${item.id} ${item.title}`), reportChip(item));
    parts.push(line, ...contextParts(item, renderText));
  }
  if (!closed(item)) parts.push(answerBox(state, { draw, alive }));
  parts.push(...sentParts(item));
  return parts;
}

// 내용 — 기록된 글만 옮긴다. 확인 대기는 세션이 끝냈다고 남긴 글(reason)이 먼저다
function contextParts(item, renderText) {
  const parts = [];
  if (item.report_kind === "confirm" && item.reason) parts.push(labelled(t("report.finished"), item.reason, renderText));
  if (item.detail) parts.push(folded(item.detail, renderText));
  if (item.next_step) parts.push(labelled(t("decision.nextStep"), item.next_step, renderText));
  if (item.open_target) parts.push(labelled(t("decision.output"), item.open_target, renderText));
  return parts;
}

function answerBox(state, { draw, alive }) {
  const { item } = state;
  const confirm = item.report_kind === "confirm";
  const box = element("div", "dec-answer");
  const locked = busy(item);
  const input = element("textarea");
  input.value = state.feedback;
  input.disabled = locked;
  input.placeholder = confirm ? t("report.placeholder.confirm") : t("report.placeholder.action");
  const hint = element("p", "hint", hintText(item, confirm));
  // 글만 보내는 버튼(보조)과 닫는 버튼(기본). 기본이 오른쪽 끝 — 결정 카드의 보내기 자리와 같다
  const note = element("button", "dec-send", confirm ? t("report.sendFix") : t("report.sendProgress"));
  note.type = "button";
  const main = element("button", "dec-send primary", confirm ? t("report.confirm") : t("report.done"));
  main.type = "button";
  main.disabled = locked;
  const status = element("p", "dec-status", "");
  const refresh = () => {
    note.disabled = locked || !state.feedback.trim();
  };
  input.addEventListener("input", () => {
    state.feedback = input.value;
    refresh();
  });
  const buttons = { note, main, status };
  note.addEventListener("click", () => submit(state, false, { draw, alive, ...buttons }));
  main.addEventListener("click", () => submit(state, true, { draw, alive, ...buttons }));
  refresh();
  const actions = element("div", "compose-actions report-actions");
  actions.append(note, main);
  box.append(input, hint, actions, status);
  return box;
}

// 누르면 무엇이 되는지. 연결 세션이 없는 직접 할 일은 매니저에만 남는다는 것을 미리 말한다 —
// 보낸 뒤에야 '원 세션 없음'을 보지 않게
function hintText(item, confirm) {
  if (confirm) return t("report.hint.confirm");
  return item.session ? t("report.hint.action") : t("report.hint.noSession");
}

// 이미 보낸 글과 그 뒤 일어난 일
function sentParts(item) {
  const parts = [];
  if (item.answer || posting(item)) {
    const line = element("p", "dec-sent");
    const sent = SENT[item.answer_via];
    if (item.answer && sent) line.append(document.createTextNode(sent(item.answer)));
    const [tone, label] = posting(item) ? POSTING : STATES[item.answer_state] ?? STATES.saved;
    line.append(element("span", `mgr-chip ${tone}`.trim(), label()));
    parts.push(line);
  }
  const note = NOTES[item.answer_state];
  if (note && !posting(item)) parts.push(element("p", "dec-note", note()));
  // 고칠 것을 이어 갈 세션이 없으면 매니저가 보조를 띄울지 묻는다(매니저 task-ui)
  if (item.answer_via === FIX_VIA && ["no_session", "parked"].includes(item.answer_state) && !posting(item)) {
    parts.push(element("p", "dec-note", t("report.fixNoSessionNote")));
  }
  if (item.job?.error && !item.job.running) parts.push(element("p", "dec-note danger", fromKorean(item.job.error)));
  return parts;
}

async function submit(state, done, { draw, alive, note, main, status }) {
  const feedback = state.feedback.trim();
  if (!done && !feedback) return;
  note.disabled = true;
  main.disabled = true;
  status.className = "dec-status";
  status.textContent = t("report.posting");
  try {
    state.item = await api.sendTaskReport(state.item.id, done, feedback || null);
    state.feedback = "";
    state.polls = 0;
    draw();
    poll(state, draw, alive);
  } catch (error) {
    main.disabled = false;
    note.disabled = !feedback;
    status.className = "dec-status danger";
    status.textContent = error.message;
  }
}

// 글이 원 세션에 닿을 때까지(뒤의 task-ui 가 끝나고 매니저가 상태를 찍을 때까지) 한 건만 다시 읽는다
function poll(state, draw, alive) {
  clearTimeout(state.timer);
  const tick = async () => {
    if (!alive() || state.polls >= POLL_LIMIT) return;
    state.polls += 1;
    try {
      state.item = await api.getTaskReport(state.item.id);
      draw();
    } catch {
      // 다음 틱에 다시 읽는다
    }
    if (busy(state.item)) state.timer = setTimeout(tick, POLL_MS);
  };
  state.timer = setTimeout(tick, POLL_MS);
}

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}
