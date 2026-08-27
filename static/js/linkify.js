// note 본문에서 URL·절대경로만 골라내 조각으로 쪼갠다. DOM 은 만들지 않는다 —
// 경계 판정(어디까지가 경로인가)이 이 기능에서 유일하게 틀리기 쉬운 곳이라
// 순수 함수로 떼어 node 로 바로 검증한다 (tests/linkify_check.mjs)

// 경로 앞은 공백·여는 괄호·따옴표·줄머리만 허용한다 — 그래야 "출고/몰고" 나
// "static/js/x.js" 처럼 낱말 중간의 슬래시가 경로로 잡히지 않는다.
// ponytail: 윈도우 표기(C:\...)는 안 본다. WSL 안에서 쓰는 경로는 전부 posix 표기다
const URL_PART = String.raw`https?://[^\s<>"'\`)\]]+`;
const PATH_PART = String.raw`(?<![^\s(\[{'"])~?(?:/[^\s<>"'\`)\]]+)+/?`;
const TOKEN = new RegExp(`(${URL_PART})|(${PATH_PART})`, "g");
// 문장 끝에 붙은 부호는 주소·경로의 일부가 아니다 ("~/a.md." 의 마지막 점)
const TRAILING = /[.,;:!?]+$/;

/** 글 한 덩어리를 [{type: "text"|"url"|"path", value}] 로 쪼갠다 */
export function linkify(text) {
  const source = String(text ?? "");
  const parts = [];
  let cursor = 0;
  for (const match of source.matchAll(TOKEN)) {
    const value = match[0].replace(TRAILING, "");
    if (!value) continue;
    if (match.index > cursor) {
      parts.push({ type: "text", value: source.slice(cursor, match.index) });
    }
    parts.push({ type: match[1] ? "url" : "path", value });
    cursor = match.index + value.length;
  }
  if (cursor < source.length) parts.push({ type: "text", value: source.slice(cursor) });
  return parts;
}
