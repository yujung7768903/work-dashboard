"""세션 최근 대화 읽기. transcript 경로는 DB 에 없으므로 세션 id 로 찾아 꼬리만 읽는다"""
import glob
import json
import os

from app.constants import (
    TRANSCRIPT_MAX_CHARS,
    TRANSCRIPT_MAX_MESSAGES,
    TRANSCRIPT_MAX_TAIL_BYTES,
    TRANSCRIPT_ROOT,
    TRANSCRIPT_TAIL_BYTES,
)

ROLES = ("user", "assistant")
TEXT_BLOCK = "text"
# 훅 주입·리마인더는 사람이 쓴 말이 아니라 목록에서 걸러낸다
SKIP_PREFIXES = ("<system-reminder>", "<local-command", "Caveat:")


def recent(claude_session_id, root=None, limit=TRANSCRIPT_MAX_MESSAGES):
    """최근 대화 [{role, text}]. transcript 가 없으면 빈 목록.

    도구 결과가 많은 세션은 꼬리 한 조각에 발화가 하나도 없다. 원하는 개수를
    채울 때까지 창을 넓히되 상한에서 멈춘다
    """
    path = find_path(claude_session_id, root)
    if not path:
        return []
    size = os.path.getsize(path)
    window = TRANSCRIPT_TAIL_BYTES
    while True:
        messages = [message for message in map(parse_line, tail(path, window)) if message]
        if len(messages) >= limit or window >= size or window >= TRANSCRIPT_MAX_TAIL_BYTES:
            return messages[-limit:]
        window *= 4


def find_path(claude_session_id, root=None):
    """~/.claude/projects/<프로젝트>/<세션id>.jsonl. 프로젝트 폴더명은 모르므로 glob"""
    if not claude_session_id:
        return None
    matches = glob.glob(os.path.join(root or TRANSCRIPT_ROOT, "*", f"{claude_session_id}.jsonl"))
    return matches[0] if matches else None


def tail(path, max_bytes=TRANSCRIPT_TAIL_BYTES):
    """파일 끝 일부만. 도구 결과까지 쌓인 수십 MB 를 통째로 읽지 않기 위함"""
    size = os.path.getsize(path)
    with open(path, "rb") as handle:
        handle.seek(max(0, size - max_bytes))
        chunk = handle.read()
    lines = chunk.decode("utf-8", "ignore").splitlines()
    return lines[1:] if size > max_bytes else lines  # 잘려 나온 첫 줄은 버림


def head(path, max_bytes):
    """파일 앞 일부만. 세션의 주제는 첫 지시에 있으므로 꼬리까지 읽을 이유가 없다"""
    with open(path, "rb") as handle:
        chunk = handle.read(max_bytes)
    lines = chunk.decode("utf-8", "ignore").splitlines()
    # 상한에 걸려 잘렸으면 마지막 줄은 반쪽이라 버림
    return lines[:-1] if len(chunk) == max_bytes else lines


def parse_line(line):
    """대화 한 줄. 사람이 읽을 발화가 아니면 None.

    stamp·cwd 는 온보딩 히스토리 스캔이 쓴다 — 어느 세션이 언제 어디서 돌았는지는
    같은 줄에 있고, 발화를 골라내는 규칙을 두 곳에 두지 않기 위해 여기서 함께 돌려준다
    """
    try:
        entry = json.loads(line)
    except (ValueError, TypeError):
        return None
    if not isinstance(entry, dict) or entry.get("isSidechain") or entry.get("isMeta"):
        return None
    role = entry.get("type")
    if role not in ROLES:
        return None
    text = _text((entry.get("message") or {}).get("content"))
    if not text or text.startswith(SKIP_PREFIXES):
        return None
    return {
        "role": role,
        "text": text[:TRANSCRIPT_MAX_CHARS],
        "stamp": entry.get("timestamp") or "",
        "cwd": entry.get("cwd") or "",
    }


def _text(content):
    """도구 호출·결과·사고 블록은 빼고 말풍선 글자만 한 줄로"""
    if isinstance(content, str):
        blocks = [content]
    elif isinstance(content, list):
        blocks = [
            block.get("text") or ""
            for block in content
            if isinstance(block, dict) and block.get("type") == TEXT_BLOCK
        ]
    else:
        return ""
    return " ".join(" ".join(blocks).split())
