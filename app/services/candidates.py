"""매니저 탭 '후보 할일' — 지금 일이 끝나면 다음에 무엇을 할지. 우선순위가 높은 할일 최대 3건.

후보: 할일(role 이 NULL — 단계 행 제외) 중 상태가 todo·doing 이고, 기다리는 것이 없고, 지금 살아 있는 세션이 잡고
있지 않은 것. 기다리는 할일은 후보에서 빼고 건수만 센다(머리의 '대기 중 N건').

기다림 — 그 할일 행이나 끝나지 않은 단계 행 중 하나라도:
- 결정 대기: mgr_kind=decision 이고 mgr_status=open
- 확인 대기: mgr_status=confirm
- 권한 대기: mgr_blocked=permission 이고 mgr_status=open
- 선행 대기(매니저): mgr_status=open 이고 mgr_after_ids 의 할일 중 mgr_status 가 done·invalid 아닌 것이 있음 —
  매니저 tasks.prereqs/waiting_on 과 같은 규칙(뷰에 없는 할일·지운 할일도 끝나지 않은 것으로 본다)
- 선행 대기(대시보드): 확정된 선행 연결(edges precedes, 앞 → 뒤)의 앞 할일이 아직 done 이 아님

일하는 중: 할일이나 그 단계를 working·idle 세션이 잡고 있음(session_todos — todos.ids_claimed_by_others 와 같은 판정).
idle 은 STALE_IDLE_HOURS 가 지나면 sweep 이 ended 로 내리므로 오래 멈춘 세션은 저절로 빠진다
"""
from app.constants import EDGE_CONFIRMED, NODE_TODO, REL_PRECEDES
from app.repositories import todos as todo_repo

LIMIT = 3
ACTIVE = ("todo", "doing")
PREREQ_FINISHED = ("done", "invalid")  # 매니저 tasks.PREREQ_FINISHED


def snapshot(con, limit=LIMIT):
    """{"items": [{id, title, status, priority, priority_max, category_name, category_color}], "waiting": 기다리는 할일 수}.
    priority_max 는 열린 할일(todo·doing) 중 최고 — 보드·결정 대기 줄과 같은 '2/3' 표시의 분모"""
    if con is None:
        return {"items": [], "waiting": 0}
    columns = {row["name"] for row in con.execute("PRAGMA table_info(todos)")}
    has_role = "role" in columns
    rows = [
        dict(row)
        for row in con.execute(
            "SELECT t.*, c.name AS category_name, c.color AS category_color FROM todos t"
            " LEFT JOIN categories c ON c.id = t.category_id"
            f" WHERE t.status IN (?, ?){' AND t.role IS NULL' if has_role else ''}"
            " ORDER BY t.priority IS NULL, t.priority DESC, t.sort_order, t.id",
            ACTIVE,
        )
    ]
    steps = _open_steps(con) if has_role else {}
    mgr_status = {row["id"]: row["mgr_status"] for row in con.execute("SELECT id, mgr_status FROM todos WHERE mgr_kind IS NOT NULL")}
    preceded = _preceded(con)
    claimed = todo_repo.ids_claimed_by_others(con)
    items, waiting = [], 0
    for row in rows:
        family = [row, *steps.get(row["id"], [])]
        if any(_waits(member, mgr_status) for member in family) or row["id"] in preceded:
            waiting += 1
            continue
        if any(member["id"] in claimed for member in family):
            continue
        if len(items) < limit:
            items.append(
                {
                    "id": row["id"],
                    "title": row["title"],
                    "status": row["status"],
                    "priority": row["priority"],
                    "category_name": row["category_name"],
                    "category_color": row["category_color"],
                }
            )
    top = max((row["priority"] for row in rows if row["priority"] is not None), default=None)
    for item in items:
        item["priority_max"] = top
    return {"items": items, "waiting": waiting}


def _open_steps(con):
    """할일 id → 끝나지 않은 단계 행"""
    out = {}
    for row in con.execute("SELECT * FROM todos WHERE role='step' AND parent_id IS NOT NULL AND status != 'done'"):
        out.setdefault(row["parent_id"], []).append(dict(row))
    return out


def _waits(row, mgr_status):
    status = row.get("mgr_status")
    if status == "confirm":
        return True
    if status != "open":
        return False
    if row.get("mgr_kind") == "decision" or row.get("mgr_blocked") == "permission":
        return True
    after = [int(part) for part in (row.get("mgr_after_ids") or "").split(",") if part.strip().isdigit()]
    return any(mgr_status.get(task_id) not in PREREQ_FINISHED for task_id in after)


def _preceded(con):
    """확정된 선행 연결에서 앞 할일이 끝나지 않은 뒤 할일 id"""
    rows = con.execute(
        "SELECT e.dst_id FROM edges e JOIN todos a ON a.id = CAST(e.src_id AS INTEGER)"
        " WHERE e.relation=? AND e.state=? AND e.src_kind=? AND e.dst_kind=? AND a.status != 'done'",
        (REL_PRECEDES, EDGE_CONFIRMED, NODE_TODO, NODE_TODO),
    )
    return {int(row["dst_id"]) for row in rows if str(row["dst_id"]).isdigit()}
