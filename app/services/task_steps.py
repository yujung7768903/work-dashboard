"""할일의 단계 행(role='step') → 할일 상세·매니저 탭이 그리는 '진행 단계'.

할일은 결과 하나로 끝나고, 그 과정의 파생 요청·결정·확인 질문은 그 할일 아래 단계 행으로 쌓인다(사용자 결정 11-18,
app/db.py ROLE_STEP). 화면은 단계 목록 하나로 (a) 끝난 단계 — 누가·언제·결과 한 줄, (b) 멈춘 단계와 넘어가는 조건,
(c) 그 단계에서 사용자가 답할 결정·확인을 보인다 — 사용자가 무엇을 정해야 하는지 헷갈리지 않게.
단계 행이 없는 할일은 예전 진행 단계(mgr_steps JSON)를 그대로 쓴다 — 여기서는 단계 행만 다룬다.

목록 모양은 매니저 tasks.steps 와 같다({name, status: done|current|todo, unblock}) — static/js/steps.js 가 그대로 그린다.
덧붙는 칸: id(단계 행 id) · by(누가) · at(끝난 시각) · result(결과 한 줄) · ask(답할 것: decision·confirm·permission)
"""
import sqlite3

from app.db import ROLE_STEP, UNIFIED_FLAG, meta_get

STATUS_DONE = "done"
STATUS_DOING = "doing"
STEP_DONE = "done"
STEP_CURRENT = "current"
STEP_TODO = "todo"
# 사용자 답을 기다리는 단계 — 상태(doing)를 아직 안 찍었어도 멈춘 단계로 본다
ASK_DECISION = "decision"
ASK_CONFIRM = "confirm"
ASK_PERMISSION = "permission"
SEPARATOR = " › "


def available(con):
    """단계 행을 읽을 수 있나 — 할일 통합 뒤(meta unified_todos)이고 role 칸이 있을 때"""
    if con is None:
        return False
    try:
        if meta_get(con, UNIFIED_FLAG) is None:
            return False
        return any(row[1] == "role" for row in con.execute("PRAGMA table_info(todos)"))
    except sqlite3.Error:
        return False


def step_rows(con, task_id):
    """그 할일의 단계 행 — 순서(sort_order, id)대로"""
    if not available(con):
        return []
    return [
        dict(row)
        for row in con.execute(
            "SELECT * FROM todos WHERE parent_id=? AND role=? ORDER BY sort_order, id", (task_id, ROLE_STEP)
        )
    ]


def ask_of(row):
    """그 단계에서 사용자가 답할 것 — 없으면 None. 끝난 단계는 묻지 않는다"""
    if row.get("status") == STATUS_DONE:
        return None
    mgr_status = row.get("mgr_status")
    if mgr_status == "confirm":
        return ASK_CONFIRM
    if mgr_status != "open":
        return None
    if row.get("mgr_blocked") == "permission":
        return ASK_PERMISSION
    return ASK_DECISION if row.get("mgr_kind") == "decision" else None


def timeline(con, task_id, current_id=None):
    """진행 단계 목록. 멈춘 단계(current)는 하나만 — current_id 를 주면 그 단계(지금 답하는 단계), 아니면
    답을 기다리는 첫 단계, 없으면 진행 중(doing)인 첫 단계. 나머지 안 끝난 단계는 남음(todo)"""
    rows = step_rows(con, task_id)
    if not rows:
        return []
    if current_id is None:
        asking = [row["id"] for row in rows if ask_of(row)]
        doing = [row["id"] for row in rows if row.get("status") == STATUS_DOING]
        current_id = (asking or doing or [None])[0]
    out = []
    for row in rows:
        if row.get("status") == STATUS_DONE:
            status = STEP_DONE
        elif row["id"] == current_id:
            status = STEP_CURRENT
        else:
            status = STEP_TODO
        out.append(
            {
                "id": row["id"],
                "name": row.get("title"),
                "status": status,
                "unblock": row.get("step_unblock"),
                "by": row.get("step_by"),
                "at": row.get("completed_at") if status == STEP_DONE else None,
                "result": row.get("step_result"),
                "ask": ask_of(row),
            }
        )
    return out


def parent_task(con, step_id):
    """단계 행이면 그 할일 {id, title}, 아니면 None"""
    if not available(con):
        return None
    row = con.execute(
        "SELECT s.parent_id AS id, t.title AS title FROM todos s JOIN todos t ON t.id = s.parent_id"
        " WHERE s.id=? AND s.role=?",
        (step_id, ROLE_STEP),
    ).fetchone()
    return {"id": row["id"], "title": row["title"]} if row else None


def step_ids(con, task_id):
    return [row["id"] for row in step_rows(con, task_id)]


def with_task(con, item):
    """매니저 할일 한 건(결정·확인 대기 줄·카드)이 단계 행이면 제목을 '<할일> › <단계>' 로, 진행 단계를 그 할일의
    단계 행으로 바꾼다 — 단계만 보면 무엇의 단계인지 모른다. 단계가 아니면 그대로"""
    if not item or item.get("id") is None:
        return item
    task = parent_task(con, item["id"])
    if not task:
        return item
    steps = timeline(con, task["id"], current_id=item["id"])
    title = item.get("title") or ""
    return {
        **item,
        "title": f"{task['title']}{SEPARATOR}{title}" if task["title"] else title,
        "step_title": title,
        "task_id": task["id"],
        "task_title": task["title"],
        "steps": steps or item.get("steps"),
    }
