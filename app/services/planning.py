"""다음에 할 일 선정과 완료분 집계"""
from datetime import datetime, timedelta, timezone

from app.constants import (
    STATUS_DOING,
    UNASSIGNED_LABEL,
    WORKABLE_STATUSES,
)
from app.repositories import todos as todo_repo
from app.services import lineage

DOING_RANK = 0
DEFAULT_RANK = 1
# 세션이 끝나도 doing 은 되돌리지 않으므로, 오래 물려 있는 것만 따로 경고함
STALE_DOING_HOURS = 24


def today_text():
    """완료 시각이 UTC 로 저장되므로 집계 기준도 UTC 날짜"""
    return datetime.now(timezone.utc).date().isoformat()


def next_todo(con, workspace_id=None, claude_session_id=None, keep=None):
    """트리 순서대로 훑는다(lineage.grouped_todos — 안 끝난 트리, 맨 위 우선순위, sort_order).
    한 트리 안에서는 doing 이 todo 보다 먼저, 그다음 sort_order. 할일(role NULL)만 후보다 — 단계(role='step')는
    후보가 아니다: 할일 하나를 맡으면 그 단계는 그 세션이 이어서 한다.

    workspace_id 는 옛 호출(CLI)이 깨지지 않게 받기만 하고 무시한다 — 워크스페이스는 없어졌다.
    돌려주는 것은 {"todo", "root"(트리 맨 위 할일, 없으면 None), "workspace": None(옛 소비자용)}.

    다른 활성 세션이 잡은 할일은 후보에서 뺀다. 내 세션이 잡은 것은 link-todo 로
    doing 이 되어 있으므로 기존 doing 우선 규칙만으로 1순위가 된다.

    keep 은 후보를 더 좁히는 술어다 — 자율 실행이 라벨·조건으로 거를 때 쓴다.
    순위 로직을 복제하지 않으려고 여기에 구멍 하나만 낸다 (사람용 next 는 안 넘긴다).
    """
    del workspace_id
    claimed = todo_repo.ids_claimed_by_others(con, claude_session_id)
    for _, head, members in _trees(con):
        picked = _first_open(members, claimed, keep)
        if picked:
            return {"todo": picked, "root": head, "workspace": None}
    return None


def ranked(con, keep=None, limit=None):
    """next_todo 와 같은 순위로 미완료 할일을 여러 건 모은다. 트리 맨 위 할일 제목(root_title)을 붙인다.

    '남이 잡은 것 제외' 는 여기서 하지 않는다 — 자율 수행 후보 목록은 잡혀 있는
    할일도 왜 못 도는지와 함께 보여줘야 한다. 거르는 쪽은 next_todo 의 규칙이다
    """
    rows = []
    for _, head, members in _trees(con):
        todos = [
            todo
            for todo in members
            if todo["status"] in WORKABLE_STATUSES and (keep is None or keep(todo))
        ]
        rows += [
            {
                **todo,
                "root_id": head["id"] if head else None,
                # 자기 자신이 맨 위면 붙일 트리 이름이 없다
                "root_title": head["title"] if head and head["id"] != todo["id"] else None,
            }
            for todo in sorted(todos, key=_priority_key)
        ]
    return rows[:limit] if limit else rows


def _trees(con):
    todos = [
        dict(row) for row in con.execute("SELECT * FROM todos ORDER BY sort_order, id")
    ]
    return lineage.grouped_todos(con, todos)


def stale_doing(con):
    """24시간 넘게 doing 인 할일. 대시보드 경고용 판정만 하고 UI 연결은 아직 없음"""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=STALE_DOING_HOURS)
    return todo_repo.list_doing_before(con, cutoff.isoformat(timespec="seconds"))


def done_on(con, date_text=None):
    """해당 날짜 완료분에 트리 맨 위 할일 제목(root_title)을 붙여 반환. daily-todo 로 넘기는 입력.
    workspace_name 은 root_title 과 같은 옛 소비자(CLI)용 별칭이다"""
    target = date_text or today_text()
    rows = []
    parents = lineage.parent_map(con)
    for todo in todo_repo.list_completed_on(con, target):
        if lineage.is_hidden(todo):
            continue  # 할일도 단계도 아닌 기록(매니저 보조 피드백 등)은 완료분이 아니다
        item = dict(todo)
        root = lineage.root_todo(con, todo["id"], parents)
        item["root_title"] = root["title"] if root and root["id"] != todo["id"] else UNASSIGNED_LABEL
        item["workspace_name"] = item["root_title"]
        rows.append(item)
    return rows


def _first_open(todos, claimed=(), keep=None):
    """미완료 중 doing 우선, 그 다음 sort_order. 남이 잡은 것과 keep 이 뺀 것은 제외.
    확인 대기(review)는 손댈 일이 아니라 사람이 볼 일이라 후보가 아니다"""
    open_todos = [
        todo
        for todo in todos
        if todo["status"] in WORKABLE_STATUSES
        and todo["id"] not in claimed
        and (keep is None or keep(todo))
    ]
    if not open_todos:
        return None
    return min(open_todos, key=_priority_key)


def _priority_key(todo):
    rank = DOING_RANK if todo["status"] == STATUS_DOING else DEFAULT_RANK
    return (rank, todo["sort_order"])
