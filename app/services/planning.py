"""다음에 할 일 선정과 완료분 집계"""
from datetime import datetime, timedelta, timezone

from app.constants import STATUS_DOING, STATUS_DONE, UNASSIGNED_LABEL, WORKSPACE_ACTIVE
from app.repositories import todos as todo_repo
from app.repositories import workspaces as workspace_repo

DOING_RANK = 0
DEFAULT_RANK = 1
# 세션이 끝나도 doing 은 되돌리지 않으므로, 오래 물려 있는 것만 따로 경고함
STALE_DOING_HOURS = 24


def today_text():
    """완료 시각이 UTC 로 저장되므로 집계 기준도 UTC 날짜"""
    return datetime.now(timezone.utc).date().isoformat()


def next_todo(con, workspace_id=None, claude_session_id=None, keep=None):
    """active 워크스페이스 순위대로 훑고, 없으면 미분류. doing 이 todo 보다 먼저

    workspace_id 가 오면 그 워크스페이스 안에서만 뽑는다(워크스페이스 status 무관).
    다른 활성 세션이 잡은 할일은 후보에서 뺀다. 내 세션이 잡은 것은 link-todo 로
    doing 이 되어 있으므로 기존 doing 우선 규칙만으로 1순위가 된다.

    keep 은 후보를 더 좁히는 술어다 — 자율 실행이 라벨·조건으로 거를 때 쓴다.
    순위 로직을 복제하지 않으려고 여기에 구멍 하나만 낸다 (사람용 next 는 안 넘긴다).
    """
    claimed = todo_repo.ids_claimed_by_others(con, claude_session_id)
    if workspace_id is not None:
        workspace = workspace_repo.get(con, workspace_id)
        picked = _first_open(
            todo_repo.list_by_workspace(con, workspace_id), claimed, keep
        )
        return {"todo": picked, "workspace": workspace} if picked else None
    for workspace in workspace_repo.list_all(con, status=WORKSPACE_ACTIVE):
        picked = _first_open(
            todo_repo.list_by_workspace(con, workspace["id"]), claimed, keep
        )
        if picked:
            return {"todo": picked, "workspace": workspace}
    picked = _first_open(todo_repo.list_by_workspace(con, None), claimed, keep)
    if picked:
        return {"todo": picked, "workspace": None}
    return None


def ranked(con, keep=None, limit=None):
    """next_todo 와 같은 순위로 미완료 할일을 여러 건 모은다. 워크스페이스 이름을 붙인다.

    '남이 잡은 것 제외' 는 여기서 하지 않는다 — 자율 수행 후보 목록은 잡혀 있는
    할일도 왜 못 도는지와 함께 보여줘야 한다. 거르는 쪽은 next_todo 의 규칙이다
    """
    rows = []
    for workspace in workspace_repo.list_all(con, status=WORKSPACE_ACTIVE):
        rows += _open_sorted(con, workspace["id"], workspace["name"], keep)
    rows += _open_sorted(con, None, UNASSIGNED_LABEL, keep)
    return rows[:limit] if limit else rows


def _open_sorted(con, workspace_id, workspace_name, keep):
    todos = [
        todo
        for todo in todo_repo.list_by_workspace(con, workspace_id)
        if todo["status"] != STATUS_DONE and (keep is None or keep(todo))
    ]
    return [
        {**todo, "workspace_id": workspace_id, "workspace_name": workspace_name}
        for todo in sorted(todos, key=_priority_key)
    ]


def stale_doing(con):
    """24시간 넘게 doing 인 할일. 대시보드 경고용 판정만 하고 UI 연결은 아직 없음"""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=STALE_DOING_HOURS)
    return todo_repo.list_doing_before(con, cutoff.isoformat(timespec="seconds"))


def done_on(con, date_text=None):
    """해당 날짜 완료분에 워크스페이스 이름을 붙여 반환. daily-todo 로 넘기는 입력"""
    target = date_text or today_text()
    rows = []
    for todo in todo_repo.list_completed_on(con, target):
        item = dict(todo)
        item["workspace_name"] = _workspace_name(con, todo["workspace_id"])
        rows.append(item)
    return rows


def _first_open(todos, claimed=(), keep=None):
    """미완료 중 doing 우선, 그 다음 sort_order. 남이 잡은 것과 keep 이 뺀 것은 제외"""
    open_todos = [
        todo
        for todo in todos
        if todo["status"] != STATUS_DONE
        and todo["id"] not in claimed
        and (keep is None or keep(todo))
    ]
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
