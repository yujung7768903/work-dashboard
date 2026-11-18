#!/usr/bin/env python3
"""작업 대시보드 CLI. 파싱·위임·출력만 하고 도메인 로직은 갖지 않음"""
import argparse
import json
import os
import sys
from datetime import datetime

from app.constants import (
    BASIS_BACKGROUND,
    BASIS_PURPOSE,
    BASIS_TRIGGER,
    EDGE_CONFIRMED,
    EDGE_PROPOSED,
    EDGE_REJECTED,
    NODE_CONTEXT,
    NODE_DOC,
    NODE_SESSION,
    NODE_TODO,
    REL_EVIDENCE,
    REL_PARENT,
    REL_PRECEDES,
    REL_RELATED,
    GTASKS_CLIENT_ID_ENV,
    GTASKS_CLIENT_SECRET_ENV,
    HISTORY_DAY_CHOICES,
    LANGUAGES,
    PRECONDITION_HINT,
    SECONDS_PER_MINUTE,
    SESSION_ID_ENV,
    STALE_JUDGE_BATCH,
    STATUS_DOING,
    STATUS_DONE,
)
from app import evidence as evidence_refs
from app.db import connect
from app.errors import DomainError, NeedsConfirm, Validation
from app.repositories import categories as category_repo
from app.repositories import graph as graph_repo
from app.repositories import todos as todo_repo
from app.repositories import sessions as session_repo
from app.repositories import settings as settings_repo
from app.repositories import autorun as autorun_repo
from app.services import (
    autorun,
    gtasks,
    gtasks_auth,
    history,
    lineage,
    merge,
    release,
    session_link,
    session_name,
    session_results,
    stale_judge,
    usage,
)

NONE_LITERAL = "none"
UNTITLED_TREE = "맥락"  # 맨 위가 할일이 아닌 트리(맥락 노드 아래)
# 조건은 참·거짓이 갈리는 문장으로. 그래야 읽는 쪽이 탐색 없이 착수 여부를 판정한다.
# 문구는 팝업과 공유한다 (app.constants.PRECONDITION_HINT)
PRECONDITION_HELP = f"착수 가능 조건. {PRECONDITION_HINT}"
AUTORUN_ACTIONS = ("on", "off", "status")
AUTORUN_RECENT = 5  # 상태 출력에 붙이는 최근 실행 건수
EXIT_OK = 0
EXIT_ERROR = 1
# 세션 인자를 생략했다는 표시. 값이 아니라 자리표라 파싱 뒤 환경변수로 바뀐다
SELF_SESSION = object()
SESSION_ARG_HELP = (
    f"생략하면 {SESSION_ID_ENV} 가 가리키는 이 세션."
    " 터미널에서 직접 실행할 때는 값을 적는다"
)
# 사용률 막대와 다른 줄에 그리므로 폭은 넉넉하다. 한글은 두 칸을 먹으니 줄 폭의 절반쯤
STATUSLINE_TITLE_MAX = 40
USAGE_CLI_DAYS = 7
# 삭제를 먼저 보여준다 — 되돌리기 어려운 것부터 눈에 들어와야 한다
GTASKS_ACTION_LABELS = (
    ("deleted_local", "대시보드에서 삭제"),
    ("deleted_remote", "구글에서 삭제"),
    ("created_local", "폰에서 받아 새로 만듦"),
    ("pulled", "폰이 최신이라 반영"),
    ("created_remote", "구글로 새로 보냄"),
    ("pushed", "대시보드가 최신이라 밀어넣음"),
    ("skipped", "규칙에 막혀 건너뜀"),
)
COMPACT_UNITS = ((1_000_000_000, "B"), (1_000_000, "M"), (1_000, "K"))
SECONDS_PER_HOUR = 3600


def main(argv=None):
    args = _build_parser().parse_args(argv)
    con = connect()
    try:
        if getattr(args, "session", None) is SELF_SESSION:
            args.session = _self_session()
        args.handler(con, args)
    except DomainError as error:
        print(str(error), file=sys.stderr)
        return EXIT_ERROR
    return EXIT_OK


def _build_parser():
    parser = argparse.ArgumentParser(description="작업 대시보드 CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    listing = sub.add_parser("ls", help="전체 트리 개요 (맨 위 할일별)")
    _add_json_flag(listing)
    listing.set_defaults(handler=_cmd_ls)

    add_category = sub.add_parser("add-category")
    add_category.add_argument("name")
    add_category.set_defaults(handler=_cmd_add_category)

    set_parent = sub.add_parser(
        "set-parent", help="상위 할일 변경 (none 이면 트리 맨 위로)"
    )
    set_parent.add_argument("todo_id", type=int)
    set_parent.add_argument("parent", help="상위 할일 id 또는 none")
    set_parent.set_defaults(handler=_cmd_set_parent)

    link = sub.add_parser(
        "link",
        help="관계 잇기. 상위: 앞이 상위·뒤가 하위 / 선행: 앞을 먼저 끝내야 뒤를 함 / 근거: 할일 → 문서 / 관련",
    )
    link.add_argument("relation", choices=sorted(LINK_RELATIONS), help="상위·선행·근거·관련 (parent·precedes·evidence·related)")
    link.add_argument("source", help=NODE_HELP)
    link.add_argument("target", help=NODE_HELP)
    link.add_argument("--basis", choices=sorted(LINK_BASES), help="상위일 때 기준: 계기·목적·배경")
    link.add_argument("--evidence", default=None, help="근거 문장 — 왜 이 연결인지 원문 한 줄")
    link.add_argument("--proposed", action="store_true", help="확정이 아니라 제안으로 — 사람이 화면에서 확인·거절")
    link.set_defaults(handler=_cmd_link)

    edges = sub.add_parser("edges", help="그 노드에 닿은 관계 보기 (수행 포함)")
    edges.add_argument("node", help=NODE_HELP)
    edges.set_defaults(handler=_cmd_edges)

    edge_state = sub.add_parser("edge", help="연결 확인·거절·삭제")
    edge_state.add_argument("action", choices=("confirm", "reject", "rm"))
    edge_state.add_argument("edge_id", type=int)
    edge_state.set_defaults(handler=_cmd_edge)

    add_context = sub.add_parser("add-context", help="맥락(할일은 아니지만 배경이 되는 묶음) 추가 — 트리의 맨 위")
    add_context.add_argument("title")
    add_context.add_argument("--category", default=None, help="카테고리 이름")
    add_context.add_argument("--note", default=None)
    add_context.set_defaults(handler=_cmd_add_context)

    collect = sub.add_parser(
        "collect-results",
        help="세션 결과물(Confluence·Jira·PR·아티팩트·사이트·파일)을 transcript 에서 다시 뽑아 결과 관계로 잇기",
    )
    collect.add_argument("--session", default=None, help="이 세션만 (기본: 대시보드가 아는 세션 전부)")
    collect.add_argument("--dry-run", action="store_true", dest="dry_run", help="DB 를 안 바꾸고 뽑힌 것만 보기")
    collect.add_argument("--verbose", action="store_true", help="결과마다 한 줄")
    collect.set_defaults(handler=_cmd_collect_results)

    edit_todo = sub.add_parser("edit-todo", help="할일 제목·note·착수조건·우선순위 수정")
    edit_todo.add_argument("todo_id", type=int)
    edit_todo.add_argument("--title", default=None)
    edit_todo.add_argument("--note", default=None, help="이 할일에만 필요한 컨텍스트")
    edit_todo.add_argument("--precondition", default=None, help=PRECONDITION_HELP)
    edit_todo.add_argument(
        "--priority", default=None, help="1 이상 정수, 클수록 높음. '-' 를 주면 우선순위를 없앤다"
    )
    edit_todo.set_defaults(handler=_cmd_edit_todo)

    remove_category = sub.add_parser("rm-category")
    remove_category.add_argument("category_id", type=int)
    remove_category.add_argument(
        "--force",
        action="store_true",
        help="분류된 세션이 있어도 미분류로 내리고 삭제",
    )
    remove_category.set_defaults(handler=_cmd_rm_category)

    sessions = sub.add_parser("sessions", help="활성 세션 목록")
    _add_json_flag(sessions)
    sessions.set_defaults(handler=_cmd_sessions)

    show_todo = sub.add_parser("show-todo", help="이 세션이 잡은 할일 (id·상태·제목·컨텍스트 유무)")
    _add_session_arg(show_todo, required=False, note="그 세션이 잡은 할일. 생략해도 이 세션.")
    _add_json_flag(show_todo)
    show_todo.set_defaults(handler=_cmd_show_todo)

    show_note = sub.add_parser("show-note", help="할일 컨텍스트(note) 전문")
    show_note.add_argument("todo_id", type=int)
    _add_json_flag(show_note)
    show_note.set_defaults(handler=_cmd_show_note)

    link_todo = sub.add_parser("link-todo", help="이 세션이 착수하는 할일 연결")
    _add_session_arg(link_todo)
    link_todo.add_argument("todo_id", type=int)
    link_todo.add_argument(
        "--status",
        choices=(STATUS_DOING, STATUS_DONE),
        default=None,
        help="연결하며 넣을 상태. 기본은 doing. 이미 master 에 병합된 작업이면 done",
    )
    link_todo.add_argument(
        "--past",
        action="store_true",
        help="끝난 히스토리 세션. scan-history 가 찍은 앞머리로 지정할 수 있고,"
        " 없으면 ended 로 등록한다. 할일 상태는 바꾸지 않는다",
    )
    link_todo.set_defaults(handler=_cmd_link_todo)

    merge_cmd = sub.add_parser(
        "merge", help="워크트리 브랜치를 master 로 병합 (상태 확인·테스트·해제까지 한 번에)"
    )
    _add_session_arg(merge_cmd)
    merge_cmd.add_argument("--worktree", default=None, help="기본값은 세션의 작업 위치")
    merge_cmd.add_argument(
        "--message", default=None, help="병합 커밋 제목. 기본값은 브랜치 첫 커밋 제목"
    )
    merge_cmd.add_argument(
        "--test",
        default=None,
        help=f"테스트 명령. 기본값은 {merge.DEFAULT_TEST_ENTRY} 가 있으면"
        f" '{merge.DEFAULT_TEST_COMMAND}'",
    )
    merge_cmd.add_argument(
        "--no-test", action="store_true", help="테스트를 돌리지 않고 병합"
    )
    merge_cmd.set_defaults(handler=_cmd_merge)

    finish = sub.add_parser("finish", help="병합 후 리소스 해제 (할일 done·서버 종료)")
    _add_session_arg(finish)
    finish.add_argument("--worktree", default=None, help="기본값은 세션의 작업 위치")
    finish.set_defaults(handler=_cmd_finish)

    status_line = sub.add_parser(
        "statusline", help="상태줄 한 줄 (연결된 할일·상태·워크트리 서버 포트)"
    )
    _add_session_arg(status_line)
    status_line.add_argument(
        "--cwd", default=None, help="세션의 현재 위치. 상태줄이 넘겨주는 값이 가장 정확하다"
    )
    status_line.set_defaults(handler=_cmd_statusline)

    scan = sub.add_parser("scan-history", help="초기 설정용 히스토리 요약 (세션당 한 줄)")
    scan.add_argument("--days", type=int, default=HISTORY_DAY_CHOICES[0])
    _add_json_flag(scan)
    scan.set_defaults(handler=_cmd_scan_history)

    onboard = sub.add_parser("onboard", help="초기 설정 상태")
    onboard.add_argument("--skip", action="store_true", help="자동 분류 거절. 다시 묻지 않음")
    onboard.set_defaults(handler=_cmd_onboard)

    language_cmd = sub.add_parser("language", help="화면 언어 (인자 없으면 현재 값)")
    language_cmd.add_argument("code", nargs="?", choices=LANGUAGES)
    language_cmd.set_defaults(handler=_cmd_language)

    usage_cmd = sub.add_parser("usage", help="한도 사용률과 토큰 추이")
    _add_json_flag(usage_cmd)
    usage_cmd.set_defaults(handler=_cmd_usage)

    auth = sub.add_parser("gtasks-auth", help="구글 태스크 최초 인증 (1회)")
    auth.add_argument(
        "--client-id",
        help=f"GCP 데스크톱 OAuth 클라이언트 id. 없으면 {GTASKS_CLIENT_ID_ENV} 환경변수",
    )
    auth.add_argument(
        "--client-secret",
        help=f"없으면 {GTASKS_CLIENT_SECRET_ENV} 환경변수. 히스토리에 남기지 않으려면 이쪽",
    )
    auth.set_defaults(handler=_cmd_gtasks_auth)

    gsync = sub.add_parser("gtasks-sync", help="구글 태스크 양방향 동기화")
    gsync.add_argument(
        "--dry-run", action="store_true", help="무엇이 바뀔지만 보고 아무것도 쓰지 않음"
    )
    _add_json_flag(gsync)
    gsync.set_defaults(handler=_cmd_gtasks_sync)

    autorun_cmd = sub.add_parser("autorun", help="자율 실행 켜기·끄기·상태")
    autorun_cmd.add_argument("action", choices=AUTORUN_ACTIONS)
    _add_json_flag(autorun_cmd)
    autorun_cmd.set_defaults(handler=_cmd_autorun)

    autorun_tick = sub.add_parser("autorun-tick", help="자율 실행 판정 (5분 크론)")
    autorun_tick.add_argument(
        "--dry-run", action="store_true", dest="dry_run", help="띄우지 않고 판정 사유만"
    )
    _add_json_flag(autorun_tick)
    autorun_tick.set_defaults(handler=_cmd_autorun_tick)

    judge_stale = sub.add_parser(
        "judge-stale", help="방치된 doing 을 모델이 읽고 done·무효·대기로 정리 (일 1회 크론)"
    )
    judge_stale.add_argument(
        "--dry-run", action="store_true", dest="dry_run", help="판정만 보고 상태·기록은 안 바꿈"
    )
    judge_stale.add_argument(
        "--limit", type=int, default=STALE_JUDGE_BATCH, help="한 번에 묻는 할일 수"
    )
    _add_json_flag(judge_stale)
    judge_stale.set_defaults(handler=_cmd_judge_stale)

    autorun_prompt = sub.add_parser("autorun-prompt", help="자율 세션에 줄 지시 전문")
    autorun_prompt.add_argument("todo_id", type=int)
    autorun_prompt.add_argument(
        "--cwd", default=None, help="기본값은 그 워크스페이스에서 작업하던 저장소"
    )
    autorun_prompt.set_defaults(handler=_cmd_autorun_prompt)

    autorun_reopen = sub.add_parser(
        "autorun-reopen", help="확인(완료)을 되돌려 다시 검토 대기로"
    )
    autorun_reopen.add_argument("run_id", type=int)
    autorun_reopen.set_defaults(handler=_cmd_autorun_reopen)

    autorun_request = sub.add_parser(
        "autorun-request", help="판단 보류 — 자율 수행을 멈추고 사람 결정을 요청"
    )
    _add_session_arg(autorun_request)
    autorun_request.add_argument(
        "note", help="무엇이 필요한지 한 문장 (기획 공백·방향 미정·토큰/Jira/문서 위치 등)"
    )
    autorun_request.set_defaults(handler=_cmd_autorun_request)

    autorun_finish = sub.add_parser(
        "autorun-finish", help="자율 수행 완료 — 검토 대기로 전환 (할일 상태는 안 건드림)"
    )
    _add_session_arg(autorun_finish)
    autorun_finish.set_defaults(handler=_cmd_autorun_finish)

    return parser


def _add_json_flag(parser):
    parser.add_argument(
        "--json", action="store_true", dest="as_json", help="Claude 파싱용 JSON 출력"
    )


def _add_session_arg(parser, required=True, note=""):
    """세션 인자. 생략하면 환경변수로 자기 세션을 찾는다.

    required 는 '이 명령에 세션이 꼭 필요한가'다. 필요 없는 쪽(--session)은 플래그를
    빼는 것이 '세션 범위 없음'이라 기존 뜻을 지키고, 값 없이 적었을 때만 이 세션으로 본다
    """
    if required:
        parser.add_argument(
            "session", nargs="?", default=SELF_SESSION, help=SESSION_ARG_HELP
        )
        return
    parser.add_argument(
        "--session", nargs="?", const=SELF_SESSION, default=None,
        help=f"{note} 값을 생략하면 이 세션 ({SESSION_ID_ENV})",
    )


def _self_session():
    session = os.environ.get(SESSION_ID_ENV)
    if not session:
        raise Validation(
            f"세션을 알 수 없음 ({SESSION_ID_ENV} 없음). session 인자에 값을 적을 것"
        )
    return session


def _cmd_ls(con, args):
    """트리(맨 위 할일)별로 할일을 묶어 보인다 — 순서는 트리 화면과 같다(lineage.grouped_todos)"""
    todos = [dict(row) for row in con.execute("SELECT * FROM todos ORDER BY sort_order, id")]
    groups = [
        {
            "root_id": head["id"] if head else None,
            "name": head["title"] if head else UNTITLED_TREE,
            "done_count": sum(todo["status"] == STATUS_DONE for todo in members),
            "total_count": len(members),
            "todos": [{key: todo[key] for key in ("id", "title", "status", "priority")} for todo in members],
        }
        for _, head, members in lineage.grouped_todos(con, todos)
    ]
    if args.as_json:
        _emit_json({"groups": groups})
        return
    if not groups:
        print("할일이 없음")
    for group in groups:
        print(f"{group['name']}  {group['done_count']}/{group['total_count']}")
        for todo in group["todos"]:
            print(f"  [{todo['status']}] {todo['id']}. {todo['title']}")


def _cmd_add_category(con, args):
    print(category_repo.create(con, args.name)["name"])


def _cmd_set_parent(con, args):
    parent_id = None if args.parent == NONE_LITERAL else args.parent
    updated = todo_repo.update(con, args.todo_id, parent_id=parent_id)
    scope = f"#{updated['parent_id']}" if updated["parent_id"] else "트리 맨 위"
    print(f"{updated['id']}. {updated['title']} → {scope}")


# CLI 는 한국어·영어 관계 이름을 다 받는다. 저장은 영어 코드
LINK_RELATIONS = {
    "상위": REL_PARENT, "parent": REL_PARENT,
    "선행": REL_PRECEDES, "precedes": REL_PRECEDES,
    "근거": REL_EVIDENCE, "evidence": REL_EVIDENCE,
    "관련": REL_RELATED, "related": REL_RELATED,
}
LINK_BASES = {
    "계기": BASIS_TRIGGER, "trigger": BASIS_TRIGGER,
    "목적": BASIS_PURPOSE, "purpose": BASIS_PURPOSE,
    "배경": BASIS_BACKGROUND, "background": BASIS_BACKGROUND,
}
NODE_HELP = (
    "할일 12 · 맥락 ctx:3 · 세션 session:<id> · 문서 jira:PFD-1 / confluence:123 / pr:<조직>/<레포>#4"
    " / artifact:<id> / site:<주소> / file:<절대경로>"
)
CONTEXT_PREFIX = "ctx:"
SESSION_PREFIX = "session:"
DOC_PREFIXES = evidence_refs.DOC_KINDS


def parse_node(text):
    """CLI 노드 표기 → (종류, id). 숫자(#12 도)는 할일"""
    value = (text or "").strip()
    if value.lstrip("#").isdigit():
        return (NODE_TODO, value.lstrip("#"))
    if value.startswith(CONTEXT_PREFIX):
        return (NODE_CONTEXT, value[len(CONTEXT_PREFIX):])
    if value.startswith(SESSION_PREFIX):
        return (NODE_SESSION, value[len(SESSION_PREFIX):])
    if value.partition(":")[0] in DOC_PREFIXES:
        return (NODE_DOC, value)
    raise Validation(f"노드 표기를 알 수 없습니다: {value} ({NODE_HELP})")


def _cmd_link(con, args):
    edge = graph_repo.add_edge(
        con,
        parse_node(args.source),
        parse_node(args.target),
        LINK_RELATIONS[args.relation],
        basis=LINK_BASES.get(args.basis) if args.basis else None,
        evidence=args.evidence,
        state=EDGE_PROPOSED if args.proposed else EDGE_CONFIRMED,
    )
    print(_edge_line(edge))


def _cmd_collect_results(con, args):
    """백필·재수집. 세션마다 지난번 읽은 곳 뒤만 읽으므로 다시 돌려도 겹치지 않는다"""
    sessions = [args.session] if args.session else None
    found = session_results.backfill(con, dry_run=args.dry_run, sessions=sessions)
    kinds, unique = {}, set()
    for claude_session_id, rows in found.items():
        for row in rows:
            unique.add((claude_session_id, row["ref"]))
            if args.verbose:
                print(f"{claude_session_id[:8]} {row['at']} {row['action']} {row['ref']} {row.get('title') or ''}")
    for _, ref in unique:
        kind = evidence_refs.kind_of(ref)
        kinds[kind] = kinds.get(kind, 0) + 1
    label = "뽑힘(DB 안 바꿈)" if args.dry_run else "이었음"
    print(f"세션 {len(found)}개에서 결과 {len(unique)}건 {label}")
    for kind in evidence_refs.DOC_KINDS:
        if kinds.get(kind):
            print(f"  {kind}: {kinds[kind]}")


def _cmd_edges(con, args):
    rows = graph_repo.edges_of(con, parse_node(args.node), include_performs=True)
    if not rows:
        print("연결 없음")
    for edge in rows:
        print(_edge_line(edge))


def _cmd_edge(con, args):
    if args.action == "rm":
        graph_repo.delete_edge(con, args.edge_id)
        print(f"연결 {args.edge_id} 삭제")
        return
    state = EDGE_CONFIRMED if args.action == "confirm" else EDGE_REJECTED
    print(_edge_line(graph_repo.set_state(con, args.edge_id, state)))


def _cmd_add_context(con, args):
    category_id = None
    if args.category:
        category_id = category_repo.get_by_name(con, args.category)["id"]
    context = graph_repo.create_context(
        con, args.title, category_id=category_id, note=args.note
    )
    print(f"{CONTEXT_PREFIX}{context['id']} {context['title']}")


def _edge_line(edge):
    """한 줄 표기. 관계·기준은 한국어 이름으로"""
    relation = {value: key for key, value in LINK_RELATIONS.items() if not key.isascii()}
    relation["performs"] = "수행"
    relation["result"] = "결과"
    basis = {value: key for key, value in LINK_BASES.items() if not key.isascii()}
    head = f"[{edge['id']}]" if edge.get("id") else "[수행]"
    kind = relation.get(edge["relation"], edge["relation"])
    if edge.get("basis") in basis:
        kind += f"({basis[edge['basis']]})"
    text = (
        f"{head} {edge['src_kind']}:{edge['src_id']} -{kind}-> "
        f"{edge['dst_kind']}:{edge['dst_id']} [{edge['state']}·{edge['created_by']}]"
    )
    return f"{text} {edge['evidence']}" if edge.get("evidence") else text


def _cmd_edit_todo(con, args):
    fields = {
        key: value
        for key, value in (
            ("title", args.title),
            ("note", args.note),
            ("precondition", args.precondition),
            ("priority", args.priority),
        )
        if value is not None
    }
    if not fields:
        raise Validation("--title/--note/--precondition/--priority 중 하나는 있어야 함")
    updated = todo_repo.update(con, args.todo_id, **fields)
    if "title" in fields:
        session_name.sync_todo(con, updated)
    print(f"{updated['id']}. {updated['title']}")


def _cmd_rm_category(con, args):
    """세션이 붙어 있으면 무엇이 바뀌는지 알리고 --force 를 요구한다"""
    try:
        category_repo.delete(con, args.category_id, force=args.force)
    except NeedsConfirm as error:
        raise NeedsConfirm(f"{error} 확인했으면 --force 로 다시 실행하세요")
    print("삭제됨")


def _cmd_sessions(con, args):
    payload = session_link.active_payload(con)
    if args.as_json:
        _emit_json(payload)
        return
    if not payload["sessions"]:
        print("돌고 있는 세션이 없음")
    for session in payload["sessions"]:
        scope = session.get("root_title") or session["category_name"] or "분류 전"
        print(f"[{session['state']}] {scope} / {session['last_prompt'] or '(지시 없음)'}")
    if payload["unclassified_count"]:
        print(f"분류 전 {payload['unclassified_count']}건")


def _cmd_show_todo(con, args):
    """그 세션이 잡은 할일. 매니저 컴팩션 인수인계(edit-todo --note)·spawn 지시가 할일 id 를 찾을 때 쓴다.
    컨텍스트 전문은 show-note 로 따로 꺼냄"""
    session = args.session if args.session not in (None, SELF_SESSION) else _self_session()
    todos = _linked_todos(con, session)
    if args.as_json:
        _emit_json(todos)
        return
    if not todos:
        print("할일이 없음")
        return
    for todo in todos:
        marker = " (컨텍스트)" if todo["note"] else ""
        rank = f" (우선순위 {todo['priority']})" if todo.get("priority") else ""
        print(f"{todo['id']}. [{todo['status']}] {todo['title']}{rank}{marker}")
        if todo["precondition"]:
            print(f"    조건: {_one_line(todo['precondition'])}")


def _cmd_merge(con, args):
    """병합 파이프라인. 어디까지 갔는지 찍고, 중단 사유가 있으면 그것으로 실패한다"""
    result = merge.merge(
        con,
        args.session,
        worktree=args.worktree,
        message=args.message,
        test=args.test,
        no_test=args.no_test,
    )
    for label, detail in result["steps"]:
        # 중단 사유는 stderr 로 나간다 — 여기서 흘려보내지 않으면 사유가 단계보다 먼저 찍힌다
        print(f"{label}: {detail}", flush=True)
    if result["aborted"]:
        raise Validation("중단 — " + result["aborted"])
    _print_release(con, result["release"])


def _cmd_finish(con, args):
    """병합으로 끝난 작업의 뒷정리. 워크트리 제거는 ExitWorktree 몫이라 안내만 한다"""
    _print_release(con, release.finish(con, args.session, worktree=args.worktree))


def _print_release(con, result):
    """해제 결과. merge 와 finish 가 같은 형식으로 찍어야 읽는 쪽이 헷갈리지 않는다"""
    print("완료한 할일: " + (_finished_labels(con, result["todos"]) or "(없음)"))
    for pid, command in result["killed"]:
        print(f"종료한 프로세스: {pid} {command}")
    if not result["killed"]:
        print(f"종료한 프로세스: (없음) — {_why_nothing_killed(result)}")
    if result["worktree"]:
        print(f"남은 정리: ExitWorktree 로 워크트리 제거 — {result['worktree']}")


def _finished_labels(con, todo_ids):
    return ", ".join(
        f"{todo_id}. {todo_repo.get(con, todo_id)['title']}" for todo_id in todo_ids
    )


def _cmd_statusline(con, args):
    """상태줄용 한 줄. 보여줄 게 없으면 아무것도 찍지 않는다 — 빈 라벨이 폭만 잡아먹는다.

    등록되지 않은 세션(훅이 아직 안 돌았거나 다른 프로젝트)에서도 조용히 끝난다
    """
    session = session_repo.find(con, args.session)
    if not session:
        return
    todos = _linked_todos(con, args.session)
    # 워크트리에서 작업 중이면 그 서버, 메인 체크아웃이면 거기서 도는 서버
    worktree = release.worktree_of(args.session, session["cwd"], worktree=args.cwd)
    port = release.serving_port(worktree or args.cwd or session["cwd"])
    marks = [
        todos[0]["status"] if todos else "",
        os.path.basename(worktree) if worktree else (session["git_branch"] or ""),
        f":{port}" if port else "",
    ]
    parts = [f"[{' | '.join(mark for mark in marks if mark)}]"] if any(marks) else []
    if todos:
        parts.append(_clipped(todos[0]["title"], STATUSLINE_TITLE_MAX))
    if len(todos) > 1:
        parts.append(f"+{len(todos) - 1}")
    if parts:
        print(" ".join(parts))


def _linked_todos(con, claude_session_id):
    """연결된 할일. 안 끝난 것이 맨 앞 — 끝난 것을 앞세우면 지금 뭘 하는지가 가려진다"""
    todos = [
        todo_repo.get(con, todo_id)
        for todo_id in session_repo.linked_todo_ids(con, claude_session_id)
    ]
    return sorted(todos, key=lambda todo: todo["status"] == STATUS_DONE)


def _clipped(text, limit):
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _why_nothing_killed(result):
    """(없음) 만 찍고 넘기면 살아남은 서버를 아무도 모른다 — 어디를 봤는지 밝힌다"""
    if result["worktree"]:
        return f"{result['worktree']} 를 cwd 로 쓰는 서버가 없음"
    looked = ", ".join(result["looked"]) or "(없음)"
    return f"워크트리를 찾지 못함 — 본 경로: {looked} (--worktree 로 직접 지정 가능)"


def _cmd_show_note(con, args):
    todo = todo_repo.get(con, args.todo_id)
    if args.as_json:
        _emit_json({"todo": todo})
        return
    print(f"[{todo['status']}] {todo['id']}. {todo['title']}")
    if todo["precondition"]:
        print(_indented("착수 조건: ", todo["precondition"]))
    print(f"컨텍스트: {todo['note'] or '(없음)'}")


def _indented(label, text):
    """여러 줄 조건의 둘째 줄부터도 라벨 폭만큼 들여씀. 안 그러면 계층이 깨져 보인다"""
    lines = (text or "").strip().splitlines()
    pad = " " * len(label)
    return "\n".join(
        f"{label if index == 0 else pad}{line}" for index, line in enumerate(lines)
    )


def _one_line(text):
    """목록에서는 조건 첫 줄만. '확인:' 명령줄까지 늘어놓으면 목록이 안 읽힌다"""
    first = (text or "").strip().splitlines()
    return first[0] if first else ""


def _cmd_link_todo(con, args):
    session = args.session
    if args.past:
        session = history.ensure_past_session(con, session)
    session_repo.link_todo(
        con, session, args.todo_id, claim=not args.past, status=args.status
    )
    # 끝난 히스토리 세션은 살아 있지 않아 이름 붙일 곳이 없다
    if not args.past:
        session_name.sync_todo(con, todo_repo.get(con, args.todo_id))
    print(f"할일 {args.todo_id} 연결됨" + (f" ({args.status})" if args.status else ""))


def _cmd_scan_history(con, args):
    groups = history.scan(args.days)
    if args.as_json:
        _emit_json(groups)
        return
    print(history.render(groups, args.days))


def _cmd_onboard(con, args):
    if args.skip:
        session_link.decline(con)
        print("자동 분류를 하지 않습니다. 초기 설정 안내가 다시 뜨지 않습니다.")
        return
    print("초기 설정 필요" if session_link.needs_onboarding(con) else "초기 설정 완료 또는 거절됨")


def _cmd_language(con, args):
    """초기 설정 때 물어본 언어를 여기 적는다. 웹 설정 탭과 같은 값을 본다"""
    if args.code:
        settings_repo.set_language(con, args.code)
    print(settings_repo.language(con))


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


def _cmd_gtasks_auth(con, args):
    path = gtasks_auth.authorize(args.client_id, args.client_secret)
    print(f"인증 정보 저장됨: {path}")
    print("이제 dash.py gtasks-sync 로 동기화할 수 있습니다")


def _cmd_gtasks_sync(con, args):
    """되돌리기 어려운 삭제가 섞이므로 무엇을 했는지 건별로 남긴다"""
    report = gtasks.run(con, dry_run=args.dry_run)
    if report is None:
        # cron 이 부르는 자리다. 꺼 뒀다고 실패로 처리하면 로그가 매번 시끄럽다
        if args.as_json:
            _emit_json({"enabled": False})
        else:
            print("연동이 꺼져 있어 아무것도 하지 않음 (설정 화면에서 켤 수 있습니다)")
        return
    if args.as_json:
        _emit_json(report)
        return
    if args.dry_run:
        print("[dry-run] 아무것도 쓰지 않음")
    changed = False
    for action, label in GTASKS_ACTION_LABELS:
        items = report[action]
        if not items:
            continue
        changed = True
        print(f"{label} {len(items)}건")
        for item in items:
            print(f"  - {item}")
    if not changed:
        print("바뀐 것 없음")


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


def _cmd_autorun(con, args):
    """켜고 끄기는 명시적. 기본 off 이고 자동으로 다시 켜지는 경로는 두지 않는다"""
    if args.action != "status":
        autorun_repo.set_enabled(con, args.action == "on")
    state = autorun_repo.state(con)
    runs = autorun_repo.recent(con, AUTORUN_RECENT)
    if args.as_json:
        _emit_json({"state": state, "recent": runs})
        return
    print(f"autorun: {'on' if state['enabled'] else 'off'}"
          f" (연속 막힘 {state['blocked_streak']}, 마지막 tick {state['last_tick_at'] or '없음'})")
    for run in runs:
        print(f"  #{run['id']} 할일 {run['todo_id']} [{run['outcome'] or '진행 중'}]"
              f" job={run['job_id'] or '?'} session={run['claude_session_id'] or '?'}")


def _cmd_autorun_tick(con, args):
    decision = autorun.tick(con, dry_run=args.dry_run)
    if args.as_json:
        _emit_json(decision)
        return
    print(decision["reason"])
    for run in decision.get("closed") or []:
        print(f"  실행 #{run['id']} 닫음 → {run['outcome']}")
    picked = decision.get("todo")
    if picked:
        print(f"  대상: {picked['id']}. {picked['title']}")
    if decision.get("cwd"):
        print(f"  작업 위치: {decision['cwd']}")
    if decision.get("run"):
        print(f"  띄움: job={decision['run']['job_id']}"
              f" session={decision['run']['claude_session_id'] or '(못 받음)'}")
    if decision.get("error"):
        print(f"  실패: {decision['error']}", file=sys.stderr)


def _cmd_judge_stale(con, args):
    report = stale_judge.run(con, dry_run=args.dry_run, limit=args.limit)
    if args.as_json:
        _emit_json(report)
        return
    if not report["judged"]:
        print("판정할 방치 doing 없음")
        return
    for item in report["results"]:
        change = f"→ {item['status']}" if item["applied"] else "(유지)"
        print(
            f"{item['todo_id']}. {item['title']}: {item['verdict']}"
            f" {item['confidence']:.2f} {change} — {item['reason']}"
        )


def _cmd_autorun_prompt(con, args):
    """자율 세션에 실제로 들어가는 지시. 띄우기 전에 사람이 눈으로 볼 수 있어야 한다"""
    todo = todo_repo.get(con, args.todo_id)
    cwd = args.cwd or autorun.target_cwd(con, todo)
    if not cwd:
        raise Validation(autorun.REASON_NO_CWD + " — --cwd 로 지정할 것")
    print(autorun.build_prompt(todo, lineage.ancestor_todos(con, todo["id"]), cwd))


def _cmd_autorun_reopen(con, args):
    run = autorun.reopen_run(con, args.run_id)
    print(f"실행 {run['id']} (할일 {run['todo_id']}) → {run['outcome']}")


def _cmd_autorun_request(con, args):
    run = autorun_repo.mark_requested(con, args.session, args.note)
    print(f"요청 등록: 할일 {run['todo_id']} (실행 #{run['id']}) — 자율 수행 후보에서 빠짐")


def _cmd_autorun_finish(con, args):
    run = autorun_repo.mark_finished(con, args.session)
    print(f"완료 표시: 할일 {run['todo_id']} (실행 #{run['id']}) — 검토 대기로 넘어감")


def _emit_json(payload):
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    sys.exit(main())
