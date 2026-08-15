// 화면 언어. 문구는 코드에 두지 않고 static/lang/<코드>.json 에 키-값으로 모아 둔다.
// 코드는 t("board.nextNone") 처럼 키만 부르고, 어느 언어를 읽을지는 여기서 정한다.
// 영어를 항상 깔고 고른 언어를 그 위에 덮는다 — 번역이 빠진 키는 영어로 뜬다.
// 화면에 키 문자열("board.nextNone")이 그대로 보이는 일은 없어야 하고, 공개로 여는
// 대시보드라 못 읽는 자리로 떨어지면 안 되기 때문이다
export const LANGUAGES = [
  { code: "en", label: "English" },
  { code: "ko", label: "한국어" },
  { code: "ja", label: "日本語" },
  { code: "zh", label: "中文" },
];

const FALLBACK_LANGUAGE = "en";
// 서버가 오류를 한국어로 내려주므로, 그 문장을 키로 되짚을 때만 이 사전이 필요하다
const SERVER_LANGUAGE = "ko";
const DICTIONARY_PATH = (code) => `/lang/${code}.json`;
// 텍스트가 아니라 속성에 들어가는 문구. 텍스트가 없는 input 은 이쪽만 바뀐다
const ATTRIBUTES = [
  ["placeholder", "data-i18n-placeholder"],
  ["title", "data-i18n-title"],
  ["aria-label", "data-i18n-aria-label"],
];
const TEXT_NODE = 3;

let dictionary = {};
let fallback = {};
let current = FALLBACK_LANGUAGE;

/** 키를 지금 언어의 문구로. {이름} 자리는 params 로 채운다 */
export function t(key, params) {
  const template = dictionary[key] ?? fallback[key] ?? key;
  if (!params) return template;
  return template.replace(/\{(\w+)\}/g, (whole, name) =>
    name in params ? params[name] : whole
  );
}

export function language() {
  return current;
}

/** 사전을 직접 넣는다. init() 과 node 체크(tests/i18n_boot.mjs)가 같은 문으로 들어온다 */
export function useDictionary(base, chosen = {}, code = FALLBACK_LANGUAGE) {
  fallback = base;
  dictionary = chosen;
  current = code;
  byKorean = null;
}

// 첫 렌더 전에 한 번(boot.js). 이게 끝난 뒤에 화면 모듈을 들여야 모듈 최상단에서
// t() 로 만드는 상수(배지·라벨 표)까지 번역된다
export async function init() {
  const code = await fetchLanguage();
  const [base, chosen] = await Promise.all([
    loadDictionary(FALLBACK_LANGUAGE),
    code === FALLBACK_LANGUAGE ? Promise.resolve({}) : loadDictionary(code),
  ]);
  useDictionary(base, chosen, code);
  document.documentElement.lang = current;
  document.title = t("app.title");
  translateStatic(document);
}

async function fetchLanguage() {
  // 설정을 못 읽어도 화면은 떠야 한다 — 폴백 언어로 떨어진다
  try {
    const response = await fetch("/api/settings");
    const payload = await response.json();
    const known = LANGUAGES.some((item) => item.code === payload?.language);
    return known ? payload.language : FALLBACK_LANGUAGE;
  } catch {
    return FALLBACK_LANGUAGE;
  }
}

async function loadDictionary(code) {
  try {
    const response = await fetch(DICTIONARY_PATH(code));
    return await response.json();
  } catch {
    return {};
  }
}

// 한국어 원문 → 키. 서버 오류 문구를 옮길 때만 쓴다(api.js). 사전을 뒤집어 만들므로
// 문구 목록이 두 벌이 되지 않는다. 오류가 실제로 났을 때 한 번만 받아 온다 —
// 평소 화면에는 한국어 사전이 필요 없다
let byKorean = null;

/** 서버가 한국어로 내려준 문구를 지금 언어로. 사전에 없는 문장은 그대로 둔다 */
export async function fromKorean(text) {
  if (current === SERVER_LANGUAGE) return text;
  if (!byKorean) {
    const korean = await loadDictionary(SERVER_LANGUAGE);
    byKorean = {};
    Object.entries(korean).forEach(([key, value]) => {
      byKorean[value] = key;
    });
  }
  const key = byKorean[text];
  return key ? t(key) : text;
}

// index.html 의 data-i18n. 아이콘 svg 를 지우지 않으려고 텍스트 노드만 건드리고,
// 텍스트 노드가 없으면(아이콘만 있는 버튼) 뒤에 하나 붙인다
function translateStatic(root) {
  root.querySelectorAll("[data-i18n]").forEach((element) => {
    setText(element, t(element.dataset.i18n));
  });
  ATTRIBUTES.forEach(([name, marker]) => {
    root.querySelectorAll(`[${marker}]`).forEach((element) => {
      element.setAttribute(name, t(element.getAttribute(marker)));
    });
  });
}

function setText(element, text) {
  const node = Array.from(element.childNodes).find(
    (child) => child.nodeType === TEXT_NODE && child.textContent.trim()
  );
  if (node) node.textContent = text;
  else element.appendChild(document.createTextNode(text));
}
