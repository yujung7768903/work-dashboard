// 결정에 답하기 — 할일 상세 창(개요 제목 아래)과 매니저 탭 결정 팝업이 같은 상자를 쓴다.
// 선택지는 세션 탭 선택창과 같은 모양(.choice: 라벨 + 설명)이고 같은 규칙을 따른다 — 눌러서 고르고, 보내기는
// 버튼 한 번. 누르는 즉시 보내지 않는 것은 이 답이 원 세션의 다음 행동을 정하기 때문이다: 잘못 누른 답을
// 세션이 먼저 실행하면 다시 답해도 늦다. 추천은 표시만 하고 미리 골라 두지 않는다 — 사람이 고른 답이어야 한다.
// 보낸 뒤에는 서버가 뒤에서 매니저 answer-ui 를 돌리고(최대 90초) 이 상자는 답 상태를 폴링해 사람 말로 보인다.
// 답 상태(answer_state)는 매니저가 계산한 값을 그대로 옮긴다 — 화면이 판정하지 않는다
import * as api from "./api.js";
import { fromKorean, t } from "./i18n.js";

// 답 상태 → (칩 색, 문구). 칩 색은 매니저 탭 줄의 칩(.mgr-chip)과 같은 뜻으로 쓴다:
// 사람을 기다리면 waiting, 넘어가는 중이면 working, 끝났으면 confirm, 원 세션이 이어 가지 못하면 failed.
// 키를 문자열 그대로 둔다 — 사전 점검(tests/test_language.py)이 코드에서 키를 찾는다
const STATES = {
  unanswered: ["waiting", () => t("decision.state.unanswered")],
  saved: ["", () => t("decision.state.saved")],
  sending: ["working", () => t("decision.state.sending")],
  relayed: ["working", () => t("decision.state.relayed")],
  delivered: ["confirm", () => t("decision.state.delivered")],
  failed: ["failed", () => t("decision.state.failed")],
  no_session: ["failed", () => t("decision.state.noSession")],
};
// 보낸 직후 매니저가 상태를 찍기 전까지. 서버 뒤의 answer-ui 가 돌고 있다는 것만 안다
const POSTING = ["working", () => t("decision.state.posting")];
// 상태 아래에 붙이는 설명. 칩만으로 다음에 무엇이 일어나는지 모르는 상태에만
const NOTES = {
  sending: () => t("decision.sendingNote"),
  relayed: () => t("decision.relayedNote"),
};
const POLL_MS = 2000;
// 매니저 answer-ui 상한(90초)의 두 배가 넘으면 멈춘다 — 그 뒤 상태는 팝업을 다시 열면 보인다
const POLL_LIMIT = 120;
const CONTEXT_FOLD_CHARS = 280;
const CONTEXT_FOLD_LINES = 5;

/** 답 상태 칩. 할일 상세 카드 머리·매니저 팝업이 같은 칩을 쓴다 */
export function stateChip(item) {
  const [tone, label] = posting(item) ? POSTING : STATES[item.answer_state] ?? STATES.unanswered;
  return element("span", `mgr-chip ${tone}`.trim(), label());
}

function posting(item) {
  return Boolean(item.job?.running) && item.answer_state !== "sending";
}

function busy(item) {
  return Boolean(item.job?.running) || item.answer_state === "sending";
}

/**
 * 결정 하나. head 면 '#id 제목 + 상태 칩'·결정 내용(배경·다음 단계)까지, 아니면(매니저 팝업 — 팝업 머리와
 * 섹션이 이미 보인다) 답하기 부분만. alive 가 false 가 되면(팝업을 닫으면) 폴링을 멈춘다.
 * textPart 는 글 안의 주소·경로를 누를 수 있게 바꾸는 함수(sessions.js notePart + linkify)다 —
 * 여기서 sessions.js 를 들이면 서로를 들이는 고리가 생긴다
 */
export function decisionCard(item, { head = true, alive = () => true, renderText = null } = {}) {
  const card = element("div", `dec-card${item.status === "open" ? "" : " answered"}${head ? "" : " bare"}`);
  const state = { item, choice: null, feedback: "", polls: 0, timer: null };
  const draw = () => card.replaceChildren(...cardParts(state, { head, renderText, draw, alive }));
  draw();
  if (busy(item)) poll(state, draw, alive);
  return card;
}

/** 매니저 팝업용 — 줄에는 선택지가 없으니 열 때 한 건을 받아 그린다 */
export function decisionLoader(id, options) {
  const box = element("div", "dec-loader");
  box.append(element("p", "mgr-pop-none", t("common.loading")));
  api
    .getDecision(id)
    .then((item) => box.replaceChildren(decisionCard(item, { ...options, head: false })))
    .catch((error) => box.replaceChildren(element("p", "mgr-pop-none", t("decision.loadFailed", { error: error.message }))));
  return box;
}

function cardParts(state, { head, renderText, draw, alive }) {
  const { item } = state;
  const parts = [];
  if (head) {
    const line = element("p", "dec-head");
    line.append(element("span", "dec-title", `#${item.id} ${item.title}`), stateChip(item));
    parts.push(line, ...contextParts(item, renderText));
  } else if (item.answer_state !== "unanswered" || item.job) {
    // 팝업 머리에는 답 상태가 없다 — 답한 뒤에만 한 줄로
    const line = element("p", "dec-head");
    line.append(element("span", "dec-title muted", t("decision.stateLabel")), stateChip(item));
    parts.push(line);
  }
  parts.push(answerBox(state, { draw, alive }));
  return parts;
}

// 결정 내용 — 배경과 추천 이유(detail), 다음 단계(next_step), 산출물(open_target). 기록된 글만 옮긴다
function contextParts(item, renderText) {
  const parts = [];
  if (item.detail) parts.push(folded(item.detail, renderText));
  if (item.next_step) parts.push(labelled(t("decision.nextStep"), item.next_step, renderText));
  if (item.open_target) parts.push(labelled(t("decision.output"), item.open_target, renderText));
  return parts;
}

function textNode(text, className, renderText, label) {
  const node = element("p", className);
  if (label) node.append(element("span", "dec-label", label));
  node.append(...(renderText ? renderText(text) : [document.createTextNode(text)]));
  return node;
}

export function labelled(label, text, renderText) {
  return textNode(text, "dec-text", renderText, label);
}

// 긴 배경은 접어 두고 펼친다 — 선택지가 화면 밖으로 밀리지 않게
export function folded(text, renderText) {
  const box = element("div", "dec-context");
  box.append(textNode(text, "dec-text", renderText));
  if (text.length <= CONTEXT_FOLD_CHARS && text.split("\n").length <= CONTEXT_FOLD_LINES) return box;
  box.classList.toggle("folded", true);
  const toggle = element("button", "dec-more", t("decision.more"));
  toggle.type = "button";
  toggle.addEventListener("click", () => {
    const fold = !box.className.split(" ").includes("folded");
    box.classList.toggle("folded", fold);
    toggle.textContent = fold ? t("decision.more") : t("decision.less");
  });
  box.append(toggle);
  return box;
}

function answerBox(state, { draw, alive }) {
  const { item } = state;
  const box = element("div", "dec-answer");
  const options = item.options ?? [];
  const locked = busy(item);
  if (options.length) {
    const list = element("ul", "choices");
    options.forEach((option) => list.appendChild(choiceItem(state, option, locked, draw)));
    box.append(list);
  }
  const input = element("textarea");
  input.value = state.feedback;
  input.disabled = locked;
  input.placeholder = options.length ? t("decision.feedbackPlaceholder") : t("decision.feedbackOnlyPlaceholder");
  // 연결 세션이 없는 결정은 답을 이어 갈 세션이 없다 — 보낸 뒤에야 '원 세션 없음'을 보지 않게 미리 말한다
  const hint = element(
    "p",
    "hint",
    !item.session ? t("decision.hintNoSession") : options.length ? t("decision.hint") : t("decision.hintNoOptions")
  );
  const how = element("p", "how");
  const send = element("button", "dec-send", item.answer ? t("decision.resend") : t("decision.send"));
  send.type = "button";
  const status = element("p", "dec-status", "");
  const refresh = () => {
    const answer = preview(state);
    how.textContent = answer ? t("decision.willSend", { answer }) : "";
    send.disabled = locked || !answer;
  };
  input.addEventListener("input", () => {
    state.feedback = input.value;
    refresh();
  });
  send.addEventListener("click", () => submit(state, { draw, alive, send, status }));
  refresh();
  const actions = element("div", "compose-actions");
  actions.append(how, send);
  box.append(input, hint, actions, ...sentParts(item), status);
  return box;
}

function choiceItem(state, option, locked, draw) {
  const { item } = state;
  const row = document.createElement("li");
  const button = element("button", "choice");
  button.type = "button";
  button.disabled = locked;
  const label = element("span", "lbl");
  label.append(element("b", "dec-key", option.key), document.createTextNode(` ${option.label}`));
  if (sameKey(option.key, item.recommend)) label.append(element("span", "dec-tag rec", t("decision.recommend")));
  if (item.answer && sameKey(option.key, item.answer_choice)) {
    label.append(element("span", "dec-tag picked", t("decision.picked")));
  }
  button.append(element("span", "mark", "✓"), label, element("span", "desc", option.desc ?? ""));
  button.classList.toggle("selected", sameKey(option.key, state.choice));
  // 같은 것을 다시 누르면 고른 것을 푼다 — 의견만 보내려는데 잘못 누른 선택지를 되돌릴 길
  button.addEventListener("click", () => {
    state.choice = sameKey(option.key, state.choice) ? null : option.key;
    draw();
  });
  row.appendChild(button);
  return row;
}

function sameKey(a, b) {
  return a != null && b != null && String(a).toLowerCase() === String(b).toLowerCase();
}

// 원 세션이 받을 답 문장과 같은 모양 — 'A(라벨)'·'A(라벨) — 추가 의견: 글'·'글' (매니저 compose_answer)
function preview(state) {
  const option = (state.item.options ?? []).find((each) => sameKey(each.key, state.choice));
  const choice = option ? `${option.key}(${option.label})` : "";
  const feedback = state.feedback.split(/\s+/).filter(Boolean).join(" ");
  if (choice && feedback) return t("decision.withFeedback", { choice, feedback });
  return choice || feedback;
}

// 이미 보낸 답과 그 뒤 일어난 일
function sentParts(item) {
  const parts = [];
  if (item.answer) parts.push(element("p", "dec-sent", t("decision.sent", { answer: item.answer })));
  const note = NOTES[item.answer_state];
  if (note && !posting(item)) parts.push(element("p", "dec-note", note()));
  if (item.job?.error && !item.job.running) {
    parts.push(element("p", "dec-note danger", fromKorean(item.job.error)));
  }
  return parts;
}

async function submit(state, { draw, alive, send, status }) {
  const option = (state.item.options ?? []).find((each) => sameKey(each.key, state.choice));
  const feedback = state.feedback.trim();
  if (!option && !feedback) return;
  send.disabled = true;
  status.className = "dec-status";
  status.textContent = t("decision.posting");
  try {
    state.item = await api.answerDecision(state.item.id, option?.key ?? null, feedback || null);
    state.choice = null;
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

// 답이 원 세션에 닿을 때까지(뒤의 answer-ui 가 끝나고 매니저가 상태를 찍을 때까지) 한 건만 다시 읽는다
function poll(state, draw, alive) {
  clearTimeout(state.timer);
  const tick = async () => {
    if (!alive() || state.polls >= POLL_LIMIT) return;
    state.polls += 1;
    try {
      state.item = await api.getDecision(state.item.id);
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
