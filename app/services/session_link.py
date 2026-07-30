"""세션에 주입할 컨텍스트 조립. 여러 엔티티에 걸치므로 service 계층"""
import re

from app.constants import JIRA_PATTERN, WORKSPACE_ACTIVE
from app.repositories import categories as category_repo
from app.repositories import sessions as session_repo
from app.repositories import todos as todo_repo
from app.repositories import workspaces as workspace_repo

BLOCK_OPEN = '<work-dashboard session="{session}" state="{state}">'
BLOCK_CLOSE = "</work-dashboard>"
STATE_CLASSIFIED = "classified"
STATE_UNCLASSIFIED = "unclassified"
CONTEXT_LABELS = (
    ("배경", "background"),
    ("목적", "purpose"),
    ("목표", "goal"),
    ("고려사항", "considerations"),
)
# 여러 세션이 같은 저장소를 동시에 고치므로 모든 주입에 붙는 공통 규칙
FRESHNESS_GUIDE = (
    "공통: 다른 세션이 같은 코드·문서를 고칠 수 있다. 착수 전에 최신 상태를 다시 읽는다 "
    "— git status/log 로 브랜치 상태를 확인하고, 고칠 파일과 관련 문서를 그때 읽는다. "
    "컨텍스트에 남아 있는 예전 내용을 근거로 수정하지 않는다."
)
CLASSIFIED_GUIDE = (
    "지침: 이 세션은 위 워크스페이스 작업이다. 배경·목적에 맞게 진행하고 "
    "범위를 벗어나는 작업은 착수 전 사용자에게 확인받는다. "
    "할일에 (컨텍스트) 표시가 있으면 착수 전 dash.py show-todo <id> 로 읽는다."
)
UNCLASSIFIED_GUIDE = (
    "지침: 이번 세션을 한 번 분류한다. "
    "(1) 위치와 질문 내용으로 카테고리를 정하고 확인 없이 등록한다. "
    "(2) 관련된 진행 중 워크스페이스가 있다고 판단되면 사용자에게 확인받고 등록한다. "
    "없으면 카테고리만 등록한다. "
    "등록: python3 dash.py classify <session> --category <이름> [--workspace <id>] "
    "코드·문서를 바꾸거나 여러 턴에 걸치거나 산출물이 남는 작업이면 "
    "dash.py add-todo 로 할일을 만들고 dash.py link-todo <session> <todo-id> 로 연결한다. "
    "단발 조회·설명 질문이면 할일을 만들지 않는다."
)
SCOPE_GUIDE = (
    "지침: 이 브랜치 작업은 위 하위단계 범위 내에서만 진행한다. "
    "범위를 벗어나는 작업은 착수 전 사용자에게 안내하고 확인받는다."
)


def jira_from_branch(branch):
    """브랜치명 첫 Jira 패턴. 대문자 정규화"""
    match = re.search(JIRA_PATTERN, branch or "")
    return match.group(0).upper() if match else None


def attach_by_branch(con, claude_session_id, branch):
    """브랜치 Jira 로 워크스페이스를 찾으면 확인 없이 분류. 못 찾으면 None"""
    jira = jira_from_branch(branch)
    if not jira:
        return None
    workspace = workspace_repo.get_by_jira(con, jira)
    if not workspace:
        return None
    return session_repo.classify(con, claude_session_id, workspace_id=workspace["id"])


def render_context(con, claude_session_id):
    """주입할 블록. 세션이 없으면 빈 문자열"""
    session = session_repo.find(con, claude_session_id)
    if not session:
        return ""
    if session["workspace_id"]:
        return _classified_block(con, session)
    return _unclassified_block(con, session)


def active_payload(con):
    """폴링 응답. 조회할 때마다 정리도 함께 수행"""
    session_repo.sweep(con)
    return {
        "unclassified_count": session_repo.count_unclassified(con),
        "sessions": session_repo.list_active(con),
    }


def scope_guard_block(con, jira_id):
    """scope-guard 가 쓰던 블록 형식 유지. SKILL.md 를 고치지 않기 위함"""
    normalized = (jira_id or "").upper()
    workspace = workspace_repo.get_by_jira(con, normalized)
    if not workspace:
        return (
            f'<scope-guard missing="{normalized}">\n'
            f"이 브랜치({normalized})에 등록된 워크스페이스가 없다.\n"
            "지침: 첫 응답에서 사용자에게 배경·목적·목표를 물어보고, "
            "답을 받으면 dash.py add-workspace 로 저장한다.\n"
            "</scope-guard>"
        )
    lines = [
        f'<scope-guard active="{normalized}" status="{workspace["status"]}">',
        f"배경: {workspace['background'] or '(미입력)'}",
        f"목적: {workspace['purpose'] or '(미입력)'}",
        f"목표: {workspace['goal'] or '(미입력)'}",
        "하위단계:",
    ]
    lines.extend(_todo_lines(con, workspace["id"]))
    lines.append(SCOPE_GUIDE)
    lines.append("</scope-guard>")
    return "\n".join(lines)


def _classified_block(con, session):
    workspace = workspace_repo.get(con, session["workspace_id"])
    category = category_repo.get(con, workspace["category_id"])
    jira = f" [{workspace['jira_id']}]" if workspace["jira_id"] else ""
    lines = [
        BLOCK_OPEN.format(session=session["claude_session_id"], state=STATE_CLASSIFIED),
        f"워크스페이스: {workspace['name']} ({category['name']}){jira}",
    ]
    for label, key in CONTEXT_LABELS:
        lines.append(f"{label}: {workspace[key] or '(미입력)'}")
    lines.append("할일:")
    lines.extend(_todo_lines(con, workspace["id"]))
    lines.append(CLASSIFIED_GUIDE)
    lines.append(FRESHNESS_GUIDE)
    lines.append(BLOCK_CLOSE)
    return "\n".join(lines)


def _unclassified_block(con, session):
    categories = category_repo.list_all(con)
    names = {row["id"]: row["name"] for row in categories}
    lines = [
        BLOCK_OPEN.format(session=session["claude_session_id"], state=STATE_UNCLASSIFIED),
        f"현재 위치: {session['cwd'] or '(알 수 없음)'}"
        f" (브랜치 {session['git_branch'] or '없음'})",
        "카테고리: " + " / ".join(row["name"] for row in categories),
        "진행 중 워크스페이스:",
    ]
    active = workspace_repo.list_all(con, status=WORKSPACE_ACTIVE)
    if active:
        for workspace in active:
            goal = (workspace["goal"] or "").strip() or "(목표 미입력)"
            category_name = names.get(workspace["category_id"], "?")
            lines.append(
                f"  {workspace['id']}. {workspace['name']} ({category_name}) — {goal}"
            )
    else:
        lines.append("  (없음)")
    lines.append(UNCLASSIFIED_GUIDE)
    lines.append(FRESHNESS_GUIDE)
    lines.append(BLOCK_CLOSE)
    return "\n".join(lines)


def _todo_lines(con, workspace_id):
    todos = todo_repo.list_by_workspace(con, workspace_id)
    if not todos:
        return ["  (없음)"]
    # note 는 내용을 넣지 않고 존재만 표시 — 할일 12개 컨텍스트를 다 넣으면 세션이 오염됨
    return [
        f"  {todo['sort_order']}. [{todo['status']}] {todo['title']}"
        + (f" (컨텍스트 #{todo['id']})" if todo["note"] else "")
        for todo in todos
    ]
