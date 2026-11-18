"""할일 계보 — 상위 연결(edges parent)만으로 위·아래를 찾는다. 워크스페이스가 사라진 뒤(사용자 결정 11-18)
트리의 맨 위는 상위가 없는 할일(또는 맥락) 자신이고, 작업 위치·배경도 위로 올라가며 가장 가까운 것을 쓴다.

주 상위는 트리 화면(todo_tree)과 같은 규칙이다: 거절된 연결은 빼고 확정 > 제안, 먼저 이은 것.
손으로 고친 DB 에 고리가 있어도 멈추도록 본 노드는 다시 보지 않는다
"""
import os

from app.constants import EDGE_PROPOSED, EDGE_REJECTED, NODE_CONTEXT, NODE_TODO, REL_PARENT, STATUS_DONE
from app.repositories import graph as graph_repo

ROLE_STEP = "step"  # app/db.py ROLE_STEP — 할일의 단계 행. 트리 노드가 아니라 그 할일 카드 안의 순서 목록이다
# role 이 NULL 이면 할일, 'step' 이면 단계, 그 밖(예: 매니저 보조 피드백 기록 'feedback')은 할일이 아니라 숨긴다


def _role(todo):
    return todo.get("role") if hasattr(todo, "get") else todo["role"]


def is_step(todo):
    return _role(todo) == ROLE_STEP


def is_task(todo):
    return _role(todo) is None


def is_hidden(todo):
    return _role(todo) not in (None, ROLE_STEP)


def parent_map(con):
    """자식 노드 (종류, id 문자열) → 주 상위 노드 (종류, id 문자열)"""
    found = {}
    for row in con.execute(
        "SELECT src_kind, src_id, dst_kind, dst_id FROM edges WHERE relation=? AND state<>?"
        " ORDER BY state=?, id",
        (REL_PARENT, EDGE_REJECTED, EDGE_PROPOSED),
    ):
        found.setdefault((row["dst_kind"], row["dst_id"]), (row["src_kind"], row["src_id"]))
    return found


def chain(con, todo_id, parents=None):
    """주 상위를 따라 올라간 노드들, 가까운 것부터"""
    parents = parents if parents is not None else parent_map(con)
    node, seen, found = (NODE_TODO, str(todo_id)), set(), []
    while node in parents and node not in seen:
        seen.add(node)
        node = parents[node]
        if node in seen:
            break
        found.append(node)
    return found


def top_of(con, todo_id, parents=None):
    """그 할일이 속한 트리의 맨 위 노드 (종류, id 문자열). 상위가 없으면 자기 자신"""
    above = chain(con, todo_id, parents)
    return above[-1] if above else (NODE_TODO, str(todo_id))


def root_todo(con, todo_id, parents=None):
    """트리 맨 위 할일 행(dict). 맨 위가 맥락이면 그 바로 아래 할일. 할일이 없으면 None"""
    nodes = [(NODE_TODO, str(todo_id))] + chain(con, todo_id, parents)
    todos = [node for node in nodes if node[0] == NODE_TODO]
    return _todo(con, todos[-1][1]) if todos else None


def ancestor_todos(con, todo_id):
    """위쪽 할일 행들, 가까운 것부터. 상위가 여럿이면 모든 상위 연결을 따라간다(거리 순)"""
    found = []
    for kind, ident in graph_repo.ancestors(con, (NODE_TODO, todo_id)):
        if kind == NODE_TODO:
            row = _todo(con, ident)
            if row is not None:
                found.append(row)
    return found


def nearest_cwd(con, todo):
    """그 할일에 적힌 작업 위치, 없으면 가장 가까운 상위 할일의 것. 없어진 경로는 건너뛴다"""
    own = (todo.get("cwd") or "").strip()
    if own and os.path.isdir(own):
        return own
    for above in ancestor_todos(con, todo["id"]):
        chosen = (above.get("cwd") or "").strip()
        if chosen and os.path.isdir(chosen):
            return chosen
    return ""


def tree_todo_ids(con, todo_id=None, top=None):
    """그 할일이 속한 트리(또는 맨 위 노드 top)의 할일 id 전부 — 맨 위 아래로 상위 연결을 다 따라간다.
    단계 행도 들어 있다(세션은 단계를 잡을 수도 있다)"""
    kind, ident = top if top is not None else top_of(con, todo_id)
    found = {int(ident)} if kind == NODE_TODO else set()
    for row in con.execute(
        """WITH RECURSIVE down(kind, ident) AS (
               SELECT ?, ?
               UNION
               SELECT e.dst_kind, e.dst_id FROM edges e JOIN down ON e.src_kind = down.kind AND e.src_id = down.ident
               WHERE e.relation = ? AND e.state <> ?
           ) SELECT ident FROM down WHERE kind = ?""",
        (kind, str(ident), REL_PARENT, EDGE_REJECTED, NODE_TODO),
    ):
        found.add(int(row["ident"]))
    return sorted(found)


def open_roots(con, limit=None):
    """안 끝난 맨 위 할일(상위 없음, 단계 아님) — 아래에 할일이 있는 트리만. 트리 순서(rank)대로"""
    parents = parent_map(con)
    owners = {above for above in parents.values() if above[0] == NODE_TODO}
    rows = [
        dict(row)
        for row in con.execute(
            "SELECT * FROM todos WHERE status<>? AND role IS NULL ORDER BY sort_order, id",
            (STATUS_DONE,),
        )
        if (NODE_TODO, str(row["id"])) not in parents and (NODE_TODO, str(row["id"])) in owners
    ]
    rows.sort(key=lambda row: rank(False, row))
    return rows[:limit] if limit else rows


def todo_by_jira(con, jira):
    """제목·note 에 그 Jira 키가 적힌 할일 중 가장 최근에 고친 것(할일만 — 단계·기록 제외). 옛 워크스페이스의 jira_id 는
    이관이 맨 위 할일 note 로 옮겼다. 없으면 None"""
    if not jira:
        return None
    pattern = f"%{jira.upper()}%"
    row = con.execute(
        "SELECT * FROM todos WHERE role IS NULL AND (UPPER(title) LIKE ? OR UPPER(COALESCE(note,'')) LIKE ?)"
        " ORDER BY updated_at DESC, id DESC LIMIT 1",
        (pattern, pattern),
    ).fetchone()
    return dict(row) if row else None


def tree_key(node):
    """트리 하나의 이름표 — 맨 위 노드 key (t12·c3). 화면의 트리 id 와 같다"""
    kind, ident = node
    return f"{'c' if kind == NODE_CONTEXT else 't'}{ident}"


def grouped_todos(con, todos, parents=None):
    """할일 → 트리별 묶음 [(맨 위 노드, 맨 위 할일 행|None, [할일…])]. 트리 순서는 todo_tree.rank 와 같다:
    안 끝난 트리 먼저, 맨 위 우선순위 높은 것(없으면 뒤), sort_order, id. 할일(role NULL)만 넣는다"""
    parents = parents if parents is not None else parent_map(con)
    groups = {}
    for todo in todos:
        if not is_task(todo):
            continue
        groups.setdefault(top_of(con, todo["id"], parents), []).append(todo)
    rows = []
    for node, members in groups.items():
        head = _todo(con, node[1]) if node[0] == NODE_TODO else None
        complete = all(member["status"] == STATUS_DONE for member in members)
        rows.append((rank(complete, head), node, head, members))
    rows.sort(key=lambda row: row[0])
    return [(node, head, members) for _, node, head, members in rows]


def rank(complete, head):
    """트리 순서 열쇠. head 는 맨 위 할일 행(맥락이면 None)"""
    priority = head.get("priority") if head else None
    return (
        bool(complete),
        priority is None,
        -(priority or 0),
        (head.get("sort_order") if head else None) or 0,
        int(head["id"]) if head else 0,
    )


def _todo(con, ident):
    row = con.execute("SELECT * FROM todos WHERE id=?", (int(ident),)).fetchone()
    return dict(row) if row else None
