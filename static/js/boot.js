// 진입점. 언어를 확정한 뒤에야 화면 모듈을 들인다 — 여러 모듈이 최상단에서 t() 로 라벨 표를
// 만들기 때문에 순서가 뒤집히면 그 상수들만 한국어로 남는다
import { init } from "./i18n.js";

await init();
await import("./main.js");
