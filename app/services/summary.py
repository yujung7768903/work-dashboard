"""지시문 한 줄 요약.

한국어 지시를 제목으로 줄이는 건 의미 판단이라 코드가 못 한다 — 어미만 떼면
"워크스페이스에서 하위할일이 펼쳐진 상태로 보이는데, 너무 길어져서 기본적으로…" 가 남는다.
그래서 이미 깔려 있는 claude CLI 를 부른다. 실패하면 None 을 돌려주고, 부르는 쪽이
규칙 기반 제목으로 떨어진다 — 요약 하나 때문에 할일이 안 만들어지면 안 된다
"""
import shutil
import subprocess

from app.constants import SUMMARY_MAX_CHARS, SUMMARY_MODEL, SUMMARY_TIMEOUT_SEC

BINARY = "claude"
SYSTEM_PROMPT = (
    "너는 개발 작업 지시를 할일 목록의 제목으로 요약한다. "
    "한국어 명사구 한 줄만 출력한다. 25자 이내. "
    "설명·따옴표·마침표·요청 어미(해줘/하세요) 없이 제목만 출력한다."
)
# 기본값으로 부르면 도구·MCP·CLAUDE.md·스킬까지 얹혀 1분이 넘고, 지시를 작업으로 착각해
# 파일을 고치려 든다. 요약은 한 번의 응답이면 되므로 하네스를 전부 끈다
FLAGS = (
    "-p",
    "--tools",
    "",
    "--strict-mcp-config",
    "--setting-sources",
    "",
    "--exclude-dynamic-system-prompt-sections",
    "--system-prompt",
    SYSTEM_PROMPT,
)


def one_line(text, model=SUMMARY_MODEL, timeout=SUMMARY_TIMEOUT_SEC):
    """제목 한 줄. CLI 가 없거나 실패·타임아웃·이상한 응답이면 None"""
    binary = shutil.which(BINARY)
    if not binary or not (text or "").strip():
        return None
    try:
        result = subprocess.run(
            [binary, *FLAGS, "--model", model, text],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return clean(result.stdout)


def clean(output):
    """첫 줄만 쓰고 따옴표·마침표를 뗀다. 비었거나 길면 요약이 아니므로 None"""
    line = next((row.strip() for row in (output or "").splitlines() if row.strip()), "")
    # 따옴표와 마침표가 겹쳐 붙어 오므로(`"제목".`) 한 번에 떼야 한다
    line = line.strip("\"'`.!?。 ")
    if not line or len(line) > SUMMARY_MAX_CHARS:
        return None
    return line
