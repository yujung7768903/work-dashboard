"""다음에 할 일 선정과 완료분 집계"""
from datetime import datetime, timezone

from app.constants import STATUS_DOING, STATUS_DONE, UNASSIGNED_LABEL, WORKSPACE_ACTIVE
from app.repositories import todos as todo_repo
from app.repositories import workspaces as workspace_repo

DOING_RANK = 0
DEFAULT_RANK = 1


def today_text():
    """완료 시각이 UTC 로 저장되므로 집계 기준도 UTC 날짜"""
    return datetime.now(timezone.utc).date().isoformat()


def next_todo(con, workspace_id=None):
    """active 워크스페이스 순위대로 훑고, 없으면 미분류. doing 이 todo 보다 먼저

    workspace_id 가 오면 그 워크스페이스 안에서만 뽑는다(워크스페이스 status 무관).
    """
    if workspace_id is not None:
        workspace = workspace_repo.get(con, workspace_id)
        picked = _first_open(todo_repo.list_by_workspace(con, workspace_id))
        return {"todo": picked, "workspace": workspace} if picked else None
    for workspace in workspace_repo.list_all(con, status=WORKSPACE_ACTIVE):
        picked = _first_open(todo_repo.list_by_workspace(con, workspace["id"]))
        if picked:
            return {"todo": picked, "workspace": workspace}
    picked = _first_open(todo_repo.list_by_workspace(con, None))
    if picked:
        return {"todo": picked, "workspace": None}
    return None


def done_on(con, date_text=None):
    """해당 날짜 완료분에 워크스페이스 이름을 붙여 반환. daily-todo 로 넘기는 입력"""
    target = date_text or today_text()
    rows = []
    for todo in todo_repo.list_completed_on(con, target):
        item = dict(todo)
        item["workspace_name"] = _workspace_name(con, todo["workspace_id"])
        rows.append(item)
    return rows


def _first_open(todos):
    """미완료 중 doing 우선, 그 다음 sort_order"""
    open_todos = [todo for todo in todos if todo["status"] != STATUS_DONE]
    if not open_todos:
        return None
    return min(open_todos, key=_priority_key)


def _priority_key(todo):
    rank = DOING_RANK if todo["status"] == STATUS_DOING else DEFAULT_RANK
    return (rank, todo["sort_order"])


def _workspace_name(con, workspace_id):
    if workspace_id is None:
        return UNASSIGNED_LABEL
    return workspace_repo.get(con, workspace_id)["name"]
