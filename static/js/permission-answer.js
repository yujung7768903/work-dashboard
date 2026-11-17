// 권한 요청에 답하기 — 할일 상세 창 개요(제목 아래). 그 할일을 잡은 세션이 기다리는 권한을 도구·명령 전문·대상·
// 기다린 시간과 함께 보이고, 매니저 permission_gate 가 결정을 기다리는 요청이면 허용·거부로 답한다.
// 결정 상자와 같은 규칙이다 — 누르면 고르기만 하고 '답 보내기'로 보낸다. 잘못 누른 허용은 되돌릴 수 없다.
// 명령은 서버가 transcript 에서 읽은 전문 그대로 보인다(자르지 않는다). 전문을 확인하지 못한 요청은 허용을
// 고를 수 없다 — 보지 못한 명령을 허용하게 두지 않는다. 화면에서 답할 수 없는 요청(터미널 프롬프트로 넘어간 것·
// 꺼진 세션)은 왜 안 되는지와 어디서 답하는지만 보인다. 자동 허용은 없다
import * as api from "./api.js";
import { fromKorean, t } from "./i18n.js";

// 모드 → (칩 색, 문구). 칩 색은 결정 상자와 같은 뜻 — 사람을 기다리면 waiting, 이어 가지 못하면 failed.
// 키를 문자열 그대로 둔다 — 사전 점검(tests/test_language.py)이 코드에서 키를 찾는다
const MODES = {
  gate: ["waiting", () => t("permission.mode.gate")],
  terminal: ["", () => t("permission.mode.terminal")],
  ended: ["failed", () => t("permission.mode.ended")],
};
const ANSWERS = {
  yes: () => t("permission.allow"),
  no: () => t("permission.deny"),
};
const SENT = {
  yes: () => t("permission.sentAllow"),
  no: () => t("permission.sentDeny"),
};
const SECONDS_PER_MINUTE = 60;

/**
 * 권한 요청 하나. onAnswered 는 답을 넘긴 뒤 부른다 — 칸을 다시 읽어 닫힌 요청을 지운다(sessions.js)
 */
export function permissionCard(item, { onAnswered = () => {} } = {}) {
  const card = element("div", `perm-card ${item.mode}`);
  const state = { choice: null, sent: null, busy: false, error: "" };
  const draw = () => card.replaceChildren(...cardParts(item, state, { draw, onAnswered }));
  draw();
  return card;
}

function cardParts(item, state, actions) {
  const [tone, label] = MODES[item.mode] ?? MODES.ended;
  const head = element("p", "dec-head");
  head.append(element("span", "dec-title", title(item)), element("span", `mgr-chip ${tone}`.trim(), label()));
  const parts = [head, meta(item)];
  item.calls.forEach((call) => parts.push(...callParts(call)));
  if (item.mode === "gate") parts.push(...gateParts(item, state, actions));
  else if (item.mode === "terminal") parts.push(...terminalParts(item));
  else parts.push(element("p", "dec-note", t("permission.endedNote")));
  return parts;
}

function title(item) {
  const tool = item.calls[0]?.tool || item.request?.tool_name || "";
  const who = item.session.name || item.session.short;
  return tool ? `${tool} · ${who}` : who;
}

// 언제 요청했고 얼마나 기다렸는지, 어디서 도는 세션인지. 명령의 상대 경로는 작업 위치 기준이다
function meta(item) {
  const line = element("p", "perm-meta");
  const bits = [];
  if (item.requested_at) bits.push(t("permission.requestedAt", { at: stamp(item.requested_at) }));
  if (item.waited_sec != null) bits.push(t("permission.waited", { duration: duration(item.waited_sec) }));
  if (item.session.cwd) bits.push(t("permission.cwd", { cwd: item.session.cwd }));
  line.textContent = bits.join(" · ");
  return line;
}

function callParts(call) {
  const parts = [];
  if (call.description) parts.push(labelled(t("permission.description"), call.description));
  if (call.target) parts.push(labelled(t("permission.target"), call.target));
  const body = element("pre", `perm-cmd${call.is_command ? " command" : ""}`, call.text);
  parts.push(body);
  return parts;
}

function labelled(label, text) {
  const node = element("p", "perm-field");
  node.append(element("span", "dec-label", label), document.createTextNode(text));
  return node;
}

function gateParts(item, state, { draw, onAnswered }) {
  const parts = [];
  if (!item.verified) {
    // 미리보기는 매니저가 비밀값을 가리고 200자에서 자른 것이다 — 전문이 아니라는 걸 같이 말한다
    parts.push(element("p", "dec-note danger", t("permission.unverified")));
    if (item.request?.preview) parts.push(element("pre", "perm-cmd preview", item.request.preview));
  }
  if (item.deadline_at) {
    parts.push(element("p", "dec-note", t("permission.deadline", { at: stamp(item.deadline_at, true) })));
  }
  const box = element("div", "dec-answer");
  const locked = state.busy || Boolean(state.sent);
  const list = element("ul", "choices perm-choices");
  ["yes", "no"].forEach((reply) => {
    // 전문을 확인하지 못한 요청은 허용을 고를 수 없다
    if (reply === "yes" && !item.verified) return;
    list.appendChild(choiceItem(state, reply, locked, draw));
  });
  const how = element("p", "how", state.choice ? t("permission.willSend", { answer: ANSWERS[state.choice]() }) : "");
  const send = element("button", "dec-send", t("permission.send"));
  send.type = "button";
  send.disabled = locked || !state.choice;
  send.addEventListener("click", () => submit(item, state, { draw, onAnswered }));
  const row = element("div", "compose-actions");
  row.append(how, send);
  box.append(list, row);
  if (state.sent) box.append(element("p", "dec-sent", SENT[state.sent]()));
  if (state.error) box.append(element("p", "dec-status danger", state.error));
  parts.push(box);
  return parts;
}

function choiceItem(state, reply, locked, draw) {
  const row = document.createElement("li");
  const button = element("button", `choice perm-${reply}`);
  button.type = "button";
  button.disabled = locked;
  button.append(element("span", "mark", "✓"), element("span", "lbl", ANSWERS[reply]()));
  button.classList.toggle("selected", state.choice === reply);
  button.addEventListener("click", () => {
    state.choice = state.choice === reply ? null : reply;
    draw();
  });
  row.appendChild(button);
  return row;
}

async function submit(item, state, { draw, onAnswered }) {
  if (!state.choice || state.busy) return;
  state.busy = true;
  state.error = "";
  draw();
  try {
    await api.answerPermission({
      id: item.request.id,
      answer: state.choice,
      session_id: item.session.claude_session_id,
      created_at: item.request.created_at,
      tool_use_id: state.choice === "yes" ? item.calls[0]?.tool_use_id ?? null : null,
    });
    state.sent = state.choice;
    onAnswered();
  } catch (error) {
    state.error = fromKorean(error.message);
  } finally {
    state.busy = false;
    draw();
  }
}

// 훅이 이미 터미널 프롬프트로 넘긴 요청 — 그 프롬프트는 세션 프로세스 안에 있어 화면에서 닿지 않는다
function terminalParts(item) {
  const note = element("p", "dec-note", t("permission.terminalNote"));
  const code = element("code", "perm-attach", item.attach ?? "");
  return [note, code];
}

// 로그와 같은 숫자 표기(로컬 시각). 기한은 시:분만 — 같은 날 몇 분 뒤다
function stamp(iso, timeOnly = false) {
  const ms = Date.parse(iso);
  if (Number.isNaN(ms)) return iso;
  const at = new Date(ms);
  const pad = (value) => String(value).padStart(2, "0");
  const time = `${pad(at.getHours())}:${pad(at.getMinutes())}`;
  return timeOnly ? time : `${pad(at.getMonth() + 1)}-${pad(at.getDate())} ${time}`;
}

function duration(seconds) {
  if (seconds < SECONDS_PER_MINUTE) return t("duration.seconds", { count: seconds });
  const minutes = Math.floor(seconds / SECONDS_PER_MINUTE);
  if (minutes < 60) return t("duration.minutes", { count: minutes });
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return t("duration.hoursMinutes", { hours, minutes: minutes % 60 });
  return t("duration.daysHours", { days: Math.floor(hours / 24), hours: hours % 24 });
}

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}
