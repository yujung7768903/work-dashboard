#!/usr/bin/env python3
"""작업 대시보드 CLI. 파싱·위임·출력만 하고 도메인 로직은 갖지 않음"""
import argparse
import json
import sys
from datetime import datetime

from app.constants import UNASSIGNED_LABEL
from app.db import connect
from app.errors import DomainError, NotFound, Validation
from app.repositories import categories as category_repo
from app.repositories import subtasks as subtask_repo
from app.repositories import todos as todo_repo
from app.repositories import sessions as session_repo
from app.repositories import workspaces as workspace_repo
from app.services import board, planning, session_link, usage

NONE_LITERAL = "none"
REORDER_KINDS = ("categories", "workspaces", "todos", "subtasks")
STATUS_TARGETS = ("todo", "subtask", "workspace")
CONTEXT_ARGS = ("background", "purpose", "goal", "considerations")
DETAIL_LABELS = (
    ("배경", "background"),
    ("목적", "purpose"),
    ("목표", "goal"),
    ("고려사항", "considerations"),
)
# 조건은 참·거짓이 갈리는 문장으로. 그래야 읽는 쪽이 탐색 없이 착수 여부를 판정한다
PRECONDITION_HELP = (
    "착수 가능 조건. 참/거짓이 갈리는 한 문장으로 쓴다."
    " 다른 할일이 조건이면 #id, 자동 확인이 되면 둘째 줄에 '확인: <명령>'"
)
EXIT_OK = 0
EXIT_ERROR = 1
USAGE_CLI_DAYS = 7
COMPACT_UNITS = ((1_000_000_000, "B"), (1_000_000, "M"), (1_000, "K"))
SECONDS_PER_MINUTE = 60
SECONDS_PER_HOUR = 3600


def main(argv=None):
    args = _build_parser().parse_args(argv)
    con = connect()
    try:
        args.handler(con, args)
    except DomainError as error:
        print(str(error), file=sys.stderr)
        return EXIT_ERROR
    return EXIT_OK


def _build_parser():
    parser = argparse.ArgumentParser(description="작업 대시보드 CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    listing = sub.add_parser("ls", help="전체 트리 개요")
    listing.add_argument(
        "--group-by",
        default=board.GROUP_BY_WORKSPACE,
        choices=board.GROUP_BY_CHOICES,
        dest="group_by",
    )
    _add_json_flag(listing)
    listing.set_defaults(handler=_cmd_ls)

    upcoming = sub.add_parser("next", help="다음에 할 일 1건")
    upcoming.add_argument("--workspace", type=int, default=None)
    upcoming.add_argument("--session", default=None,
                          help="이 세션이 잡은 할일은 후보로 남기고 남의 것은 뺌")
    _add_json_flag(upcoming)
    upcoming.set_defaults(handler=_cmd_next)

    show = sub.add_parser("show", help="워크스페이스 상세")
    show.add_argument("target", help="워크스페이스 id 또는 Jira ID")
    _add_json_flag(show)
    show.set_defaults(handler=_cmd_show)

    add_category = sub.add_parser("add-category")
    add_category.add_argument("name")
    add_category.set_defaults(handler=_cmd_add_category)

    add_workspace = sub.add_parser("add-workspace")
    add_workspace.add_argument("category")
    add_workspace.add_argument("name")
    for field in CONTEXT_ARGS:
        add_workspace.add_argument(f"--{field}", default=None)
    add_workspace.add_argument("--jira", default=None)
    add_workspace.set_defaults(handler=_cmd_add_workspace)

    add_todo = sub.add_parser("add-todo")
    add_todo.add_argument("title")
    add_todo.add_argument("--category", default=None)
    add_todo.add_argument("--workspace", default=None)
    add_todo.add_argument("--session", default=None,
                          help="이 세션이 붙은 워크스페이스에 추가")
    add_todo.add_argument("--note", default=None, help="이 할일에만 필요한 컨텍스트")
    add_todo.add_argument("--precondition", default=None, help=PRECONDITION_HELP)
    add_todo.set_defaults(handler=_cmd_add_todo)

    add_subtask = sub.add_parser("add-subtask")
    add_subtask.add_argument("todo_id", type=int)
    add_subtask.add_argument("title")
    add_subtask.add_argument("--precondition", default=None, help=PRECONDITION_HELP)
    add_subtask.set_defaults(handler=_cmd_add_subtask)

    move_todo = sub.add_parser("move-todo")
    move_todo.add_argument("todo_id", type=int)
    move_todo.add_argument("--workspace", required=True, help="워크스페이스 id 또는 none")
    move_todo.set_defaults(handler=_cmd_move_todo)

    set_status = sub.add_parser("set-status")
    set_status.add_argument("target", choices=STATUS_TARGETS)
    set_status.add_argument("item_id", type=int)
    set_status.add_argument("status")
    set_status.set_defaults(handler=_cmd_set_status)

    reorder = sub.add_parser("reorder")
    reorder.add_argument("kind", choices=REORDER_KINDS)
    reorder.add_argument(
        "--scope",
        default=None,
        help="todos 면 워크스페이스 id(미분류는 none), subtasks 면 할일 id",
    )
    reorder.add_argument("ids", nargs="+", type=int)
    reorder.set_defaults(handler=_cmd_reorder)

    remove_category = sub.add_parser("rm-category")
    remove_category.add_argument("category_id", type=int)
    remove_category.set_defaults(handler=_cmd_rm_category)

    done_today = sub.add_parser("done-today")
    done_today.add_argument("--date", default=None)
    _add_json_flag(done_today)
    done_today.set_defaults(handler=_cmd_done_today)

    sessions = sub.add_parser("sessions", help="활성 세션 목록")
    _add_json_flag(sessions)
    sessions.set_defaults(handler=_cmd_sessions)

    classify = sub.add_parser("classify", help="세션 분류 등록")
    classify.add_argument("session")
    classify.add_argument("--category", default=None)
    classify.add_argument("--workspace", type=int, default=None)
    classify.set_defaults(handler=_cmd_classify)

    show_todo = sub.add_parser("show-todo", help="할일 목록 (id·제목·컨텍스트 유무)")
    show_todo.add_argument("--workspace", type=int, default=None)
    show_todo.add_argument("--session", default=None)
    _add_json_flag(show_todo)
    show_todo.set_defaults(handler=_cmd_show_todo)

    show_note = sub.add_parser("show-note", help="할일 컨텍스트(note) 전문")
    show_note.add_argument("todo_id", type=int)
    _add_json_flag(show_note)
    show_note.set_defaults(handler=_cmd_show_note)

    link_todo = sub.add_parser("link-todo", help="세션이 만든 할일 연결")
    link_todo.add_argument("session")
    link_todo.add_argument("todo_id", type=int)
    link_todo.set_defaults(handler=_cmd_link_todo)

    usage_cmd = sub.add_parser("usage", help="한도 사용률과 토큰 추이")
    _add_json_flag(usage_cmd)
    usage_cmd.set_defaults(handler=_cmd_usage)

    return parser


def _add_json_flag(parser):
    parser.add_argument(
        "--json", action="store_true", dest="as_json", help="Claude 파싱용 JSON 출력"
    )


def _cmd_ls(con, args):
    tree = board.tree(con, args.group_by)
    if args.as_json:
        _emit_json(tree)
        return
    for group in tree["groups"]:
        print(f"{group['name']}  {group['done_count']}/{group['total_count']}")
        for todo in group["todos"]:
            print(f"  [{todo['status']}] {todo['id']}. {todo['title']}")
            for subtask in todo["subtasks"]:
                print(f"      - [{subtask['status']}] {subtask['title']}")


def _cmd_next(con, args):
    picked = planning.next_todo(con, args.workspace, args.session)
    if args.as_json:
        _emit_json(picked)
        return
    if not picked:
        print("다음에 할 일이 없음")
        return
    scope = picked["workspace"]["name"] if picked["workspace"] else UNASSIGNED_LABEL
    print(f"{scope} / {picked['todo']['title']}")


def _cmd_show(con, args):
    workspace = _resolve_workspace(con, args.target)
    todos = todo_repo.list_by_workspace(con, workspace["id"])
    if args.as_json:
        _emit_json({"workspace": workspace, "todos": todos})
        return
    print(f"{workspace['name']} [{workspace['status']}]")
    for label, key in DETAIL_LABELS:
        print(f"{label}: {workspace[key] or '(미입력)'}")
    for todo in todos:
        print(f"  [{todo['status']}] {todo['id']}. {todo['title']}")


def _cmd_add_category(con, args):
    print(category_repo.create(con, args.name)["name"])


def _cmd_add_workspace(con, args):
    category = category_repo.get_by_name(con, args.category)
    created = workspace_repo.create(
        con,
        category["id"],
        args.name,
        background=args.background,
        purpose=args.purpose,
        goal=args.goal,
        considerations=args.considerations,
        jira_id=args.jira,
    )
    print(f"{created['id']}. {created['name']}")


def _cmd_add_todo(con, args):
    category_id = (
        category_repo.get_by_name(con, args.category)["id"] if args.category else None
    )
    workspace_id = int(args.workspace) if args.workspace else None
    if args.session and workspace_id is None and category_id is None:
        workspace_id, category_id = _scope_from_session(con, args.session)
    created = todo_repo.create(
        con,
        args.title,
        category_id=category_id,
        workspace_id=workspace_id,
        note=args.note,
        precondition=args.precondition,
    )
    print(f"{created['id']}. {created['title']}")


def _scope_from_session(con, claude_session_id):
    """세션이 붙은 워크스페이스(없으면 카테고리)에 할일을 만들기 위한 소속 결정"""
    session = session_repo.get(con, claude_session_id)
    if session["workspace_id"] is None and session["category_id"] is None:
        raise Validation("세션이 아직 분류되지 않아 할일을 붙일 곳이 없음")
    return session["workspace_id"], session["category_id"]


def _cmd_add_subtask(con, args):
    created = subtask_repo.create(
        con, args.todo_id, args.title, precondition=args.precondition
    )
    print(f"{created['id']}. {created['title']}")


def _cmd_move_todo(con, args):
    workspace_id = None if args.workspace == NONE_LITERAL else int(args.workspace)
    moved = todo_repo.update(con, args.todo_id, workspace_id=workspace_id)
    scope = (
        workspace_repo.get(con, workspace_id)["name"]
        if workspace_id
        else UNASSIGNED_LABEL
    )
    print(f"{moved['title']} → {scope}")


def _cmd_set_status(con, args):
    updaters = {
        "workspace": workspace_repo.update,
        "subtask": subtask_repo.update,
        "todo": todo_repo.update,
    }
    updated = updaters[args.target](con, args.item_id, status=args.status)
    print(f"{updated.get('title') or updated.get('name')} → {updated['status']}")


def _cmd_reorder(con, args):
    if args.kind == "categories":
        category_repo.reorder(con, args.ids)
    elif args.kind == "workspaces":
        workspace_repo.reorder(con, args.ids)
    elif args.kind == "todos":
        scope = None if args.scope in (None, NONE_LITERAL) else int(args.scope)
        todo_repo.reorder(con, args.ids, scope)
    else:
        subtask_repo.reorder(con, args.ids, int(args.scope))
    print(f"{len(args.ids)}건 재정렬")


def _cmd_rm_category(con, args):
    category_repo.delete(con, args.category_id)
    print("삭제됨")


def _cmd_done_today(con, args):
    rows = planning.done_on(con, args.date)
    if args.as_json:
        _emit_json(rows)
        return
    if not rows:
        print("완료한 할일이 없음")
        return
    for row in rows:
        print(f"- {row['workspace_name']} / {row['title']}")


def _cmd_sessions(con, args):
    payload = session_link.active_payload(con)
    if args.as_json:
        _emit_json(payload)
        return
    if not payload["sessions"]:
        print("돌고 있는 세션이 없음")
    for session in payload["sessions"]:
        scope = session["workspace_name"] or session["category_name"] or "분류 전"
        print(f"[{session['state']}] {scope} / {session['last_prompt'] or '(지시 없음)'}")
    if payload["unclassified_count"]:
        print(f"분류 전 {payload['unclassified_count']}건")


def _cmd_classify(con, args):
    updated = session_repo.classify(
        con, args.session, category_name=args.category, workspace_id=args.workspace
    )
    scope = updated["workspace_id"] or "-"
    print(f"분류됨: category={updated['category_id']} workspace={scope}")


def _cmd_show_todo(con, args):
    """할일 목록. 컨텍스트 전문은 show-note 로 따로 꺼냄"""
    todos = _todos_in_scope(con, args)
    if args.as_json:
        _emit_json(todos)
        return
    if not todos:
        print("할일이 없음")
        return
    for todo in todos:
        marker = " (컨텍스트)" if todo["note"] else ""
        print(f"{todo['id']}. [{todo['status']}] {todo['title']}{marker}")
        if todo["precondition"]:
            print(f"    조건: {_one_line(todo['precondition'])}")


def _todos_in_scope(con, args):
    """--workspace / --session 이 있으면 그 범위, 없으면 전체"""
    if args.session:
        workspace_id, category_id = _scope_from_session(con, args.session)
        if workspace_id is not None:
            return todo_repo.list_by_workspace(con, workspace_id)
        return todo_repo.list_by_category(con, category_id)
    if args.workspace is not None:
        workspace_repo.get(con, args.workspace)
        return todo_repo.list_by_workspace(con, args.workspace)
    return [
        todo
        for group in board.tree(con, board.GROUP_BY_CATEGORY)["groups"]
        for todo in group["todos"]
    ]


def _cmd_show_note(con, args):
    todo = todo_repo.get(con, args.todo_id)
    subtasks = subtask_repo.list_by_todo(con, args.todo_id)
    if args.as_json:
        _emit_json({"todo": todo, "subtasks": subtasks})
        return
    print(f"[{todo['status']}] {todo['id']}. {todo['title']}")
    if todo["precondition"]:
        print(f"착수 조건: {todo['precondition']}")
    print(f"컨텍스트: {todo['note'] or '(없음)'}")
    for subtask in subtasks:
        print(f"  - [{subtask['status']}] {subtask['title']}")
        if subtask["precondition"]:
            print(f"      조건: {subtask['precondition']}")


def _one_line(text):
    """목록에서는 조건 첫 줄만. '확인:' 명령줄까지 늘어놓으면 목록이 안 읽힌다"""
    first = (text or "").strip().splitlines()
    return first[0] if first else ""


def _cmd_link_todo(con, args):
    session_repo.link_todo(con, args.session, args.todo_id)
    print(f"할일 {args.todo_id} 연결됨")


def _cmd_usage(con, args):
    """/usage 와 같은 창 + 최근 토큰. 낡은 값일 수 있다는 사실을 값과 같이 보여준다"""
    payload = usage.snapshot(con)
    if args.as_json:
        _emit_json(payload)
        return
    print(f"플랜: {payload['plan'] or '알 수 없음'}")
    if not payload["windows"]:
        print(f"한도 정보 없음 — {payload['limit_source']} 를 읽을 수 없음")
    for window in payload["windows"]:
        reset = _reset_text(window["resets_at"])
        print(f"{window['title']}: {window['used_percentage']}%  (초기화 {reset})")
    if payload["windows"] and payload["stale"]:
        print(f"※ {_age_text(payload['stale_seconds'])} 전 값 — statusline 이 그려질 때만 갱신됨")
    print(f"※ 사이드카에 없는 창: {', '.join(payload['missing_windows'])}")
    for day in payload["tokens"]["days"][-USAGE_CLI_DAYS:]:
        print(f"{day['date']}  {_compact(day['total'])} 토큰  ${day['cost_usd']}")


def _compact(value):
    for size, suffix in COMPACT_UNITS:
        if value >= size:
            return f"{value / size:.1f}{suffix}"
    return str(value)


def _reset_text(epoch_seconds):
    if not epoch_seconds:
        return "시각 미확인"
    return datetime.fromtimestamp(epoch_seconds).astimezone().strftime("%m/%d %H:%M")


def _age_text(seconds):
    if seconds is None:
        return "시각 미확인"
    if seconds < SECONDS_PER_MINUTE:
        return f"{seconds}초"
    if seconds < SECONDS_PER_HOUR:
        return f"{seconds // SECONDS_PER_MINUTE}분"
    return f"{seconds // SECONDS_PER_HOUR}시간"


def _resolve_workspace(con, target):
    """숫자면 id, 아니면 Jira ID 로 조회"""
    if target.isdigit():
        return workspace_repo.get(con, int(target))
    found = workspace_repo.get_by_jira(con, target)
    if not found:
        raise NotFound(f"'{target}' 에 해당하는 워크스페이스 없음")
    return found


def _emit_json(payload):
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    sys.exit(main())
