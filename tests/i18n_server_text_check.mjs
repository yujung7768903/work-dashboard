// 서버가 한국어로 내려준 문구를 고른 언어로 되짚는지 검증. 건수·이름이 박힌 문장까지
// 옮겨져야 하고(사전에 {값} 자리를 뚫은 틀로 있다), 사전에 없는 문장은 그대로 남아야 한다
import assert from "node:assert";
import { readFile } from "node:fs/promises";

const dictionary = async (code) =>
  JSON.parse(await readFile(new URL(`../static/lang/${code}.json`, import.meta.url), "utf8"));

const english = await dictionary("en");
const korean = await dictionary("ko");
const i18n = await import("../static/js/i18n.js");
i18n.useDictionary(english, {}, "en", korean);

// 자율 수행 tick 사유. 값이 안 박힌 문장이라 통째로 맞아떨어진다
assert.strictEqual(i18n.fromKorean("autorun 이 꺼져 있음"), english["reason.off"]);
assert.strictEqual(i18n.fromKorean("시작 가능"), english["reason.ready"]);

// 워크트리 서버 조작 알림. 주소가 박혀 있어 틀로 되짚는다
assert.strictEqual(
  i18n.fromKorean("실행했습니다 — http://127.0.0.1:9081/"),
  "Started — http://127.0.0.1:9081/"
);
assert.strictEqual(i18n.fromKorean("종료할 서버가 없었습니다"), english["notice.nothingToStop"]);

// 이름·건수가 박힌 오류
assert.strictEqual(
  i18n.fromKorean("'개발' 카테고리가 이미 있습니다"),
  "The category '개발' already exists"
);
assert.strictEqual(
  i18n.fromKorean("할일 3건에서 이 라벨이 떨어집니다. 삭제할까요?"),
  "This label will come off 3 todo(s). Delete it?"
);

// 값 자리에 서버가 끼워 넣은 한국어 라벨도 함께 옮긴다 — 반만 영어면 읽히지 않는다
assert.strictEqual(
  i18n.fromKorean("기준 브랜치는 적용 대상이 아님"),
  `The base branch is not a target for ${english["worktree.apply"]}`
);
assert.strictEqual(
  i18n.fromKorean("메인 체크아웃 에 커밋되지 않은 변경사항이 있습니다"),
  "Main checkout has uncommitted changes"
);

// "git ... 실행 실패" 가 "git {args} 실패" 틀에 먼저 걸리면 안 된다 — 사전에 적은 순서가
// 곧 우선순위라, 좁은 틀이 앞에 와야 한다
assert.strictEqual(
  i18n.fromKorean("git worktree remove /tmp/x 실행 실패: timeout"),
  "Failed to run git worktree remove /tmp/x: timeout"
);

// 사전에 없는 문장은 그대로. 화면에서 문장이 사라지는 것이 못 옮긴 것보다 나쁘다
assert.strictEqual(i18n.fromKorean("여기 없는 문장입니다"), "여기 없는 문장입니다");

// 화면 라벨은 틀로 세우지 않는다 — "{count}개" 같은 짧은 라벨이 서버 문장을 먼저 문다
assert.strictEqual(i18n.fromKorean("3개"), "3개");

// 한국어 화면에서는 되짚을 일이 없다
i18n.useDictionary(english, korean, "ko");
assert.strictEqual(i18n.fromKorean("autorun 이 꺼져 있음"), "autorun 이 꺼져 있음");
