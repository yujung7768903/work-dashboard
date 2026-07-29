"""보드 그룹핑 트리 조립. 여러 엔티티에 걸치므로 service 계층"""
from app.constants import STATUS_DONE, UNASSIGNED_LABEL
from app.errors import Validation
from app.repositories import categories as category_repo
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
    names = {row["id"]: row["name"] for row in category_repo.list_all(con)}
    groups = []
    for workspace in workspace_repo.list_all(con):
        todos = _with_subtasks(con, todo_repo.list_by_workspace(con, workspace["id"]))
        if not todos:
            continue
        groups.append(
            _group(
                kind=GROUP_BY_WORKSPACE,
                item_id=workspace["id"],
                name=workspace["name"],
                sort_order=workspace["sort_order"],
                todos=todos,
                category_name=names.get(workspace["category_id"]),
                status=workspace["status"],
                jira_id=workspace["jira_id"],
            )
        )
    groups.append(_unassigned_group(con))
    return groups


def _category_groups(con):
    groups = []
    for category in category_repo.list_all(con):
        todos = _with_subtasks(con, todo_repo.list_by_category(con, category["id"]))
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


def _unassigned_group(con):
    return _group(
        kind=KIND_UNASSIGNED,
        item_id=None,
        name=UNASSIGNED_LABEL,
        sort_order=None,
        todos=_with_subtasks(con, todo_repo.list_by_workspace(con, None)),
    )


def _with_subtasks(con, todos):
    enriched = []
    for todo in todos:
        item = dict(todo)
        item["subtasks"] = subtask_repo.list_by_todo(con, todo["id"])
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
