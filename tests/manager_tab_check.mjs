// 매니저 탭 — 주기 구조를 사람 말로 옮기고, 칸을 한 줄에 하나씩 그리며, 한 칸이 실패해도
// 나머지는 그리는지 본다. 하위 탭(작업·설정)은 보이는 탭의 칸만 받는다. 실행: node tests/manager_tab_check.mjs (tests/test_manager_tab.py 가 부른다)
import assert from "node:assert/strict";
import { bootKorean } from "./i18n_boot.mjs";
import { CARD_H } from "../static/js/tree-layout.js";

const node = (tag) => {
  const self = {
    tag, className: "", textContent: "", title: "", children: [], listeners: {}, hidden: false,
    dataset: {}, style: { setProperty() {} },
    classList: {
      toggle(name, on) {
        const names = new Set(self.className.split(" ").filter(Boolean));
        if (on) names.add(name);
        else names.delete(name);
        self.className = [...names].join(" ");
      },
    },
    addEventListener(type, fn) { self.listeners[type] = fn; },
    showModal() { self.open = true; },
    append(...kids) { self.children.push(...kids); },
    appendChild(kid) { self.children.push(kid); return kid; },
    replaceChildren(...kids) { self.children = kids; },
  };
  return self;
};
const elements = {};
globalThis.document = {
  createElement: node,
  createTextNode: (text) => ({ textContent: text }),
  getElementById: (id) => (elements[id] ??= node("ul")),
};

const inMinutes = (minutes) => new Date(Date.now() + minutes * 60000).toISOString();
const agoMinutes = (minutes) => new Date(Date.now() - minutes * 60000).toISOString();
const PAYLOAD = {
  automations: {
    error: null,
    items: [
      {
        source: "crontab", name: "자율 실행", desc: "자율 실행 판정 (5분 크론)", desc_from: "script", expr: "*/5 * * * *",
        cycle: { days: { kind: "every" }, time: { kind: "interval", minutes: 5, hours: null } },
        next_at: inMinutes(3), last: { at: agoMinutes(2), status: "ok", detail: null }, command: "dash.py autorun-tick",
      },
      {
        source: "manager", name: "manager-check", expr: null,
        cycle: { days: { kind: "weekdays" }, time: { kind: "interval", minutes: 10, hours: [8, 20] } },
        next_at: null, next_within_sec: 600, off_duty: false,
        last: { at: agoMinutes(14), status: null, detail: "woke" }, command: "hook",
      },
      {
        source: "sre-watch", name: "훅 차단 실패 1% 미만", expr: "30 11 * * *",
        cycle: { every_days: 1, manual: false, runner: { days: { kind: "every" }, time: { kind: "at", times: ["11:30"] } } },
        next_at: inMinutes(60 * 15), last: { at: agoMinutes(500), status: "fail", detail: "4%" }, command: "run.py",
      },
      {
        source: "crontab", name: "skill-prune · tick", desc: null, expr: "@reboot", cycle: { reboot: true },
        next_at: null, last: null, command: "prune.py tick",
      },
    ],
  },
  helpers: { error: "RuntimeError: claude agents 응답 없음", items: [] },
  // 후보 할일 — 서버(app/services/candidates.py)가 대기를 빼고 우선순위 순으로 3건까지 준다. 머리는 대기 건수
  candidates: {
    error: null, waiting: 2,
    items: [
      { id: 41, title: "보도자료 자동 분류", status: "doing", priority: 3, priority_max: 3, category_name: "회사", category_color: "#d33" },
      { id: 52, title: "블로그 2편", status: "todo", priority: null, priority_max: 3, category_name: null, category_color: null },
    ],
  },
  tools: {
    error: null,
    items: [
      { id: "mcp:rovo", kind: "mcp", name: "Jira·Confluence", source: "claude.ai Atlassian Rovo", category: "docs", maker: "external",
        desc: "Jira 이슈와 Confluence 페이지 조회·작성", status: "connected", checked_at: agoMinutes(5) },
      { id: "mcp:discord", kind: "mcp", name: "디스코드", source: "plugin:discord:discord", category: "talk", maker: "external",
        desc: "매니저 채널로 사용자와 주고받기", status: "connected", checked_at: agoMinutes(5) },
      { id: "cli:aws", kind: "cli", name: "AWS CLI", source: "aws", category: "infra", maker: "external",
        desc: "AWS 리소스 조회", status: "auth", checked_at: agoMinutes(5) },
      { id: "mcp:x", kind: "mcp", name: "mystery", source: "mystery", category: "etc", maker: null,
        desc: null, status: "unknown", checked_at: agoMinutes(5) },
      { id: "cmd:open", kind: "command", name: "manager.py open", source: "open", category: "command", maker: "inhouse",
        desc: "사용자 PC 에 띄운다", detail: "사용자 PC 에 띄운다 — URL 은 기본 브라우저", status: "available", checked_at: null },
    ],
  },
  decisions: {
    error: null,
    items: [
      {
        id: 87, title: "우선순위 출처", state: "decision", detail: "A 추천", priority: 2, priority_max: 3, since: agoMinutes(30), held: false,
        popup: {
          detail: "todos 에 priority 칸이 없음\n선택지 A·B", next_step: "A 와 B 중 고르기", plan: null,
          plan_status: null, reason: null, source_ref: null, open_target: "/home/u/x.md",
          session_id: "s1", reply_tail: "…\nA 를 추천해.", reply_from: "transcript",
          request: { status: "ok", text: "우선순위 칸을 정해 줘.\n보드와 같은 표기로." },
        },
        card: null,
      },
    ],
  },
  confirms: {
    error: null,
    items: [
      {
        id: 61, title: "보조 한도", state: "confirm", detail: null, priority: null, priority_max: 3, since: agoMinutes(90), held: false,
        popup: {
          detail: null, next_step: null, reason: "master 905f617 반영", session_id: null, reply_tail: null,
          source: "jira", source_ref: "PFD-6350", request: { status: "no_session" },
        },
      },
      {
        id: 62, title: "블로그 글 반영", state: "confirm", detail: "초안 반영", priority: 2, priority_max: 3, since: agoMinutes(5), held: false,
        popup: {
          detail: "초안 반영\n표 너비 수정", next_step: "문체 확인", plan: null, plan_status: null,
          reason: "PR #12 머지", source_ref: null, open_target: "https://github.com/x/y/pull/12",
          session_id: "abcdef12-3456", session_name: "보조2 | 블로그", reply_tail: "…\n끝났어.", reply_from: "transcript",
          // 보조 세션의 spawn 지시문 — 길어서 접혀야 한다
          request: { status: "ok", text: Array.from({ length: 14 }, (_, i) => `${i + 1}. 지시 줄`).join("\n") },
        },
        // 이 일이 붙어 있는 트리 카드. 줄 제목이 이 카드 기준이 된다
        card: { todo_id: 355, title: "트리 메뉴 추가", status: "doing", root_id: 3, tree_key: "t3",
          root_title: "작업 대시보드", category_color: "#4a5ae8" },
      },
    ],
  },
};
// 선행 대기 — 다른 할일이 끝나야 하는 일. 결정 대기와 다른 칩, 줄 아랫줄은 남은 사전 조건
PAYLOAD.waits = {
  error: null,
  items: [
    {
      id: 9, title: "문의 자동화에 KT 로그 붙이기", state: "prereq", detail: "muni log_search", priority: 3, priority_max: 3,
      since: agoMinutes(30), held: false,
      prereqs: [
        { id: 168, title: "KT 서버 로그 경로", status: "open", finished: false },
        { id: 169, title: "KT 로그 Lambda 배포", status: "confirm", finished: false },
      ],
      popup: { detail: "muni log_search", next_step: "168·169 처리 뒤 PR #69 머지", session_id: null, source_ref: null,
        request: { status: "no_session" } },
    },
  ],
};
// 권한 대기 — 권한·로그인 막힘(ask --blocked permission). 결정 대기와 따로 세고 다른 칩. 예전 ask 가 결정으로 남긴 막힘은 답 칸
PAYLOAD.permissions = {
  error: null,
  items: [
    {
      id: 223, title: "에이전트 크롬에서 OpenSearch Dashboards 로그인해 주기", kind: "decision", state: "permission",
      detail: "로그인 화면에서 멈춤", priority: 2, priority_max: 3, since: agoMinutes(10), held: false, prereqs: [],
      popup: { detail: "로그인 화면에서 멈춤", next_step: "에이전트 크롬에서 로그인", session_id: null, source_ref: null,
        request: { status: "no_session" } },
    },
  ],
};
// 새로고침 검사용 — 부른 칸을 적고, 켜 두면 실패한다
const fetched = [];
let failFetch = false;
let holdFetch = null;
// 결정 팝업의 '답하기' 칸이 열 때 받는 한 건 — 선택지·추천·답 상태는 줄에 없다
const DECISION_ONE = {
  id: 87, title: "우선순위 출처", status: "open", options: [
    { key: "A", label: "칸 추가", desc: "todos 에 priority 칸" }, { key: "B", label: "note 에 적기", desc: "스키마 그대로" },
  ], recommend: "A", answer_state: "unanswered", answer: null, answer_choice: null, job: null,
};
const decisionFetched = [];
// 진행 단계가 있는 결정 — 멈춘 단계를 강조하고 그 줄 아래에 답하는 상자가 들어간다
const STEPPED = {
  id: 181, title: "수정 범위 결정", state: "decision", detail: "필터 무력화", priority: 2, priority_max: 3, prereqs: [],
  steps: [
    { name: "조사·선택지 정리", status: "done" },
    { name: "선택지 결정", status: "current", unblock: "A/B/C 중 하나 고르기 (추천 A)" },
    { name: "PR 작성", status: "todo" },
  ],
  popup: { detail: "필터 무력화", next_step: "A/B/C 중 고르기", session_id: null, request: { status: "no_session" } },
};
// 확인 대기 팝업의 '확인하기' 칸이 열 때 받는 한 건(app/services/task_report.py)
const reportFetched = [];
const helperFetched = [];
const managerTaskFetched = [];
const prereqPosted = [];
globalThis.fetch = async (url, options) => {
  if (url === "/api/prereq-action") {
    const body = JSON.parse(options.body);
    prereqPosted.push(body);
    // 선행이 모두 풀린 할일 — 선행 대기에서 빠져 결정 대기가 된다
    return {
      ok: true, status: 200,
      json: async () => ({ task: { id: body.task_id, title: "문의 자동화에 KT 로그 붙이기", state: "decision", detail: null,
        priority: 3, priority_max: 3, prereqs: [{ id: 169, title: "KT 로그 Lambda 배포", status: "done", finished: true }],
        popup: { detail: "muni", next_step: null, session_id: null, request: { status: "no_session" } } } }),
    };
  }
  if (url.startsWith("/api/manager-task/")) {
    const id = Number(url.split("/").at(-1));
    managerTaskFetched.push(id);
    if (id === 181) return { ok: true, status: 200, json: async () => STEPPED };
    return {
      ok: true, status: 200,
      json: async () => ({ id, title: "KT 서버 로그 경로", state: "action", detail: null, priority: 2, priority_max: 3,
        prereqs: [], popup: { detail: "catalina", next_step: "7일 삭제 크론", session_id: null, request: { status: "no_session" } } }),
    };
  }
  if (url.startsWith("/api/decisions/")) {
    decisionFetched.push(url);
    return { ok: true, status: 200, json: async () => DECISION_ONE };
  }
  if (url.startsWith("/api/helper-feedback?")) {
    const sessionId = new URL(url, "http://x").searchParams.get("session_id");
    helperFetched.push(sessionId);
    return {
      ok: true, status: 200,
      json: async () => ({ session: { id: sessionId, name: "보조", alive: true }, items: [], job: null }),
    };
  }
  if (url.startsWith("/api/task-reports/")) {
    reportFetched.push(url);
    const id = Number(url.split("/").at(-1));
    return {
      ok: true, status: 200,
      json: async () => ({ id, title: "확인 대기", status: "confirm", report_kind: "confirm", answer: null,
        answer_via: null, answer_state: "unanswered", session: null, job: null }),
    };
  }
  // 할일 상세(후보 할일을 누를 때)가 읽는 것 — 이 검사는 상세 모양을 보지 않는다
  if (!url.startsWith("/api/manager?")) return { ok: true, status: 200, json: async () => ({}) };
  const part = new URL(url, "http://x").searchParams.get("part");
  fetched.push(part);
  if (holdFetch) await holdFetch;
  if (failFetch) throw new Error("서버 응답 없음");
  return { ok: true, status: 200, json: async () => ({ [part]: PAYLOAD[part] }) };
};

await bootKorean();
const manager = await import("../static/js/manager.js");

// 주기 → 사람 말
const cases = [
  [{ days: { kind: "weekdays" }, time: { kind: "interval", minutes: 10, hours: [8, 20] } }, "10분마다 (평일 08~20시)"],
  [{ days: { kind: "every" }, time: { kind: "hourly", minute: 7, hours: null } }, "매시 07분"],
  [{ days: { kind: "dom", values: [5] }, time: { kind: "at", times: ["05:00"] } }, "매월 5일 05:00"],
  [{ days: { kind: "weekdays" }, time: { kind: "at", times: ["08:00", "09:00"] } }, "평일 08:00, 09:00"],
  [{ reboot: true }, "부팅 시"],
  [{ raw: "1 2 3" }, "1 2 3"],
  // 못 옮기는 모양은 원문 표현식으로
  [{ days: { kind: "custom" }, time: { kind: "at", times: ["01:00"] } }, "0 1 * 3 *"],
];
for (const [cycle, expected] of cases) {
  assert.equal(manager.cycleText(cycle, "0 1 * 3 *"), expected);
}
assert.match(manager.cycleText({ days: { kind: "dow", values: [3] }, time: { kind: "at", times: ["15:00"] } }), /^매주 수 15:00$/);

await manager.renderManager();

// 처음은 작업 탭 — 그 탭 칸만 받고, 설정 판은 숨긴다
assert.deepEqual([...fetched].sort(), ["candidates", "confirms", "decisions", "helpers", "permissions", "waits"], "작업 탭 칸만 받는다");

// 후보 할일 — 머리는 후보 수가 아니라 '대기 중 N건' 한 줄. 줄은 '#id 우선순위 제목', 아래 카테고리 칩, 옆 상태
assert.equal(elements["mgr-candidates-count"].textContent, "대기 중 2건");
const candidateRows = elements["mgr-candidates"].children;
assert.equal(candidateRows.length, 2);
const candidateText = (line) => {
  const [main, side] = line.children;
  return [main.children[0].children.map((kid) => kid.textContent).join(" "), main.children[1].children[0].textContent,
    side.children[0].textContent];
};
assert.deepEqual(candidateText(candidateRows[0]), ["#41 3/3 보도자료 자동 분류", "회사", "진행 중"]);
assert.deepEqual(candidateText(candidateRows[1]), ["#52 - 블로그 2편", "미분류", "할 일"]);
assert.match(candidateRows[0].children[1].children[0].className, /\bworking\b/);
// 누르면 할일 상세가 열린다
candidateRows[0].listeners.click();
assert.equal(elements["session-modal"].open, true, "후보를 누르면 할일 상세");
elements["session-modal"].open = false;
assert.equal(elements["mgr-pane-work"].hidden, false);
assert.equal(elements["mgr-pane-setup"].hidden, true);
assert.match(elements["mgr-subtab-work"].className, /\bactive\b/);
assert.doesNotMatch(elements["mgr-subtab-setup"].className, /\bactive\b/);
assert.equal((elements["mgr-automations"]?.children ?? []).length, 0, "설정 탭 칸은 아직 안 그린다");

// 설정 탭으로 바꾸면 그 탭 칸(자동화·도구)만 바로 받는다. 탭 버튼은 svg 를 품어 closest 로 버튼을 찾는다
fetched.length = 0;
elements["manager-tabs"].listeners.click({ target: { closest: () => ({ dataset: { subtab: "setup" } }) } });
await manager.selectManagerSubtab("setup"); // 이미 그 탭이면 다시 받지 않는다
await new Promise((resolve) => setTimeout(resolve, 0));
assert.deepEqual([...fetched].sort(), ["automations", "tools"], "설정 탭 칸만 받는다");
assert.equal(elements["mgr-pane-work"].hidden, true);
assert.equal(elements["mgr-pane-setup"].hidden, false);
assert.match(elements["mgr-subtab-setup"].className, /\bactive\b/);

const [header, ...rows] = elements["mgr-automations"].children;
// 세 칸 표: 주기 / 자동화 내용 / 수행 시간 — 머리줄 하나 + 항목마다 한 줄
assert.deepEqual(header.children.map((cell) => cell.textContent), ["주기", "자동화 내용", "수행 시간"]);
assert.equal(rows.length, 4, "자동화는 항목마다 한 줄");
const cells = (row) => {
  const [cycle, main, side] = row.children;
  return [cycle.textContent, main.children[0].textContent, main.children[1].textContent,
    side.children[0].textContent, side.children[1].textContent];
};
// 주기는 맨 왼쪽 칸 — 이름 아래 줄로 내려가지 않는다
assert.deepEqual(cells(rows[0]), ["5분마다", "자율 실행", "자율 실행 판정 (5분 크론)", "3분 후", "성공 2m 전"]);
assert.deepEqual(cells(rows[1]), ["10분마다 (평일 08~20시)", "매니저 주기 점검", "설명 없음", "10분 안", "마지막 알림 14m 전"]);
assert.match(rows[1].children[1].children[1].className, /mgr-nodesc/);
assert.equal(cells(rows[2])[1], "SRE 체크 · 훅 차단 실패 1% 미만");
assert.equal(cells(rows[2])[0], "매일 11:30");
assert.match(rows[2].children[2].children[1].className, /fail/);
assert.deepEqual(cells(rows[3]).slice(0, 1).concat(cells(rows[3]).slice(3)), ["부팅 시", "부팅 시", "마지막 실행 모름"]);
assert.equal(elements["mgr-automations-count"].textContent, "4");

// 보조 세션 칸이 실패해도 그 칸에 사유만 남고 다른 칸은 그려진다
const helperRows = elements["mgr-helpers"].children;
assert.equal(helperRows.length, 1);
assert.match(helperRows[0].textContent, /claude agents 응답 없음/);
const decisionRows = elements["mgr-decisions"].children;
// 결정 대기 제목 칸은 '#번호'·우선순위 배지·제목 세 조각이다
const titleText = (title) => (title.children.length ? title.children.map((kid) => kid.textContent).join(" ") : title.textContent);
assert.equal(decisionRows.length, 1, "결정 대기 칸에는 열린 결정만 — 확인 대기는 옆 칸");
const texts = (row) => {
  const [main, side] = row.children;
  return [titleText(main.children[0]), titleText(main.children[1]), side.children[0].textContent, side.children[1].textContent];
};
assert.deepEqual(texts(decisionRows[0]), ["#87 2/3 우선순위 출처", "A 추천", "결정", "30m 전"]);

// 권한 대기 칸 — 건수는 결정 대기와 따로, 칩은 '권한 대기'(permission 색)
assert.equal(elements["mgr-permissions-count"].textContent, "1");
assert.equal(elements["mgr-decisions-count"].textContent, "1");
const permRow = elements["mgr-permissions"].children[0];
assert.deepEqual(texts(permRow), ["#223 2/3 에이전트 크롬에서 OpenSearch Dashboards 로그인해 주기", "로그인 화면에서 멈춤", "권한 대기", "10m 전"]);
assert.match(permRow.children[1].children[0].className, /\bpermission\b/);
assert.doesNotMatch(permRow.children[1].children[0].className, /\bwaiting\b/);
// 번호 오른쪽 우선순위는 보드 할일 줄과 같은 배지(.todo-priority)
const badge = decisionRows[0].children[0].children[0].children[1];
assert.equal(badge.className, "todo-priority");
assert.equal(badge.title, "우선순위 2 / 열린 할일 중 최고 3");

// 결정 대기 줄을 누르면 팝업 — 제목·상세|트리 탭, 상세는 사용자 요청 / 지금까지 한 일 / 결정할 것, 기록된 글만
decisionRows[0].listeners.click();
const modal = elements["mgr-decision-modal"];
assert.equal(modal.open, true);
const headTitle = () => elements["mgr-decision-head"].children[0].children[0].textContent;
assert.equal(headTitle(), "#87 우선순위 출처");
const body = elements["mgr-decision-body"].children;
const sectionText = (section) => section.children.map((kid) => kid.textContent || kid.children.map((c) => c.textContent || c.children?.map((g) => g.textContent).join("")).join("")).join("|");
// 사용자 요청 — 그 일을 시작한 첫 지시 전문, 줄바꿈 그대로
assert.equal(body[0].children[0].textContent, "사용자 요청");
assert.equal(sectionText(body[0]), "사용자 요청|우선순위 칸을 정해 줘.\n보드와 같은 표기로.");
assert.doesNotMatch(body[0].children[1].className, /folded/, "짧은 요청은 접지 않는다");
assert.equal(body[1].children[0].textContent, "지금까지 한 일");
assert.match(sectionText(body[1]), /todos 에 priority 칸이 없음/);
assert.equal(body[2].children[0].textContent, "결정할 것");
assert.match(sectionText(body[2]), /A 와 B 중 고르기/);
assert.match(sectionText(body[2]), /연결 세션의 마지막 답 \(끝부분\)/);
assert.match(sectionText(body[2]), /A 를 추천해/);

// 결정할 것 바로 아래 '답하기' — 열 때 한 건을 받아 선택지 버튼·의견 입력칸을 그린다. 팝업 머리·섹션이 이미
// 제목·배경을 보이므로 상자는 답하기 부분만(테두리 없이)
assert.equal(body[3].children[0].textContent, "답하기");
assert.deepEqual(decisionFetched, ["/api/decisions/87"]);
for (let i = 0; !body[3].children[1].children[0]?.className.startsWith("dec-card") && i < 50; i += 1) {
  await new Promise((resolve) => setTimeout(resolve, 0));
}
const answerCard = body[3].children[1].children[0];
assert.equal(answerCard.className, "dec-card bare", "답을 기다리는 결정, 팝업 안이라 테두리 없이");
const answerBox = answerCard.children.at(-1);
const answerChoices = answerBox.children[0].children.map((li) => li.children[0]);
assert.deepEqual(answerChoices.map((button) => button.children[1].children.map((kid) => kid.textContent).join("")),
  ["A 칸 추가추천", "B note 에 적기"]);
assert.equal(answerBox.children[1].tag, "textarea");
// 결정에도 연결 세션 칸 — 이름이 없으면 세션 id 앞 8자리. 마지막 답은 결정할 것 쪽에만
assert.equal(body[4].children[0].textContent, "연결 세션");
assert.equal(sectionText(body[4]), "연결 세션|s1");
// 붙은 카드가 없는 일 — 트리 탭은 안내 글만 두지 않고 그 일 하나를 트리 카드 모양으로 그린다.
// 카드 아래에 '연결되지 않은 일' 안내. 카드 한 장이라 팝업은 넓히지 않는다
const openTab = (tab) => elements["mgr-pop-tabs"].listeners.click({ target: { closest: () => ({ dataset: { tab } }) } });
// 트리 탭 판 = [카드, 안내]. 카드 = [머리(상태 칩·번호·대기 배지), 제목, 꼬리]
const solo = () => {
  const board = elements["mgr-decision-tree"].children[0];
  const [card, noteLine] = board.children;
  const [head, title, foot] = card.children;
  return { board, card, head: head.children.map((kid) => kid.textContent), title, foot, note: noteLine.textContent };
};
openTab("tree");
assert.equal(elements["mgr-decision-body"].hidden, true);
assert.equal(elements["mgr-decision-tree"].hidden, false);
assert.match(elements["mgr-decision-tree"].className, /\bsolo\b/);
let one = solo();
assert.equal(one.board.className, "tm-viewport mgr-solo", "맵과 같은 점 격자 판");
assert.equal(one.card.className, "tm-card tm-solo", "트리 카드와 같은 카드 클래스");
assert.equal(one.card.style.width, "248px", "트리 카드와 같은 크기");
assert.equal(one.card.style.height, `${CARD_H}px`);
// 결정은 바탕이 진행 중, 사람을 기다린다는 것은 트리 카드와 같은 대기 표시(답 대기)
assert.equal(one.card.dataset.status, "doing");
assert.equal(one.card.dataset.waiting, "input");
assert.deepEqual(one.head, ["결정", "#87", "답 대기"]);
assert.equal(one.title.tag, "div", "대시보드 할일이 아니라 열 상세가 없다");
assert.equal(one.title.textContent, "우선순위 출처", "줄에 보이는 제목");
assert.equal(one.note, "대시보드 할일과 연결되지 않은 일입니다");
assert.doesNotMatch(modal.className, /\bwide\b/);
openTab("detail");
assert.equal(elements["mgr-decision-body"].hidden, false);
assert.doesNotMatch(modal.className, /\bwide\b/);

// 선행 대기 — 칩은 '선행 대기'(결정 대기와 다른 색), 아랫줄은 남은 사전 조건. 팝업 맨 위에 사전 조건 목록,
// 답하는 칸은 없다. 사전 조건을 누르면 그 할일 한 건을 받아 그 팝업으로 바뀐다(직접 할 일이면 완료·진행 상황 칸)
const waitRows = elements["mgr-waits"].children;
assert.equal(elements["mgr-waits-count"].textContent, "1");
assert.deepEqual(texts(waitRows[0]), ["#9 3/3 문의 자동화에 KT 로그 붙이기", "#168 · #169 끝나야 함", "선행 대기", "30m 전"]);
assert.match(waitRows[0].children[1].children[0].className, /\bprereq\b/);
waitRows[0].listeners.click();
assert.equal(headTitle(), "#9 문의 자동화에 KT 로그 붙이기");
const waitBody = elements["mgr-decision-body"].children;
assert.deepEqual(waitBody.map((section) => section.children[0].textContent),
  ["사용자 요청", "사전 조건", "지금까지 한 일", "결정할 것"]);
const prereqItems = waitBody[1].children[1].children;
assert.equal(prereqItems.length, 2);
const firstPrereq = prereqItems[0].children[0];
assert.deepEqual(firstPrereq.children.map((kid) => kid.textContent), ["#168 KT 서버 로그 경로", "남음"]);
assert.deepEqual(prereqItems[1].children[0].children.map((kid) => kid.textContent), ["#169 KT 로그 Lambda 배포", "확인 대기"]);
// 사전 조건 줄 상자 안, 상태 칩(남음) 바로 오른쪽 케밥 — 제거하기·완료 처리하기. 누르기 전에 되묻고, 처리 뒤 선행 대기·결정 대기 칸을 다시 읽고
// 팝업을 갱신된 할일로 다시 그린다(선행이 풀리면 답하는 칸이 생긴다). 끝난 사전 조건은 닫을 것이 없어 제거만 있다
// 테두리는 줄(li.prereq-row)이 그려 케밥이 상자 밖에 따로 떠 있지 않다
assert.match(prereqItems[0].className, /\bprereq-row\b/);
assert.equal(prereqItems[0].children.length, 2, "줄 상자 안에 여는 버튼과 케밥만 있다");
const kebab = prereqItems[0].children[1];
assert.match(kebab.className, /\bws-menu\b/);
assert.equal(kebab.children[0].textContent, "⋮");
assert.equal(kebab.children[1].hidden, true);
assert.deepEqual(kebab.children[1].children.map((kid) => kid.textContent), ["사전 조건 제거하기", "완료 처리하기"]);
kebab.children[0].listeners.click({ stopPropagation() {} });
assert.equal(kebab.children[1].hidden, false);
const asked = [];
globalThis.confirm = (text) => (asked.push(text), false);
kebab.children[1].children[1].listeners.click({ stopPropagation() {} });
await new Promise((resolve) => setTimeout(resolve, 0));
assert.deepEqual(prereqPosted, [], "되물어 취소하면 보내지 않는다");
assert.match(asked[0], /#168 KT 서버 로그 경로/);
globalThis.confirm = (text) => (asked.push(text), true);
fetched.length = 0;
await kebab.children[1].children[0].listeners.click({ stopPropagation() {} });
assert.deepEqual(prereqPosted, [{ task_id: 9, prereq_id: 168, action: "remove" }]);
assert.match(asked[1], /#9/);
assert.deepEqual([...fetched].sort(), ["decisions", "permissions", "waits"]);
assert.deepEqual(elements["mgr-decision-body"].children.map((section) => section.children[0].textContent),
  ["사용자 요청", "사전 조건", "지금까지 한 일", "결정할 것", "답하기"]);
const finishedItem = elements["mgr-decision-body"].children[1].children[1].children[0];
assert.deepEqual(finishedItem.children[1].children[1].children.map((kid) => kid.textContent), ["사전 조건 제거하기"]);
waitRows[0].listeners.click();
const reopenedPrereq = elements["mgr-decision-body"].children[1].children[1].children[0].children[0];
reportFetched.length = 0;
reopenedPrereq.listeners.click({ stopPropagation() {} });
for (let i = 0; !managerTaskFetched.length || headTitle() !== "#168 KT 서버 로그 경로"; i += 1) {
  assert.ok(i < 50, "사전 조건 할일 팝업이 열려야 한다");
  await new Promise((resolve) => setTimeout(resolve, 0));
}
assert.deepEqual(managerTaskFetched, [168]);
assert.deepEqual(elements["mgr-decision-body"].children.map((section) => section.children[0].textContent),
  ["사용자 요청", "지금까지 한 일", "결정할 것", "완료·진행 상황 알리기"]);
assert.deepEqual(reportFetched, ["/api/task-reports/168"]);
reportFetched.length = 0;

// 완료 확인 대기 — 결정 대기와 같은 줄 모양, 같은 팝업. 우선순위가 없으면 보드처럼 '-'
const confirmRows = elements["mgr-confirms"].children;
assert.equal(elements["mgr-confirms-count"].textContent, "2");
assert.deepEqual(texts(confirmRows[0]), ["#61 - 보조 한도", "", "확인 대기", "1h 전"]);
// 트리 카드에 붙은 일은 줄 제목이 카드 기준 — 트리 칩 + 카드 번호·제목. 확인할 일은 아랫줄로
assert.deepEqual(texts(confirmRows[1]), ["작업 대시보드 #355 트리 메뉴 추가", "#62 2/3 블로그 글 반영", "확인 대기", "5m 전"]);
const treeChip = confirmRows[1].children[0].children[0].children[0];
assert.equal(treeChip.className, "mgr-tree-chip");
assert.equal(treeChip.title, "트리: 작업 대시보드");
// 팝업: 사용자 요청 / 끝낸 내용 / 확인하기 / 작업 사항 / 다음 단계 / 산출물(있을 때만) / 연결 세션(이름·마지막 답)
confirmRows[1].listeners.click();
assert.equal(headTitle(), "#62 블로그 글 반영");
const confirmBody = elements["mgr-decision-body"].children;
assert.deepEqual(confirmBody.map((section) => section.children[0].textContent),
  ["사용자 요청", "끝낸 내용", "확인하기", "작업 사항", "다음 단계", "산출물", "연결 세션"]);
// 끝낸 내용 바로 아래 '확인하기' — 열 때 한 건을 받아 확인(기본)·고칠 것 보내기(글이 있을 때)를 그린다
assert.deepEqual(reportFetched, ["/api/task-reports/62"]);
for (let i = 0; !confirmBody[2].children[1].children[0]?.className.startsWith("dec-card") && i < 50; i += 1) {
  await new Promise((resolve) => setTimeout(resolve, 0));
}
const confirmCard = confirmBody[2].children[1].children[0];
assert.equal(confirmCard.className, "dec-card report-card bare", "팝업 안이라 테두리 없이, 머리 없이");
const confirmBox = confirmCard.children[0];
assert.equal(confirmBox.children[0].tag, "textarea");
const [fixButton, confirmButton] = confirmBox.children[2].children;
assert.deepEqual([fixButton.textContent, confirmButton.textContent], ["고칠 것 보내기", "확인"]);
assert.equal(fixButton.disabled, true, "글이 없으면 고칠 것은 못 보낸다");
assert.equal(confirmButton.disabled, false, "확인은 바로 누를 수 있다");
assert.match(confirmButton.className, /\bprimary\b/);
// 긴 요청은 접혀 있고 '전체 보기' 로 펼친다 — 전문은 그대로 들어 있다
const requestBox = confirmBody[0].children[1];
assert.match(requestBox.className, /\bfolded\b/);
assert.match(sectionText(confirmBody[0]), /1\. 지시 줄\n2\. 지시 줄[\s\S]*14\. 지시 줄/);
const toggle = requestBox.children[1];
assert.equal(toggle.textContent, "전체 보기");
toggle.listeners.click();
assert.doesNotMatch(requestBox.className, /\bfolded\b/);
assert.equal(toggle.textContent, "접기");
assert.equal(sectionText(confirmBody[1]), "끝낸 내용|PR #12 머지");
assert.match(sectionText(confirmBody[3]), /표 너비 수정/);
assert.equal(sectionText(confirmBody[4]), "다음 단계|문체 확인");
// 산출물 URL 은 새 탭 링크
const outputLink = confirmBody[5].children[1].children[0];
assert.equal(outputLink.href, "https://github.com/x/y/pull/12");
assert.equal(outputLink.target, "_blank");
assert.match(sectionText(confirmBody[6]), /^연결 세션\|보조2 \| 블로그\|연결 세션의 마지막 답 \(끝부분\)\|…\n끝났어\.$/);
// 비어 있는 칸은 지어내지 않고 '기록 없음', 산출물·연결 세션은 없으면 칸째 뺀다.
// 세션 없이 들어온 일은 사용자 요청 자리에 '세션 없음' 과 출처
confirmRows[0].listeners.click();
const bareBody = elements["mgr-decision-body"].children.filter((section) => section.children[0].textContent !== "확인하기");
assert.equal(elements["mgr-decision-body"].children[2].children[0].textContent, "확인하기");
assert.deepEqual(bareBody.map(sectionText), [
  "사용자 요청|세션 없음출처: jira · PFD-6350",
  "끝낸 내용|master 905f617 반영", "작업 사항|기록 없음", "다음 단계|기록 없음", "근거 자료|PFD-6350",
]);
// 완료 확인 대기의 단독 카드 — 트리 카드의 확인 대기 색, 기다리는 세션이 없으면 대기 표시 없음
openTab("tree");
one = solo();
assert.equal(one.card.dataset.status, "review");
assert.equal(one.card.dataset.waiting, undefined);
assert.deepEqual(one.head, ["확인 대기", "#61"]);
assert.equal(one.title.textContent, "보조 한도");
openTab("detail");

// 붙은 할일은 있는데 워크스페이스가 없으면 트리가 없다 — 그 할일을 카드로, 제목을 누르면 할일 상세
const loose = {
  ...PAYLOAD.decisions.items[0], id: 88, title: "미분류 결정", waiting: "permission",
  card: { todo_id: 90, title: "미분류 할일", status: "review", root_id: null, tree_key: null, root_title: null },
};
const savedDecisions = PAYLOAD.decisions.items;
PAYLOAD.decisions.items = [loose];
await manager.refreshPart("decisions");
elements["mgr-decisions"].children[0].listeners.click();
openTab("tree");
one = solo();
assert.equal(one.card.dataset.status, "review", "할일 상태 그대로");
assert.equal(one.card.dataset.waiting, "permission", "세션이 권한을 기다리면 권한 대기가 이긴다");
assert.deepEqual(one.head, ["확인 대기", "#90", "권한 대기"]);
assert.equal(one.title.tag, "button");
assert.equal(one.title.textContent, "미분류 할일");
assert.equal(one.note, "워크스페이스가 없는 할일이라 트리가 없습니다");
openTab("detail");
PAYLOAD.decisions.items = savedDecisions;
await manager.refreshPart("decisions");

// 도구 목록 — 용도 칩(받은 용도만)·'연결됨' 줄(개수만)·줄마다 이름/설명(같은 줄)/용도/제작 주체/상태
const chipTexts = () => elements["mgr-tools-cats"].children.map((chip) => chip.textContent);
const toolNames = () => elements["mgr-tools"].children.map((row) => row.children[0]?.children[0]?.textContent);
assert.deepEqual(chipTexts(), ["전체", "메신저·소통", "업무 문서", "인프라·모니터링", "매니저 명령", "기타"]);
assert.match(elements["mgr-tools-cats"].children[0].className, /\bon\b/);
assert.equal(elements["mgr-tools-count"].textContent, "5");
const connected = elements["mgr-tools-connected"];
assert.equal(connected.hidden, false);
// 글자 동그라미 아이콘 묶음은 없다 — 라벨·개수·확인 시각만
assert.deepEqual(connected.children.map((child) => child.textContent), ["연결됨", "2", "5m 전 확인"], "연결된 외부 도구만 센다");
const toolRows = elements["mgr-tools"].children;
const toolCells = (row) => [row.children[0].children[0].textContent, row.children[0].children[1].textContent,
  ...row.children.slice(1).map((child) => child.textContent)];
assert.deepEqual(toolCells(toolRows[0]), ["Jira·Confluence", "Jira 이슈와 Confluence 페이지 조회·작성", "업무 문서", "외부", "연결됨"]);
assert.deepEqual(toolCells(toolRows[2]), ["AWS CLI", "AWS 리소스 조회", "인프라·모니터링", "외부", "인증 필요"]);
assert.deepEqual(toolCells(toolRows[3]), ["mystery", "설명 없음", "기타", "확인 안 됨"],
  "확인 못 한 것은 확인 안 됨, 설명·제작 주체는 지어내지 않음");
assert.deepEqual(toolCells(toolRows[4]), ["manager.py open", "사용자 PC 에 띄운다", "매니저 명령", "사내", "사용 가능"]);
assert.match(toolRows[4].title, /URL 은 기본 브라우저/, "전문은 줄의 title 로");
assert.equal(toolRows[0].children[0].className, "mgr-tool-main", "이름과 설명이 한 줄 묶음 안에");
assert.match(toolRows[4].children[2].className, /mgr-maker inhouse/);
assert.ok(!toolRows.some((row) => /mgr-ico/.test(row.children[0].className)), "글자 원 아이콘 없음");
// 보기 전용 — 줄에 버튼·클릭 동작이 없다
assert.equal(Object.keys(toolRows[0].listeners).length, 0);
// 칩을 누르면 그 용도만 — 이때 줄의 용도 표시는 빠진다. 다시 전체
elements["mgr-tools-cats"].children[4].listeners.click();
assert.deepEqual(toolNames(), ["manager.py open"]);
assert.deepEqual(toolCells(elements["mgr-tools"].children[0]).slice(2), ["사내", "사용 가능"]);
assert.equal(elements["mgr-tools-count"].textContent, "5", "개수는 전체 그대로");
elements["mgr-tools-cats"].children[0].listeners.click();
assert.equal(toolNames().length, 5);
// 검색 — 이름·설명·출처에서 찾는다. 없으면 '맞는 도구가 없습니다'
const search = elements["mgr-tools-search"];
search.value = "confluence";
search.listeners.input();
assert.deepEqual(toolNames(), ["Jira·Confluence"]);
search.value = "사내";
search.listeners.input();
assert.deepEqual(toolNames(), ["manager.py open"], "제작 주체로도 찾는다");
search.value = "없는도구";
search.listeners.input();
assert.equal(elements["mgr-tools"].children[0].textContent, "맞는 도구가 없습니다");
search.value = "";
search.listeners.input();
assert.equal(toolNames().length, 5);

// 칸마다 10줄씩 페이지로 넘긴다. 칸끼리 페이지가 따로 가고, 폴링으로 다시 그려도 보던 페이지가 남는다
const autoTemplate = PAYLOAD.automations.items[0];
PAYLOAD.automations.items = Array.from({ length: 23 }, (_, index) => ({ ...autoTemplate, name: `자동화 ${index + 1}` }));
PAYLOAD.decisions.items = Array.from({ length: 15 }, (_, index) => ({ ...PAYLOAD.decisions.items[0], id: index + 1 }));
PAYLOAD.helpers = {
  error: null,
  items: [
    {
      session_id: "s-helper-1", name: "보조1 | 일", status: "작업 중", doing: "테스트", percent: 40, moved_at: agoMinutes(1),
      waiting: "permission",
    },
    { name: "보조2 | 결정", status: "결정 대기", doing: "결정 요청", percent: 70, moved_at: agoMinutes(3), waiting: null },
    { name: "보조3 | 쉼", status: "쉼", doing: null, percent: null, moved_at: null, waiting: null },
  ],
};
// 지금은 설정 탭 — 폴링은 그 탭 칸만 받는다. 작업 탭 칸은 탭을 오갈 때 받는다(숨은 판도 그린 것은 남는다)
fetched.length = 0;
await manager.renderManager();
assert.deepEqual([...fetched].sort(), ["automations", "tools"], "폴링도 보이는 탭 칸만");
await manager.selectManagerSubtab("work");
await manager.selectManagerSubtab("setup");
const autoList = () => elements["mgr-automations"].children;
const autoNames = () => autoList().slice(1).map((row) => row.children[1].children[0].textContent);
const pager = (part) => elements[`mgr-${part}-pager`];
// 이전·다음은 아이콘이라 글자가 없고 이름은 title 에 있다
const labels = (part) => pager(part).children.map((button) => button.title || button.textContent);
assert.equal(elements["mgr-automations-count"].textContent, "23", "개수는 전체");
assert.equal(autoList()[0].children[0].textContent, "주기", "페이지마다 머리줄");
assert.equal(autoNames().length, 10);
assert.equal(autoNames()[0], "자동화 1");
assert.equal(pager("automations").hidden, false);
assert.deepEqual(labels("automations"), ["이전", "1", "2", "3", "다음"]);
assert.equal(pager("automations").children[0].disabled, true, "첫 페이지에서 이전은 못 누른다");
assert.match(pager("automations").children[1].className, /\bon\b/);
assert.match(pager("automations").children[0].innerHTML, /<svg/, "이전은 글자 대신 chevron 아이콘");
assert.equal(pager("automations").children[0].textContent, "", "이전 버튼에 글자가 없다");
// 한 페이지로 끝나는 칸은 넘김을 숨긴다
assert.equal(pager("helpers").hidden, true);

// 카드 없는 보조 세션 — 트리 탭에 세션 이름 카드 한 장. 상태 색은 트리 카드 규칙으로 옮긴다
// (작업 중 = 진행 중, 결정 대기 = 진행 중 + 답 대기, 쉼 = 할 일). 세션이 권한을 기다리면 권한 대기
const helperSolo = (index) => {
  elements["mgr-helpers"].children[index].listeners.click();
  openTab("tree");
  const parts = solo();
  openTab("detail");
  return parts;
};
one = helperSolo(0);
assert.equal(one.title.textContent, "보조1 | 일");
// 보조 세션 상세: 사용자 요청 / 지금 하는 일 / 피드백 보내기 / 연결 세션. 피드백 상자는 열 때 그 세션 한 건을 받는다
assert.deepEqual(elements["mgr-decision-body"].children.map((section) => section.children[0].textContent),
  ["사용자 요청", "지금 하는 일", "피드백 보내기", "연결 세션"]);
assert.deepEqual(helperFetched, ["s-helper-1"]);
const feedbackSection = elements["mgr-decision-body"].children[2];
for (let i = 0; !feedbackSection.children[1].children[0]?.className.startsWith("dec-card") && i < 50; i += 1) {
  await new Promise((resolve) => setTimeout(resolve, 0));
}
assert.match(feedbackSection.children[1].children[0].className, /\bhelper-feedback\b/);
assert.equal(one.card.dataset.status, "doing");
assert.equal(one.card.dataset.waiting, "permission");
assert.deepEqual(one.head, ["작업 중", "권한 대기"]);
one = helperSolo(1);
assert.equal(one.card.dataset.status, "doing");
assert.equal(one.card.dataset.waiting, "input");
assert.deepEqual(one.head, ["결정 대기", "답 대기"]);
one = helperSolo(2);
assert.equal(one.card.dataset.status, "todo");
assert.equal(one.card.dataset.waiting, undefined);
assert.deepEqual(one.head, ["쉼"]);
assert.equal(one.note, "대시보드 할일과 연결되지 않은 일입니다");
assert.deepEqual(labels("decisions"), ["이전", "1", "2", "다음"]);

pager("automations").children[3].listeners.click(); // 3쪽
assert.deepEqual(autoNames(), ["자동화 21", "자동화 22", "자동화 23"]);
assert.equal(pager("automations").children.at(-1).disabled, true, "마지막 페이지에서 다음은 못 누른다");
assert.equal(titleText(elements["mgr-decisions"].children[0].children[0].children[0]), "#1 2/3 우선순위 출처", "다른 칸은 그대로");
pager("decisions").children.at(-1).listeners.click(); // 결정 다음
assert.equal(elements["mgr-decisions"].children.length, 5);
assert.equal(autoNames()[0], "자동화 21", "결정 칸을 넘겨도 자동화 칸은 그대로");
pager("automations").children[0].listeners.click(); // 이전 → 2쪽
assert.equal(autoNames()[0], "자동화 11");

// 폴링 재렌더 — 보던 페이지 유지. 줄이 줄어 그 페이지가 사라지면 마지막 페이지로
pager("automations").children[3].listeners.click();
await manager.renderManager();
assert.equal(autoNames()[0], "자동화 21");
PAYLOAD.automations.items = PAYLOAD.automations.items.slice(0, 12);
await manager.renderManager();
assert.deepEqual(autoNames(), ["자동화 11", "자동화 12"]);
assert.deepEqual(labels("automations"), ["이전", "1", "2", "다음"]);

// 도구 목록도 10줄씩 넘긴다 — 분류를 바꾸면 첫 페이지로
const toolTemplate = PAYLOAD.tools.items[4];
PAYLOAD.tools.items = Array.from({ length: 14 }, (_, index) => ({ ...toolTemplate, id: `c${index}`, name: `명령 ${index + 1}` }));
await manager.renderManager();
assert.equal(toolNames().length, 10);
assert.deepEqual(labels("tools"), ["이전", "1", "2", "다음"]);
assert.deepEqual(chipTexts(), ["전체", "매니저 명령"], "받은 목록에 있는 분류만 칩으로");
assert.equal(elements["mgr-tools-connected"].hidden, true, "연결된 외부 도구가 없으면 줄을 숨긴다");
pager("tools").children.at(-1).listeners.click();
assert.deepEqual(toolNames(), ["명령 11", "명령 12", "명령 13", "명령 14"]);
elements["mgr-tools-cats"].children[1].listeners.click();
assert.equal(toolNames()[0], "명령 1");

// 칸 제목 줄 새로고침 — 그 칸만 다시 받는다
const refresh = elements["mgr-decisions-refresh"];
assert.match(refresh.innerHTML, /<svg/, "새로고침은 아이콘 버튼");
PAYLOAD.decisions.items = [{ ...PAYLOAD.decisions.items[0], id: 501, title: "새로 생긴 결정" }];
fetched.length = 0;
let release;
holdFetch = new Promise((resolve) => (release = resolve));
const pending = refresh.listeners.click();
assert.equal(refresh.disabled, true, "받는 동안 버튼이 잠긴다(아이콘이 돈다)");
refresh.listeners.click(); // 받는 중 다시 눌러도 한 번만 부른다
release();
holdFetch = null;
await pending;
assert.deepEqual(fetched, ["decisions"], "다른 칸은 다시 받지 않는다");
assert.equal(refresh.disabled, false);
assert.equal(titleText(elements["mgr-decisions"].children[0].children[0].children[0]), "#501 2/3 새로 생긴 결정");
assert.equal(elements["mgr-decisions-count"].textContent, "1");
// 실패하면 보던 목록은 두고 카드 맨 위에 짧은 오류 한 줄 — 전문은 title
failFetch = true;
await refresh.listeners.click();
failFetch = false;
const [failLine, keptRow] = elements["mgr-decisions"].children;
assert.equal(failLine.className, "mgr-error");
assert.equal(failLine.textContent, "새로고침하지 못했습니다 — 보던 목록을 그대로 둡니다");
assert.match(failLine.title, /서버 응답 없음/);
assert.equal(titleText(keptRow.children[0].children[0]), "#501 2/3 새로 생긴 결정");
assert.equal(elements["mgr-decisions-count"].textContent, "1");
// 다음에 성공하면 오류 줄이 사라진다
await refresh.listeners.click();
assert.notEqual(elements["mgr-decisions"].children[0].className, "mgr-error");

// 진행 단계 — '사용자 요청' 다음에 단계 목록. 멈춘 단계만 강조되고 그 줄에 '넘어가려면'과 답하는 상자가 붙는다.
// 따로 '답하기' 칸은 없다
decisionFetched.length = 0;
await manager.openManagerTask(181);
const stepBody = elements["mgr-decision-body"].children;
assert.deepEqual(stepBody.map((section) => section.children[0].textContent),
  ["사용자 요청", "진행 단계", "지금까지 한 일", "결정할 것"]);
const stepItems = stepBody[1].children[1].children;
assert.deepEqual(stepItems.map((item) => item.className),
  ["prereq-item step-item step-done", "prereq-item step-item step-current stuck", "prereq-item step-item step-todo"]);
assert.deepEqual(stepItems[1].children[0].children.map((kid) => kid.textContent), ["2", "선택지 결정"]);
assert.equal(stepItems[1].children[0].children.length, 2, "멈춘 단계는 칩 없이 주황 강조(stuck)만");
assert.deepEqual(stepItems[1].children[1].children.map((kid) => kid.textContent), ["넘어가려면", "A/B/C 중 하나 고르기 (추천 A)"]);
assert.equal(stepItems[1].children[2].className, "dec-loader", "답하는 상자는 멈춘 단계 줄 바로 아래");
assert.deepEqual(decisionFetched, ["/api/decisions/181"]);
assert.equal(stepItems[0].children.length, 1, "지난 단계에는 넘어가는 조건이 없다");
assert.deepEqual(stepItems[2].children[0].children.map((kid) => kid.textContent), ["3", "PR 작성", "남음"]);
// 권한 대기 팝업 — 결정으로 남은 막힘(223)은 답 칸, 직접 할 일로 남은 막힘은 완료 칸. 트리 없는 카드의 대기 표시는 '권한 대기'
elements["mgr-permissions"].children[0].listeners.click();
assert.equal(headTitle(), "#223 에이전트 크롬에서 OpenSearch Dashboards 로그인해 주기");
assert.ok(elements["mgr-decision-body"].children.some((section) => section.children[0].textContent === "답하기"));

// 단계 행(할일 통합 뒤)의 진행 단계 — 끝난 단계는 줄 안 완료 시각 + 결과 한 줄, 멈춘 단계는 넘어가는 조건
const { stepList, stepMeta } = await import("../static/js/steps.js");
const rowSteps = [
  { id: 301, name: "자료 조사", status: "done", by: "보조2", at: "2026-11-18T05:05:00Z", result: "후보 3개 정리" },
  { id: 302, name: "방식 결정", status: "current", unblock: "A·B 중 고르기", ask: "decision" },
];
const rowList = stepList(rowSteps).children;
assert.equal(rowList[0].children[1].className, "step-meta");
assert.equal(rowList[0].children[1].textContent, "후보 3개 정리", "누가(보조 세션)·시각은 결과 줄에 없다");
const doneHead = rowList[0].children[0].children;
assert.equal(doneHead.at(-1).className, "step-at", "끝난 단계는 칩 대신 완료 시각");
assert.match(doneHead.at(-1).textContent, /^11-18 \d\d:05$/);
assert.equal(rowList[1].children[0].children.length, 2, "멈춘 단계는 칩 없이 번호·이름만(강조는 CSS)");
assert.equal(rowList[1].children[1].className, "step-unblock");
assert.equal(stepMeta({ name: "x", status: "done" }), "", "예전 진행 단계(JSON)에는 줄이 없다");

console.log("ok");
