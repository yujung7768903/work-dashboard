"""구글 태스크 연동 설정. 단일 행이라 autorun_state 와 같은 모양으로 다룬다"""
from app.db import now, transaction

STATE_ROW_ID = 1


def state(con):
    """단일 행. 없으면 만들어 돌려준다 — 기본은 off"""
    row = con.execute(
        "SELECT * FROM gtasks_state WHERE id=?", (STATE_ROW_ID,)
    ).fetchone()
    if row:
        return dict(row)
    with transaction(con):
        con.execute(
            "INSERT INTO gtasks_state(id, enabled, updated_at) VALUES(?,0,?)",
            (STATE_ROW_ID, now()),
        )
    return state(con)


def set_enabled(con, enabled):
    """켤 때 last_error 를 지운다 — 다시 켰다는 것은 원인을 봤다는 뜻 (autorun 과 같은 규칙)"""
    state(con)
    stamp = now()
    with transaction(con):
        con.execute(
            "UPDATE gtasks_state SET enabled=?, updated_at=? WHERE id=?",
            (1 if enabled else 0, stamp, STATE_ROW_ID),
        )
        if enabled:
            con.execute(
                "UPDATE gtasks_state SET last_error=NULL WHERE id=?", (STATE_ROW_ID,)
            )
    return state(con)


def record_success(con):
    """한 바퀴를 끝까지 돌았다. 지난 사유를 지워야 ⚠ 가 남아 있지 않는다"""
    state(con)
    stamp = now()
    with transaction(con):
        con.execute(
            "UPDATE gtasks_state SET last_sync_at=?, last_error=NULL, updated_at=?"
            " WHERE id=?",
            (stamp, stamp, STATE_ROW_ID),
        )
    return state(con)


def record_error(con, reason):
    """실패 사유만 남기고 enabled 는 건드리지 않는다.

    일시적인 실패로 설정을 꺼 버리면 사용자가 껐다는 사실조차 모른 채 며칠이 지난다.
    끄는 판단은 사람이 하고, 화면은 ⚠ 옆에 이 사유를 보여준다
    """
    state(con)
    with transaction(con):
        con.execute(
            "UPDATE gtasks_state SET last_error=?, updated_at=? WHERE id=?",
            (reason, now(), STATE_ROW_ID),
        )
    return state(con)
