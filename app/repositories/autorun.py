"""자율 실행 설정과 실행 기록. 판정은 여기 없고 service 가 한다"""
from app.constants import (
    AUTORUN_FAIL_LIMIT,
    AUTORUN_OUTCOMES,
    OUTCOME_BLOCKED,
    OUTCOME_DONE,
    OUTCOME_FAILED,
)
from app.db import now, transaction
from app.errors import Validation

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
    """그 할일의 끝난 실행을 뒤에서부터, done 이 나오기 전까지 센 실패 수"""
    count = 0
    for row in con.execute(
        "SELECT outcome FROM autorun_runs WHERE todo_id=? AND ended_at IS NOT NULL"
        " ORDER BY id DESC",
        (todo_id,),
    ):
        if row["outcome"] == OUTCOME_DONE:
            break
        count += 1
    return count


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
    """끝난 잡의 결과. 할일이 done 이면 done, 아니면 실패.
    이 실패로 한도에 닿으면 그 자리에서 blocked 로 올린다"""
    if todo_done:
        return OUTCOME_DONE
    if consecutive_failures(con, todo_id) + 1 >= AUTORUN_FAIL_LIMIT:
        return OUTCOME_BLOCKED
    return OUTCOME_FAILED
