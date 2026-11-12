// 주기 칸 표기 — stdin 의 [{cycle, expr}] 를 화면과 같은 cycleText 로 옮겨 JSON 배열로 출력한다.
// tests/test_manager_tab.py 가 현재 자동화 전 항목을 넣고 결과를 대조한다
import { readFileSync } from "node:fs";
import { bootKorean } from "./i18n_boot.mjs";

globalThis.document = { getElementById: () => null, createElement: () => ({}) };
await bootKorean();
const { cycleText } = await import("../static/js/manager.js");
const items = JSON.parse(readFileSync(0, "utf8"));
process.stdout.write(JSON.stringify(items.map((item) => cycleText(item.cycle, item.expr))));
