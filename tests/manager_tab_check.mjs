// 매니저 탭 — 주기 구조를 사람 말로 옮기고, 칸을 한 줄에 하나씩 그리며, 한 칸이 실패해도
// 나머지는 그리는지 본다. 하위 탭(작업·설정)은 보이는 탭의 칸만 받는다. 실행: node tests/manager_tab_check.mjs (tests/test_manager_tab.py 가 부른다)
import assert from "node:assert/strict";
import { bootKorean } from "./i18n_boot.mjs";

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
        card: { todo_id: 355, title: "트리 메뉴 추가", status: "doing", workspace_id: 3,
          workspace_name: "작업 대시보드", category_color: "#4a5ae8" },
      },
    ],
  },
};
// 새로고침 검사용 — 부른 칸을 적고, 켜 두면 실패한다
const fetched = [];
let failFetch = false;
let holdFetch = null;
globalThis.fetch = async (url) => {
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
assert.deepEqual([...fetched].sort(), ["confirms", "decisions", "helpers"], "작업 탭 칸만 받는다");
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

// 결정에도 연결 세션 칸 — 이름이 없으면 세션 id 앞 8자리. 마지막 답은 결정할 것 쪽에만
assert.equal(body[3].children[0].textContent, "연결 세션");
assert.equal(sectionText(body[3]), "연결 세션|s1");
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
assert.equal(one.card.style.height, "116px");
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

// 완료 확인 대기 — 결정 대기와 같은 줄 모양, 같은 팝업. 우선순위가 없으면 보드처럼 '-'
const confirmRows = elements["mgr-confirms"].children;
assert.equal(elements["mgr-confirms-count"].textContent, "2");
assert.deepEqual(texts(confirmRows[0]), ["#61 - 보조 한도", "", "확인 대기", "1h 전"]);
// 트리 카드에 붙은 일은 줄 제목이 카드 기준 — 트리 칩 + 카드 번호·제목. 확인할 일은 아랫줄로
assert.deepEqual(texts(confirmRows[1]), ["작업 대시보드 #355 트리 메뉴 추가", "#62 2/3 블로그 글 반영", "확인 대기", "5m 전"]);
const treeChip = confirmRows[1].children[0].children[0].children[0];
assert.equal(treeChip.className, "mgr-tree-chip");
assert.equal(treeChip.title, "트리: 작업 대시보드");
// 팝업: 사용자 요청 / 끝낸 내용 / 작업 사항 / 다음 단계 / 산출물(있을 때만) / 연결 세션(이름·마지막 답)
confirmRows[1].listeners.click();
assert.equal(headTitle(), "#62 블로그 글 반영");
const confirmBody = elements["mgr-decision-body"].children;
assert.deepEqual(confirmBody.map((section) => section.children[0].textContent),
  ["사용자 요청", "끝낸 내용", "작업 사항", "다음 단계", "산출물", "연결 세션"]);
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
assert.match(sectionText(confirmBody[2]), /표 너비 수정/);
assert.equal(sectionText(confirmBody[3]), "다음 단계|문체 확인");
// 산출물 URL 은 새 탭 링크
const outputLink = confirmBody[4].children[1].children[0];
assert.equal(outputLink.href, "https://github.com/x/y/pull/12");
assert.equal(outputLink.target, "_blank");
assert.match(sectionText(confirmBody[5]), /^연결 세션\|보조2 \| 블로그\|연결 세션의 마지막 답 \(끝부분\)\|…\n끝났어\.$/);
// 비어 있는 칸은 지어내지 않고 '기록 없음', 산출물·연결 세션은 없으면 칸째 뺀다.
// 세션 없이 들어온 일은 사용자 요청 자리에 '세션 없음' 과 출처
confirmRows[0].listeners.click();
const bareBody = elements["mgr-decision-body"].children;
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
  card: { todo_id: 90, title: "미분류 할일", status: "review", workspace_id: null, workspace_name: null },
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
    { name: "보조1 | 일", status: "작업 중", doing: "테스트", percent: 40, moved_at: agoMinutes(1), waiting: "permission" },
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

console.log("ok");
