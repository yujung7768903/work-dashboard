// 서버 통신 전담. 다른 모듈은 fetch 를 직접 부르지 않음
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
    const error = new Error(payload?.error ?? `요청 실패 (${response.status})`);
    // 서버가 확인을 요구한 것과 진짜 실패를 호출부가 구분할 수 있게 넘긴다
    error.confirm = Boolean(payload?.confirm);
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

export const createSubtask = (todoId, title) =>
  request("POST", "/subtasks", { todo_id: todoId, title });
export const updateSubtask = (id, fields) => request("PATCH", `/subtasks/${id}`, fields);
export const deleteSubtask = (id) => request("DELETE", `/subtasks/${id}`);

export const reorder = (kind, ids, scopeId) =>
  request("POST", "/reorder", { kind, ids, scope_id: scopeId ?? null });
