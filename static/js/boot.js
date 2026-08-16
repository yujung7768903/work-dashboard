// 진입점. 언어를 확정한 뒤에야 화면 모듈을 들인다 — 여러 모듈이 최상단에서 t() 로 라벨 표를
// 만들기 때문에 순서가 뒤집히면 그 상수들만 한국어로 남는다
import { init } from "./i18n.js";

await init();
await import("./main.js");

// 밝기·언어 메뉴는 탭 밖(상단바)이라 탭을 그릴 때마다가 아니라 여기서 한 번만 그린다
const { renderThemeMenu } = await import("./theme.js");
renderThemeMenu();
const { renderLanguageMenu } = await import("./language.js");
renderLanguageMenu();

// 열 수·레일 접힘도 탭 밖이라 한 번만. 들이는 것으로 저장해 둔 값이 화면에 붙는다
await import("./layout.js");
