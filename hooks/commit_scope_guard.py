#!/usr/bin/env python3
"""PreToolUse 훅: git add/commit 의 전체 스테이징·전체 커밋 차단.

커밋 범위는 사용자가 지정한 파일만이어야 함 - pathspec 없는
`git add -A/--all/-u/.`, 스테이징을 건너뛰는 `git commit -a/--all/-am` 차단.
세미콜론·&&·파이프로 이어진 복합 명령도 구간별로 검사.
훅 자체 오류는 fail-open(exit 0) - worktree_guard.py 와 동일 원칙.
"""
import json
import shlex
import sys
from os import environ

EXIT_OK = 0
EXIT_BLOCK = 2
BYPASS_ENV = "ALLOW_BROAD_COMMIT"
BASH_TOOL = "Bash"

GIT_ADD_BROAD_FLAGS = {"-A", "--all", "-u", "--update"}
GIT_SUBCOMMANDS = {"add", "commit"}
# git 전역 옵션 중 값을 따로 받는 것들 (예: git -C <dir> add ...)
GIT_GLOBAL_OPTS_WITH_VALUE = {"-C", "-c"}

ADD_DENY_MESSAGE = """전체 스테이징 명령 차단: {command}

커밋 범위는 사용자가 지정한 파일만이어야 함. git add -A/--all/-u/. 는 의도치 않은 파일까지 스테이징할 수 있음.
- 지정한 파일만 개별 경로로 스테이징: git add <경로1> <경로2>
- 정말 전체가 필요하면: git add -A -- <경로> 처럼 pathspec 을 명시하거나 ALLOW_BROAD_COMMIT=1 환경변수로 실행"""

COMMIT_DENY_MESSAGE = """전체 커밋 명령 차단: {command}

git commit -a/--all/-am 는 스테이징 단계를 건너뛰고 추적 중인 파일을 전부 커밋함.
- git add 로 원하는 파일만 스테이징한 뒤 git commit -m "..." 실행
- 정말 필요하면 ALLOW_BROAD_COMMIT=1 환경변수로 실행"""


def main(stdin=None):
    try:
        payload = json.loads((stdin or sys.stdin).read() or "{}")
        if payload.get("tool_name") != BASH_TOOL:
            return EXIT_OK
        command = (payload.get("tool_input") or {}).get("command") or ""
        if not command or environ.get(BYPASS_ENV):
            return EXIT_OK
        reason = find_blocked_reason(command)
        if not reason:
            return EXIT_OK
    except Exception:  # 훅 실패로 커밋을 막지 않음
        return EXIT_OK
    print(reason, file=sys.stderr)
    return EXIT_BLOCK


def find_blocked_reason(command):
    for statement in _split_statements(command):
        statement = statement.strip()
        if not statement:
            continue
        try:
            tokens = shlex.split(statement)
        except ValueError:  # 괄호/따옴표 불균형 - 파싱 포기
            continue
        subcommand, args = _find_git_subcommand(tokens)
        if subcommand == "add" and _is_broad_add(args):
            return ADD_DENY_MESSAGE.format(command=statement)
        if subcommand == "commit" and _is_broad_commit(args):
            return COMMIT_DENY_MESSAGE.format(command=statement)
    return None


def _split_statements(command):
    """따옴표 안은 무시하고 ; && || | 기준으로 최상위 구간을 나눔"""
    statements = []
    buf = []
    in_squote = False
    in_dquote = False
    i = 0
    n = len(command)
    while i < n:
        c = command[i]
        if in_squote:
            buf.append(c)
            in_squote = c != "'"
            i += 1
            continue
        if in_dquote:
            buf.append(c)
            in_dquote = c != '"'
            i += 1
            continue
        if c == "'":
            in_squote = True
            buf.append(c)
        elif c == '"':
            in_dquote = True
            buf.append(c)
        elif c in "&|" and i + 1 < n and command[i + 1] == c:
            statements.append("".join(buf))
            buf = []
            i += 1
        elif c in (";", "|"):
            statements.append("".join(buf))
            buf = []
        else:
            buf.append(c)
        i += 1
    statements.append("".join(buf))
    return statements


def _find_git_subcommand(tokens):
    """git add/commit 서브커맨드와 그 뒤 인자를 찾음. 전역 옵션은 건너뜀"""
    if not tokens or tokens[0] != "git":
        return None, []
    i = 1
    while i < len(tokens):
        token = tokens[i]
        if token in GIT_SUBCOMMANDS:
            return token, tokens[i + 1:]
        if token in GIT_GLOBAL_OPTS_WITH_VALUE:
            i += 2
            continue
        if token.startswith("-"):
            i += 1
            continue
        break  # 알 수 없는 서브커맨드/경로 - 대상 아님
    return None, []


def _is_broad_add(args):
    has_broad_flag = any(a in GIT_ADD_BROAD_FLAGS for a in args)
    has_bare_dot = "." in args
    if not has_broad_flag and not has_bare_dot:
        return False
    explicit_paths = [
        a for a in args if a not in ("--", ".") and not a.startswith("-")
    ]
    return not explicit_paths


def _is_broad_commit(args):
    for a in args:
        if a == "--all":
            return True
        if a.startswith("-") and not a.startswith("--") and "a" in a[1:]:
            return True
    return False


if __name__ == "__main__":
    sys.exit(main())
