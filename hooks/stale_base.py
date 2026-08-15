#!/usr/bin/env python3
"""UserPromptSubmit 훅: 낡은 베이스 위 착수 경고. 네트워크 fetch 없이 로컬 ref만 비교.

브랜치가 upstream(@{u}) 또는 워크트리 기준 브랜치(master/main)보다 뒤처졌으면
착수 전 최신화하라는 한 줄 경고를 stdout 에 출력. 그 외에는 무출력.
훅 자체 오류는 fail-open(exit 0, 무출력) — 세션 시작을 막지 않음.
"""
import hashlib
import json
import os
import subprocess
import sys

EXIT_OK = 0
GIT_TIMEOUT_SEC = 2
BASE_BRANCHES = ("master", "main")
CACHE_DIR = os.path.expanduser("~/.claude/.stale-base-cache")


def main(stdin=None):
    try:
        payload = json.loads((stdin or sys.stdin).read() or "{}")
        cwd = payload.get("cwd") or ""
        if not cwd or not os.path.isdir(cwd):
            return EXIT_OK
        message = _build_message(cwd)
        if not message:
            return EXIT_OK
        session_id = (payload.get("session_id") or "").strip()
        if _already_shown(session_id, message):
            return EXIT_OK
        print(message)
        _remember(session_id, message)
    except Exception:  # 훅 실패가 세션을 막으면 안 됨
        return EXIT_OK
    return EXIT_OK


def _build_message(cwd):
    """뒤처졌으면 경고 문구, 아니면 None"""
    branch = _run_git(cwd, "branch", "--show-current")
    if not branch:  # 레포가 아니거나 detached HEAD
        return None

    upstream_n = _upstream_behind(cwd)
    if upstream_n:
        upstream_name = _run_git(cwd, "rev-parse", "--abbrev-ref", "@{u}") or "upstream"
        return (
            f"[최신화 필요] 현재 브랜치가 {upstream_name} 보다 {upstream_n} 커밋 뒤처짐. "
            "착수 전 git pull 로 최신화할 것."
        )

    if not _is_worktree(cwd):
        return None
    base = _base_branch(cwd)
    if not base or base == branch:
        return None
    base_n = _base_behind(cwd, base)
    if not base_n:
        return None
    return (
        f"[최신화 필요] 현재 브랜치가 {base} 보다 {base_n} 커밋 뒤처짐. "
        f"착수 전 git merge {base} 로 최신화할 것."
    )


def _upstream_behind(cwd):
    """upstream 미설정이면 None"""
    out = _run_git(cwd, "rev-list", "--count", "HEAD..@{u}")
    return int(out) if out and out.isdigit() else None


def _is_worktree(cwd):
    """git-dir 경로에 /worktrees/ 가 있으면 워크트리 (worktree_guard.py 와 동일 판별법)"""
    git_dir = _run_git(cwd, "rev-parse", "--absolute-git-dir")
    return bool(git_dir) and "/worktrees/" in git_dir


def _base_branch(cwd):
    """master 우선, 없으면 main. 로컬에 둘 다 없으면 None"""
    for name in BASE_BRANCHES:
        if _run_git(cwd, "rev-parse", "--verify", "--quiet", name) is not None:
            return name
    return None


def _base_behind(cwd, base):
    out = _run_git(cwd, "rev-list", "--count", f"HEAD..{base}")
    return int(out) if out and out.isdigit() else None


def _run_git(cwd, *args):
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_SEC,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _cache_path(session_id):
    key = session_id or "default"
    digest = hashlib.sha256(key.encode()).hexdigest()[:16]
    return os.path.join(CACHE_DIR, digest)


def _already_shown(session_id, message):
    try:
        with open(_cache_path(session_id), "r") as f:
            return f.read() == message
    except Exception:
        return False


def _remember(session_id, message):
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(_cache_path(session_id), "w") as f:
            f.write(message)
    except Exception:
        pass


if __name__ == "__main__":
    sys.exit(main())
