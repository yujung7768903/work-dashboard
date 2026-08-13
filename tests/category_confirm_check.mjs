// 카테고리 삭제 확인 흐름 검증. fetch 를 스텁해 api.js 동작만 본다
import assert from "node:assert";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { bootKorean } from "./i18n_boot.mjs";

const API = pathToFileURL(
  path.join(import.meta.dirname, "..", "static", "js", "api.js")
).href;

const calls = [];
globalThis.fetch = async (url, options) => {
  calls.push(`${options.method} ${url}`);
  if (calls.length === 1) {
    return {
      ok: false,
      status: 409,
      json: async () => ({ error: "세션 1건이 미분류로 바뀝니다. 삭제할까요?", confirm: true }),
    };
  }
  return { ok: true, status: 200, json: async () => ({ deleted: 7 }) };
};

await bootKorean();
const api = await import(API);

// 확인이 필요한 응답은 confirm 플래그를 에러에 실어 호출부로 넘긴다
const needsConfirm = await api.deleteCategory(7).catch((error) => error);
assert.strictEqual(needsConfirm.confirm, true);
assert.match(needsConfirm.message, /삭제할까요/);

// 확인을 받은 재요청은 ?force=1 로 나간다
assert.deepStrictEqual(await api.deleteCategory(7, true), { deleted: 7 });
assert.deepStrictEqual(calls, [
  "DELETE /api/categories/7",
  "DELETE /api/categories/7?force=1",
]);

// 확인과 무관한 실패는 confirm 이 붙지 않아 그대로 에러로 보인다
globalThis.fetch = async () => ({
  ok: false,
  status: 409,
  json: async () => ({ error: "워크스페이스 1건이 남아 있어 삭제할 수 없음" }),
});
const plainFailure = await api.deleteCategory(1).catch((error) => error);
assert.strictEqual(plainFailure.confirm, false);
