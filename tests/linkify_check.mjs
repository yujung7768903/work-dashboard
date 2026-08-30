// note 본문에서 무엇을 링크로 볼지 본다. 경계 판정이 틀리면 멀쩡한 낱말이
// 링크가 되거나(출고/몰고) 진짜 경로를 놓친다.
// 실행: node tests/linkify_check.mjs (tests/test_linkify.py 가 부른다)
import assert from "node:assert/strict";

import { linkify } from "../static/js/linkify.js";

const kinds = (text) => linkify(text).map((part) => `${part.type}:${part.value}`);

// 주소는 통째로 한 조각이다 — 주소 안의 /x 가 경로로 또 잡히면 안 된다
assert.deepEqual(kinds("문서는 https://a.co/x/y 참고"), [
  "text:문서는 ",
  "url:https://a.co/x/y",
  "text: 참고",
]);

// 절대경로 두 표기(~ 와 /)를 모두 잡는다
assert.deepEqual(kinds("~/work/a.md 와 /home/ujung/b 를 봐"), [
  "path:~/work/a.md",
  "text: 와 ",
  "path:/home/ujung/b",
  "text: 를 봐",
]);

// 상대경로·낱말 사이 슬래시는 경로가 아니다 (출고/몰고 는 기사 상태다)
assert.deepEqual(kinds("static/js/x.js 의 출고/몰고 처리"), [
  "text:static/js/x.js 의 출고/몰고 처리",
]);

// 문장 끝 부호와 닫는 괄호는 경로 밖이다 — 붙여서 열면 없는 경로가 된다
assert.deepEqual(kinds("(/home/x/y.txt) 끝."), [
  "text:(",
  "path:/home/x/y.txt",
  "text:) 끝.",
]);
assert.deepEqual(kinds("~/a.md."), ["path:~/a.md", "text:."]);

// 비어 있거나 없는 note 도 그냥 빈 목록이다 — 호출부가 따로 막지 않는다
assert.deepEqual(linkify(null), []);
assert.deepEqual(linkify(""), []);

console.log("ok");
