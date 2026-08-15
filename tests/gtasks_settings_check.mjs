// 설정 탭의 구글 태스크 연동 카드. 브라우저 없이 돌려야 하므로 gtasks.js 가 만지는
// DOM 만 흉내낸다. 확인하는 것: 미연동이면 안내 문구, 켜기 전에 합집합 확인을 거치는지,
// 끄면 카테고리 스위치가 값을 유지한 채 회색으로 잠기는지
// 실행: node tests/gtasks_settings_check.mjs (tests/test_gtasks_settings.py 가 이걸 부른다)
import assert from "node:assert/strict";
import { bootKorean } from "./i18n_boot.mjs";

const asked = [];
let panel = {
  state: { enabled: 0, last_sync_at: null, last_error: null },
  connected: false,
  reason: "연결 안 됨",
  categories: [
    { id: 1, name: "개발", enabled: true, linked: false },
    { id: 2, name: "블로그", enabled: false, linked: false },
  ],
};

globalThis.fetch = async (url, options) => {
  const method = options?.method ?? "GET";
  asked.push(`${method} ${url}`);
  if (url === "/api/gtasks-plan" && method === "POST") {
    return {
      ok: true,
      status: 200,
      json: async () => ({
        local: ["개발", "블로그"],
        remote: ["운동"],
        union: ["개발", "블로그", "운동"],
        create_local: ["운동"],
        create_remote: ["개발", "블로그"],
      }),
    };
  }
  if (url === "/api/gtasks-setup" && method === "POST") {
    panel = {
      state: { enabled: 1, last_sync_at: null, last_error: null },
      connected: true,
      reason: null,
      categories: [
        { id: 1, name: "개발", enabled: true, linked: true },
        { id: 2, name: "블로그", enabled: false, linked: true },
        { id: 3, name: "운동", enabled: true, linked: true },
      ],
    };
    return { ok: true, status: 200, json: async () => ({ result: {}, panel }) };
  }
  if (url === "/api/gtasks" && method === "PATCH") {
    panel = { ...panel, state: { ...panel.state, enabled: JSON.parse(options.body).enabled ? 1 : 0 } };
  }
  if (url.startsWith("/api/gtasks-categories/") && method === "PATCH") {
    const id = Number(url.split("/").pop());
    const enabled = JSON.parse(options.body).enabled;
    panel = {
      ...panel,
      categories: panel.categories.map((row) => (row.id === id ? { ...row, enabled } : row)),
    };
  }
  return { ok: true, status: 200, json: async () => panel };
};

function node(tag = "div") {
  return {
    tag,
    textContent: "",
    className: "",
    value: "",
    type: "",
    checked: false,
    disabled: false,
    hidden: false,
    returnValue: "",
    children: [],
    // 진짜 DOM 은 innerHTML="" 로 자식이 사라진다. 안 비우면 다시 그린 뒤에도
    // 옛 줄이 남아 '꺼져도 안 잠긴다' 같은 거짓 실패가 난다
    set innerHTML(_value) {
      this.children = [];
    },
    get innerHTML() {
      return "";
    },
    listeners: {},
    classList: {
      names: new Set(),
      toggle(name, on) {
        if (on) this.names.add(name);
        else this.names.delete(name);
      },
      add(name) {
        this.names.add(name);
      },
      remove(name) {
        this.names.delete(name);
      },
      contains(name) {
        return this.names.has(name);
      },
    },
    append(...kids) {
      this.children.push(...kids);
    },
    appendChild(kid) {
      this.children.push(kid);
      return kid;
    },
    remove() {},
    addEventListener(type, handler) {
      this.listeners[type] = handler;
    },
    showModal() {
      this.shown = true;
      // 사용자가 '진행'을 누른 것으로 본다 — 취소 경로는 아래에서 따로 확인한다
      this.returnValue = decision;
      this.listeners.close?.();
    },
  };
}

let decision = "go";
const elements = {};
globalThis.document = {
  getElementById: (id) => (elements[id] ??= node()),
  createElement: (tag) => node(tag),
};

function flatten(root) {
  return root.children.flatMap((kid) => [kid, ...flatten(kid)]);
}

function switches() {
  return flatten(elements["gtasks-card"]).filter((kid) => kid.type === "checkbox");
}

await bootKorean();
const gtasks = await import("../static/js/gtasks.js");

// ── 1. 미연동: 빈 카드가 아니라 무엇을 할 수 있는지 알린다 ──────────────────
await gtasks.renderGtasks();
const card = elements["gtasks-card"];
const intro = flatten(card).find((kid) => kid.className === "gt-empty");
assert.ok(intro, "미연동인데 안내 문구가 없다");
assert.equal(
  intro.textContent,
  "구글 태스크와 연동하면, 이 곳에서 연동할 카테고리를 관리할 수 있습니다."
);
assert.equal(elements["gtasks-switch"].hidden, true, "미연동인데 스위치가 보인다");
assert.equal(elements["gtasks-warn"].hidden, false, "사유가 있는데 경고가 안 보인다");
assert.equal(elements["gtasks-reason"].textContent, "연결 안 됨");
assert.equal(switches().length, 0, "미연동인데 카테고리 스위치가 있다");

// ── 2. 켜기: 바로 동기화하지 않고 합집합 확인을 거친다 ──────────────────────
const connect = flatten(card).find((kid) => kid.textContent === "연결하기");
assert.ok(connect, "연결하기 버튼이 없다");

panel = { ...panel, connected: true, reason: null };
await gtasks.renderGtasks();
const setup = flatten(elements["gtasks-card"]).find((kid) => kid.textContent === "카테고리 맞추기");
assert.ok(setup, "연결됐는데 카테고리 맞추기 버튼이 없다");

await setup.listeners.click();
assert.ok(asked.includes("POST /api/gtasks-plan"), asked.join(", "));
assert.equal(elements["gtasks-plan-union"].textContent, "개발, 블로그, 운동");
assert.ok(asked.includes("POST /api/gtasks-setup"), "확인했는데 적용이 안 나갔다");
// 카테고리만 맞추고 멈춘다 — 할일 동기화는 사용자가 따로 눌러야 한다
assert.ok(!asked.includes("POST /api/gtasks-sync"), "확인 직후에 동기화까지 돌았다");

// ── 3. 카테고리별 스위치 ────────────────────────────────────────────────────
const rows = switches();
assert.equal(rows.length, 3, "카테고리 스위치 수가 다르다");
assert.deepEqual(rows.map((box) => box.checked), [true, false, true]);
assert.deepEqual(rows.map((box) => box.disabled), [false, false, false]);

rows[1].checked = true;
await rows[1].listeners.change();
assert.ok(asked.includes("PATCH /api/gtasks-categories/2"), asked.join(", "));

// ── 4. 끄면 값은 그대로 두고 잠근다 ─────────────────────────────────────────
const master = elements["gtasks-toggle"];
master.checked = false;
await master.listeners.change();
assert.ok(asked.includes("PATCH /api/gtasks"), asked.join(", "));
const locked = switches();
assert.deepEqual(locked.map((box) => box.disabled), [true, true, true], "꺼졌는데 안 잠겼다");
assert.deepEqual(locked.map((box) => box.checked), [true, true, true], "꺼지면서 값이 바뀌었다");
assert.equal(elements["gtasks-card"].classList.contains("off"), true, "회색 처리가 안 됐다");

// ── 5. 확인 팝업에서 취소하면 아무것도 안 나간다 ────────────────────────────
decision = "cancel";
const before = asked.length;
panel = { ...panel, categories: panel.categories.map((row) => ({ ...row, linked: false })) };
await gtasks.renderGtasks();
const again = flatten(elements["gtasks-card"]).find((kid) => kid.textContent === "카테고리 맞추기");
await again.listeners.click();
assert.ok(
  !asked.slice(before).includes("POST /api/gtasks-setup"),
  "취소했는데 적용이 나갔다"
);

console.log("ok");
