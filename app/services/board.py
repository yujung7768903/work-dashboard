"""보드 그룹핑 트리 조립. 여러 엔티티에 걸치므로 service 계층"""
from app.constants import STATUS_DONE, UNASSIGNED_LABEL
from app.errors import Validation
from app.repositories import autorun as autorun_repo
from app.repositories import categories as category_repo
from app.repositories import labels as label_repo
from app.repositories import sessions as session_repo
from app.repositories import todos as todo_repo
from app.repositories import workspaces as workspace_repo

GROUP_BY_WORKSPACE = "workspace"
GROUP_BY_CATEGORY = "category"
GROUP_BY_CHOICES = (GROUP_BY_WORKSPACE, GROUP_BY_CATEGORY)
KIND_UNASSIGNED = "unassigned"


def tree(con, group_by):
    """워크스페이스는 비어 있어도 포함(빈 카테고리는 제외). 미분류는 항상 마지막"""
    if group_by not in GROUP_BY_CHOICES:
        raise Validation(f"group_by 는 {GROUP_BY_CHOICES} 중 하나여야 함")
    builder = _workspace_groups if group_by == GROUP_BY_WORKSPACE else _category_groups
    groups = builder(con)
    return {
        "group_by": group_by,
        "groups": groups,
        # 할일 줄의 '3/10' 에서 분모. 화면이 그룹을 걸러도 분모는 전체 기준이어야 한다
        "priority_max": open_priority_max(
            todo for group in groups for todo in group["todos"]
        ),
    }


def open_priority_max(todos):
    """열린(완료 아닌) 할일 중 가장 높은 우선순위. 하나도 없으면 None"""
    values = [
        todo["priority"]
        for todo in todos
        if todo["status"] != STATUS_DONE and todo.get("priority") is not None
    ]
    return max(values) if values else None


def workspace_rank(group):
    """워크스페이스 카드 순서. 열린 할일의 최고 우선순위가 높은 쪽, 같으면 열린 할일이 많은 쪽,
    그래도 같으면 사람이 끌어 정한 순서(sort_order). 우선순위가 하나도 없는 카드는 뒤로 간다"""
    top = open_priority_max(group["todos"])
    open_count = group["total_count"] - group["done_count"]
    return (top is None, -(top or 0), -open_count, group["sort_order"])


def _workspace_groups(con):
    # 보드가 카테고리 색·이모지로 카드 상단을 칠하고 카테고리 필터를 거는 데 씀
    by_id = {row["id"]: row for row in category_repo.list_all(con)}
    # 라벨은 트리 한 번에 한 번만 읽는다. 카드마다 다시 물으면 카드 수만큼 쿼리가 는다
    labels = label_repo.map_by_todo(con)
    locked = autorun_repo.locked_todo_ids(con)
    # 세션 활동 시각도 한 번에. 상태별 뷰가 카드를 이 순서로 세운다
    last_session = session_repo.last_activity_by_todo(con)
    groups = []
    for workspace in workspace_repo.list_all(con):
        todos = _enriched(
            con,
            todo_repo.list_by_workspace(con, workspace["id"]),
            labels,
            locked,
            last_session,
        )
        category = by_id.get(workspace["category_id"]) or {}
        groups.append(
            _group(
                kind=GROUP_BY_WORKSPACE,
                item_id=workspace["id"],
                name=workspace["name"],
                sort_order=workspace["sort_order"],
                todos=todos,
                category_id=workspace["category_id"],
                category_name=category.get("name"),
                category_color=category.get("color"),
                status=workspace["status"],
                jira_id=workspace["jira_id"],
            )
        )
    groups.sort(key=workspace_rank)
    groups.append(_unassigned_group(con, labels, locked, last_session))
    return groups


def _category_groups(con):
    labels = label_repo.map_by_todo(con)
    locked = autorun_repo.locked_todo_ids(con)
    groups = []
    for category in category_repo.list_all(con):
        todos = _enriched(
            con, todo_repo.list_by_category(con, category["id"]), labels, locked
        )
        if not todos:
            continue
        groups.append(
            _group(
                kind=GROUP_BY_CATEGORY,
                item_id=category["id"],
                name=category["name"],
                sort_order=category["sort_order"],
                todos=todos,
            )
        )
    return groups


def _unassigned_group(con, labels, locked, last_session=None):
    return _group(
        kind=KIND_UNASSIGNED,
        item_id=None,
        name=UNASSIGNED_LABEL,
        sort_order=None,
        todos=_enriched(
            con, todo_repo.list_by_workspace(con, None), labels, locked, last_session
        ),
    )


def _enriched(con, todos, labels, locked, last_session=None):
    enriched = []
    for todo in todos:
        item = dict(todo)
        item["labels"] = labels.get(todo["id"], [])
        item["autorun_locked"] = todo["id"] in locked
        # 상태별 뷰가 카드를 세우는 순서. 한 번도 안 잡힌 할일은 None
        item["last_session_at"] = (last_session or {}).get(todo["id"])
        enriched.append(item)
    return enriched


def _group(kind, item_id, name, sort_order, todos, **extra):
    group = {
        "kind": kind,
        "id": item_id,
        "name": name,
        "sort_order": sort_order,
        "done_count": sum(1 for todo in todos if todo["status"] == STATUS_DONE),
        "total_count": len(todos),
        "todos": todos,
    }
    group.update(extra)
    return group
