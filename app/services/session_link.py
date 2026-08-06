"""세션에 주입할 컨텍스트 조립. 여러 엔티티에 걸치므로 service 계층"""
import re

from app.constants import (
    HISTORY_DAY_CHOICES,
    JIRA_PATTERN,
    ONBOARDING_DECLINED_FLAG,
    ONBOARDING_MIN_SESSIONS,
    STATUS_DONE,
    WORKSPACE_ACTIVE,
)
from app.db import meta_get, meta_set
from app.repositories import categories as category_repo
from app.repositories import sessions as session_repo
from app.repositories import subtasks as subtask_repo
from app.repositories import todos as todo_repo
from app.repositories import workspaces as workspace_repo
from app.services import precondition, transcript, worktrees

BLOCK_OPEN = '<work-dashboard session="{session}" state="{state}">'
BLOCK_CLOSE = "</work-dashboard>"
STATE_CLASSIFIED = "classified"
STATE_UNCLASSIFIED = "unclassified"
STATE_ONBOARDING = "onboarding"
STATE_RELEASED = "released"
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
# 해제 뒤 같은 세션이 이어질 때. 끝난 할일에 새 작업을 얹으면 무엇이 끝났는지 알 수 없어진다
RELEASED_GUIDE = (
    "지침: 이 세션이 잡았던 할일은 모두 끝났다(done). "
    "사용자가 새 요청을 하면 끝난 할일에 얹지 말고 새 할일로 진행한다 — "
    "dash.py add-todo <제목> --session 으로 만들고 "
    "dash.py link-todo <todo-id> 로 연결한다. "
    "단발 조회·설명 질문이면 만들지 않는다."
)
# 연결은 착수 선언이지만 늘 그런 것은 아니다 — 이미 끝난 작업을 뒤늦게 연결하는 일도 있다.
# 무엇이 끝난 것인지는 작업 내용을 본 쪽만 알므로 코드가 추측하지 않고 여기서 규칙을 알린다
LINK_STATUS_RULE = (
    "연결 상태는 기본 doing 이고, 이미 master 에 병합돼 끝난 작업이면 "
    "--status done 을 붙인다."
)
# 브랜치로 워크스페이스는 알아냈지만 아직 할일을 안 잡은 세션. 잡아야 보드에 보인다
UNLINKED_GUIDE = (
    "미연결: 이 세션은 아직 어느 할일도 잡지 않았다. 위 목록에서 이번 작업에 해당하는 "
    "할일을 dash.py link-todo <todo-id> 로 잡는다. 해당하는 것이 없으면 "
    "dash.py add-todo <제목> --workspace <id> 로 만들고 연결한다. "
    + LINK_STATUS_RULE
)
CLASSIFIED_GUIDE = (
    "지침: 이 세션은 위 워크스페이스 작업이다. 배경·목적에 맞게 진행하고 "
    "범위를 벗어나는 작업은 착수 전 사용자에게 확인받는다. "
    "할일에 (컨텍스트) 표시가 있으면 착수 전 dash.py show-note <id> 로 읽는다. "
    "'조건:' 이 붙은 할일은 그 조건이 충족됐는지 먼저 확인하고, "
    "미충족이면 착수하지 않고 사용자에게 알린다."
)
UNCLASSIFIED_GUIDE = (
    "지침: 이번 세션을 한 번 분류한다. "
    "(1) 위치와 질문 내용으로 카테고리를 정하고 확인 없이 등록한다. "
    "(2) 관련된 진행 중 워크스페이스가 있다고 판단되면 사용자에게 확인받고 등록한다. "
    "없으면 카테고리만 등록한다. "
    "등록: python3 dash.py classify --category <이름> [--workspace <id>] "
    "코드·문서를 바꾸거나 여러 턴에 걸치거나 산출물이 남는 작업이면 "
    "dash.py add-todo 로 할일을 만들고 dash.py link-todo <todo-id> 로 연결한다. "
    + LINK_STATUS_RULE
    + " 단발 조회·설명 질문이면 할일을 만들지 않는다. "
    "분류 등록 직후에는 이 세션에 워크스페이스 블록이 다시 주입되지 않으므로, "
    "dash.py show-todo --session 으로 할일을 직접 확인하고 "
    "(컨텍스트) 표시가 있으면 dash.py show-note <id> 로 읽는다."
)
ONBOARDING_GUIDE = (
    "지침: 등록된 워크스페이스가 하나도 없다. 초기 설정을 진행한다. "
    "(1) 먼저 사용자에게 묻는다 — 최근 며칠 치 Claude 히스토리를 보고 자동 분류할지. "
    f"{' / '.join(f'{days}일' for days in HISTORY_DAY_CHOICES)} / 자동 분류 안 함. "
    "'안 함' 이면 python3 dash.py onboard --skip 을 실행하고 여기서 끝낸다 "
    "— 이후 이 질문은 다시 뜨지 않는다. "
    "(2) python3 dash.py scan-history --days <선택> 을 실행한다. 세션당 한 줄로 나온다. "
    "(3) 그 출력을 읽고 같은 일감끼리 묶는다. "
    "묶는 단위는 기본적으로 작업 위치(디렉토리) 하나 = 워크스페이스 하나다. "
    "한 저장소 안의 기획·구현·배포는 워크스페이스가 아니라 착수 순서대로 놓는 할일이다. "
    "홈 디렉토리나 scratch 성격의 위치처럼 서로 무관한 일이 섞인 곳만 내용으로 쪼갠다. "
    f"세션 {ONBOARDING_MIN_SESSIONS}건 미만인 묶음은 워크스페이스로 만들지 않고 "
    "맨 아래 '(기타: 세션 N건 — 워크스페이스 미생성)' 한 줄로만 표시한다. "
    "(4) 카테고리 두 안을 제시하고 고르게 한다 — A 는 위 디폴트 그대로, "
    "B 는 히스토리에서 도출한 목록. B 를 고르면 B 에만 있는 것을 dash.py add-category 로 "
    "추가한다. 어느 쪽이든 기존 카테고리는 지우지 않으며, 이 사실을 질문할 때 함께 알리고 "
    "사용자가 지목해 빼달라고 할 때만 지운다. "
    "(5) 카테고리 > 워크스페이스 트리를 보여주고 확인받는다. 워크스페이스마다 "
    "이름·목표·세션 건수·기간을 적는다. 항목별로 하나씩 묻지 말고 트리 전체를 보여준 뒤 "
    "자유 수정을 반복한다. 확정 전에는 DB 에 쓰지 않는다. "
    "(6) 확정되면 dash.py add-workspace <카테고리> <이름> --goal <목표> 로 등록한다. "
    "배경·목적·고려사항은 이 단계에서 채우지 않는다. "
    "(7) 워크스페이스마다 할일을 dash.py add-todo --workspace <id> 로 만들고, "
    "히스토리로 미루어 짐작되는 상태를 dash.py set-status todo <id> <todo|doing|done> 로 넣는다. "
    "할일은 착수 가능한 순서로 놓는다(중요도 순이 아니다). "
    "할일을 반드시 만드는 이유 — 보드는 할일이 0개인 워크스페이스를 통째로 감춘다. "
    "워크스페이스만 만들면 사용자 화면에는 아무것도 안 나타나 초기 설정이 실패한 것처럼 보인다. "
    "상태 추정이 틀려도 사용자가 보드에서 바로 고칠 수 있으므로 비워두는 것보다 낫다. "
    "(8) 할일마다 그 할일을 뽑아낸 근거 세션을 "
    "dash.py link-todo <세션앞머리> <todo-id> --past 로 연결한다. "
    "앞머리는 scan-history 출력 각 줄 맨 앞에 찍혀 있다. --past 는 없는 세션을 ended 로 "
    "등록하고 할일 상태를 건드리지 않는다(끝난 세션 연결은 착수 선언이 아니다). "
    "이어서 그 세션들에서 이 할일을 착수할 때 필요한 구체 정보를 뽑아 "
    "dash.py add-todo 의 --note 또는 웹에서 note 에 적는다 — "
    "실패한 명령과 오류 문구, 확정된 수치·기준, 제외하기로 한 범위, 참고 경로·주소처럼 "
    "다시 찾으려면 시간이 드는 것들이다. 근거 세션이 없는 할일은 연결하지 말고 "
    "note 에 아직 착수 세션이 없다는 사실과 선행 조건을 적는다. "
    "(9) 마지막으로 배경·목적·고려사항도 채울지 묻는다 — "
    "1 아니요(기본) / 2 순차: 워크스페이스 하나를 채우고 확인받고 다음으로 / "
    "3 병렬: 전부 추정해 한 번에 보여주고 한 번만 확인. "
    "추정으로 채운 내용은 이후 매 세션 주입되므로 2 가 기본 동작이고, "
    "3 은 사용자가 속도를 명시적으로 고를 때만 쓴다. "
    "채울 때의 기준은 '매 세션 주입돼도 값어치가 있는가' 하나다 — "
    "배경은 왜 이 일이 존재하는가(도메인의 문제, 시간이 지나도 안 변하는 것), "
    "목적은 그 문제를 어떤 방향으로 푸는가, 목표는 끝났다고 판정할 수 있는 상태, "
    "고려사항은 벗어나면 안 되는 제약·금지다. "
    "기술 스택·URL·포트·저장소 주소·재현 절차처럼 특정 할일에서만 필요한 것은 "
    "워크스페이스가 아니라 그 할일의 note 로 내린다."
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
        return _classified_block(con, session, session["workspace_id"])
    by_branch = _workspace_by_branch(con, session)
    if by_branch:
        # 소속은 아직 없다(할일 미연결). 워크스페이스 컨텍스트만 브랜치로 되찾아 준다 —
        # 저장하지 않고 매번 다시 계산하므로 세션에 워크스페이스가 남지는 않는다
        return _classified_block(con, session, by_branch["id"], linked=False)
    if needs_onboarding(con):
        return _onboarding_block(con, session)
    return _unclassified_block(con, session)


def _workspace_by_branch(con, session):
    jira = jira_from_branch(session["git_branch"])
    return workspace_repo.get_by_jira(con, jira) if jira else None


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
    """워크스페이스가 없고 사용자가 거절한 적도 없을 때.

    완료 플래그는 두지 않는다 — 온보딩이 끝나면 워크스페이스가 생겨 첫 조건이 저절로 깨진다.
    상태를 플래그와 실제 데이터 두 곳에 적으면 어긋나고, 그때 믿어야 하는 건 실제 데이터다
    """
    if meta_get(con, ONBOARDING_DECLINED_FLAG):
        return False
    return not workspace_repo.list_all(con)


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
        # 하위할일까지 실어준다 — 분류 직후 자동 생성된 것을 팝업에서 바로 확인해야 함
        "todos": [
            {
                **_with_conditions(con, todo_repo.get(con, todo_id)),
                "subtasks": subtask_repo.list_by_todo(con, todo_id),
            }
            for todo_id in todo_ids
        ],
        # 워크트리 탭도 같은 팝업에 있다 — 세션에서 열든 할일에서 열든 같은 이력을 본다
        "worktrees": worktrees.history(con, todo_ids),
    }


def todo_detail(con, todo_id):
    """할일 팝업. 세션 탭도 같은 팝업에 있으므로 잡고 있는 세션을 함께 준다.

    하위할일은 싣지 않는다 — 개요 탭이 안 그리고, 펼쳐 보는 자리는 보드 카드다
    """
    return {
        "todo": _with_conditions(con, todo_repo.get(con, todo_id)),
        "sessions": session_repo.list_by_todo(con, todo_id),
        # 워크트리 탭용 이력. 병합·삭제된 워크트리도 이름과 상태로 남는다
        "worktrees": worktrees.history(con, [todo_id]),
    }


def _with_conditions(con, todo):
    """착수 조건을 항목으로 쪼개 붙인다 — 팝업이 원문 대신 체크리스트로 그린다"""
    return {**todo, "precondition_items": precondition.items(con, todo["precondition"])}


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


def _classified_block(con, session, workspace_id, linked=True):
    workspace = workspace_repo.get(con, workspace_id)
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
    if not linked:
        lines.append(UNLINKED_GUIDE)
    lines.append(CLASSIFIED_GUIDE)
    lines.append(RELEASE_GUIDE)
    lines.append(FRESHNESS_GUIDE)
    lines.append(BLOCK_CLOSE)
    return "\n".join(lines)


def _onboarding_block(con, session):
    categories = category_repo.list_all(con)
    lines = [
        BLOCK_OPEN.format(session=session["claude_session_id"], state=STATE_ONBOARDING),
        f"현재 위치: {session['cwd'] or '(알 수 없음)'}",
        "카테고리(디폴트): " + " / ".join(row["name"] for row in categories),
        "워크스페이스: (없음)",
        ONBOARDING_GUIDE,
        FRESHNESS_GUIDE,
        BLOCK_CLOSE,
    ]
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
    lines.append(RELEASE_GUIDE)
    lines.append(FRESHNESS_GUIDE)
    lines.append(BLOCK_CLOSE)
    return "\n".join(lines)


def _todo_lines(con, workspace_id):
    todos = todo_repo.list_by_workspace(con, workspace_id)
    if not todos:
        return ["  (없음)"]
    # note 는 내용을 넣지 않고 존재만 표시 — 할일 12개 컨텍스트를 다 넣으면 세션이 오염됨.
    # 조건은 반대로 내용을 넣는다. 착수 가능 여부를 보려고 show-note 를 또 불러야 하면
    # 조건을 둔 의미가 없다. 대신 첫 줄만 — '확인:' 명령줄은 show-note 에서 본다
    lines = []
    for todo in todos:
        marker = f" (컨텍스트 #{todo['id']})" if todo["note"] else ""
        lines.append(
            f"  {todo['sort_order']}. [{todo['status']}] {todo['title']}{marker}"
        )
        if todo["precondition"]:
            lines.append(f"     조건: {_first_line(todo['precondition'])}")
    return lines


def _first_line(text):
    parts = (text or "").strip().splitlines()
    return parts[0] if parts else ""
