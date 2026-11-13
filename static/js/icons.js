// 화면 여러 곳이 같이 쓰는 아이콘. 다른 모듈을 import 하지 않는다 — 가져다 쓰는 쪽(매니저 탭 등)이
// 보드 모듈의 부작용(문서 이벤트 등록)까지 끌고 오지 않게

// 사이드바 메뉴와 같은 16 격자 · currentColor 스트로크 아이콘. 오른쪽을 가리킨다 —
// 워크트리 커밋 토글은 펼치면 90도, 매니저 탭 '이전' 은 좌우로 뒤집어 쓴다 (CSS)
export const CHEVRON_SVG = `<svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
  <path d="M6 3.5 10.5 8 6 12.5" fill="none" stroke="currentColor"
        stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
</svg>`;

// 새로고침 — 같은 16 격자 스트로크. 매니저 탭 카드 제목 줄 오른쪽 끝, 받는 동안 돈다 (CSS)
export const REFRESH_SVG = `<svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
  <path d="M13 8a5 5 0 1 1-1.46-3.54" fill="none" stroke="currentColor"
        stroke-width="1.5" stroke-linecap="round"/>
  <path d="M13 2.5v2.5h-2.5" fill="none" stroke="currentColor"
        stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
</svg>`;
