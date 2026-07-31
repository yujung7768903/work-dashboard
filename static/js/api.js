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
    throw new Error(payload?.error ?? `요청 실패 (${response.status})`);
  }
  return payload;
}

export const getTree = (groupBy) => request("GET", `/tree?group_by=${groupBy}`);
export const getNext = () => request("GET", "/next");
export const getCategories = () => request("GET", "/categories");
export const getWorkspaces = () => request("GET", "/workspaces");
export const getSessions = () => request("GET", "/sessions");
export const getUsage = () => request("GET", "/usage");
export const getWorkspace = (id) => request("GET", `/workspaces/${id}`);

export const createCategory = (name) => request("POST", "/categories", { name });
export const updateCategory = (id, fields) => request("PATCH", `/categories/${id}`, fields);
export const deleteCategory = (id) => request("DELETE", `/categories/${id}`);

export const createWorkspace = (fields) => request("POST", "/workspaces", fields);
export const updateWorkspace = (id, fields) => request("PATCH", `/workspaces/${id}`, fields);
export const deleteWorkspace = (id) => request("DELETE", `/workspaces/${id}`);

export const createTodo = (fields) => request("POST", "/todos", fields);
export const updateTodo = (id, fields) => request("PATCH", `/todos/${id}`, fields);
export const deleteTodo = (id) => request("DELETE", `/todos/${id}`);

export const createSubtask = (todoId, title) =>
  request("POST", "/subtasks", { todo_id: todoId, title });
export const updateSubtask = (id, fields) => request("PATCH", `/subtasks/${id}`, fields);
export const deleteSubtask = (id) => request("DELETE", `/subtasks/${id}`);

export const reorder = (kind, ids, scopeId) =>
  request("POST", "/reorder", { kind, ids, scope_id: scopeId ?? null });
