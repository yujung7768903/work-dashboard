"""자율 실행 설정과 실행 기록. 판정은 여기 없고 service 가 한다"""
from app.constants import (
    AUTORUN_FAIL_LIMIT,
    AUTORUN_OUTCOMES,
    OUTCOME_BLOCKED,
    OUTCOME_DONE,
    OUTCOME_FAILED,
    OUTCOME_REVIEW,
)
from app.db import now, transaction
from app.errors import NotFound, Validation

STATE_ROW_ID = 1


def state(con):
    """단일 행. 없으면 만들어 돌려준다 — 기본은 off"""
    row = con.execute(
        "SELECT * FROM autorun_state WHERE id=?", (STATE_ROW_ID,)
    ).fetchone()
    if row:
        return dict(row)
    with transaction(con):
        con.execute(
            "INSERT INTO autorun_state(id, enabled, blocked_streak, updated_at)"
            " VALUES(?,0,0,?)",
            (STATE_ROW_ID, now()),
        )
    return state(con)


def set_enabled(con, enabled):
    """켤 때 blocked_streak 을 0 으로 되돌린다 — 다시 켰다는 것은 원인을 봤다는 뜻"""
    state(con)
    stamp = now()
    with transaction(con):
        con.execute(
            "UPDATE autorun_state SET enabled=?, updated_at=? WHERE id=?",
            (1 if enabled else 0, stamp, STATE_ROW_ID),
        )
        if enabled:
            con.execute(
                "UPDATE autorun_state SET blocked_streak=0 WHERE id=?", (STATE_ROW_ID,)
            )
    return state(con)


def touch_tick(con):
    state(con)
    stamp = now()
    with transaction(con):
        con.execute(
            "UPDATE autorun_state SET last_tick_at=?, updated_at=? WHERE id=?",
            (stamp, stamp, STATE_ROW_ID),
        )


def bump_blocked_streak(con):
    """연속 blocked 하나 더"""
    current = state(con)
    with transaction(con):
        con.execute(
            "UPDATE autorun_state SET blocked_streak=?, updated_at=? WHERE id=?",
            (current["blocked_streak"] + 1, now(), STATE_ROW_ID),
        )
    return state(con)


def clear_blocked_streak(con):
    state(con)
    with transaction(con):
        con.execute(
            "UPDATE autorun_state SET blocked_streak=0, updated_at=? WHERE id=?",
            (now(), STATE_ROW_ID),
        )
    return state(con)


def open_runs(con):
    """아직 안 끝난 실행. 동시 1건 판정에 쓴다"""
    return [
        dict(row)
        for row in con.execute(
            "SELECT * FROM autorun_runs WHERE ended_at IS NULL ORDER BY id"
        )
    ]


def start_run(con, todo_id, claude_session_id=None, job_id=None):
    with transaction(con):
        cursor = con.execute(
            "INSERT INTO autorun_runs(todo_id, claude_session_id, job_id, started_at)"
            " VALUES(?,?,?,?)",
            (todo_id, claude_session_id, job_id, now()),
        )
    return get(con, cursor.lastrowid)


def close_run(con, run_id, outcome):
    if outcome not in AUTORUN_OUTCOMES:
        raise Validation(f"실행 결과는 {AUTORUN_OUTCOMES} 중 하나여야 함: {outcome!r}")
    with transaction(con):
        con.execute(
            "UPDATE autorun_runs SET ended_at=?, outcome=?"
            " WHERE id=? AND ended_at IS NULL",
            (now(), outcome, run_id),
        )
    return get(con, run_id)


def get(con, run_id):
    row = con.execute("SELECT * FROM autorun_runs WHERE id=?", (run_id,)).fetchone()
    return dict(row) if row else None


def recent_with_todos(con, limit=10):
    """최근 실행 + 그 할일 제목·워크스페이스 이름. 자율 수행 패널이 그대로 뿌린다"""
    rows = con.execute(
        """SELECT r.*, t.title AS todo_title, w.name AS workspace_name
             FROM autorun_runs r
             JOIN todos t ON t.id = r.todo_id
             LEFT JOIN workspaces w ON w.id = t.workspace_id
            ORDER BY r.id DESC LIMIT ?""",
        (limit,),
    )
    return [dict(row) for row in rows]


def find_by_session(con, claude_session_id):
    """그 세션이 자율 실행으로 뜬 것인지. 사람이 끼어들었을 때의 판정에 쓴다"""
    row = con.execute(
        "SELECT * FROM autorun_runs WHERE claude_session_id=? ORDER BY id DESC LIMIT 1",
        (claude_session_id,),
    ).fetchone()
    return dict(row) if row else None


def recent(con, limit=10):
    return [
        dict(row)
        for row in con.execute(
            "SELECT * FROM autorun_runs ORDER BY id DESC LIMIT ?", (limit,)
        )
    ]


def consecutive_failures(con, todo_id):
    """그 할일의 끝난 실행을 뒤에서부터, 성공이 나오기 전까지 센 실패 수.

    review 도 성공으로 센다 — 사람이 아직 확인하지 않았을 뿐 잡은 할일을 끝냈다.
    실패로 세면 확인이 밀린 동안 그 할일이 blocked 로 올라가 후보에서 빠진다
    """
    count = 0
    for row in con.execute(
        "SELECT outcome FROM autorun_runs WHERE todo_id=? AND ended_at IS NOT NULL"
        " ORDER BY id DESC",
        (todo_id,),
    ):
        if row["outcome"] in (OUTCOME_DONE, OUTCOME_REVIEW):
            break
        count += 1
    return count


def confirm_run(con, run_id):
    """사람이 확인을 마쳤다 — review 를 done 으로 내린다.

    무엇이 '확인' 인가는 코드가 판정할 수 없다(diff 를 읽고 병합할지 정하는 일이다).
    그래서 이 함수는 판정하지 않고 사람의 클릭을 기록만 한다
    """
    run = get(con, run_id)
    if not run:
        raise NotFound(f"실행 기록 {run_id} 없음")
    if run["outcome"] != OUTCOME_REVIEW:
        raise Validation(f"확인 필요 상태가 아님: {run['outcome'] or '진행 중'}")
    with transaction(con):
        con.execute(
            "UPDATE autorun_runs SET outcome=? WHERE id=?", (OUTCOME_DONE, run_id)
        )
    return get(con, run_id)


def locked_todo_ids(con):
    """확인 필요로 닫힌 실행이 있는 할일. 사람이 확인 버튼을 누르기 전까지 상태를 못 바꾼다.

    돌고 있는 중(ended_at IS NULL)은 안 잠근다 — 자율 세션 자신이 끝에 `set-status
    done` 을 부르는데, 그때는 아직 잡이 열려 있어 여기서 잠그면 그 호출이 막힌다
    """
    return {
        row["todo_id"]
        for row in con.execute(
            "SELECT DISTINCT todo_id FROM autorun_runs WHERE outcome=?",
            (OUTCOME_REVIEW,),
        )
    }


def reopen_run(con, run_id):
    """확인을 되돌린다 — done 을 review 로. confirm_run 의 역방향, 잘못 누른 확인을 무른다"""
    run = get(con, run_id)
    if not run:
        raise NotFound(f"실행 기록 {run_id} 없음")
    if run["outcome"] != OUTCOME_DONE:
        raise Validation(f"완료 상태가 아님: {run['outcome'] or '진행 중'}")
    with transaction(con):
        con.execute(
            "UPDATE autorun_runs SET outcome=? WHERE id=?", (OUTCOME_REVIEW, run_id)
        )
    return get(con, run_id)


def blocked_todo_ids(con):
    """막힌 것으로 기록된 할일. 다음 tick 의 후보에서 뺀다.

    자동으로는 풀리지 않는다 — 실패 한도가 무의미해지기 때문이다. 사람이 원인을
    보고 그 기록을 지우거나 할일을 손봐야 다시 후보가 된다
    """
    return {
        row["todo_id"]
        for row in con.execute(
            "SELECT DISTINCT todo_id FROM autorun_runs WHERE outcome=?",
            (OUTCOME_BLOCKED,),
        )
    }


def outcome_for_close(con, todo_id, todo_done):
    """끝난 잡의 결과. 할일이 done 이면 확인 필요, 아니면 실패.
    이 실패로 한도에 닿으면 그 자리에서 blocked 로 올린다"""
    if todo_done:
        return OUTCOME_REVIEW
    if consecutive_failures(con, todo_id) + 1 >= AUTORUN_FAIL_LIMIT:
        return OUTCOME_BLOCKED
    return OUTCOME_FAILED
