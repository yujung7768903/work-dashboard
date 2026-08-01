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
from app.services.transcript import head, parse_line

USER_ROLE = "user"
DAY_SECONDS = 86400
# 사람이 친 지시처럼 보이지만 아닌 것들. 이게 첫 발화로 잡히면 세션의 주제를 가린다.
# transcript.SKIP_PREFIXES 를 늘리지 않는 이유 — 세션 팝업은 슬래시 명령도 보여주는 게 맞다
NOISE_PREFIXES = (
    "<",  # <command-name>/model</command-name> 같은 슬래시 명령·주입 블록
    "Below is a conversation log",  # 자동 압축이 만드는 요약 요청
    "Please write a 5-10 word title",  # 세션 제목 생성 요청
)


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


def render(groups, days):
    """Claude 가 읽을 텍스트. 세션당 한 줄"""
    total = sum(len(group["sessions"]) for group in groups)
    lines = [f"최근 {days}일 세션 {total}건 / 작업 위치 {len(groups)}곳"]
    for group in groups:
        lines.append("")
        lines.append(f"== {group['cwd']} (세션 {len(group['sessions'])}건) ==")
        for row in group["sessions"]:
            span = row["started"] if row["started"] == row["last"] else f"{row['started']}~{row['last']}"
            lines.append(f"  {span}  {row['first_prompt']}")
    return "\n".join(lines)


def _date(epoch):
    return time.strftime("%Y-%m-%d", time.localtime(epoch))
