// 결과물 카드 내용 검사 — 종류 이름·동작이 화면 언어로, 카드 제목은 사람 말이고 키는 보조 줄로,
// 파일만 주소 대신 폴더 열기(노드 id)로 연다.
// 실행: node tests/result_card_check.mjs (tests/test_result_card.py 가 부른다)
import assert from "node:assert/strict";
import { bootKorean } from "./i18n_boot.mjs";

await bootKorean();
const { resultView } = await import("../static/js/result-card.js");

{
  const view = resultView({
    node_id: 7, doc_kind: "pr", label: "muni#69", title: "muni#69 로그 조회에 KT 더하기",
    url: "https://github.com/hkilbo/muni/pull/69", actions: "생성",
  });
  assert.equal(view.kindLabel, "PR");
  assert.equal(view.title, "로그 조회에 KT 더하기", "카드 제목은 키를 뗀 사람 말");
  assert.equal(view.line, "muni#69 로그 조회에 KT 더하기", "목록 한 줄은 키째");
  assert.equal(view.sub, "muni#69");
  assert.equal(view.href, "https://github.com/hkilbo/muni/pull/69");
  assert.equal(view.folder, null);
  assert.equal(view.actions, "생성");
}

{
  // 요약을 모르는 Jira 는 키가 곧 제목이고 보조 줄은 비운다. 동작은 합친 순서대로
  const view = resultView({ node_id: 8, doc_kind: "jira", label: "PFD-6517", title: null, url: "https://x/browse/PFD-6517", actions: "수정·댓글" });
  assert.equal(view.title, "PFD-6517");
  assert.equal(view.sub, "");
  assert.equal(view.actions, "수정 · 댓글");
}

{
  // Confluence 페이지 번호·아티팩트 id 는 보조 줄에 안 쓴다
  const page = resultView({ node_id: 9, doc_kind: "confluence", label: "Confluence 7316537432", title: "dev 취약점 점검 결과", url: "https://x", actions: "수정" });
  assert.equal(page.kindLabel, "Confluence");
  assert.equal(page.sub, "");
  const artifact = resultView({ node_id: 10, doc_kind: "artifact", label: "artifact DRkobpKn", title: "대나무숲", url: "https://claude.ai/artifact/DRkobpKn43HNpdMgoGdaae", actions: "발행" });
  assert.equal(artifact.kindLabel, "아티팩트");
  assert.equal(artifact.actions, "발행");
  assert.equal(artifact.sub, "");
}

{
  // 파일: 주소가 없고 폴더 열기에 노드 id 만 넘긴다. 홈은 ~ 로 줄인 폴더가 보조 줄
  const view = resultView({
    node_id: 11, doc_kind: "file", label: "report.md", title: null, url: null, actions: "보고",
    path: "/home/ujung/work/vuln-scan/report.md", missing: false,
  });
  assert.equal(view.kindLabel, "파일");
  assert.equal(view.href, null);
  assert.equal(view.folder, 11);
  assert.equal(view.sub, "~/work/vuln-scan");
  assert.match(view.tip, /탐색기로 엽니다/);
  const gone = resultView({ node_id: 12, doc_kind: "file", label: "a.md", path: "/x/a.md", missing: true });
  assert.equal(gone.missing, true);
  assert.match(gone.tip, /파일이 없습니다/);
}

{
  const view = resultView({ node_id: 13, doc_kind: "site", label: "hkilbo.github.io/blog/a", title: null, url: "https://hkilbo.github.io/blog/a/", actions: "보고" });
  assert.equal(view.kindLabel, "사이트");
  assert.equal(view.title, "hkilbo.github.io/blog/a");
  assert.equal(view.sub, "");
  assert.equal(view.href, "https://hkilbo.github.io/blog/a/");
}

console.log("result card ok");
