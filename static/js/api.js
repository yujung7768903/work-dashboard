// 서버 통신 전담. 다른 모듈은 fetch 를 직접 부르지 않음
// (i18n.js 는 예외다 — 첫 렌더 전에 언어를 알아야 해서 이 모듈보다 먼저 돈다)
import { fromKorean, t } from "./i18n.js";

const JSON_HEADERS = { "Content-Type": "application/json" };

async function request(method, path, body) {
  const options = { method };
  if (body !== undefined) {
    options.headers = JSON_HEADERS;
    options.body = JSON.stringify(body);
  }
  const response = await fetch(`/api${path}`, options);
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    // 서버는 한국어로 내려준다. 사전에 같은 문장이 있으면 옮기고, 건수·이름이 박힌
    // 문장은 사전에 없으므로 원문 그대로 뜬다 (README '초기 설정 (⑤) > 화면 언어' 참고)
    const error = new Error(
      payload?.error
        ? fromKorean(payload.error)
        : t("error.requestFailed", { status: response.status })
    );
    // 서버가 확인을 요구한 것과 진짜 실패를 호출부가 구분할 수 있게 넘긴다
    error.confirm = Boolean(payload?.confirm);
    // 바꾸려던 게 안 바뀌었으면 반드시 눈에 띄어야 한다 — 호출부마다 에러 표시가
    // 제각각(상단바 텍스트·툴팁·무시)이라 여기서 한 번에 띄운다.
    // GET 은 제외 — 목록 폴링이 실패하면 몇 초마다 창이 뜬다.
    // confirm 은 호출부가 되묻는 흐름이라 여기서 가로채면 창이 두 번 뜬다
    if (method !== "GET" && !error.confirm) globalThis.alert?.(error.message);
    throw error;
  }
  return payload;
}

export const getTree = (groupBy) => request("GET", `/tree?group_by=${groupBy}`);
export const getNext = () => request("GET", "/next");
export const getCategories = () => request("GET", "/categories");
export const getWorkspaces = () => request("GET", "/workspaces");
export const getSessions = () => request("GET", "/sessions");
export const getSession = (id) => request("GET", `/sessions/${id}`);
export const classifySession = (id, fields) => request("PATCH", `/sessions/${id}`, fields);
export const getUsage = () => request("GET", "/usage");
export const getWorktrees = () => request("GET", "/worktrees");
export const applyWorktree = (repo, branch) =>
  request("POST", "/worktrees", { repo, branch, action: "apply" });
export const discardWorktree = (repo, branch) =>
  request("POST", "/worktrees", { repo, branch, action: "discard" });
// action: start(띄우기) · restart(다시 띄우기) · stop(내리기)
export const controlWorktree = (repo, branch, action) =>
  request("POST", "/worktrees", { repo, branch, action });
export const getAutorun = () => request("GET", "/autorun");
export const setAutorun = (enabled) => request("PATCH", "/autorun", { enabled });
export const confirmAutorunRun = (id) => request("PATCH", `/autorun-runs/${id}`);
export const getWorkspace = (id) => request("GET", `/workspaces/${id}`);

export const createCategory = (name) => request("POST", "/categories", { name });
export const updateCategory = (id, fields) => request("PATCH", `/categories/${id}`, fields);
export const deleteCategory = (id, force = false) =>
  request("DELETE", `/categories/${id}${force ? "?force=1" : ""}`);

export const getLabels = () => request("GET", "/labels");
export const createLabel = (name) => request("POST", "/labels", { name });
export const updateLabel = (id, fields) => request("PATCH", `/labels/${id}`, fields);
export const deleteLabel = (id, force = false) =>
  request("DELETE", `/labels/${id}${force ? "?force=1" : ""}`);

export const createWorkspace = (fields) => request("POST", "/workspaces", fields);
export const updateWorkspace = (id, fields) => request("PATCH", `/workspaces/${id}`, fields);
export const deleteWorkspace = (id) => request("DELETE", `/workspaces/${id}`);

export const getTodo = (id) => request("GET", `/todos/${id}`);
export const createTodo = (fields) => request("POST", "/todos", fields);
export const updateTodo = (id, fields) => request("PATCH", `/todos/${id}`, fields);
export const deleteTodo = (id) => request("DELETE", `/todos/${id}`);

export const getSettings = () => request("GET", "/settings");
export const updateSettings = (fields) => request("PATCH", "/settings", fields);

export const reorder = (kind, ids, scopeId) =>
  request("POST", "/reorder", { kind, ids, scope_id: scopeId ?? null });
