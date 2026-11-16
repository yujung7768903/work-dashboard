// 세션 결과물 카드의 내용 — 종류별 로고·이름·제목·보조 줄·누르면 할 일. 트리 Map 카드(tree-map.js)와
// 목록 줄(tree.js)이 같이 쓴다. 로고는 인라인 SVG 다 — 외부 파비콘을 불러오지 않는다(오프라인·추적).
// 서버가 주는 결과 하나: { node_id, ref, doc_kind, label, title, url, actions('생성·수정'), path, missing }
import { t } from "./i18n.js";

const SVG_NS = "http://www.w3.org/2000/svg";
export const FILE = "file";

// 사전 키를 글자로 조립하지 않는다 — 안 쓰는 키 검사(tests/test_language.py)가 t("…") 호출에서 키를 찾는다
const KIND_LABEL = {
  confluence: () => t("tree.resultKind.confluence"),
  jira: () => t("tree.resultKind.jira"),
  pr: () => t("tree.resultKind.pr"),
  artifact: () => t("tree.resultKind.artifact"),
  site: () => t("tree.resultKind.site"),
  file: () => t("tree.resultKind.file"),
};
// 서버는 동작을 한국어 낱말로 저장한다(app/constants.py RESULT_ACTIONS). 화면 언어로 바꿔 보인다
const ACTION_LABEL = {
  생성: () => t("tree.resultAction.create"),
  수정: () => t("tree.resultAction.edit"),
  댓글: () => t("tree.resultAction.comment"),
  발행: () => t("tree.resultAction.publish"),
  보고: () => t("tree.resultAction.report"),
};

// 로고 모양. viewBox 하나에 path 여럿 — fill 이 있으면 채우고, 없으면 currentColor 선으로 그린다.
// Jira·Confluence 는 브랜드 색을 그대로 둔다(어두운 화면에서도 읽힌다). GitHub 는 글자색을 따른다
const LOGOS = {
  confluence: {
    box: "0 0 24 24",
    paths: [
      {
        fill: "#1868DB",
        d: "M.87 18.257c-.248.382-.53.875-.763 1.245a.764.764 0 0 0 .255 1.04l4.965 3.054a.764.764 0 0 0 1.058-.26c.199-.332.454-.763.733-1.221 1.967-3.247 3.945-2.853 7.508-1.146l4.957 2.337a.764.764 0 0 0 1.028-.382l2.364-5.346a.764.764 0 0 0-.382-1 599.851 599.851 0 0 1-4.965-2.361C10.911 10.97 5.224 11.185.87 18.257z",
      },
      {
        fill: "#2684FF",
        d: "M23.131 5.743c.249-.405.531-.875.764-1.25a.764.764 0 0 0-.256-1.034L18.675.404a.764.764 0 0 0-1.058.26c-.195.335-.451.763-.734 1.225-1.966 3.246-3.945 2.85-7.508 1.146L4.437.694a.764.764 0 0 0-1.027.382L1.046 6.422a.764.764 0 0 0 .382 1c1.039.49 3.105 1.467 4.965 2.361 6.698 3.246 12.392 3.029 16.738-4.04z",
      },
    ],
  },
  jira: {
    box: "0 0 24 24",
    paths: [
      {
        fill: "#2684FF",
        d: "M23.013 0H11.455a5.215 5.215 0 0 0 5.215 5.215h2.129v2.057A5.215 5.215 0 0 0 24 12.483V1.005A1.001 1.001 0 0 0 23.013 0z",
      },
      {
        fill: "#1868DB",
        d: "M17.294 5.757H5.736a5.215 5.215 0 0 0 5.215 5.214h2.129v2.058a5.218 5.218 0 0 0 5.215 5.214V6.758a1.001 1.001 0 0 0-1.001-1.001z",
      },
      {
        fill: "#0052CC",
        d: "M11.571 11.513H0a5.218 5.218 0 0 0 5.232 5.215h2.13v2.057A5.215 5.215 0 0 0 12.575 24V12.518a1.005 1.005 0 0 0-1.005-1.005z",
      },
    ],
  },
  pr: {
    box: "0 0 16 16",
    paths: [
      {
        fill: "currentColor",
        d: "M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0 0 16 8c0-4.42-3.58-8-8-8z",
      },
    ],
  },
  // 아티팩트: 창 하나 + 코드 괄호. 색은 CSS(--result-artifact)
  artifact: {
    box: "0 0 16 16",
    paths: [{ d: "M2.5 3.5h11v9h-11zM2.5 6h11M6.5 8l-1.5 1.25 1.5 1.25M9.5 8l1.5 1.25-1.5 1.25" }],
  },
  // 사이트: 지구본
  site: {
    box: "0 0 16 16",
    paths: [
      {
        d: "M8 2.5a5.5 5.5 0 1 0 0 11 5.5 5.5 0 1 0 0-11zM2.5 8h11M8 2.5c-1.7 1.5-2.5 3.3-2.5 5.5s.8 4 2.5 5.5M8 2.5c1.7 1.5 2.5 3.3 2.5 5.5s-.8 4-2.5 5.5",
      },
    ],
  },
  // 파일: 모서리 접힌 문서
  file: {
    box: "0 0 16 16",
    paths: [{ d: "M4 2.5h5l3 3v8H4zM9 2.5v3h3M6 8.5h4M6 10.5h4" }],
  },
};

/**
 * 결과 하나를 그릴 내용. DOM 을 모른다 — node 로 바로 검사한다(tests/result_card_check.mjs)
 * href: 새 탭으로 열 주소(파일이 아닐 때) · folder: 폴더 열기에 보낼 노드 id(파일일 때)
 */
export function resultView(result) {
  const kind = result.doc_kind;
  const label = result.label || "";
  // 한 줄(목록)은 '키 제목' 그대로, 카드는 제목을 사람 말로 두고 키(muni#54·PFD-6528)를 보조 줄로 내린다 —
  // 카드 제목 두 줄이 키에 먹히지 않게
  const line = result.title || label;
  const keyed = Boolean(label) && line.startsWith(`${label} `);
  const title = keyed ? line.slice(label.length + 1) : line;
  const actions = (result.actions || "")
    .split("·")
    .filter(Boolean)
    .map((action) => ACTION_LABEL[action]?.() ?? action)
    .join(" · ");
  const isFile = kind === FILE;
  // 보조 줄 — 제목만으로 무엇·어디인지 안 읽히는 것만. 파일은 담긴 폴더, PR·Jira 는 키.
  // Confluence 페이지 번호·아티팩트 id 는 읽어도 뜻이 없어 비운다. 사이트는 주소가 곧 제목이다
  const sub = isFile ? folderOf(result.path) : keyed ? label : "";
  const kindLabel = KIND_LABEL[kind]?.() ?? kind;
  const hint = isFile ? (result.missing ? t("tree.resultMissing") : t("tree.resultFolder")) : t("tree.resultOpen");
  return {
    kind,
    kindLabel,
    title,
    line,
    actions,
    sub,
    href: isFile ? null : result.url || null,
    folder: isFile ? result.node_id : null,
    missing: Boolean(result.missing),
    tip: [line, isFile ? result.path : result.url, hint].filter(Boolean).join("\n"),
  };
}

/** 종류 로고 SVG 요소. 모르는 종류면 파일 모양 */
export function resultLogo(kind) {
  const logo = LOGOS[kind] ?? LOGOS.file;
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("viewBox", logo.box);
  svg.setAttribute("width", "14");
  svg.setAttribute("height", "14");
  svg.setAttribute("aria-hidden", "true");
  svg.classList.add("tm-result-logo");
  logo.paths.forEach(({ d, fill }) => {
    const path = document.createElementNS(SVG_NS, "path");
    path.setAttribute("d", d);
    if (fill) {
      path.setAttribute("fill", fill);
    } else {
      path.setAttribute("fill", "none");
      path.setAttribute("stroke", "currentColor");
      path.setAttribute("stroke-width", "1.4");
      path.setAttribute("stroke-linecap", "round");
      path.setAttribute("stroke-linejoin", "round");
    }
    svg.appendChild(path);
  });
  return svg;
}

// 홈 아래 경로는 ~ 로 줄인다 — 카드 한 줄에 폴더가 읽히게
function folderOf(path) {
  if (!path) return "";
  const folder = path.replace(/\/[^/]*$/, "") || "/";
  return folder.replace(/^\/home\/[^/]+/, "~");
}
