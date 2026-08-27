#!/usr/bin/env python3
"""PreToolUse 훅: ~/work/ 레포의 메인 체크아웃에서 소스 파일 편집을 차단.

워크트리 안이거나, 문서·설정 파일이거나, ~/work/ 밖이면 통과.
훅 자체 오류는 fail-open(exit 0) — 편집을 못 하게 막는 사고가 더 큼.
"""
import json
import os
import subprocess
import sys

EXIT_OK = 0
EXIT_BLOCK = 2
GIT_TIMEOUT_SEC = 2
WORK_ROOT = os.path.expanduser("~/work")
BYPASS_ENV = "ALLOW_MAIN_CHECKOUT"
# 문서·설정·이미지는 메인 체크아웃에서 고쳐도(생성해도) 충돌 위험이 작아 통과시킴
PASS_EXTENSIONS = {
    ".md",
    ".txt",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    ".conf",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".webp",
    ".drawio",
}

DENY_MESSAGE = """메인 체크아웃 소스 편집 차단: {path}

이 파일은 워크트리가 아닌 메인 체크아웃에 있어 다른 세션 작업과 충돌할 수 있음.
- 워크트리에서 작업: EnterWorktree 툴로 워크트리를 만들고 그 안의 같은 경로를 편집
- 정말 메인에서 고쳐야 하면: ALLOW_MAIN_CHECKOUT=1 환경변수로 실행"""


def main(stdin=None):
    try:
        payload = json.loads((stdin or sys.stdin).read() or "{}")
        tool_input = payload.get("tool_input") or {}
        path = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
        if not path or not should_block(path):
            return EXIT_OK
    except Exception:  # 훅 실패로 편집을 막지 않음
        return EXIT_OK
    print(DENY_MESSAGE.format(path=path), file=sys.stderr)
    return EXIT_BLOCK


def should_block(path):
    if os.environ.get(BYPASS_ENV) == "1":
        return False
    path = os.path.abspath(path)
    if not path.startswith(WORK_ROOT + os.sep):
        return False
    if _is_pass_through(path):
        return False
    git_dir = _git_dir(path)
    if not git_dir:  # 레포가 아니면 관여하지 않음
        return False
    return "/worktrees/" not in git_dir


def _is_pass_through(path):
    name = os.path.basename(path)
    if name.startswith(".env"):
        return True
    if os.path.splitext(name)[1].lower() in PASS_EXTENSIONS:
        return True
    return "/docs/" in path


def _git_dir(path):
    """대상 파일 기준 git 디렉토리. 파일이 아직 없을 수 있어 존재하는 상위 디렉토리를 찾음"""
    directory = os.path.dirname(path)
    while directory and not os.path.isdir(directory):
        directory = os.path.dirname(directory)
    if not directory:
        return None
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--absolute-git-dir"],
            cwd=directory,
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_SEC,
        )
    except Exception:
        return None
    return result.stdout.strip() or None


if __name__ == "__main__":
    sys.exit(main())
