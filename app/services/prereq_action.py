"""선행 대기 사전 조건 항목의 케밥 메뉴 — 사전 조건 하나 빼기, 사전 조건 할일 완료 처리.

매니저 CLI 만 부른다. 매니저 DB 를 직접 쓰지 않는다.
- 빼기: 남은 선행 목록으로 task update <id> --after 를 다시 지정한다(마지막 하나면 none)
- 완료 처리: 사용자가 화면에서 직접 끝냈다고 한 것이다. 직접 할 일·확인 대기는 화면 완료 버튼과 같은 task-ui --done
  (task_report.start)으로, task-ui 가 받지 않는 열린 결정은 task done --by-user 로 닫는다 — 둘 다 사용자 말이 곧 확인이라
  바로 완료된다

처리 뒤 선행을 가진 할일(owner)을 매니저 탭 줄 모양으로 다시 읽어 돌려준다. 선행이 모두 풀렸으면 state 가 prereq 가 아니다.
"""
import subprocess
import sys
import time

from app.errors import Validation
from app.services import decision_answer, manager_panel, task_report

FINISHED = ("done", "invalid")
# 화면 완료 처리의 근거(사용자 말) — 매니저가 완료 근거로 남긴다
FINISH_TEXT = "작업 대시보드 선행 대기에서 완료 처리를 눌렀다"
# task-ui 는 뒤에서 돈다. 상태는 원 세션 전달 전에 바뀌므로 이 안에 닫힌 것이 보여야 한다
FINISH_WAIT_SEC = 15
FINISH_POLL_SEC = 0.5


def remove(task_id, prereq_id, home=None):
    """할일 task_id 의 선행에서 prereq_id 하나만 뺀다"""
    home = home or decision_answer.manager_home()
    row = decision_answer._task(task_id, home)
    ids = [item["id"] for item in row.get("after") or []]
    if prereq_id not in ids:
        raise Validation(f"#{task_id} 의 사전 조건이 아닙니다: #{prereq_id}")
    rest = [i for i in ids if i != prereq_id]
    decision_answer._call(["task", "update", str(task_id), "--after", ",".join(map(str, rest)) or "none"], home)
    return {"task": manager_panel.task_item(task_id, manager_home=home)}


def finish(task_id, prereq_id, home=None, popen=subprocess.Popen, run=subprocess.run, sleep=time.sleep):
    """할일 task_id 의 사전 조건 prereq_id 를 사용자 완료로 닫는다"""
    home = home or decision_answer.manager_home()
    owner = decision_answer._task(task_id, home)
    if prereq_id not in [item["id"] for item in owner.get("after") or []]:
        raise Validation(f"#{task_id} 의 사전 조건이 아닙니다: #{prereq_id}")
    row = decision_answer._task(prereq_id, home)
    status = row.get("status")
    if status in FINISHED:
        raise Validation(f"이미 닫힌 할일입니다: #{prereq_id}")
    if status == task_report.CONFIRM_STATUS or row.get("kind") == task_report.ACTION_KIND:
        task_report.start(prereq_id, done=True, feedback=FINISH_TEXT, home=home, popen=popen)
        _wait_closed(prereq_id, home, sleep)
    else:
        done = run(
            [sys.executable, decision_answer._script(home), "task", "done", str(prereq_id), f"--by-user={FINISH_TEXT}"],
            cwd=home, capture_output=True, text=True, timeout=decision_answer.MANAGER_TASK_TIMEOUT_SEC,
        )
        if done.returncode != 0:
            raise RuntimeError((done.stderr or done.stdout).strip() or f"task done exit {done.returncode}")
    return {"task": manager_panel.task_item(task_id, manager_home=home)}


def _wait_closed(prereq_id, home, sleep):
    for _ in range(int(FINISH_WAIT_SEC / FINISH_POLL_SEC)):
        if decision_answer._task(prereq_id, home).get("status") in FINISHED:
            return
        sleep(FINISH_POLL_SEC)
    raise RuntimeError(f"#{prereq_id} 완료 처리를 보냈지만 {FINISH_WAIT_SEC}초 안에 닫히지 않았습니다")
