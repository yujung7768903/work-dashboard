// 서버 통신 전담. 다른 모듈은 fetch 를 직접 부르지 않음
// (i18n.js 는 예외다 — 첫 렌더 전에 언어를 알아야 해서 이 모듈보다 먼저 돈다)
import { fromKorean, t } from "./i18n.js";

const JSON_HEADERS = { "Content-Type": "application/json" };

async function request(method, path, body, { silent } = {}) {
  const options = { method };
  if (body !== undefined) {
    options.headers = JSON_HEADERS;
    options.body = JSON.stringify(body);
  }
  const response = await fetch(`/api${path}`, options);
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    // 서버는 한국어로 내려준다. 건수·이름이 박힌 문장까지 사전에서 되짚는다
    // (README '초기 설정 (⑤) > 화면 언어' 참고)
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
    // confirm 은 호출부가 되묻는 흐름이라 여기서 가로채면 창이 두 번 뜬다.
    // silent 는 호출부가 실패를 되물어 재시도할 때 쓴다 — startTodo 의 위치 선택처럼
    if (method !== "GET" && !error.confirm && !silent) globalThis.alert?.(error.message);
    throw error;
  }
  return payload;
}

export const getTree = (groupBy) => request("GET", `/tree?group_by=${groupBy}`);
// 트리 메뉴. 워크스페이스마다 할일 상하 관계째 (보드의 getTree 는 묶음만 준다)
export const getTodoTrees = () => request("GET", "/todo-trees");
// 할일 관계 그래프. 제안 확인·거절은 state 만 바꾼다
export const getProposals = () => request("GET", "/graph-proposals");
export const updateEdge = (id, fields) => request("PATCH", `/edges/${id}`, fields);
// 결과물 파일 카드. 경로가 아니라 결과물 노드 id 만 보낸다 — 서버가 DB 에서 경로를 꺼내 탐색기로 연다
export const openResultFolder = (id) => request("POST", "/result-folder", { id });
export const getNext = () => request("GET", "/next");
export const getCategories = () => request("GET", "/categories");
export const getWorkspaces = () => request("GET", "/workspaces");
export const getSessions = () => request("GET", "/sessions");
export const getSession = (id) => request("GET", `/sessions/${id}`);
export const classifySession = (id, fields) => request("PATCH", `/sessions/${id}`, fields);
export const getUsage = () => request("GET", "/usage");
export const getWorktrees = (groupBy) => request("GET", `/worktrees?group_by=${groupBy}`);
export const applyWorktree = (repo, branch) =>
  request("POST", "/worktrees", { repo, branch, action: "apply" });
export const discardWorktree = (repo, branch) =>
  request("POST", "/worktrees", { repo, branch, action: "discard" });
// action: start(띄우기) · restart(다시 띄우기) · stop(내리기)
export const controlWorktree = (repo, branch, action) =>
  request("POST", "/worktrees", { repo, branch, action });
export const getGtasks = () => request("GET", "/gtasks");
export const setGtasks = (enabled) => request("PATCH", "/gtasks", { enabled });
export const setGtasksCategory = (id, enabled) =>
  request("PATCH", `/gtasks-categories/${id}`, { enabled });
export const connectGtasks = (credentials) => request("POST", "/gtasks-auth", credentials);
export const planGtasks = () => request("POST", "/gtasks-plan", {});
export const setupGtasks = (chosen) => request("POST", "/gtasks-setup", { chosen });
export const syncGtasks = () => request("POST", "/gtasks-sync", {});
export const disconnectGtasks = () => request("POST", "/gtasks-disconnect", {});

export const getAutorun = () => request("GET", "/autorun");
// 매니저 탭 한 칸. part: automations · helpers · decisions
export const getManager = (part) =>
  request("GET", `/manager?part=${encodeURIComponent(part)}`);
export const setAutorun = (enabled) => request("PATCH", "/autorun", { enabled });
export const confirmAutorunRun = (id) => request("PATCH", `/autorun-runs/${id}`);
// 돌릴 명령은 서버가 저장된 조건 문장에서 읽는다 — 여기서는 몇 번째 항목인지만 보낸다
export const checkPrecondition = (todoId, index) =>
  request("POST", "/precondition-check", { todo_id: todoId, index });
// 세션 탭의 입력칸. 서버가 살아 있는 세션이면 소켓으로, 끝났으면 --resume 으로 넣는다
export const sendSessionMessage = (sessionId, text) =>
  request("POST", "/session-message", { session_id: sessionId, text });
// 결정 답하기. 할일 상세에 붙은 결정들 · 한 건(답 보낸 뒤 폴링) · 보내기.
// 원 세션 전달은 서버 뒤에서 돈다(최대 90초) — 보내기는 바로 돌아오고 화면이 한 건을 폴링한다.
// 실패는 상자 안 상태 줄에 보이므로 alert 를 띄우지 않는다
// 매니저 할일 한 건(매니저 탭 줄과 같은 모양) — 사전 조건 할일을 눌러 그 할일 팝업을 열 때
export const getManagerTask = (id) => request("GET", `/manager-task/${id}`);
export const getTodoDecisions = (todoId) => request("GET", `/decisions?todo_id=${todoId}`);
export const getDecision = (id) => request("GET", `/decisions/${id}`);
export const answerDecision = (id, choice, feedback) =>
  request("POST", "/decision-answer", { id, choice, feedback }, { silent: true });
// 직접 할 일·확인 대기 응답. 할일 상세에 붙은 것은 getTodoDecisions 의 reports 로 함께 온다 · 한 건 · 보내기.
// done 은 완료(직접 할 일)·확인(확인 대기), feedback 은 진행 상황·고칠 것(done 과 함께면 그 메모)
export const getTaskReport = (id) => request("GET", `/task-reports/${id}`);
export const sendTaskReport = (id, done, feedback) =>
  request("POST", "/task-report", { id, done, feedback }, { silent: true });
// 보조 세션 피드백. 매니저 탭 보조 세션 상세가 열 때·보낸 뒤 폴링할 때 읽는다(세션 생사 + 보낸 피드백) · 보내기.
// 할일 상태는 바꾸지 않는다 — 돌고 있는 보조에게 말을 거는 것이다
export const getHelperFeedback = (sessionId) =>
  request("GET", `/helper-feedback?session_id=${encodeURIComponent(sessionId)}`);
export const sendHelperFeedback = (sessionId, feedback) =>
  request("POST", "/helper-feedback", { session_id: sessionId, feedback }, { silent: true });
// 권한 요청. 할일 상세에 붙은 것들 · 허용/거부 보내기. 보내기는 화면이 본 요청(세션·생성 시각·호출 id)을 같이
// 보낸다 — 그 사이 같은 id 로 바뀐 요청에 답이 가지 않게. 실패는 카드 안에 보이므로 alert 를 띄우지 않는다
export const getTodoPermissions = (todoId) => request("GET", `/permissions?todo_id=${todoId}`);
export const answerPermission = (body) => request("POST", "/permission-answer", body, { silent: true });
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
export const startTodo = (id, cwd) =>
  request("POST", "/todo-start", cwd ? { id, cwd } : { id }, { silent: true });
export const browseDir = (path) =>
  request("GET", `/browse${path ? `?path=${encodeURIComponent(path)}` : ""}`);
// note 에 적힌 경로를 탐색기로 연다. 브라우저는 file:// 로 탐색기를 못 띄워 서버가 띄운다
export const openPath = (path) => request("POST", "/open-path", { path });

export const getSettings = () => request("GET", "/settings");
export const updateSettings = (fields) => request("PATCH", "/settings", fields);

export const reorder = (kind, ids, scopeId) =>
  request("POST", "/reorder", { kind, ids, scope_id: scopeId ?? null });
