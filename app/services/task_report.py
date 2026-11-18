"""직접 할 일·확인 대기에 화면에서 응답하기 — 할일 상세 창과 매니저 탭 확인 대기 팝업의 완료·확인 버튼과
진행 상황·고칠 것 입력칸.

결정 답하기(decision_answer)와 같은 방식이다. 매니저 CLI 만 부른다(task list --json · task show · task-ui).
상태 변경(완료 = task done --by-user, 확인 = task confirm, 고칠 것 = task reopen)과 원 세션 전달은 매니저 몫이고,
여기서는 매니저 DB 를 읽거나 쓰지 않는다. task-ui 는 살아 있는 원 세션에 넘기느라 수 초에서 수십 초 걸려
뒤에서 돌리고(decision_answer.launch) 화면은 show() 를 폴링한다. 글은 --feedback=<글> 한 덩어리 리스트 인자로만
넘긴다 — 셸·argparse 가 글을 명령·옵션으로 읽지 않게.

- 직접 할 일(kind=action, 열림): 사용자가 해야 하는 일. 완료하거나 진행 상황·막힌 점을 알린다
- 확인 대기(status=confirm, 종류 무관): 세션이 끝냈다고 보고해 사용자 확인만 남은 일. 확인하거나 고칠 것을 알린다
"""
import subprocess
import sys

from app.errors import Validation
from app.services import decision_answer

ACTION_KIND = "action"
OPEN_STATUS = "open"
CONFIRM_STATUS = "confirm"
DONE_STATUS = "done"
# 매니저 task-ui 가 남기는 화면 응답 종류(answer_via) — 매니저 tasks.VIA_* 와 같은 값
ACTION_VIAS = ("ui:progress", "ui:done")
CONFIRM_VIAS = ("ui:confirm", "ui:fix")
REPORT_VIAS = ACTION_VIAS + CONFIRM_VIAS
# 화면이 칸 모양·버튼 이름을 고르는 값
KIND_ACTION = "action"
KIND_CONFIRM = "confirm"
FIELDS = (
    "id", "title", "kind", "status", "detail", "next_step", "reason", "open_target", "answer", "answer_via",
    "answer_state", "answered_at", "created_at", "priority", "session",
    "after", "prereq_waiting", "steps",
)


def listable(row):
    """할일 상세에 올릴 것 — 열린 직접 할 일, 확인 대기, 화면에서 알린 뒤 닫힌 것(접어서 결과만 보인다)"""
    status = row.get("status")
    if status == CONFIRM_STATUS:
        return True
    if status == OPEN_STATUS:
        return row.get("kind") == ACTION_KIND
    return status == DONE_STATUS and row.get("answer_via") in REPORT_VIAS


def ordered(rows):
    """응답을 기다리는 것(우선순위 높은 것, 오래된 것 먼저)이 앞, 화면에서 알려 닫힌 것은 최근 순으로 뒤에"""
    waiting = sorted(
        (row for row in rows if row.get("status") != DONE_STATUS),
        key=lambda row: (-(row.get("priority") or 0), row.get("created_at") or "", row["id"]),
    )
    closed = sorted(
        (row for row in rows if row.get("status") == DONE_STATUS),
        key=lambda row: row.get("answered_at") or "",
        reverse=True,
    )
    return [view(row) for row in waiting + closed]


def show(task_id, home=None):
    """한 건 + 뒤에서 도는 응답 보내기(job). 매니저 탭 팝업이 열 때, 화면이 보낸 뒤 폴링할 때 읽는다"""
    return view(decision_answer._task(task_id, home))


def start(task_id, done=False, feedback=None, home=None, popen=subprocess.Popen):
    """task-ui 를 뒤에서 띄우고 바로 돌아온다. 매니저도 같은 검사를 하지만 고칠 수 있는 입력 오류는 여기서 먼저 막는다"""
    done = bool(done)
    feedback = (feedback or "").strip() or None
    if not done and not feedback:
        raise Validation("완료·확인을 누르거나 진행 상황·고칠 것을 적어 주세요")
    home = home or decision_answer.manager_home()
    row = decision_answer._task(task_id, home)
    status = row.get("status")
    if status == OPEN_STATUS and row.get("kind") != ACTION_KIND:
        raise Validation(f"결정은 답하기 칸에서 답합니다: #{task_id}")
    if status not in (OPEN_STATUS, CONFIRM_STATUS):
        raise Validation(f"이미 닫힌 할일입니다: #{task_id}")
    args = [sys.executable, decision_answer._script(home), "task-ui", str(task_id)]
    if done:
        args.append("--done")
    if feedback:
        args.append(f"--feedback={feedback}")
    busy = f"이 할일에 보낸 응답을 아직 전하는 중입니다: #{task_id}"
    return {**view(row), "job": decision_answer.launch(task_id, args, home, popen, busy)}


def view(row):
    out = {field: row.get(field) for field in FIELDS}
    out["report_kind"] = report_kind(row)
    out["job"] = decision_answer.job_of(row["id"])
    return out


def report_kind(row):
    """칸 모양 — 확인 대기(확인·고칠 것)인가 직접 할 일(완료·진행 상황)인가. 매니저 task-ui 가 상태로 동작을 고르므로
    열린 것은 상태를 따른다(고칠 것을 보내 다시 열린 직접 할 일은 다시 직접 할 일이다). 닫힌 것은 마지막 응답 종류로 가린다"""
    status = row.get("status")
    if status == CONFIRM_STATUS:
        return KIND_CONFIRM
    if status == OPEN_STATUS:
        return KIND_ACTION
    return KIND_CONFIRM if row.get("answer_via") in CONFIRM_VIAS else KIND_ACTION
