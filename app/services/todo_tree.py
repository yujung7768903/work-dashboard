"""할일 트리 조립. 워크스페이스 하나가 트리 하나(루트)이고, 할일은 parent_id 로 깊이
제한 없이 매달린다. 화면의 '트리' 메뉴(List·Map)가 한 번에 받아 그린다.

트리 완료는 저장하지 않고 여기서 계산한다 — 그 트리의 할일이 전부 done 이면 완료다.
워크스페이스 status 와 따로 두는 이유는 할일 상태가 바뀔 때마다 두 곳을 맞출 필요가
없게 하려는 것이다. 할일이 하나도 없는 트리는 끝낼 것이 아직 없으므로 완료로 보지 않는다
"""
from app.constants import STATUS_DONE, TODO_STATUSES
from app.repositories import autorun as autorun_repo
from app.repositories import categories as category_repo
from app.repositories import sessions as session_repo
from app.repositories import todos as todo_repo
from app.repositories import workspaces as workspace_repo
from app.services import board

NODE_FIELDS = ("id", "title", "status", "parent_id", "priority", "sort_order")


def forest(con):
    """진행 중인 트리가 앞, 완료된 트리가 뒤. 같은 쪽 안에서는 보드의 워크스페이스 순서"""
    categories = {row["id"]: row for row in category_repo.list_all(con)}
    waiting = session_repo.waiting_by_todo(con)
    locked = autorun_repo.locked_todo_ids(con)
    ranked = []
    for workspace in workspace_repo.list_all(con):
        todos = todo_repo.list_by_workspace(con, workspace["id"])
        tree = build(workspace, todos, waiting, locked)
        tree["workspace"].update(_category_of(categories, workspace))
        ranked.append((tree, _board_rank(workspace, todos)))
    ranked.sort(key=lambda pair: (pair[0]["complete"], pair[1]))
    return {"trees": [tree for tree, _ in ranked], "statuses": list(TODO_STATUSES)}


def build(workspace, todos, waiting=None, locked=None):
    """할일 목록을 중첩 노드로. 부모가 이 트리에 없는 할일(손으로 고친 DB)은 루트 바로
    아래로 올려 화면에서 사라지지 않게 한다. 고리도 같은 이유로 끊어 루트 아래에 둔다"""
    waiting = waiting or {}
    locked = locked or set()
    nodes = {todo["id"]: _node(todo, waiting, locked) for todo in todos}
    roots = []
    for todo in todos:
        node = nodes[todo["id"]]
        parent = nodes.get(todo.get("parent_id"))
        if parent is None or _reaches(nodes, parent["id"], node["id"]):
            node["parent_id"] = None
            roots.append(node)
        else:
            parent["children"].append(node)
    for node in roots:
        _fill_progress(node)
    counts = {status: 0 for status in TODO_STATUSES}
    for todo in todos:
        counts[todo["status"]] = counts.get(todo["status"], 0) + 1
    total = len(todos)
    done = counts.get(STATUS_DONE, 0)
    return {
        "workspace": {
            "id": workspace["id"],
            "name": workspace["name"],
            "status": workspace["status"],
            "jira_id": workspace.get("jira_id"),
        },
        "children": roots,
        "progress": {"done": done, "total": total},
        "counts": counts,
        "waiting": sum(1 for node in nodes.values() if node["waiting"]),
        "complete": total > 0 and done == total,
    }


def _node(todo, waiting, locked):
    node = {key: todo.get(key) for key in NODE_FIELDS}
    node["waiting"] = waiting.get(todo["id"])
    # 자율 수행이 done 으로 닫았지만 사람이 아직 확인하지 않은 것 (보드의 검토 대기)
    node["autorun_locked"] = todo["id"] in locked
    node["children"] = []
    return node


def _reaches(nodes, start_id, target_id):
    """start 에서 부모를 타고 올라가 target 을 만나면 고리다"""
    seen = set()
    current = nodes.get(start_id)
    while current is not None and current["id"] not in seen:
        if current["id"] == target_id:
            return True
        seen.add(current["id"])
        current = nodes.get(current["parent_id"])
    return False


def _fill_progress(node):
    """하위 전체(자식·손자…) 중 완료 수. 자기 자신은 세지 않는다 — 카드의 '3/5' 는
    그 아래 가지가 얼마나 끝났는지다. 반환은 (자기 포함 완료, 자기 포함 전체)"""
    done = total = 0
    for child in node["children"]:
        child_done, child_total = _fill_progress(child)
        done += child_done
        total += child_total
    node["progress"] = {"done": done, "total": total}
    return done + (node["status"] == STATUS_DONE), total + 1


def _category_of(categories, workspace):
    category = categories.get(workspace["category_id"]) or {}
    return {
        "category_id": workspace["category_id"],
        "category_name": category.get("name"),
        "category_color": category.get("color"),
    }


def _board_rank(workspace, todos):
    """보드가 워크스페이스 카드를 세우는 순서를 그대로 쓴다 (app/services/board.py)"""
    done = sum(1 for todo in todos if todo["status"] == STATUS_DONE)
    return board.workspace_rank(
        {
            "todos": todos,
            "total_count": len(todos),
            "done_count": done,
            "sort_order": workspace["sort_order"],
        }
    )
