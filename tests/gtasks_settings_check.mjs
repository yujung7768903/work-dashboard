// 설정 탭의 구글 태스크 연동 카드. 브라우저 없이 돌려야 하므로 gtasks.js 가 만지는
// DOM 만 흉내낸다. 확인하는 것: 미연동이면 안내 문구, 켜기 전에 합집합 확인을 거치는지,
// 끄면 카테고리 스위치가 값을 유지한 채 회색으로 잠기는지
// 실행: node tests/gtasks_settings_check.mjs (tests/test_gtasks_settings.py 가 이걸 부른다)
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { bootKorean } from "./i18n_boot.mjs";

const asked = [];
const sent = {};
let panel = {
  state: { enabled: 0, last_sync_at: null, last_error: null },
  connected: false,
  has_client: false,
  client_id: "",
  reason: "연결 안 됨",
  categories: [
    { id: 1, name: "개발", enabled: true, linked: false },
    { id: 2, name: "블로그", enabled: false, linked: false },
  ],
};

globalThis.fetch = async (url, options) => {
  const method = options?.method ?? "GET";
  asked.push(`${method} ${url}`);
  if (options?.body) sent[`${method} ${url}`] = JSON.parse(options.body);
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
      // 합집합 팝업은 사용자가 '진행'을 누른 것으로 본다 (취소는 아래에서 따로 확인).
      // 자격증명 창은 단계를 밟아야 하므로 close() 를 부를 때까지 열어 둔다
      if (this.autoClose) {
        this.returnValue = decision;
        this.listeners.close?.();
      }
    },
    close() {
      this.listeners.close?.();
    },
  };
}

let decision = "go";
const elements = { "gtasks-plan": node() };
elements["gtasks-plan"].autoClose = true;
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

function dialogSwitch() {
  return document.getElementById("gtasks-switch");
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
// hidden 속성만으로는 부족하다 — .switch 에 display 가 걸려 있으면 브라우저 기본
// [hidden] 규칙을 덮어써서 속성이 true 여도 그대로 그려진다. CSS 쪽도 같이 본다
const css = await readFile(new URL("../static/css/app.css", import.meta.url), "utf-8");
assert.ok(
  /\.switch\[hidden\]\s*\{[^}]*display:\s*none/.test(css),
  ".switch[hidden] 에 display:none 이 없다 — hidden=true 여도 화면에는 보인다"
);
// 스피너는 span 이다. inline 이면 width·height 가 무시돼 테두리만 남은 막대가 된다
assert.ok(
  /\.gt-spin\s*\{[^}]*display:\s*inline-block/.test(css),
  ".gt-spin 이 inline-block 이 아니다 — 원이 아니라 막대로 그려진다"
);
// 도는 동안 disabled 기본색(--line)이 걸리면 글자가 면과 같아져 사라진다
assert.ok(
  /button\.busy:disabled\s*\{[^}]*color:/.test(css),
  "button.busy:disabled 에 색이 없다 — 도는 동안 버튼 글자가 사라진다"
);
assert.equal(elements["gtasks-warn"].hidden, false, "사유가 있는데 경고가 안 보인다");
assert.equal(elements["gtasks-reason"].textContent, "연결 안 됨");
assert.equal(switches().length, 0, "미연동인데 카테고리 스위치가 있다");

// ── 2. 연결하기: 안내 → 다음 → 입력 → 저장 ──────────────────────────────────
const connect = flatten(card).find((kid) => kid.textContent === "연결하기");
assert.ok(connect, "연결하기 버튼이 없다");

// elements[] 는 getElementById 로 처음 닿을 때 생긴다 — 직접 꺼내면 undefined 다
const dialog = document.getElementById("gtasks-auth");
const guide = document.getElementById("gtasks-auth-guide");
const form = document.getElementById("gtasks-auth-form");
const pending = connect.listeners.click();
await new Promise((resolve) => setTimeout(resolve, 0));
// 값을 어디서 받는지 먼저 알려준다. 바로 입력창을 띄우면 무엇을 넣을지 모른다
assert.equal(guide.hidden, false, "안내를 건너뛰고 입력창이 떴다");
assert.equal(form.hidden, true);
assert.ok(!asked.includes("POST /api/gtasks-auth"), "안내 단계인데 인증이 나갔다");

elements["gtasks-auth-next"].onclick();
assert.equal(guide.hidden, true);
assert.equal(form.hidden, false, "다음을 눌렀는데 입력창이 안 떴다");
// 이전으로 돌아갈 수 있어야 한다 — 콘솔을 다시 봐야 하는 경우가 많다
elements["gtasks-auth-back"].onclick();
assert.equal(guide.hidden, false);
elements["gtasks-auth-next"].onclick();

elements["gtasks-client-id"].value = "  아이디  ";
elements["gtasks-client-secret"].value = "비밀";
form.onsubmit({ preventDefault() {} });
await pending;
assert.ok(asked.includes("POST /api/gtasks-auth"), asked.join(", "));
assert.deepEqual(sent["POST /api/gtasks-auth"], { client_id: "아이디", client_secret: "비밀" });

// 이미 받아 둔 자격증명이 있으면 다시 묻지 않는다
panel = { ...panel, connected: false, has_client: true, client_id: "아이디" };
await gtasks.renderGtasks();
dialog.shown = false;
const reconnect = flatten(elements["gtasks-card"]).find((kid) => kid.textContent === "연결하기");
await reconnect.listeners.click();
assert.equal(dialog.shown, false, "자격증명이 있는데 입력창을 또 띄웠다");

panel = { ...panel, connected: true, reason: null };
await gtasks.renderGtasks();
const setup = flatten(elements["gtasks-card"]).find((kid) => kid.textContent === "카테고리 맞추기");
assert.ok(setup, "연결됐는데 카테고리 맞추기 버튼이 없다");
// 맞추기 전에는 켤 것이 없다. 스위치가 보이면 누를 수 없는 것을 누르게 된다
assert.equal(dialogSwitch().hidden, true, "카테고리를 맞추기 전인데 스위치가 보인다");

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
const master = document.getElementById("gtasks-toggle");
master.checked = false;
await master.listeners.change();
assert.ok(asked.includes("PATCH /api/gtasks"), asked.join(", "));
// 다시 켤 때는 합집합 팝업을 띄우지 않는다 — 확인은 최초 맞추기 한 번뿐이다
const beforeOn = asked.length;
master.checked = true;
await master.listeners.change();
assert.ok(
  !asked.slice(beforeOn).includes("POST /api/gtasks-plan"),
  "이미 맞춘 뒤인데 켤 때 또 확인을 물었다"
);
master.checked = false;
await master.listeners.change();
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
// 취소하고 돌아온 자리에서 버튼이 죽어 있으면 다시 시도할 길이 없다
assert.equal(again.disabled, false, "취소했더니 버튼이 잠긴 채로 남았다");

console.log("ok");
