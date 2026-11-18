#!/usr/bin/env python3
"""작업 대시보드 훅 진입점. 어떤 실패에서도 exit 0 무출력 — 세션을 막지 않음"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.constants import RESULT_HOOK_MAX_BYTES, STATE_ENDED, STATE_IDLE, STATE_WORKING  # noqa: E402
from app.db import connect  # noqa: E402
from app.repositories import sessions as session_repo  # noqa: E402
from app.services import autorun, session_link, session_results  # noqa: E402

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
    """할일을 끝낸(finish 한) 세션에만 다시 알린다 — 끝난 할일에 새 요청을 얹지 않게.
    분류 전 세션에 분류 지시를 매 턴 다시 넣던 것은 뺐다 — 분류·할일 연결은 세션 몫이 아니다(session_link NO_FILING_RULE).

    자율 실행으로 뜬 잡에 사람이 말을 걸면 그 실행만 인계로 닫는다. autorun 은 계속 돈다.
    판정은 서비스가 하고 훅은 순서만 지킨다 — set_last_prompt 앞에서 불러야 자율 세션
    자신의 첫 프롬프트를 사람으로 오판하지 않는다
    """
    prompt = payload.get("prompt") or ""
    autorun.handover_if_human(con, session_id, prompt)
    session_repo.set_state(con, session_id, STATE_WORKING)
    session_repo.set_last_prompt(con, session_id, prompt)
    return session_link.released_context(con, session_id)


def _on_stop(con, session_id, payload):
    """위치도 다시 적는다 — SessionStart 에서만 잡으면 세션이 뒤에 EnterWorktree 해도
    cwd 가 메인 체크아웃에 머문다. 그러면 워크트리 뷰가 할일을 워크트리 줄이 아니라
    base 줄에 붙이므로, 그 줄을 눌러도 상세가 안 열린다. 자율 세션은 프롬프트가 한 번뿐
    이라 이 훅이 유일한 갱신 지점이다"""
    cwd = payload.get("cwd") or ""
    if cwd:
        session_repo.register(con, session_id, cwd=cwd, git_branch=_current_branch(cwd))
    session_repo.set_state(con, session_id, STATE_IDLE)
    _collect_results(con, session_id)
    return ""


def _on_session_end(con, session_id, payload):
    session_repo.set_state(con, session_id, STATE_ENDED)
    _collect_results(con, session_id)
    return ""


def _collect_results(con, session_id):
    """이번 턴에 새로 붙은 transcript 꼬리에서 결과물(만들거나 고친 문서·PR·아티팩트·파일)을 잇는다.
    상태 기록 뒤에 부른다 — 수집이 실패하거나 시간 제한에 걸려도 상태는 이미 남아 있다.
    한 번에 읽는 양을 묶어 두고 나머지는 다음 턴이 이어 읽는다"""
    try:
        session_results.collect(con, session_id, max_bytes=RESULT_HOOK_MAX_BYTES)
    except Exception:
        pass


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
