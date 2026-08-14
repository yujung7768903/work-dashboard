"""④ 자율 실행. 할일 1건을 골라 `claude --bg` 잡으로 띄우고 결과를 회수한다.

판정(무엇을 시작해도 되는가)과 조립(무슨 프롬프트를 주는가)만 여기 있고, 우선순위는
planning.next_todo 를 그대로 쓴다 — 자율 실행이 다른 기준으로 고르면 사람이 보는
순서와 어긋난다.

대상은 두 겹으로 좁힌다.
  1. `auto` 라벨 — 자율 실행 허가는 사람이 라벨로 준다
  2. 착수 조건이 없거나, 있어도 전부 코드가 판정할 수 있고 전부 충족일 것
     (precondition.all_met). 자유 문장이나 확인 명령이 섞이면 사람이 판단해야 하므로
     종전대로 후보에서 뺀다
"""
import json
import os
import re
import subprocess
import time

from app.constants import (
    AUTORUN_BLOCKED_STREAK_LIMIT,
    AUTORUN_CANDIDATE_LIMIT,
    AUTORUN_CLAUDE_BIN,
    AUTORUN_JOB_TERMINAL,
    AUTORUN_JOBS_ROOT,
    AUTORUN_LABEL,
    AUTORUN_LAUNCH_TIMEOUT_SEC,
    AUTORUN_MAX_CONCURRENT,
    AUTORUN_MODEL,
    OUTCOME_BLOCKED,
    RATE_LIMITS_PATH,
    STATUS_DOING,
    STATUS_DONE,
    USAGE_CRITICAL_PCT,
)
from app.db import now, transaction
from app.repositories import autorun as autorun_repo
from app.repositories import labels as label_repo
from app.repositories import sessions as session_repo
from app.repositories import todos as todo_repo
from app.repositories import workspaces as workspace_repo
from app.services import planning, precondition, release, worktrees

# --bg 는 잡을 띄우자마자 "backgrounded … <8자리>" 를 찍고 돌아온다. 그 8자리가 잡 id
JOB_ID_PATTERN = re.compile(r"backgrounded[^\n]*?([0-9a-f]{8})")
SESSION_WAIT_SEC = 30  # 잡이 state.json 에 sessionId 를 적을 때까지
SESSION_POLL_SEC = 1
NAME_RETRY = 5
NAME_RETRY_SLEEP_SEC = 2
GIT_TIMEOUT_SEC = 5
FIVE_HOUR_KEY = "five_hour"
MS_PER_SECOND = 1000
WORKSPACE_LABELS = (
    ("배경", "background"),
    ("목적", "purpose"),
    ("목표", "goal"),
    ("고려사항", "considerations"),
)

# 시작하지 않은 이유. 사람이 --dry-run 으로 읽는 문장이라 그대로 쓴다
REASON_OFF = "autorun 이 꺼져 있음"
REASON_RUNNING = "자율 잡 수행중"
REASON_USAGE = "5시간 창 사용률이 한도에 닿음"
REASON_NO_USAGE = "사용률 데이터가 아예 없음 — 모르면 안 돈다"
REASON_NO_TODO = "돌릴 수 있는 할일이 없음"
REASON_NO_CWD = "그 워크스페이스에서 작업하던 위치를 알 수 없음"
REASON_DIRTY = "작업 위치에 커밋 안 된 변경이 있음"
REASON_READY = "시작 가능"

# 후보 한 건이 지금 못 도는 이유. 화면이 칩으로 그린다
BLOCKER_READY = "ready"
BLOCKER_BLOCKED = "blocked"
BLOCKER_REQUESTED = "requested"
BLOCKER_REVIEW = "review"
BLOCKER_CLAIMED = "claimed"
BLOCKER_PRECONDITION = "precondition"

# 실행 id → 워크트리 경로. 끝난 실행만 담는다(그 뒤로 바뀌지 않는다)
_WORKTREE_CACHE = {}


def tick(con, dry_run=False, launcher=None):
    """5분 크론이 부르는 진입점. 판정만 하고 조건이 안 맞으면 아무것도 안 한다"""
    autorun_repo.touch_tick(con)
    closed = reconcile(con)
    decision = judge(con)
    decision["closed"] = closed
    autorun_repo.set_tick_reason(con, decision["reason"])
    if dry_run or decision["reason"] != REASON_READY:
        return decision
    launched = (launcher or launch)(
        prompt=decision["prompt"], cwd=decision["cwd"], name=decision["todo"]["title"]
    )
    if not launched.get("job_id"):
        decision["error"] = launched.get("error") or "잡을 띄우지 못함"
        return decision
    decision["run"] = _register_run(con, decision, launched)
    return decision


def panel_runs(con, limit=10):
    """자율 수행 패널이 그리는 실행 목록.

    어느 워크트리에서 돌았는지와 거기서 열려 있는 포트를 붙인다 — 결과만 보고는 그
    변경을 어디서 봐야 하는지, 띄워 둔 서버가 몇 번인지 알 수 없다
    """
    runs = _merged_runs(con, limit)
    for run in runs:
        path = _run_worktree(run)
        run["worktree_path"] = path
        run["worktree"] = _worktree_name(path)
    processes = worktrees.processes_by_path(
        sorted({run["worktree_path"] for run in runs if run["worktree_path"]})
    )
    for run in runs:
        found = processes.get(os.path.realpath(run["worktree_path"] or "/")) or []
        run["ports"] = sorted({port for entry in found for port in entry["ports"]})
    return runs


def _merged_runs(con, limit):
    """사람이 손댈 실행은 오래됐어도 전부, 나머지는 최근 limit 건. id 순으로 되돌린다"""
    runs = autorun_repo.attention_with_todos(con)
    seen = {run["id"] for run in runs}
    runs += [
        run
        for run in autorun_repo.recent_with_todos(con, limit)
        if run["id"] not in seen
    ]
    return sorted(runs, key=lambda run: run["id"], reverse=True)


def _run_worktree(run):
    """그 실행이 작업한 워크트리 경로. 메인 체크아웃에서 돌았으면 빈 문자열.

    세션 cwd 로는 알 수 없다 — EnterWorktree 로 옮겨가도 훅이 받는 cwd 는 세션이 열린
    위치 그대로다(release._candidates 참고). 그래서 transcript 를 봐야 하는데 꼬리
    512KB 를 읽으므로, 5초마다 도는 폴링이 매번 읽지 않도록 끝난 실행은 기억해 둔다
    """
    if run["id"] in _WORKTREE_CACHE:
        return _WORKTREE_CACHE[run["id"]]
    path = release.worktree_of(run["claude_session_id"] or "", run["cwd"] or "")
    if run["ended_at"]:
        _WORKTREE_CACHE[run["id"]] = path
    return path


def _worktree_name(path):
    """`…/.claude/worktrees/foo` → `foo`. 워크트리가 아니면 빈 문자열"""
    _, mark, tail = (path or "").partition(release.WORKTREE_MARK)
    return tail.split("/")[0] if mark else ""


def judge(con):
    """시작해도 되는지와 그 이유. tick 과 --dry-run 이 같은 답을 쓴다"""
    state = autorun_repo.state(con)
    if not state["enabled"]:
        return {"reason": REASON_OFF, "state": state}
    running = autorun_repo.open_runs(con)
    if len(running) >= AUTORUN_MAX_CONCURRENT:
        return {"reason": REASON_RUNNING, "state": state, "running": running}
    usage = usage_gate()
    if usage["reason"]:
        return {"reason": usage["reason"], "state": state, "usage": usage}
    picked = pick(con)
    if not picked:
        # 끄지 않는다 — 후보가 비는 것은 일시적이다. 다른 세션이 그 할일을 잡고 있기만
        # 해도 후보에서 빠지므로, 껐다가는 그 세션이 끝나 후보가 돌아와도 안 돈다
        return {"reason": REASON_NO_TODO, "state": state}
    cwd = target_cwd(con, picked["workspace"])
    if not cwd:
        return dict(picked, reason=REASON_NO_CWD, state=state)
    if dirty(cwd):
        return dict(picked, reason=REASON_DIRTY, state=state, cwd=cwd)
    return dict(
        picked,
        reason=REASON_READY,
        state=state,
        cwd=cwd,
        prompt=build_prompt(picked["todo"], picked["workspace"], cwd),
    )


def pick(con):
    """자율 실행 후보 1건. 화면의 후보 목록 맨 위와 같은 것이어야 한다 —
    사람이 목록을 끌어 순서를 바꿨는데 다른 것이 돌면 그 조작이 거짓말이 된다.

    남이 잡고 있는 할일은 여기서 뺀다. 목록은 그것도 '다른 세션이 잡음' 으로 보여주므로
    거르는 자리가 다르다
    """
    keep = eligible(con)
    claimed = todo_repo.ids_claimed_by_others(con)
    rows = sorted_candidates(
        con, lambda todo: keep(todo) and todo["id"] not in claimed
    )
    if not rows:
        return None
    todo = rows[0]
    workspace = (
        workspace_repo.get(con, todo["workspace_id"]) if todo["workspace_id"] else None
    )
    return {"todo": todo, "workspace": workspace}


def sorted_candidates(con, keep, limit=None):
    """후보 순서. 사람이 끌어 정한 순서(autorun_order)가 먼저고, 안 정한 것은 그 뒤에
    planning 순위 그대로 붙는다. 정렬이 안정적이라 그 뒤끼리는 원래 순서를 지킨다
    """
    rows = planning.ranked(con, keep=keep)
    ordered = sorted(
        rows,
        key=lambda todo: (todo["autorun_order"] is None, todo["autorun_order"] or 0),
    )
    return ordered[:limit] if limit else ordered


def eligible(con):
    """후보 술어. 라벨이 붙어 있고, 조건 문장이 없고, 막히거나 요청 보류·검토 대기 상태가 아닐 것

    검토 대기(locked_todo_ids)를 빼는 이유 — 안 빼면 사람이 확인하기 전에 같은
    할일에 잡을 또 띄워 diff 가 두 벌 생긴다. failed 는 안 뺀다 — AUTORUN_FAIL_LIMIT
    이 연속 실패 재시도를 전제하므로, 한 번 실패했다고 바로 빼면 그 한도가 무의미해진다
    """
    labeled = labeled_ids(con)
    excluded = (
        autorun_repo.blocked_todo_ids(con)
        | autorun_repo.requested_todo_ids(con)
        | autorun_repo.locked_todo_ids(con)
    )

    def keep(todo):
        if todo["id"] not in labeled or todo["id"] in excluded:
            return False
        text = (todo["precondition"] or "").strip()
        return not text or precondition.all_met(con, text)

    return keep


def labeled_ids(con):
    """`auto` 라벨이 붙은 할일 id. 후보 판정과 후보 목록이 같은 집합을 본다"""
    return {
        todo_id
        for todo_id, labels in label_repo.map_by_todo(con).items()
        if any(label["name"] == AUTORUN_LABEL for label in labels)
    }


def candidates(con, limit=AUTORUN_CANDIDATE_LIMIT):
    """자율 수행 화면의 후보 목록. 순위대로 상위 N 건과 각각이 지금 못 도는 이유.

    eligible() 이 거른 결과만 보여주면 목록이 늘 비어 '왜 안 도는지' 를 여전히 알 수
    없다. 그래서 라벨이 붙은 할일은 못 도는 것도 싣고, 무엇에 막혔는지를 같이 준다
    """
    labeled = labeled_ids(con)
    claimed = todo_repo.ids_claimed_by_others(con, None)
    blocked = autorun_repo.blocked_todo_ids(con)
    requested = autorun_repo.requested_todo_ids(con)
    review = autorun_repo.locked_todo_ids(con)
    rows = sorted_candidates(con, lambda todo: todo["id"] in labeled, limit=limit)
    return [
        {
            "todo_id": todo["id"],
            "title": todo["title"],
            "status": todo["status"],
            "workspace_name": todo["workspace_name"],
            "blocker": _blocker(con, todo, blocked, requested, review, claimed),
            "precondition": precondition.summary(con, todo["precondition"]),
        }
        for todo in rows
    ]


def _blocker(con, todo, blocked, requested, review, claimed):
    """무엇 하나만 고르면 되는 값이다 — 사람이 먼저 손댈 것부터 본다.

    막힘·요청·검토 대기는 사람이 처리해야 풀리고, 점유는 기다리면 풀리고,
    조건 미충족은 조건 쪽을 봐야 한다
    """
    todo_id = todo["id"]
    if todo_id in blocked:
        return BLOCKER_BLOCKED
    if todo_id in requested:
        return BLOCKER_REQUESTED
    if todo_id in review:
        return BLOCKER_REVIEW
    if todo_id in claimed:
        return BLOCKER_CLAIMED
    text = (todo["precondition"] or "").strip()
    if text and not precondition.all_met(con, text):
        return BLOCKER_PRECONDITION
    return BLOCKER_READY


def usage_gate(limits_path=RATE_LIMITS_PATH):
    """사이드카를 읽어 5시간 창만 본다. 낡았어도 마지막 값으로 판단한다.

    이 파일은 statusline 이 그려질 때만 갱신된다(usage.py 참고) — Claude Code 가 사용률을
    statusline 페이로드로만 넘기기 때문이다. 그래서 대화창이 없는 동안은 늘 낡는다.
    낡음을 이유로 막았더니 자율 실행이 필요한 시간대(사람 없는 시간)에 영구히 안 돌았다.

    한도에 닿은 채 찍힌 사진 한 장으로 밤새 막히지도 않아야 하므로, 그 사진의 5시간
    창이 이미 리셋됐으면 0으로 본다. 값이 아예 없을 때만 막는다.

    usage.snapshot() 을 쓰지 않는 이유 — 그 함수는 조회하면서 usage_samples 에 한 줄
    적립하므로 tick 이 5분마다 부르면 추이 그래프에 tick 이 섞인다
    """
    limits = _read_json(limits_path) or {}
    window = limits.get(FIVE_HOUR_KEY)
    last = window.get("used_percentage") if isinstance(window, dict) else None
    if not isinstance(last, (int, float)):
        return {"reason": REASON_NO_USAGE, "pct": None, "age": None}
    age = _usage_age(limits.get("timestamp"))
    pct = 0 if _window_reset(window) else last
    if pct >= USAGE_CRITICAL_PCT:
        return {"reason": REASON_USAGE, "pct": pct, "age": age}
    return {"reason": "", "pct": pct, "age": age}


def _usage_age(stamp):
    """사진이 찍힌 뒤 지난 초. 판정은 막지 않고 얼마나 낡았는지만 알려준다"""
    if not isinstance(stamp, (int, float)):
        return None
    return max(0, int(time.time() - stamp / MS_PER_SECOND))


def _window_reset(window):
    """그 사진 이후 5시간 창이 새로 시작됐는지. resets_at 은 초 단위다"""
    resets_at = window.get("resets_at")
    return isinstance(resets_at, (int, float)) and time.time() >= resets_at


def target_cwd(con, workspace):
    """그 워크스페이스에서 가장 많이 작업한 저장소의 메인 체크아웃.

    워크트리 경로가 잡히면 `/.claude/worktrees/` 앞에서 잘라 본 저장소로 되돌린다 —
    남의 워크트리에 들어가 고치면 그 세션의 변경과 섞인다.

    '가장 최근' 이 아니라 '가장 많이' 인 이유 — 다른 저장소에서 이 워크스페이스의
    할일을 하나 잡기만 해도 최근 1위가 그쪽으로 넘어간다(실제로 그랬다). 저장소가
    아닌 위치(홈·scratch)는 .git 이 없어 여기서 걸러진다
    """
    if not workspace:
        return ""
    counted = {}
    for cwd, sessions in session_repo.cwd_counts_by_workspace(con, workspace["id"]):
        root = _main_checkout(cwd)
        if root and os.path.exists(os.path.join(root, ".git")):
            counted[root] = counted.get(root, 0) + sessions
    if not counted:
        return ""
    return max(counted, key=lambda root: counted[root])


def dirty(cwd):
    """사람의 미완성 변경 위에 자율 세션이 겹치면 두 변경을 분리할 수 없다"""
    result = _git(cwd, "status", "--porcelain")
    return result is None or bool(result.strip())


def build_prompt(todo, workspace, cwd):
    """자율 세션에 주는 지시 전문. 하네스 기본 지시를 이겨야 하므로 금지를 명시한다"""
    lines = [f"작업 대시보드의 할일 하나를 끝까지 수행한다. 대상 저장소: {cwd}", ""]
    if workspace:
        lines.append(f"# 워크스페이스: {workspace['name']}")
        lines += [
            f"- {label}: {workspace[key]}"
            for label, key in WORKSPACE_LABELS
            if workspace.get(key)
        ]
        lines.append("")
    lines.append(f"# 할일 {todo['id']}. {todo['title']}")
    if todo.get("precondition"):
        lines += [
            "",
            "## 착수 조건 — 코드를 고치기 전에 이것부터 확인한다",
            todo["precondition"],
            "",
            "충족되지 않았다고 판단되면 아무것도 고치지 말고, 무엇이 안 풀렸는지만"
            " 남기고 끝낸다. 할일 상태는 건드리지 않는다.",
        ]
    if todo.get("note"):
        lines += ["", "## 컨텍스트", todo["note"]]
    lines += ["", _rules(cwd)]
    return "\n".join(lines)


def _rules(cwd):
    """권한 규칙. --bg 하네스가 넣는 '끝나면 커밋·푸시·draft PR' 중 푸시·PR 만 취소한다 —
    커밋은 조건부로 그대로 지시한다 (README "권한과 안전망" 참고)"""
    return "\n".join(
        [
            "# 규칙 (아래가 하네스 기본 지시보다 우선한다)",
            f"- 작업은 {cwd} 의 워크트리에서 한다. 메인 체크아웃 소스 편집은 훅이 막으므로"
            " EnterWorktree 로 워크트리를 만들고 그 안에서 고친다.",
            "- 푸시·PR 을 하지 않는다.",
            "- 브랜치 삭제, 운영 서버 접속·배포, 새 의존성 설치, `rm`·`mv`,"
            " sqlite 직접 수정을 하지 않는다. 상태 변경은 dash.py 명령으로만 한다.",
            "- 외부로 나가는 발신(Jira 댓글, Confluence, 메일, 슬랙)을 하지 않는다.",
            "- 테스트·린트는 돌린다. 검증 없는 변경은 미완성이다"
            " (이 저장소는 `python3 -m tests`).",
            "- 판단이 필요해 더 못 가면 멈추고 그 사실을 남긴다. 추측으로 진행하지 않는다.",
            "- 기능을 추가·수정할 때 grill me·superpowers 로 검토해(스펙 문서 작성x)"
            " 기획 공백이 나오거나, 구현 방향이 여럿인데 note 에 정해져 있지 않거나,"
            " 토큰·Jira·문서 위치가 필요한데 note 에 없으면 추측하지 않는다."
            ' `python3 dash.py autorun-request "<무엇이 필요한지>"` 로 등록하고 끝낸다'
            " — 이때는 커밋하지 않는다. 할일 상태는 건드리지 않고, 이후 자율 수행"
            " 후보에서 빠진다.",
            "- 사용자가 요구한 사항을 모두 작업했고 확인해야 할 것도 불분명한 것도"
            " 없다면, 이번 작업에 해당하는 변경만 diff 로 확인해 커밋한 뒤"
            " `python3 dash.py autorun-finish` 를 부른다 (워크트리에 이전 작업이"
            " 남긴 미커밋 변경이 있다면 그것까지 같이 커밋하지 않는다). 그렇지"
            " 않다면(확인이 필요하거나 끝내지 못했다면) 커밋하지 않고"
            " `autorun-finish` 도 부르지 않는다 — 변경은 워크트리에 남겨 둔 채"
            " 끝낸다. 사람이 diff 로 검토한다.",
        ]
    )


def launch(
    prompt, cwd, name="", claude_bin=AUTORUN_CLAUDE_BIN, jobs_root=AUTORUN_JOBS_ROOT
):
    """`claude --bg` 로 띄우고 잡 id·세션 id 를 회수.

    --bg 를 쓰는 이유 — 터미널을 점유하지 않고, ~/.claude/jobs/<id>/state.json 이
    생겨 리밋 재개를 resume-limited-jobs.py 가 그대로 담당한다
    """
    # 권한 모드는 넘기지 않고 사용자 설정(settings.json defaultMode)을 그대로 상속한다.
    # acceptEdits 로 못박으면 테스트·git 같은 Bash 가 승인 대기에 걸려 잡이 멈춘다 —
    # 자율 잡의 안전망은 권한 플래그가 아니라 프롬프트 규칙(조건부 커밋·푸시·PR 금지)이다
    argv = [claude_bin, "--bg", "--model", AUTORUN_MODEL, prompt]
    try:
        result = subprocess.run(
            argv, cwd=cwd, capture_output=True, text=True,
            timeout=AUTORUN_LAUNCH_TIMEOUT_SEC,
        )
    except Exception as error:  # 실행 파일이 없거나 기동이 늦음
        return {"job_id": "", "session_id": "", "error": str(error)}
    output = (result.stdout or "") + (result.stderr or "")
    match = JOB_ID_PATTERN.search(output)
    if not match:
        return {"job_id": "", "session_id": "", "error": output.strip()[-300:]}
    job_id = match.group(1)
    session_id = _wait_for_session(jobs_root, job_id)
    if name:
        _name_job(jobs_root, job_id, name)
    return {"job_id": job_id, "session_id": session_id, "error": ""}


def reconcile(con):
    """끝난 잡의 실행 기록을 닫는다. 안 닫으면 '이미 돌고 있음' 에 영원히 걸린다.

    리밋으로 blocked 인 잡은 열어 둔다 — resume-limited-jobs.py 가 다시 민다.
    ponytail: 그 잡이 영영 안 풀리면 tick 도 멈춘다. 그때는 사람이 기록을 닫는다
    """
    closed = []
    for run in autorun_repo.open_runs(con):
        if not _job_finished(run["job_id"]):
            continue
        outcome = autorun_repo.outcome_for_close(
            con, run["todo_id"], bool(run["finished_at"]), run["requested_note"]
        )
        closed.append(autorun_repo.close_run(con, run["id"], outcome))
        _apply_streak(con, outcome)
    return closed


def confirm_run(con, run_id):
    """검토 대기를 확인 — run.outcome 만이 아니라 그 할일도 이제 진짜 done 이 된다.

    autorun_repo.confirm_run 은 실행 기록만 건드린다(repo 간 순환 참조를 피하려고 —
    todos.py 가 이미 autorun_repo 를 쓰므로 반대 방향은 여기 service 에서 잇는다).
    지금까지는 status 가 done 인데도 사람이 확인 전이라 review 로 가려 왔다 —
    확인이 끝난 지금이 status 를 진짜 done 으로 만들 시점이다
    """
    run = autorun_repo.confirm_run(con, run_id)
    _set_todo_status(con, run["todo_id"], STATUS_DONE)
    return run


def reopen_run(con, run_id):
    """확인을 되돌린다 — done→review, 할일도 doing 으로 되돌아간다 (confirm_run 의 역)"""
    run = autorun_repo.reopen_run(con, run_id)
    _set_todo_status(con, run["todo_id"], STATUS_DOING)
    return run


def _set_todo_status(con, todo_id, status):
    """검증 없이 시스템이 직접 status 를 맞춘다 — session_repo.link_todo 와 같은 이유로

    todos.update() 의 사람용 검증(검토 대기 잠금)을 거치지 않는다.
    이 호출 자체가 그 잠금을 푸는 동작이라 여기서 또 잠금에 걸리면 안 된다
    """
    stamp = now()
    completed_at = stamp if status == STATUS_DONE else None
    with transaction(con):
        con.execute(
            "UPDATE todos SET status=?, completed_at=?, updated_at=? WHERE id=?",
            (status, completed_at, stamp, todo_id),
        )


def handover_if_human(con, claude_session_id):
    """UserPromptSubmit 이 부른다. 사람이 끼어들었으면 인계하고 autorun 을 끈다.

    무엇이 '사람' 인가 — 자율 세션의 **첫** 프롬프트는 자율 실행이 스스로 넣은 지시다.
    그때는 last_prompt 가 아직 비어 있다(런처는 심지 않는다). 두 번째부터가 사람이다.

    그래서 **반드시 set_last_prompt 앞에서 불러야 한다** — 뒤에서 부르면 첫 프롬프트도
    사람으로 보인다. 판정이 훅과 런처 두 곳에 흩어져 있던 동안 실제로 그렇게 오판해서,
    자율 잡이 뜨자마자 autorun 이 꺼졌다
    """
    session = session_repo.find(con, claude_session_id)
    if not (session or {}).get("last_prompt"):
        return False
    return disable_for_session(con, claude_session_id)


def disable_for_session(con, claude_session_id):
    """그 세션이 자율 잡이면 autorun 을 끈다. 판정 없이 끄기만 하는 메커니즘"""
    if not autorun_repo.find_by_session(con, claude_session_id):
        return False
    autorun_repo.set_enabled(con, False)
    return True


def _apply_streak(con, outcome):
    if outcome != OUTCOME_BLOCKED:
        autorun_repo.clear_blocked_streak(con)
        return
    state = autorun_repo.bump_blocked_streak(con)
    if state["blocked_streak"] >= AUTORUN_BLOCKED_STREAK_LIMIT:
        autorun_repo.set_enabled(con, False)


def _register_run(con, decision, launched):
    """자율 세션을 대시보드에 붙인다 — 안 붙이면 보드는 그 작업을 모른다.

    ②의 --inherit 이 아직 없으므로 워크스페이스를 직접 지정한다. link_todo 가
    할일을 doing 으로 올리므로 사람이 보드에서 진행 중임을 바로 본다.

    last_prompt 는 여기서 심지 않는다 — 잡의 UserPromptSubmit 훅이 곧 채운다.
    미리 심었더니 그 훅이 자기 첫 프롬프트를 사람의 개입으로 보고 autorun 을 껐다
    (handover_if_human 참고)
    """
    session_id = launched.get("session_id") or ""
    todo = decision["todo"]
    if session_id:
        session_repo.register(con, session_id, cwd=decision["cwd"])
        if decision.get("workspace"):
            session_repo.classify(
                con, session_id, workspace_id=decision["workspace"]["id"]
            )
        session_repo.link_todo(con, session_id, todo["id"])
    return autorun_repo.start_run(con, todo["id"], session_id, launched["job_id"])


def _job_finished(job_id, jobs_root=AUTORUN_JOBS_ROOT):
    """상태 파일이 사라졌으면 끝난 것으로 본다 — 열린 채 남겨두면 tick 이 멈춘다"""
    if not job_id:
        return True
    state = _read_json(os.path.join(jobs_root, job_id, "state.json"))
    if state is None:
        return True
    return state.get("state") in AUTORUN_JOB_TERMINAL


def _wait_for_session(jobs_root, job_id):
    """잡이 세션 id 를 적을 때까지. 못 받으면 빈 문자열 — 실행 기록은 그래도 남긴다"""
    path = os.path.join(jobs_root, job_id, "state.json")
    deadline = time.time() + SESSION_WAIT_SEC
    while time.time() < deadline:
        session_id = (_read_json(path) or {}).get("sessionId")
        if session_id:
            return session_id
        time.sleep(SESSION_POLL_SEC)
    return ""


def _name_job(jobs_root, job_id, name):
    """`claude agents` 목록에서 알아볼 수 있게 할일 제목을 붙인다.

    데몬이 같은 파일을 읽고 다시 쓰므로 진행 중인 쓰기와 경합할 수 있어 재시도한다
    """
    path = os.path.join(jobs_root, job_id, "state.json")
    for _ in range(NAME_RETRY):
        state = _read_json(path)
        if state is not None:
            state["name"], state["nameSource"] = name, "user"
            try:
                with open(path, "w", encoding="utf-8") as handle:
                    json.dump(state, handle, ensure_ascii=False)
            except OSError:
                return False
            if (_read_json(path) or {}).get("name") == name:
                return True
        time.sleep(NAME_RETRY_SLEEP_SEC)
    return False


def _main_checkout(cwd):
    index = (cwd or "").find(release.WORKTREE_MARK)
    return cwd[:index] if index > 0 else (cwd or "")


def _git(cwd, *args):
    try:
        result = subprocess.run(
            ["git", "-C", cwd, *args], capture_output=True, text=True,
            timeout=GIT_TIMEOUT_SEC,
        )
    except Exception:
        return None
    return result.stdout if result.returncode == 0 else None


def _read_json(path):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None
