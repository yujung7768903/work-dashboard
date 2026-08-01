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
    """제목 한 줄. CLI 가 없거나 실패·타임아웃·이상한 응답이면 None.

    실패는 이유를 로그로 남긴다 — 조용히 None 을 돌려주면 제목이 왜 안 붙었는지
    알 방법이 없다(화면에는 '요약 안 됨' 배지만 뜬다)
    """
    binary = shutil.which(BINARY)
    if not binary:
        return _failed(f"{BINARY} 를 PATH 에서 찾지 못함")
    if not (text or "").strip():
        return None  # 요약할 글이 없는 건 실패가 아니다
    try:
        result = subprocess.run(
            [binary, *FLAGS, "--model", model, text],
            capture_output=True,
            text=True,
            timeout=timeout,
            stdin=subprocess.DEVNULL,  # 붙잡을 입력이 없어야 CLI 가 기다리지 않는다
        )
    except subprocess.TimeoutExpired:
        return _failed(f"{timeout}초 안에 응답 없음")
    except (OSError, subprocess.SubprocessError) as error:
        return _failed(f"실행 실패 — {type(error).__name__}: {error}")
    if result.returncode != 0:
        return _failed(f"종료코드 {result.returncode} — {_tail(result.stderr)}")
    cleaned = clean(result.stdout)
    if not cleaned:
        return _failed(f"제목으로 쓸 수 없는 응답 — {_tail(result.stdout)}")
    return cleaned


def _failed(reason):
    print(f"제목 요약 실패: {reason}", flush=True)
    return None


def _tail(output):
    """로그 한 줄로 줄인다. CLI 는 경고를 여러 줄 뱉을 수 있다"""
    lines = [row.strip() for row in (output or "").splitlines() if row.strip()]
    return lines[-1][:200] if lines else "(출력 없음)"


def clean(output):
    """첫 줄만 쓰고 따옴표·마침표를 뗀다. 비었거나 길면 요약이 아니므로 None"""
    line = next((row.strip() for row in (output or "").splitlines() if row.strip()), "")
    # 따옴표와 마침표가 겹쳐 붙어 오므로(`"제목".`) 한 번에 떼야 한다
    line = line.strip("\"'`.!?。 ")
    if not line or len(line) > SUMMARY_MAX_CHARS:
        return None
    return line
