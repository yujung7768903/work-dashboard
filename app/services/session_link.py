"""세션에 주입할 컨텍스트 조립. 여러 엔티티에 걸치므로 service 계층"""
import re

from app.constants import (
    JIRA_PATTERN,
    ONBOARDING_DECLINED_FLAG,
    STATUS_DONE,
)
from app.db import meta_get, meta_set
from app.repositories import categories as category_repo
from app.repositories import labels as label_repo
from app.repositories import sessions as session_repo
from app.repositories import todos as todo_repo
from app.services import lineage, precondition, transcript, worktrees

BLOCK_OPEN = '<work-dashboard session="{session}" state="{state}">'
BLOCK_CLOSE = "</work-dashboard>"
STATE_CLASSIFIED = "classified"
STATE_UNCLASSIFIED = "unclassified"
STATE_ONBOARDING = "onboarding"
STATE_RELEASED = "released"
# 미분류 블록에 보여 줄 진행 중 트리 수. 전부 넣으면 세션 첫 주입이 길어진다
UNCLASSIFIED_TREE_LIMIT = 20
# 여러 세션이 같은 저장소를 동시에 고치므로 모든 주입에 붙는 공통 규칙
FRESHNESS_GUIDE = (
    "공통: 다른 세션이 같은 코드·문서를 고칠 수 있다. 착수 전에 최신 상태를 다시 읽는다 "
    "— git status/log 로 브랜치 상태를 확인하고, 고칠 파일과 관련 문서를 그때 읽는다. "
    "컨텍스트에 남아 있는 예전 내용을 근거로 수정하지 않는다."
)
# 끝난 작업의 리소스(할일·서버·워크트리)가 남으면 다음 세션이 그걸 진행 중으로 오해한다
RELEASE_GUIDE = (
    "완료: 사용자가 병합을 지시하면(\"병합해줘\", \"master 에 반영해줘\") "
    "python3 dash.py merge 한 번으로 수행한다 — 상태 확인·master 들이기·테스트·병합·"
    "할일 done·서버 종료를 그 순서로 한다. git merge 를 손으로 조립하지 않는다. "
    "그 뒤 ExitWorktree 로 워크트리를 제거한다. "
    "병합 없이 리소스만 해제할 때만 dash.py finish 를 쓴다. "
    "충돌은 사람에게 넘기지 않고 직접 해결한다 — 양쪽 기능이 모두 동작하게, 최신 코드 기준으로. "
    "다만 하나를 버려야 하거나 동작이 달라지는 선택이면 추측하지 않고 사용자에게 확인한다 "
    "(자율 세션이면 dash.py autorun-request 로 남긴다)."
)
# 분류·할일 연결은 세션 몫이 아니다(사용자 결정 11-18) — 대시보드가 세션 카테고리를 판정하고 매니저가 세션을 할일
# (그 할일의 단계)에 잇는다. 세션에게 맡기면 같은 일이 매니저 할일·세션 할일 두 장으로 갈라졌다
NO_FILING_RULE = (
    " 이 세션은 카테고리 분류도 할일 등록·연결도 하지 않는다 — 분류는 대시보드가, "
    "할일 연결은 매니저가 한다."
)
# 해제 뒤 같은 세션이 이어질 때. 끝난 할일에 새 작업을 얹으면 무엇이 끝났는지 알 수 없어진다
RELEASED_GUIDE = (
    "지침: 이 세션이 잡았던 할일은 모두 끝났다(done). "
    "사용자가 새 요청을 하면 끝난 할일에 얹지 않는다."
    + NO_FILING_RULE
)
# 브랜치 Jira 로 트리는 알아냈지만 아직 할일을 안 잡은 세션
UNLINKED_GUIDE = "미연결: 이 세션은 아직 어느 할일에도 이어지지 않았다." + NO_FILING_RULE
CLASSIFIED_GUIDE = (
    "지침: 이 세션은 위 트리(맨 위 할일) 작업이다. 배경·목적에 맞게 진행하고 "
    "범위를 벗어나는 작업은 착수 전 사용자에게 확인받는다. "
    "할일에 (컨텍스트) 표시가 있으면 착수 전 dash.py show-note <id> 로 읽는다. "
    "'조건:' 이 붙은 할일은 그 조건이 충족됐는지 먼저 확인하고, "
    "미충족이면 착수하지 않고 사용자에게 알린다."
)
UNCLASSIFIED_GUIDE = "지침:" + NO_FILING_RULE + " 위 목록은 참고용이다."
SCOPE_GUIDE = (
    "지침: 이 브랜치 작업은 위 하위단계 범위 내에서만 진행한다. "
    "범위를 벗어나는 작업은 착수 전 사용자에게 안내하고 확인받는다."
)


def jira_from_branch(branch):
    """브랜치명 첫 Jira 패턴. 대문자 정규화"""
    match = re.search(JIRA_PATTERN, branch or "")
    return match.group(0).upper() if match else None


def attach_by_branch(con, claude_session_id, branch):
    """브랜치 Jira 가 적힌 할일을 찾으면 확인 없이 그 할일의 카테고리로 분류. 못 찾으면 None.
    워크스페이스 jira_id 는 이관이 맨 위 할일 note 로 옮겼다(lineage.todo_by_jira)"""
    found = lineage.todo_by_jira(con, jira_from_branch(branch))
    if not found or found.get("category_id") is None:
        return None
    category = category_repo.get(con, found["category_id"])
    return session_repo.classify(con, claude_session_id, category_name=category["name"])


def render_context(con, claude_session_id):
    """주입할 블록. 세션이 없으면 빈 문자열"""
    session = session_repo.find(con, claude_session_id)
    if not session:
        return ""
    if session.get("linked_todo_id"):
        return _classified_block(con, session, session["linked_todo_id"])
    by_branch = lineage.todo_by_jira(con, jira_from_branch(session["git_branch"]))
    if by_branch:
        # 할일은 아직 안 잡았다. 브랜치 Jira 로 그 트리 컨텍스트만 되찾아 준다 — 저장하지 않고 매번 다시 계산한다
        return _classified_block(con, session, by_branch["id"], linked=False)
    return _unclassified_block(con, session)


def released_context(con, claude_session_id):
    """잡은 할일이 전부 done 인 세션에만 주입. 새 할일을 연결하면 저절로 조용해진다.

    별도 플래그를 두지 않는 이유 — 플래그와 실제 할일 상태가 어긋나면 믿을 것은 할일 쪽이다
    """
    session = session_repo.find(con, claude_session_id)
    if not session:
        return ""
    todo_ids = session_repo.linked_todo_ids(con, claude_session_id)
    if not todo_ids:
        return ""
    if any(todo_repo.get(con, todo_id)["status"] != STATUS_DONE for todo_id in todo_ids):
        return ""
    return "\n".join(
        [
            BLOCK_OPEN.format(session=claude_session_id, state=STATE_RELEASED),
            RELEASED_GUIDE,
            FRESHNESS_GUIDE,
            BLOCK_CLOSE,
        ]
    )


def needs_onboarding(con):
    """할일이 하나도 없고 사용자가 거절한 적도 없을 때. 세션 주입은 더 이상 초기 설정 블록을 내지 않는다
    (워크스페이스 초기 설정이 없어졌다) — CLI onboard 가 상태를 보일 때만 쓴다.

    완료 플래그는 두지 않는다 — 온보딩이 끝나면 할일이 생겨 첫 조건이 저절로 깨진다.
    상태를 플래그와 실제 데이터 두 곳에 적으면 어긋나고, 그때 믿어야 하는 건 실제 데이터다
    """
    if meta_get(con, ONBOARDING_DECLINED_FLAG):
        return False
    return con.execute("SELECT 1 FROM todos LIMIT 1").fetchone() is None


def decline(con):
    """자동 분류 거절. 이후 온보딩 블록이 주입되지 않는다"""
    meta_set(con, ONBOARDING_DECLINED_FLAG)


def active_payload(con):
    """폴링 응답. 조회할 때마다 정리도 함께 수행"""
    session_repo.sweep(con)
    return {
        "unclassified_count": session_repo.count_unclassified(con),
        "sessions": session_repo.list_active(con),
    }


def detail(con, session_row_id):
    """세션 팝업. 목록 한 줄로는 어느 세션인지 몰라서 id 와 최근 대화를 함께 준다.

    todos 는 같은 팝업의 개요 탭이 쓴다 — 이 세션이 잡은 할일의 시각·note
    """
    session = session_repo.get_by_row_id(con, session_row_id)
    todo_ids = session_repo.linked_todo_ids(con, session["claude_session_id"])
    return {
        "session": session,
        "messages": transcript.recent(session["claude_session_id"]),
        # 답을 기다리는 선택창. 세션 탭이 선택지 버튼으로 그린다
        "pending_question": transcript.pending_question(session["claude_session_id"]),
        "todos": [
            _with_conditions(con, todo_repo.get(con, todo_id)) for todo_id in todo_ids
        ],
        # 워크트리 탭도 같은 팝업에 있다 — 세션에서 열든 할일에서 열든 같은 이력을 본다
        "worktrees": worktrees.history(con, todo_ids),
    }


def todo_detail(con, todo_id):
    """할일 팝업. 세션 탭도 같은 팝업에 있으므로 잡고 있는 세션을 함께 준다"""
    return {
        "todo": _with_conditions(con, todo_repo.get(con, todo_id)),
        "sessions": session_repo.list_by_todo(con, todo_id),
        # 워크트리 탭용 이력. 병합·삭제된 워크트리도 이름과 상태로 남는다
        "worktrees": worktrees.history(con, [todo_id]),
    }


def _with_conditions(con, todo):
    """착수 조건을 항목으로 쪼개 붙인다 — 팝업이 원문 대신 체크리스트로 그린다.
    붙은 라벨도 싣는다 — 팝업의 라벨 켜고 끄기가 지금 상태를 알아야 한다"""
    return {
        **todo,
        "precondition_items": precondition.items(con, todo["precondition"]),
        "labels": label_repo.list_by_todo(con, todo["id"]),
    }


def scope_guard_block(con, jira_id):
    """scope-guard 가 쓰던 블록 형식 유지. SKILL.md 를 고치지 않기 위함.
    그 Jira 키가 적힌 할일의 트리 맨 위 할일 note(옛 워크스페이스 배경·목표)와 그 트리 할일을 싣는다"""
    normalized = (jira_id or "").upper()
    found = lineage.todo_by_jira(con, normalized)
    root = lineage.root_todo(con, found["id"]) if found else None
    if not root:
        return (
            f'<scope-guard missing="{normalized}">\n'
            f"이 브랜치({normalized})가 적힌 할일이 없다.\n"
            "지침: 첫 응답에서 사용자에게 배경·목적·목표를 물어보고, "
            "답은 작업 대시보드 할일(note)로 남도록 사용자에게 알린다 — 세션이 할일을 만들지 않는다.\n"
            "</scope-guard>"
        )
    lines = [
        f'<scope-guard active="{normalized}" status="{root["status"]}">',
        f"맨 위 할일: #{root['id']} {root['title']}",
        root["note"] or "(배경·목표 미입력)",
        "하위단계:",
    ]
    lines.extend(_todo_lines(con, root["id"]))
    lines.append(SCOPE_GUIDE)
    lines.append("</scope-guard>")
    return "\n".join(lines)


def _classified_block(con, session, todo_id, linked=True):
    root = lineage.root_todo(con, todo_id) or todo_repo.get(con, todo_id)
    category = category_repo.get(con, root["category_id"]) if root.get("category_id") else None
    lines = [
        BLOCK_OPEN.format(session=session["claude_session_id"], state=STATE_CLASSIFIED),
        f"트리: #{root['id']} {root['title']}" + (f" ({category['name']})" if category else ""),
        "배경·목표(맨 위 할일 note):",
        root["note"] or "(미입력)",
        "할일:",
    ]
    lines.extend(_todo_lines(con, root["id"]))
    if not linked:
        lines.append(UNLINKED_GUIDE)
    lines.append(CLASSIFIED_GUIDE)
    lines.append(RELEASE_GUIDE)
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
        "진행 중 트리(맨 위 할일):",
    ]
    active = lineage.open_roots(con, UNCLASSIFIED_TREE_LIMIT)
    if active:
        for root in active:
            category_name = names.get(root["category_id"], "?")
            lines.append(f"  {root['id']}. {root['title']} ({category_name})")
    else:
        lines.append("  (없음)")
    lines.append(UNCLASSIFIED_GUIDE)
    lines.append(RELEASE_GUIDE)
    lines.append(FRESHNESS_GUIDE)
    lines.append(BLOCK_CLOSE)
    return "\n".join(lines)


def _todo_lines(con, root_id):
    """그 트리의 할일(맨 위 제외, 단계·기록 제외)"""
    ids = [todo_id for todo_id in lineage.tree_todo_ids(con, root_id) if todo_id != root_id]
    todos = [todo for todo in (todo_repo.get(con, todo_id) for todo_id in ids) if lineage.is_task(todo)]
    todos.sort(key=lambda todo: (todo["sort_order"] or 0, todo["id"]))
    if not todos:
        return ["  (없음)"]
    # note 는 내용을 넣지 않고 존재만 표시 — 할일 12개 컨텍스트를 다 넣으면 세션이 오염됨.
    # 조건은 반대로 내용을 넣는다. 착수 가능 여부를 보려고 show-note 를 또 불러야 하면
    # 조건을 둔 의미가 없다. 대신 첫 줄만 — '확인:' 명령줄은 show-note 에서 본다
    lines = []
    # 번호는 트리 안 순서(1부터) — sort_order 는 이제 트리 밖까지 한 줄로 매겨져 있어 번호로 쓰면 튄다
    for position, todo in enumerate(todos, start=1):
        marker = f" (컨텍스트 #{todo['id']})" if todo["note"] else ""
        lines.append(
            f"  {position}. [{todo['status']}] {todo['title']}{marker}"
        )
        if todo["precondition"]:
            lines.append(f"     조건: {_first_line(todo['precondition'])}")
    return lines


def _first_line(text):
    parts = (text or "").strip().splitlines()
    return parts[0] if parts else ""
