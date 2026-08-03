#!/usr/bin/env python3
"""PostToolUse 훅: Write/Edit/NotebookEdit 로 저장된 .md 파일을 markdownlint-cli2 로 검사.

린트 에러가 있으면 exit 2 + stderr 에 에러 목록과 재저장 지시.
markdownlint-cli2 미설치·타임아웃·그 외 예외는 fail-open(exit 0) — 훅 오류로
저장을 막는 사고가 더 큼. worktree_guard.py 와 동일한 원칙.
"""
import json
import os
import subprocess
import sys

EXIT_OK = 0
EXIT_BLOCK = 2
LINT_TIMEOUT_SEC = 5
LINT_TOOL_NAMES = {"Write", "Edit", "NotebookEdit"}
SUMMARY_MARKER = "Summary:"  # markdownlint-cli2 가 실제로 실행됐다는 표시 (stdout)

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


def _lint(path):
    """markdownlint-cli2 실행 결과 에러 텍스트. 통과·미설치·타임아웃이면 빈 문자열"""
    try:
        result = subprocess.run(
            ["npx", "--no-install", "markdownlint-cli2", path],
            capture_output=True,
            text=True,
            timeout=LINT_TIMEOUT_SEC,
        )
    except Exception:
        return ""
    # npm 이 패키지를 못 찾아도 exit 1 을 주므로, 실제로 린트가 돌았다는 표시(stdout 의
    # Summary 줄)가 있을 때만 에러로 취급한다
    if result.returncode == 0 or SUMMARY_MARKER not in result.stdout:
        return ""
    return result.stderr.strip()


if __name__ == "__main__":
    sys.exit(main())
