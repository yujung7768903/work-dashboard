#!/usr/bin/env python3
"""작업 대시보드 훅 진입점. 어떤 실패에서도 exit 0 무출력 — 세션을 막지 않음"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.constants import STATE_ENDED, STATE_IDLE, STATE_WORKING  # noqa: E402
from app.db import connect  # noqa: E402
from app.repositories import sessions as session_repo  # noqa: E402
from app.services import autorun, session_link  # noqa: E402

EXIT_OK = 0
GIT_BRANCH_TIMEOUT_SEC = 1


def main(argv=None, stdin=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        return EXIT_OK
    try:
        payload = json.loads((stdin or sys.stdin).read() or "{}")
        session_id = (payload.get("session_id") or "").strip()
        handler = HANDLERS.get(argv[0])
        if not session_id or not handler:
            return EXIT_OK
        text = handler(connect(), session_id, payload)
        if text:
            print(text)
    except Exception:  # 훅 실패가 세션을 막으면 안 됨
        return EXIT_OK
    return EXIT_OK


def _on_session_start(con, session_id, payload):
    cwd = payload.get("cwd") or ""
    branch = _current_branch(cwd)
    session_repo.register(con, session_id, cwd=cwd or None, git_branch=branch)
    session_link.attach_by_branch(con, session_id, branch)
    return session_link.render_context(con, session_id)


def _on_prompt_submit(con, session_id, payload):
    """분류 전이면 지시를 다시 주입. 분류되면 조용해짐.

    예외로 할일을 끝낸(finish 한) 세션에는 새 요청을 새 할일로 받으라고 다시 알린다.

    자율 실행으로 뜬 잡에 사람이 말을 걸면 그 잡은 사람 것으로 인계하고 autorun 을 끈다.
    판정은 서비스가 하고 훅은 순서만 지킨다 — set_last_prompt 앞에서 불러야 자율 세션
    자신의 첫 프롬프트를 사람으로 오판하지 않는다
    """
    autorun.handover_if_human(con, session_id)
    session_repo.set_state(con, session_id, STATE_WORKING)
    session_repo.set_last_prompt(con, session_id, payload.get("prompt") or "")
    session = session_repo.find(con, session_id)
    if not session:
        return ""
    if session["category_id"]:
        return session_link.released_context(con, session_id)
    return session_link.render_context(con, session_id)


def _on_stop(con, session_id, payload):
    session_repo.set_state(con, session_id, STATE_IDLE)
    return ""


def _on_session_end(con, session_id, payload):
    session_repo.set_state(con, session_id, STATE_ENDED)
    return ""


def _current_branch(cwd):
    """훅 입력에 브랜치가 없어 git 으로 직접 확인. 저장소가 아니면 None"""
    if not cwd or not os.path.isdir(cwd):
        return None
    try:
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=GIT_BRANCH_TIMEOUT_SEC,
        )
    except Exception:
        return None
    return result.stdout.strip() or None


HANDLERS = {
    "SessionStart": _on_session_start,
    "UserPromptSubmit": _on_prompt_submit,
    "Stop": _on_stop,
    "SessionEnd": _on_session_end,
}


if __name__ == "__main__":
    sys.exit(main())
