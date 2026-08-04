"""보드 그룹핑 트리 조립. 여러 엔티티에 걸치므로 service 계층"""
from app.constants import STATUS_DONE, UNASSIGNED_LABEL
from app.errors import Validation
from app.repositories import autorun as autorun_repo
from app.repositories import categories as category_repo
from app.repositories import labels as label_repo
from app.repositories import subtasks as subtask_repo
from app.repositories import todos as todo_repo
from app.repositories import workspaces as workspace_repo

GROUP_BY_WORKSPACE = "workspace"
GROUP_BY_CATEGORY = "category"
GROUP_BY_CHOICES = (GROUP_BY_WORKSPACE, GROUP_BY_CATEGORY)
KIND_UNASSIGNED = "unassigned"


def tree(con, group_by):
    """빈 그룹은 제외. 미분류는 비어 있어도 항상 마지막에 포함"""
    if group_by not in GROUP_BY_CHOICES:
        raise Validation(f"group_by 는 {GROUP_BY_CHOICES} 중 하나여야 함")
    builder = _workspace_groups if group_by == GROUP_BY_WORKSPACE else _category_groups
    return {"group_by": group_by, "groups": builder(con)}


def _workspace_groups(con):
    # 보드가 카테고리 색·이모지로 카드 상단을 칠하고 카테고리 필터를 거는 데 씀
    by_id = {row["id"]: row for row in category_repo.list_all(con)}
    # 라벨은 트리 한 번에 한 번만 읽는다. 카드마다 다시 물으면 카드 수만큼 쿼리가 는다
    labels = label_repo.map_by_todo(con)
    locked = autorun_repo.locked_todo_ids(con)
    groups = []
    for workspace in workspace_repo.list_all(con):
        todos = _enriched(
            con, todo_repo.list_by_workspace(con, workspace["id"]), labels, locked
        )
        if not todos:
            continue
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
    groups.append(_unassigned_group(con, labels, locked))
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


def _unassigned_group(con, labels, locked):
    return _group(
        kind=KIND_UNASSIGNED,
        item_id=None,
        name=UNASSIGNED_LABEL,
        sort_order=None,
        todos=_enriched(con, todo_repo.list_by_workspace(con, None), labels, locked),
    )


def _enriched(con, todos, labels, locked):
    enriched = []
    for todo in todos:
        item = dict(todo)
        item["subtasks"] = subtask_repo.list_by_todo(con, todo["id"])
        item["labels"] = labels.get(todo["id"], [])
        item["autorun_locked"] = todo["id"] in locked
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
