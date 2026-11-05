"""방치된 doing 판정 기록. 판정은 하루 한 번 도는 크론이 남기고, 보드는 note 로 본다"""
from app.db import now, transaction


def record(con, todo_id, verdict, confidence, reason, applied):
    stamp = now()
    with transaction(con):
        con.execute(
            """INSERT INTO stale_judgments(todo_id, judged_at, verdict, confidence, reason, applied)
               VALUES (?,?,?,?,?,?)""",
            (todo_id, stamp, verdict, confidence, reason, 1 if applied else 0),
        )
    return stamp


def last_judged_at(con):
    """할일마다 마지막 판정 시각. keep 으로 본 할일을 매일 다시 묻지 않으려고 본다"""
    rows = con.execute(
        "SELECT todo_id, MAX(judged_at) AS judged_at FROM stale_judgments GROUP BY todo_id"
    )
    return {row["todo_id"]: row["judged_at"] for row in rows}


def recent(con, limit=20):
    rows = con.execute(
        """SELECT j.*, t.title FROM stale_judgments j JOIN todos t ON t.id = j.todo_id
           ORDER BY j.id DESC LIMIT ?""",
        (limit,),
    )
    return [dict(row) for row in rows]
