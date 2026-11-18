"""결정에 화면에서 답하기 — 할일 상세 창과 매니저 탭 결정 팝업의 선택지 버튼·의견 입력칸.

매니저 CLI 만 부른다(manager.py task list --json · task show · answer-ui). 선택지(options)·추천(recommend)·
답 상태(answer_state)·연결 세션(session)은 매니저가 계산해 내려 주는 칸이고, 답을 원 세션에 넘기는 일
(죽은 세션 되살리기·도착 확인·메인 매니저에 넘기기)도 매니저 몫이다. 여기서는 매니저 DB 를 읽거나 쓰지 않는다 —
정본이 둘이면 화면과 매니저가 다른 상태를 말하게 된다.

answer-ui 는 원 세션을 되살려 도착을 확인하느라 최대 90초 걸린다. 요청을 붙잡지 않게 뒤에서 돌리고 화면은
show() 를 폴링한다. 뒤의 프로세스는 새 세션 그룹으로 띄워 대시보드 서버가 다시 떠도 답 전달이 끊기지 않는다.
인자는 리스트로만 넘겨 셸을 거치지 않는다 — 의견 글이 명령으로 해석되지 않게. 값은 --feedback=<글> 한 덩어리로
붙여 '-' 로 시작하는 글이 argparse 옵션으로 읽히지도 않게 한다.
"""
import json
import os
import subprocess
import sys
import threading
from datetime import datetime

from app.constants import MANAGER_ANSWER_TIMEOUT_SEC, MANAGER_TASK_TIMEOUT_SEC
from app.errors import Conflict, NotFound, Validation
from app.repositories import sessions as session_repo

DECISION_KIND = "decision"
OPEN_STATUS = "open"
# 매니저가 답을 받는 상태. 이 밖이면 답이 있을 때만(다시 답하기) 받는다 — 매니저 answer-ui 와 같은 규칙
ACTIVE_STATUSES = ("open", "confirm")
SCRIPT = "manager.py"
# 화면이 쓰는 칸만 옮긴다. task list --json 은 매니저 내부 칸(보류·재알림·검증 시각)까지 준다
FIELDS = (
    "id", "title", "status", "detail", "next_step", "open_target", "options", "recommend",
    "answer_state", "answer", "answer_choice", "answer_feedback", "answered_at", "created_at", "session",
    "after", "prereq_waiting", "steps",
    # 권한 막힘 표시(ask --blocked permission) — 할일 상세가 결정 대기·직접 할 일과 따로 '권한 대기'로 모은다
    "blocked",
)
STDERR_TAIL_LINES = 1
# 답이 저장된 매니저 exit — 0 전달 · 1 전달 확인 못 함 · 3 원 세션 없음 · 4 매니저에 넘김 · 5 원 세션 꺼짐(task-ui)
SAVED_EXITS = (0, 1, 3, 4, 5)

# 결정 id → 뒤에서 도는 answer-ui 한 건. 서버 프로세스 하나가 들고 있다 — 서버가 다시 뜨면 비지만,
# 그때도 답 상태(answer_state)는 매니저 DB 에 남아 화면이 그것으로 이어 본다
_jobs = {}
_lock = threading.Lock()


class ManagerMissing(NotFound):
    """이 PC 에 매니저 레포가 없다"""


def manager_home():
    from app.services import manager_panel

    return manager_panel.manager_home()


def for_todo(con, todo_id, home=None):
    """그 할일에 붙은 결정. 결정을 올린 세션이 지금 붙잡은 할일(가장 최근 연결)이 이 할일인 것 —
    매니저 탭 줄이 카드를 고르는 규칙(manager_links.cards)과 같아, 줄의 카드를 눌러 열면 같은 결정이 보인다.
    열린 결정(답 대기)이 먼저, 이미 답한 결정(다시 답할 수 있다)은 최근 답 순으로 뒤에.
    같은 규칙으로 고른 직접 할 일·확인 대기(task_report)도 reports 로 함께 준다 — 매니저 목록을 한 번만 읽는다.
    → {"available": 매니저가 있나, "items": [...], "reports": [...]}"""
    from app.services import task_report

    try:
        rows = _call(["task", "list", "--json", "--all"], home)
    except ManagerMissing:
        return {"available": False, "items": [], "reports": []}
    decisions = [row for row in rows or [] if _answerable(row)]
    reports = [row for row in rows or [] if task_report.listable(row)]
    session_ids = sorted({row.get("session_id") for row in decisions + reports} - {None, ""})
    cards = session_repo.current_cards(con, session_ids)

    def here(row):
        return (cards.get(row.get("session_id")) or {}).get("todo_id") == todo_id

    mine = [row for row in decisions if here(row)]
    waiting = sorted(
        (row for row in mine if row.get("status") == OPEN_STATUS),
        key=lambda row: (-(row.get("priority") or 0), row.get("created_at") or "", row["id"]),
    )
    answered = sorted(
        (row for row in mine if row.get("status") != OPEN_STATUS),
        key=lambda row: row.get("answered_at") or "",
        reverse=True,
    )
    return {
        "available": True,
        "items": [_view(row) for row in waiting + answered],
        "reports": task_report.ordered([row for row in reports if here(row)]),
    }


def show(task_id, home=None):
    """결정 한 건 + 뒤에서 도는 답 보내기(job). 화면이 답을 보낸 뒤 이걸 폴링한다"""
    return _view(_task(task_id, home))


def start(task_id, choice=None, feedback=None, home=None, popen=subprocess.Popen):
    """answer-ui 를 뒤에서 띄우고 바로 돌아온다. 매니저도 같은 검사를 하지만, 뒤에서 실패하면 화면이
    폴링이 끝난 뒤에야 알게 되므로 고칠 수 있는 입력 오류는 여기서 먼저 막는다"""
    choice = (choice or "").strip() or None
    feedback = (feedback or "").strip() or None
    if not choice and not feedback:
        raise Validation("고를 선택지나 의견 중 하나는 있어야 합니다")
    home = home or manager_home()
    row = _task(task_id, home)
    if row.get("kind") != DECISION_KIND:
        raise Validation(f"결정이 아니라 답할 수 없습니다: #{task_id}")
    if row.get("status") not in ACTIVE_STATUSES and not row.get("answer"):
        raise Validation(f"답 없이 닫힌 결정이라 답할 수 없습니다: #{task_id}")
    keys = [str(option.get("key", "")) for option in row.get("options") or []]
    if choice and choice.casefold() not in {key.casefold() for key in keys}:
        raise Validation(f"이 결정에 없는 선택지입니다: {choice}")
    args = [sys.executable, _script(home), "answer-ui", str(task_id)]
    if choice:
        args.append(f"--choice={choice}")
    if feedback:
        args.append(f"--feedback={feedback}")
    busy = f"이 결정에 보낸 답을 아직 전하는 중입니다: #{task_id}"
    return {**_view(row), "job": launch(task_id, args, home, popen, busy)}


def launch(task_id, args, home, popen, busy):
    """매니저 명령 한 건을 뒤에서 띄우고 job 을 돌려준다. 같은 할일에 돌고 있는 것이 있으면 Conflict(busy).
    직접 할 일·확인 대기 응답(task_report)도 이것을 쓴다 — 할일 id 는 종류를 가리지 않고 하나라 job 도 한 표에 둔다"""
    with _lock:
        running = _jobs.get(task_id)
        if running and running["running"]:
            raise Conflict(busy)
        proc = popen(
            args,
            cwd=home,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        job = {"running": True, "started_at": _now(), "finished_at": None, "exit": None, "error": None}
        _jobs[task_id] = job
    threading.Thread(target=_wait, args=(proc, job), daemon=True).start()
    return dict(job)


def _wait(proc, job):
    try:
        out, err = proc.communicate(timeout=MANAGER_ANSWER_TIMEOUT_SEC)
        code = proc.returncode
        error = _job_error(code, out, err)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        code = None
        error = f"답 전달이 {MANAGER_ANSWER_TIMEOUT_SEC}초 안에 끝나지 않았습니다"
    with _lock:
        job.update(running=False, finished_at=_now(), exit=code, error=error)


def _job_error(code, out, err):
    """사용법 오류(exit 2)는 매니저가 JSON 의 error 로 사유를 준다. 그 밖의 exit(0·1·3·4, task-ui 의 5 원 세션 꺼짐)는
    답이 저장된 결과라 오류가 아니다 — 무엇이 됐는지는 answer_state 가 말한다. 모르는 exit 는 stderr 끝줄을 사유로"""
    if code in SAVED_EXITS:
        return None
    parsed = _last_json(out)
    if isinstance(parsed, dict) and parsed.get("error"):
        return parsed["error"]
    tail = (err or out or "").strip().splitlines()[-STDERR_TAIL_LINES:]
    return " ".join(tail) or f"exit {code}"


def _last_json(text):
    for line in reversed((text or "").strip().splitlines()):
        try:
            return json.loads(line)
        except ValueError:
            continue
    return None


def _answerable(row):
    """결정 중 화면에 올릴 것 — 답을 기다리는 것과 이미 답한 것. 답 없이 닫힌 것은 답할 수 없다.
    확인 대기로 갔다가 화면에서 확인·고칠 것을 받은 결정(answer_via 가 task-ui 종류)은 답이 아니라 task_report 몫이다"""
    from app.services import task_report

    if row.get("kind") != DECISION_KIND:
        return False
    if row.get("status") == OPEN_STATUS:
        return True
    return bool(row.get("answer")) and row.get("answer_via") not in task_report.REPORT_VIAS


def _view(row):
    view = {field: row.get(field) for field in FIELDS}
    view["options"] = view["options"] or []
    view["job"] = job_of(row["id"])
    return view


def job_of(task_id):
    """그 할일에 뒤에서 돌고 있거나 마지막으로 돈 매니저 명령(answer-ui·task-ui)의 사본. 없으면 None"""
    with _lock:
        job = _jobs.get(task_id)
        return dict(job) if job else None


def _task(task_id, home):
    row = _call(["task", "show", str(task_id)], home)
    if not row:
        raise NotFound(f"매니저 할일이 없습니다: #{task_id}")
    return row


def _call(args, home=None):
    home = home or manager_home()
    done = subprocess.run(
        [sys.executable, _script(home), *args],
        cwd=home,
        capture_output=True,
        text=True,
        timeout=MANAGER_TASK_TIMEOUT_SEC,
    )
    if done.returncode != 0:
        tail = (done.stderr or done.stdout).strip().splitlines()[-STDERR_TAIL_LINES:]
        raise RuntimeError(" ".join(tail) or f"manager.py {' '.join(args)} exit {done.returncode}")
    return json.loads(done.stdout or "null")


def _script(home):
    script = os.path.join(home, SCRIPT)
    if not os.path.isfile(script):
        raise ManagerMissing(f"매니저가 없습니다: {script}")
    return script


def _now():
    return datetime.now().astimezone().isoformat(timespec="seconds")
