// 화면 모듈은 boot.js 가 언어를 정한 뒤에 들어온다 — 여러 모듈이 최상단에서 t() 로 라벨
// 표를 만들기 때문이다. node 체크도 같은 순서를 지켜야 문구가 키가 아니라 한국어로 나온다.
// 체크마다 이 함수를 부른 **뒤에** 검사할 모듈을 await import 한다
import { readFile } from "node:fs/promises";

const KOREAN = new URL("../static/lang/ko.json", import.meta.url);

export async function bootKorean() {
  const korean = JSON.parse(await readFile(KOREAN, "utf8"));
  const i18n = await import("../static/js/i18n.js");
  i18n.useDictionary(korean, {}, "ko");
}
