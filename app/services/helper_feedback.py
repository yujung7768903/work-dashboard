"""보조 세션에 화면에서 피드백 보내기 — 매니저 탭 보조 세션 상세의 입력칸.

결정 답하기(decision_answer)·직접 할 일 응답(task_report)과 같은 방식이다. 매니저 CLI 만 부른다(manager.py helper-ui).
세션 생사 판정·피드백 기록·살아 있는 세션 전달(못 넣으면 메인 매니저에 넘기기)은 매니저 몫이고, 여기서는 매니저 DB 를
읽거나 쓰지 않는다. 할일 상태는 바꾸지 않는다 — 진행 중인 보조에게 말을 거는 것이다.
helper-ui 는 원 세션 훅이 가져가는지 지켜보느라 수 초에서 수십 초 걸려 뒤에서 돌리고(decision_answer.launch) 화면은
show() 를 폴링한다. 글은 --feedback=<글> 한 덩어리 리스트 인자로만 넘긴다 — 셸·argparse 가 글을 명령·옵션으로 읽지 않게.
"""
import subprocess
import sys

from app.errors import Validation
from app.services import decision_answer

# 같은 표(decision_answer._jobs)에 할일 id(정수)와 함께 둔다 — 겹치지 않게 접두를 붙인다
JOB_PREFIX = "helper:"


def show(session_id, home=None):
    """그 세션의 생사와 화면에서 보낸 피드백(최근 것부터) + 뒤에서 도는 보내기(job).
    매니저 탭 보조 세션 상세가 열 때, 보낸 뒤 폴링할 때 읽는다"""
    session_id = _session_id(session_id)
    found = decision_answer._call(["helper-ui", session_id], home) or {}
    return {
        "session": found.get("session") or {"id": session_id, "name": None, "alive": False},
        "items": found.get("items") or [],
        "job": decision_answer.job_of(_job_key(session_id)),
    }


def start(session_id, feedback, home=None, popen=subprocess.Popen):
    """helper-ui 를 뒤에서 띄우고 바로 돌아온다. 세션이 끝났는지는 매니저가 보낼 때 다시 보고 남기지 않는다 —
    화면은 폴링한 show() 의 session.alive 로 그 사실을 보인다"""
    session_id = _session_id(session_id)
    feedback = (feedback or "").strip()
    if not feedback:
        raise Validation("보낼 피드백을 적어 주세요")
    home = home or decision_answer.manager_home()
    args = [sys.executable, decision_answer._script(home), "helper-ui", session_id, f"--feedback={feedback}"]
    busy = "이 보조 세션에 보낸 피드백을 아직 전하는 중입니다"
    job = decision_answer.launch(_job_key(session_id), args, home, popen, busy)
    return {"session_id": session_id, "job": job}


def _session_id(session_id):
    session_id = (session_id or "").strip()
    if not session_id:
        raise Validation("session_id 가 필요함")
    return session_id


def _job_key(session_id):
    return f"{JOB_PREFIX}{session_id}"
