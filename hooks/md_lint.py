#!/usr/bin/env python3
"""PostToolUse 훅: Write/Edit/NotebookEdit 로 저장된 .md 파일을 markdownlint-cli2 로 검사.

검사 대상은 이 저장소 트리 안의 파일로 한정한다(.claude/worktrees/ 하위 포함).
밖의 .md — 임시 디렉터리, 외부에서 받아온 문서, 다른 프로젝트 — 는 이 저장소의
마크다운 규약을 따를 이유가 없으므로 건너뛴다.

린트 에러가 있으면 exit 2 + stderr 에 에러 목록과 재저장 지시.
markdownlint-cli2 미설치·타임아웃·그 외 예외는 fail-open(exit 0) — 훅 오류로
저장을 막는 사고가 더 큼. worktree_guard.py 와 동일한 원칙.

바이너리를 PATH 에서 직접 부른다. npx 경유는 비대화형 셸에서 매달릴 수 있고,
패키지를 못 찾을 때도 exit 1 을 줘서 린트 실패와 구분되지 않는다.
설치: npm i -g markdownlint-cli2
"""
import json
import os
import shutil
import subprocess
import sys

EXIT_OK = 0
EXIT_BLOCK = 2
LINT_TIMEOUT_SEC = 5
LINT_TOOL_NAMES = {"Write", "Edit", "NotebookEdit"}
LINT_BINARY = "markdownlint-cli2"
SCOPE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

FIX_MESSAGE = """마크다운 린트 오류 발견: {path}

{errors}

위 오류를 수정 후 다시 저장하라."""


def main(stdin=None):
    try:
        payload = json.loads((stdin or sys.stdin).read() or "{}")
        if payload.get("tool_name") not in LINT_TOOL_NAMES:
            return EXIT_OK
        tool_input = payload.get("tool_input") or {}
        path = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
        if not path or os.path.splitext(path)[1].lower() != ".md":
            return EXIT_OK
        path = _resolve_path(path, payload.get("cwd"))
        if not _in_scope(path):
            return EXIT_OK
        errors = _lint(path)
        if not errors:
            return EXIT_OK
    except Exception:  # 훅 실패로 저장을 막지 않음
        return EXIT_OK
    print(FIX_MESSAGE.format(path=path, errors=errors), file=sys.stderr)
    return EXIT_BLOCK


def _resolve_path(path, cwd):
    if os.path.isabs(path):
        return path
    return os.path.join(cwd or os.getcwd(), path)


def _in_scope(path):
    """SCOPE_ROOT 트리 안이면 True. 심볼릭 링크로 밖을 가리키면 False"""
    root = os.path.realpath(SCOPE_ROOT)
    target = os.path.realpath(path)
    return target == root or target.startswith(root + os.sep)


def _lint(path):
    """markdownlint-cli2 실행 결과 에러 텍스트. 통과·미설치·타임아웃이면 빈 문자열"""
    binary = shutil.which(LINT_BINARY)
    if not binary:  # 미설치면 관여하지 않는다
        return ""
    try:
        result = subprocess.run(
            [binary, path],
            capture_output=True,
            text=True,
            timeout=LINT_TIMEOUT_SEC,
        )
    except Exception:
        return ""
    return "" if result.returncode == 0 else result.stderr.strip()


if __name__ == "__main__":
    sys.exit(main())
