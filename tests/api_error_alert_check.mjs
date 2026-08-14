// 실패한 변경 요청이 alert 으로 보이는지 검증. fetch·alert 을 스텁해 api.js 동작만 본다
import assert from "node:assert";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { bootKorean } from "./i18n_boot.mjs";

const API = pathToFileURL(
  path.join(import.meta.dirname, "..", "static", "js", "api.js")
).href;

const alerts = [];
globalThis.alert = (message) => alerts.push(message);

await bootKorean();
const api = await import(API);

// 변경 요청 실패는 창으로 알린다 — 화면이 그대로면 사용자가 실패를 모른다
globalThis.fetch = async () => ({
  ok: false,
  status: 409,
  json: async () => ({ error: "자율 수행 검토 대기 중입니다. 자율 수행 패널에서 확인해 주세요" }),
});
const failed = await api.updateTodo(39, { status: "done" }).catch((error) => error);
assert.match(failed.message, /검토 대기 중입니다/);
assert.deepStrictEqual(alerts, [failed.message]);

// 확인을 요구하는 응답은 호출부가 confirm 으로 되묻는다. 여기서 또 띄우면 창이 두 번
globalThis.fetch = async () => ({
  ok: false,
  status: 409,
  json: async () => ({ error: "세션 1건이 미분류로 바뀝니다. 삭제할까요?", confirm: true }),
});
await api.deleteCategory(7).catch(() => {});
assert.strictEqual(alerts.length, 1);

// 조회 실패는 조용히 — 목록 폴링이 실패할 때마다 창이 뜨면 화면을 못 쓴다
globalThis.fetch = async () => ({
  ok: false,
  status: 500,
  json: async () => ({ error: "서버 오류" }),
});
await api.getTree("category").catch(() => {});
assert.strictEqual(alerts.length, 1);
