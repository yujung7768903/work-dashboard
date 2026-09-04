"""세션 최근 대화 읽기. transcript 경로는 DB 에 없으므로 세션 id 로 찾아 꼬리만 읽는다"""
import glob
import json
import os

from app.constants import (
    HISTORY_HEAD_BYTES,
    TRANSCRIPT_MAX_CHARS,
    TRANSCRIPT_MAX_MESSAGES,
    TRANSCRIPT_MAX_TAIL_BYTES,
    TRANSCRIPT_ROOT,
    TRANSCRIPT_TAIL_BYTES,
)

ROLES = ("user", "assistant")
USER_ROLE = ROLES[0]
TEXT_BLOCK = "text"
# 훅 주입·리마인더는 사람이 쓴 말이 아니라 목록에서 걸러낸다
SKIP_PREFIXES = ("<system-reminder>", "<local-command", "Caveat:")
# 사람이 친 지시처럼 보이지만 아닌 것들. 이게 첫 발화로 잡히면 세션의 주제를 가린다.
# SKIP_PREFIXES 를 늘리지 않는 이유 — 세션 팝업은 슬래시 명령도 보여주는 게 맞다
NOISE_PREFIXES = (
    "<",  # <command-name>/model</command-name> 같은 슬래시 명령·주입 블록
    "Below is a conversation log",  # 자동 압축이 만드는 요약 요청
    "Please write a 5-10 word title",  # 세션 제목 생성 요청
)


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


def user_prompts(claude_session_id, root=None, max_bytes=HISTORY_HEAD_BYTES):
    """사람이 친 지시만 순서대로 [str]. transcript 가 없으면 빈 목록.

    꼬리가 아니라 앞 조각을 읽는다 — 무엇을 하려는 세션인지는 첫 지시들에 들어 있고,
    뒤로 갈수록 곁가지·수정 지시라 할일 제목으로 쓰면 주제가 어긋난다
    """
    path = find_path(claude_session_id, root)
    if not path:
        return []
    return [
        entry["text"]
        for entry in (parse_line(line, collapse=False) for line in head(path, max_bytes))
        if entry
        and entry["role"] == USER_ROLE
        and not entry["text"].startswith(NOISE_PREFIXES)
    ]


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


def parse_line(line, collapse=True):
    """대화 한 줄. 사람이 읽을 발화가 아니면 None.

    collapse=False 면 줄바꿈을 살린다 — 지시 안의 목록 표기를 봐야 하는 쪽(user_prompts)용.

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
    text = _text((entry.get("message") or {}).get("content"), collapse)
    if not text or text.startswith(SKIP_PREFIXES):
        return None
    return {
        "role": role,
        "text": text[:TRANSCRIPT_MAX_CHARS],
        "stamp": entry.get("timestamp") or "",
        "cwd": entry.get("cwd") or "",
    }


def _text(content, collapse=True):
    """도구 호출·결과·사고 블록은 빼고 말풍선 글자만. 기본은 목록용 한 줄"""
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
    if not collapse:
        return "\n".join(blocks).strip()
    return " ".join(" ".join(blocks).split())


ASK_TOOL = "AskUserQuestion"
TOOL_USE_BLOCK = "tool_use"
TOOL_RESULT_BLOCK = "tool_result"
ASSISTANT_ROLE = ROLES[1]


def pending_question(claude_session_id, root=None):
    """답을 기다리는 AskUserQuestion. 없으면 None.

    {"tool_use_id", "questions"} — questions 는 도구 입력 그대로(question·header·multiSelect·options).
    parse_line 은 도구 블록을 버리므로 여기서 원문 항목을 직접 본다. 꼬리 한 창만 읽는다 —
    답을 기다리는 질문은 반드시 끝 근처에 있고, CLI 에서 골랐거나 Esc 로 끊었으면
    같은 tool_use_id 의 tool_result 가 뒤따른다
    """
    path = find_path(claude_session_id, root)
    if not path:
        return None
    asked = None
    answered = set()
    for line in tail(path):
        entry = _entry(line)
        if not entry:
            continue
        for block in _blocks(entry):
            kind = block.get("type")
            if (
                kind == TOOL_USE_BLOCK
                and entry.get("type") == ASSISTANT_ROLE
                and block.get("name") == ASK_TOOL
            ):
                asked = {
                    "tool_use_id": block.get("id") or "",
                    "questions": (block.get("input") or {}).get("questions") or [],
                }
            elif kind == TOOL_RESULT_BLOCK:
                answered.add(block.get("tool_use_id"))
    if asked and asked["tool_use_id"] not in answered:
        return asked
    return None


def _entry(line):
    """transcript 한 줄을 dict 로. 서브에이전트 줄과 깨진 줄은 None"""
    try:
        entry = json.loads(line)
    except (ValueError, TypeError):
        return None
    if not isinstance(entry, dict) or entry.get("isSidechain"):
        return None
    return entry


def _blocks(entry):
    content = (entry.get("message") or {}).get("content")
    if not isinstance(content, list):
        return []
    return [block for block in content if isinstance(block, dict)]
