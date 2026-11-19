"""오래 방치된 doing 을 모델이 읽고 정리한다.

규칙으로 안 하는 이유 — "끝났다"는 흔적이 할일마다 다른 곳에 남는다. 어떤 것은 워크트리가
병합됐고, 어떤 것은 Confluence 에 문서가 올라갔고, 어떤 것은 세션 마지막 대화가 완료 보고다.
그래서 근거를 한데 모아 보여주고 판정은 모델에 맡기되, 확신이 낮으면 아무것도 안 바꾼다.

판정은 넷이다.
  done     — 끝났다. status=done, note 에 사유
  invalid  — 더 이상 할 이유가 없다(전제 소멸·다른 할일로 대체). status=done, note 에 무효 표시
  todo     — 시작만 했고 멈춰 있는데 여전히 필요하다. status=todo 로 되돌림
  keep     — 정말 진행 중이거나 판단 근거가 부족. 기록만 남기고 두 주 뒤 다시 본다

되돌리기 — 보드에서 상태를 바꾸면 끝이다. note 의 [자동 판정 …] 줄이 왜 그랬는지 남는다
"""
import json
import re
import subprocess
from datetime import datetime, timedelta, timezone

from app.constants import (
    AUTORUN_CLAUDE_BIN,
    STALE_JUDGE_BATCH,
    STALE_JUDGE_IDLE_DAYS,
    STALE_JUDGE_LABELS,
    STALE_JUDGE_MIN_CONFIDENCE,
    STALE_JUDGE_MODEL,
    STALE_JUDGE_NOTE_CHARS,
    STALE_JUDGE_NOTE_MARK,
    STALE_JUDGE_REPEAT_DAYS,
    STALE_JUDGE_SESSION_LIMIT,
    STALE_JUDGE_SIBLING_LIMIT,
    STALE_JUDGE_TEXT_CHARS,
    STALE_JUDGE_TIMEOUT_SEC,
    STALE_JUDGE_TRANSCRIPT_MESSAGES,
    STALE_JUDGE_VERDICTS,
    STATUS_DONE,
    STATUS_TODO,
    VERDICT_DONE,
    VERDICT_INVALID,
    VERDICT_KEEP,
    VERDICT_TODO,
)
from app.repositories import autorun as autorun_repo
from app.repositories import sessions as session_repo
from app.repositories import stale_judgments as judgment_repo
from app.repositories import todos as todo_repo
from app.repositories import worktrees as worktree_repo
from app.services import lineage, transcript

JSON_OBJECT = re.compile(r"\{[^{}]*\}", re.S)
STATUS_BY_VERDICT = {
    VERDICT_DONE: STATUS_DONE,
    VERDICT_INVALID: STATUS_DONE,
    VERDICT_TODO: STATUS_TODO,
}

PROMPT = """너는 작업 대시보드의 할일 정리를 맡은 동료다. 아래 할일은 '진행 중(doing)' 인데 {idle_days}일 넘게 아무도 손대지 않았다.
근거를 읽고 이 할일이 지금 어떤 상태인지 판정해라. 추측으로 채우지 말고 근거에 있는 것만 써라.

판정 값:
- done: 근거에 끝난 흔적이 있다 (워크트리 병합, 완료 보고, 문서·배포 완료 등)
- invalid: 더 이상 할 이유가 없다 (전제가 사라졌거나 다른 할일이 대신 끝냈다)
- todo: 시작만 하고 멈췄는데 여전히 필요하다 — 진행 중이 아니라 대기가 맞다
- keep: 정말 진행 중이거나 (예: 외부 답을 기다림) 근거가 부족해 판단할 수 없다

confidence 는 0~1 이고, 근거가 약하면 낮게 줘라. 낮으면 코드가 아무것도 바꾸지 않는다.
JSON 하나만 출력해라. 다른 말은 쓰지 마라:
{{"verdict": "done|invalid|todo|keep", "confidence": 0.0, "reason": "한두 문장, 근거를 가리켜서"}}

=== 할일 ===
{todo}

=== 트리 맨 위 할일 (배경·목표) ===
{root}

=== 같은 상위 아래 다른 할일 ===
{siblings}

=== 이 할일을 잡았던 세션 (최근순) ===
{sessions}

=== 가장 최근 세션의 마지막 대화 ===
{tail}

=== 이 할일의 워크트리 ===
{worktrees}
"""


def run(con, dry_run=False, limit=STALE_JUDGE_BATCH, judge=None, root=None, now=None):
    """후보를 모아 하나씩 묻고 적용한다. judge 는 테스트가 모델 호출을 바꿔 끼우는 자리"""
    judge = judge or ask
    results = []
    for todo in candidates(con, now=now)[:limit]:
        verdict = judge(evidence(con, todo, root=root))
        results.append(apply(con, todo, verdict, dry_run=dry_run))
    return {"judged": len(results), "results": results}


def candidates(con, now=None):
    """idle 기준보다 오래된 doing 중, 살아 있는 세션·자율 실행·검토 대기가 안 잡은 것.

    최근에 keep 으로 본 할일은 빼서 같은 질문을 매일 반복하지 않는다
    """
    moment = now or datetime.now(timezone.utc)
    cutoff = (moment - timedelta(days=STALE_JUDGE_IDLE_DAYS)).isoformat(timespec="seconds")
    repeat_cutoff = (moment - timedelta(days=STALE_JUDGE_REPEAT_DAYS)).isoformat(timespec="seconds")
    busy = set(todo_repo.ids_claimed_by_others(con))
    busy |= {run["todo_id"] for run in autorun_repo.open_runs(con)}
    busy |= autorun_repo.locked_todo_ids(con)
    judged = judgment_repo.last_judged_at(con)
    return [
        todo
        for todo in todo_repo.list_doing_before(con, cutoff)
        if todo["id"] not in busy and judged.get(todo["id"], "") < repeat_cutoff
    ]


def evidence(con, todo, root=None):
    """모델에 보여줄 근거. 프롬프트 한 장에 들어가게 조각마다 길이를 자른다"""
    # 워크스페이스 대신 트리 맨 위 할일(옛 워크스페이스의 배경·목표가 note 에 있다)과 같은 상위 아래 할일
    top = lineage.root_todo(con, todo["id"])
    top = top if top and top["id"] != todo["id"] else None
    above = lineage.parent_map(con).get(("todo", str(todo["id"])))
    siblings = (
        [
            dict(other)
            for other in con.execute(
                "SELECT t.* FROM edges e JOIN todos t ON t.id = CAST(e.dst_id AS INTEGER)"
                " WHERE e.relation='parent' AND e.state<>'rejected' AND e.src_kind=? AND e.src_id=?"
                " AND e.dst_kind='todo' AND t.id<>? AND t.role IS NULL ORDER BY t.sort_order, t.id",
                (above[0], above[1], todo["id"]),
            )
        ][:STALE_JUDGE_SIBLING_LIMIT]
        if above
        else []
    )
    sessions = session_repo.list_by_todo(con, todo["id"])[:STALE_JUDGE_SESSION_LIMIT]
    tail = (
        transcript.recent(
            sessions[0]["claude_session_id"], root=root, limit=STALE_JUDGE_TRANSCRIPT_MESSAGES
        )
        if sessions
        else []
    )
    return {
        "todo": {
            "id": todo["id"],
            "title": todo["title"],
            "note": _clip(todo.get("note"), STALE_JUDGE_NOTE_CHARS),
            "precondition": _clip(todo.get("precondition"), STALE_JUDGE_TEXT_CHARS),
            "created_at": todo["created_at"],
            "updated_at": todo["updated_at"],
        },
        "root": (
            {"title": top["title"], "note": _clip(top.get("note"), STALE_JUDGE_TEXT_CHARS)}
            if top
            else None
        ),
        "siblings": [
            {"id": other["id"], "title": other["title"], "status": other["status"]}
            for other in siblings
        ],
        "sessions": [
            {
                "state": session["state"],
                "started_at": session["started_at"],
                "last_seen_at": session["last_seen_at"],
                "last_prompt": _clip(session.get("last_prompt"), STALE_JUDGE_TEXT_CHARS),
            }
            for session in sessions
        ],
        "tail": [
            {"role": message["role"], "text": _clip(message["text"], STALE_JUDGE_TEXT_CHARS)}
            for message in tail
        ],
        "worktrees": [
            {
                "branch": row["branch"],
                "merged_at": row["merged_at"],
                "deleted_at": row["deleted_at"],
            }
            for row in worktree_repo.list_by_branch_fragment(con, f"todo-{todo['id']}-")
        ],
    }


def ask(facts, claude_bin=AUTORUN_CLAUDE_BIN, model=STALE_JUDGE_MODEL):
    """`claude -p` 한 번. 실패·파싱 불가는 keep 으로 — 모델이 안 보이면 아무것도 안 바꾼다"""
    try:
        # 판정 근거(note·대화 발췌)는 프롬프트에 다 넣으므로 MCP 가 필요 없다. 세션마다 MCP 서버가 뜨면 WSL 연동 부하만 쌓인다
        result = subprocess.run(
            [claude_bin, "-p", "--strict-mcp-config", "--model", model, prompt(facts)],
            capture_output=True,
            text=True,
            timeout=STALE_JUDGE_TIMEOUT_SEC,
        )
    except Exception as error:  # 실행 파일 없음·시간 초과
        return _keep(f"모델 호출 실패: {error}")
    return parse(result.stdout)


def prompt(facts):
    return PROMPT.format(
        idle_days=STALE_JUDGE_IDLE_DAYS,
        todo=_dump(facts["todo"]),
        root=_dump(facts["root"]) if facts["root"] else "(없음)",
        siblings=_dump(facts["siblings"]) if facts["siblings"] else "(없음)",
        sessions=_dump(facts["sessions"]) if facts["sessions"] else "(이 할일을 잡은 세션이 없음)",
        tail=_dump(facts["tail"]) if facts["tail"] else "(대화 기록 없음)",
        worktrees=_dump(facts["worktrees"]) if facts["worktrees"] else "(없음)",
    )


def parse(text):
    """출력에서 JSON 하나를 건진다. 모델이 앞뒤에 말을 붙여도 객체 하나만 있으면 읽는다"""
    for match in JSON_OBJECT.finditer(text or ""):
        try:
            data = json.loads(match.group())
        except json.JSONDecodeError:
            continue
        verdict = str(data.get("verdict", "")).strip().lower()
        if verdict not in STALE_JUDGE_VERDICTS:
            continue
        try:
            confidence = float(data.get("confidence", 0))
        except (TypeError, ValueError):
            confidence = 0.0
        return {
            "verdict": verdict,
            "confidence": max(0.0, min(1.0, confidence)),
            "reason": str(data.get("reason", "")).strip(),
        }
    return _keep("모델 출력에서 판정을 읽지 못함")


def apply(con, todo, verdict, dry_run=False):
    """확신이 기준 이상인 done·invalid·todo 만 상태를 바꾼다. 나머지는 기록만"""
    status = STATUS_BY_VERDICT.get(verdict["verdict"])
    applied = bool(status) and verdict["confidence"] >= STALE_JUDGE_MIN_CONFIDENCE
    outcome = {
        "todo_id": todo["id"],
        "title": todo["title"],
        "verdict": verdict["verdict"],
        "confidence": verdict["confidence"],
        "reason": verdict["reason"],
        "applied": applied,
        "status": status if applied else todo["status"],
    }
    if dry_run:
        return outcome
    if applied:
        todo_repo.update(
            con,
            todo["id"],
            status=status,
            note=_annotated(todo.get("note"), verdict),
        )
    judgment_repo.record(
        con, todo["id"], verdict["verdict"], verdict["confidence"], verdict["reason"], applied
    )
    return outcome


def _annotated(note, verdict):
    stamp = datetime.now(timezone.utc).astimezone().date().isoformat()
    label = STALE_JUDGE_LABELS[verdict["verdict"]]
    line = f"{STALE_JUDGE_NOTE_MARK} {stamp}] {label} — {verdict['reason']}".rstrip(" —")
    return f"{note.rstrip()}\n\n{line}" if (note or "").strip() else line


def _keep(reason):
    return {"verdict": VERDICT_KEEP, "confidence": 0.0, "reason": reason}


def _clip(text, limit):
    text = (text or "").strip()
    return text if len(text) <= limit else text[:limit] + "…"


def _dump(value):
    return json.dumps(value, ensure_ascii=False, indent=1)
