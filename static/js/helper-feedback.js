// 보조 세션에 피드백 보내기 — 매니저 탭 보조 세션 상세(지금 하는 일 아래)의 상자.
// 할일 상세의 직접 할 일·확인 대기 상자(task-report.js)와 같은 틀이다: 입력칸 + 보내기, 보낸 글마다 전달 상태 칩.
// 다른 점은 할일 상태를 바꾸지 않는다는 것 — 돌고 있는 보조에게 말을 거는 것이라 '완료' 같은 기본 동작이 없다.
// 보낸 뒤에는 서버가 뒤에서 매니저 helper-ui 를 돌리고 이 상자는 세션 상태를 폴링한다. 세션 생사(session.alive)와
// 전달 상태(answer_state)는 매니저가 계산한 값을 그대로 옮긴다 — 화면이 판정하지 않는다.
// 세션이 이미 끝났으면 입력칸 대신 그 사실을 보이고 보내지 않는다
import * as api from "./api.js";
import { fromKorean, t } from "./i18n.js";

// 보낸 글의 전달 상태. 칩 색·문구는 할일 상세 피드백(task-report.js)과 같다.
// 키를 문자열 그대로 둔다 — 사전 점검(tests/test_language.py)이 코드에서 키를 찾는다
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
const NOT_SENT = ["failed", () => t("helper.state.notSent")];
// 칩만으로 다음에 무엇이 일어나는지 모르는 상태에만 붙이는 설명 — 가장 최근 글에만
const NOTES = {
  sending: () => t("report.sendingNote"),
  relayed: () => t("helper.relayedNote"),
  parked: () => t("helper.parkedNote"),
};
// 매니저 helper-ui 가 '세션이 이미 끝나 남기지 않았다'로 끝낸 exit (answer_send.NO_SESSION)
const ENDED_EXIT = 3;
const SHOWN = 3;
const POLL_MS = 2000;
// helper-ui 는 되살리지 않아 길어야 수십 초다. 다른 상자와 같은 상한 — 그 뒤 상태는 다시 열면 보인다
const POLL_LIMIT = 120;

function running(data) {
  return Boolean(data.job?.running);
}

function busy(data) {
  return running(data) || data.items?.[0]?.answer_state === "sending";
}

/** 매니저 팝업용 — 열 때 그 세션의 생사·보낸 피드백을 받아 그린다. alive 가 false 가 되면(창을 닫으면) 폴링을 멈춘다 */
export function feedbackLoader(sessionId, { alive = () => true } = {}) {
  const box = element("div", "dec-loader");
  box.append(element("p", "mgr-pop-none", t("common.loading")));
  api
    .getHelperFeedback(sessionId)
    .then((data) => box.replaceChildren(feedbackCard(sessionId, data, { alive })))
    .catch((error) => box.replaceChildren(element("p", "mgr-pop-none", t("report.loadFailed", { error: error.message }))));
  return box;
}

export function feedbackCard(sessionId, data, { alive = () => true } = {}) {
  const card = element("div", "dec-card report-card bare helper-feedback");
  // sent: 이 창에서 마지막으로 보낸 글 — 매니저가 행을 남기기 전(보내는 중)과 끝난 세션이라 남기지 않았을 때 보인다
  const state = { sessionId, data, feedback: "", sent: null, sentAfter: 0, polls: 0, timer: null };
  const draw = () => card.replaceChildren(...cardParts(state, { draw, alive }));
  draw();
  if (busy(data)) poll(state, draw, alive);
  return card;
}

function cardParts(state, { draw, alive }) {
  const { data } = state;
  const parts = [];
  if (data.session?.alive) parts.push(answerBox(state, { draw, alive }));
  else parts.push(element("p", "dec-note", t("helper.ended")));
  parts.push(...sentParts(state));
  return parts;
}

function answerBox(state, { draw, alive }) {
  const box = element("div", "dec-answer");
  const locked = running(state.data);
  const input = element("textarea");
  input.value = state.feedback;
  input.disabled = locked;
  input.placeholder = t("helper.placeholder");
  const hint = element("p", "hint", t("helper.hint"));
  const send = element("button", "dec-send primary", t("helper.send"));
  send.type = "button";
  const status = element("p", "dec-status", "");
  const refresh = () => {
    send.disabled = locked || !state.feedback.trim();
  };
  input.addEventListener("input", () => {
    state.feedback = input.value;
    refresh();
  });
  send.addEventListener("click", () => submit(state, { draw, alive, send, status }));
  refresh();
  const actions = element("div", "compose-actions report-actions");
  actions.append(send);
  box.append(input, hint, actions, status);
  return box;
}

// 보낸 글과 그 뒤 일어난 일. 보내는 중인 글이 맨 위, 그 아래 매니저에 남은 최근 글
function sentParts(state) {
  const { data } = state;
  const parts = [];
  const items = (data.items ?? []).slice(0, SHOWN);
  // 보낸 뒤 매니저가 새 행을 남겼으면(보내기 전 가장 최근 id 보다 큰 것) 그 행이 상태를 말한다
  const pending = state.sent && !((items[0]?.id ?? 0) > state.sentAfter);
  if (pending && running(data)) parts.push(sentLine(state.sent, POSTING));
  if (pending && !running(data) && data.job?.exit === ENDED_EXIT) parts.push(sentLine(state.sent, NOT_SENT));
  items.forEach((item, index) => {
    parts.push(sentLine(item.answer, STATES[item.answer_state] ?? STATES.saved));
    const note = NOTES[item.answer_state];
    if (index === 0 && note && !running(data)) parts.push(element("p", "dec-note", note()));
  });
  if (data.job?.error && !running(data)) parts.push(element("p", "dec-note danger", fromKorean(data.job.error)));
  return parts;
}

function sentLine(text, [tone, label]) {
  const line = element("p", "dec-sent");
  line.append(document.createTextNode(t("helper.sent", { text })));
  line.append(element("span", `mgr-chip ${tone}`.trim(), label()));
  return line;
}

async function submit(state, { draw, alive, send, status }) {
  const feedback = state.feedback.trim();
  if (!feedback) return;
  send.disabled = true;
  status.className = "dec-status";
  status.textContent = t("report.posting");
  try {
    const started = await api.sendHelperFeedback(state.sessionId, feedback);
    // 매니저가 남기는 글과 같게 공백을 정리해 둔다(helper-ui 가 " ".join(split()) 으로 남긴다)
    state.sent = feedback.split(/\s+/).join(" ");
    state.sentAfter = state.data.items?.[0]?.id ?? 0;
    state.data = { ...state.data, job: started.job };
    state.feedback = "";
    state.polls = 0;
    draw();
    poll(state, draw, alive);
  } catch (error) {
    send.disabled = false;
    status.className = "dec-status danger";
    status.textContent = error.message;
  }
}

// 글이 세션에 닿을 때까지(뒤의 helper-ui 가 끝나고 매니저가 상태를 찍을 때까지) 그 세션 한 건만 다시 읽는다
function poll(state, draw, alive) {
  clearTimeout(state.timer);
  const tick = async () => {
    if (!alive() || state.polls >= POLL_LIMIT) return;
    state.polls += 1;
    try {
      state.data = await api.getHelperFeedback(state.sessionId);
      draw();
    } catch {
      // 다음 틱에 다시 읽는다
    }
    if (busy(state.data)) state.timer = setTimeout(tick, POLL_MS);
  };
  state.timer = setTimeout(tick, POLL_MS);
}

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}
