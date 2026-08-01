"""초기 설정용 히스토리 스캔.

transcript 전문은 수백 MB 라 세션에 못 넣는다. 여기서 세션당 한 줄로 압축해 뱉고,
같은 일감끼리 묶는 의미 판단은 이 출력을 읽은 Claude 가 한다 (셸은 내용을 이해 못 함)
"""
import glob
import os
import time

from app.constants import (
    HISTORY_FIRST_PROMPT_CHARS,
    HISTORY_HEAD_BYTES,
    TRANSCRIPT_ROOT,
)
from app.errors import NotFound
from app.repositories import sessions as session_repo
from app.services.transcript import NOISE_PREFIXES, USER_ROLE, head, parse_line

DAY_SECONDS = 86400
SESSION_REF_CHARS = 8  # 세션 id 앞머리. 45줄에 uuid 전체를 싣지 않으려고 자른다
PAST_STATE = "ended"


def scan(days, root=None):
    """최근 <days> 일 안에 손댄 세션들의 요약. cwd 별로 묶어 [{cwd, sessions}] 로"""
    cutoff = time.time() - days * DAY_SECONDS
    groups = {}
    for path in glob.glob(os.path.join(root or TRANSCRIPT_ROOT, "*", "*.jsonl")):
        if os.path.getmtime(path) < cutoff:
            continue
        summary = summarize(path)
        if summary:
            groups.setdefault(summary["cwd"], []).append(summary)
    # 같은 날 시작한 세션끼리는 glob 순서에 맡기지 않는다 — 두 번 돌리면 순서가 달라진다
    return [
        {"cwd": cwd, "sessions": sorted(rows, key=lambda row: (row["started"], row["session_id"]))}
        for cwd, rows in sorted(groups.items(), key=lambda item: (-len(item[1]), item[0]))
    ]


def summarize(path):
    """세션 한 건. 사람 발화가 하나도 없으면 None (도구만 돌다 끝난 세션)"""
    entries = [parse_line(line) for line in head(path, HISTORY_HEAD_BYTES)]
    prompts = [
        entry
        for entry in entries
        if entry and entry["role"] == USER_ROLE and not entry["text"].startswith(NOISE_PREFIXES)
    ]
    if not prompts:
        return None
    return {
        "session_id": os.path.basename(path)[: -len(".jsonl")],
        "cwd": prompts[0]["cwd"] or "(알 수 없음)",
        "started": prompts[0]["stamp"][:10],
        # mtime = 마지막 덧붙임 = 마지막 활동. 시작일만 보면 오래된 세션처럼 보인다
        "last": _date(os.path.getmtime(path)),
        # 발화 수는 싣지 않는다 — 앞 조각 안에서만 셀 수 있어 대부분 1 로 나오고,
        # 규모를 뜻하는 것처럼 읽히면 오히려 분류를 틀리게 만든다. 규모는 묶음의 세션 건수로 본다
        "first_prompt": prompts[0]["text"][:HISTORY_FIRST_PROMPT_CHARS],
    }


def ensure_past_session(con, ref, root=None):
    """끝난 히스토리 세션을 sessions 에 넣고 전체 id 를 돌려준다. 이미 있으면 그대로.

    ref 는 scan-history 가 찍어준 앞머리도 되고 전체 id 도 된다.
    session_repo.register() 를 쓰지 않는 이유 — 그건 무조건 idle + 지금 시각으로 넣어서
    이미 끝난 세션이 활성 목록에 살아 있는 것처럼 뜬다
    """
    path = find_by_ref(ref, root)
    if not path:
        raise NotFound(f"히스토리에 없는 세션: {ref}")
    session_id = os.path.basename(path)[: -len(".jsonl")]
    if session_repo.find(con, session_id):
        return session_id
    prompts = [
        entry
        for entry in (parse_line(line) for line in head(path, HISTORY_HEAD_BYTES))
        if entry and entry["role"] == USER_ROLE and entry["stamp"]
    ]
    last = _stamp(os.path.getmtime(path))
    started = (prompts[0]["stamp"][:19] + "+00:00") if prompts else last
    con.execute(
        "INSERT INTO sessions(claude_session_id, cwd, state, started_at,"
        " last_seen_at, ended_at) VALUES(?,?,?,?,?,?)",
        (session_id, prompts[0]["cwd"] if prompts else None, PAST_STATE, started, last, last),
    )
    con.commit()
    return session_id


def find_by_ref(ref, root=None):
    """세션 id 앞머리 또는 전체 id 로 transcript 경로를 찾는다. 모호하면 None"""
    if not ref:
        return None
    matches = glob.glob(os.path.join(root or TRANSCRIPT_ROOT, "*", f"{ref}*.jsonl"))
    return matches[0] if len(matches) == 1 else None


def render(groups, days):
    """Claude 가 읽을 텍스트. 세션당 한 줄"""
    total = sum(len(group["sessions"]) for group in groups)
    lines = [f"최근 {days}일 세션 {total}건 / 작업 위치 {len(groups)}곳"]
    for group in groups:
        lines.append("")
        lines.append(f"== {group['cwd']} (세션 {len(group['sessions'])}건) ==")
        for row in group["sessions"]:
            span = row["started"] if row["started"] == row["last"] else f"{row['started']}~{row['last']}"
            # 세션 id 앞머리를 함께 준다 — 이걸 link-todo --past 에 그대로 넘겨 할일에 붙인다
            lines.append(f"  {row['session_id'][:SESSION_REF_CHARS]}  {span}  {row['first_prompt']}")
    return "\n".join(lines)


def _date(epoch):
    return time.strftime("%Y-%m-%d", time.localtime(epoch))


def _stamp(epoch):
    """DB 의 시각 컬럼 형식 (ISO8601 UTC 초 단위)"""
    return time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(epoch))
