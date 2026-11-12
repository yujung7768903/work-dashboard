"""매니저 탭 '도구 목록' — 매니저가 쓰는 외부 연결(MCP·CLI)과 매니저 명령.

목록은 지어내지 않고 실제 설정에서 읽는다.
- MCP: `claude mcp list` (사용자·프로젝트·플러그인·claude.ai 커넥터 전부와 연결 상태)
- CLI: PATH 에 있는 gh·aws 와 그 인증 확인 명령의 종료 코드
- 매니저 명령: manager.py 의 모듈 docstring(= `manager.py --help`). 실행하지 않고 ast 로 읽는다

화면에는 이름·설명·분류·상태만 싣는다. `claude mcp list` 출력의 주소·명령줄과 CLI 출력은
토큰이 섞일 수 있어 버리고 종료 코드·상태 문구만 쓴다.

`claude mcp list` 는 15초쯤 걸리고 stdio 서버(디스코드 플러그인 포함)를 실제로 띄워 본다.
디스코드 플러그인은 띄울 때마다 봇으로 한 번 더 로그인하므로 자주 돌리지 않는다 —
결과를 TOOLS_CACHE_SEC 동안 들고 있고, 지나면 지난 결과를 먼저 돌려준 뒤 뒤에서 다시 읽는다.
"""
import ast
import os
import re
import shutil
import subprocess
import threading
import time
import unicodedata
from datetime import datetime

from app.constants import (
    TOOLS_CACHE_SEC,
    TOOLS_CLI_TIMEOUT_SEC,
    TOOLS_MCP_TIMEOUT_SEC,
)

# 용도 분류 — 화면 칩 순서. 이름은 화면이 사전(manager.toolCat.<키>)으로 옮긴다
CATEGORIES = ("talk", "docs", "dev", "infra", "data", "command", "etc")
# 제작 주체 — 사내(회사·팀이 만든 것) · 외부(claude.ai 공식 커넥터·서드파티 MCP·CLI).
# 누가 만들었는지 확인하지 못한 것은 None 으로 두고 화면에 표시하지 않는다
INHOUSE = "inhouse"
EXTERNAL = "external"
CONNECTED = "connected"
NEEDS_AUTH = "auth"
FAILED = "failed"
UNKNOWN = "unknown"
AVAILABLE = "available"
STATUS_ORDER = {CONNECTED: 0, AVAILABLE: 0, NEEDS_AUTH: 1, FAILED: 2, UNKNOWN: 3}

# MCP 서버 이름 → (화면 이름, 용도, 제작 주체, 무엇을 하는 데 쓰는지). 설명은 그 서버가 내는 도구로 확인한 것만 적는다.
# 여기 없는 서버는 이름을 그대로 쓰고 용도는 '기타', 제작 주체·설명은 비워 둔다(화면이 '설명 없음'으로 드러낸다).
# athena·apihive 는 사용자 설정에 있지만 누가 무엇으로 만든 것인지 확인하지 못해 표에 넣지 않았다
KNOWN_MCP = {
    # 메신저·소통
    "plugin:discord:discord": ("디스코드", "talk", EXTERNAL, "매니저 채널로 사용자와 주고받기"),
    "claude.ai Microsoft 365": ("Microsoft 365", "talk", EXTERNAL, "팀즈 대화, 아웃룩 메일·일정, SharePoint 조회"),
    "claude.ai Slack": ("Slack", "talk", EXTERNAL, "슬랙 채널 읽기·메시지 보내기"),
    "claude.ai Gmail": ("Gmail", "talk", EXTERNAL, "지메일 검색·초안"),
    "claude.ai PlayMCP": ("카카오 PlayMCP", "talk", EXTERNAL, "카카오톡 나와의 채팅에 메모 보내기"),
    "claude.ai Intercom": ("Intercom", "talk", EXTERNAL, "인터콤 고객 대화"),
    # 업무 문서·협업 (Jira·Confluence·Office·Google·회의록·프로젝트 관리·디자인)
    "claude.ai Atlassian Rovo": ("Jira·Confluence", "docs", EXTERNAL, "Jira 이슈와 Confluence 페이지 조회·작성"),
    "claude.ai Atlassian MCP": ("Atlassian MCP", "docs", EXTERNAL, "Jira·Confluence 연결 (Rovo 와 별도 커넥터)"),
    "claude.ai Google Calendar": ("Google 캘린더", "docs", EXTERNAL, "구글 캘린더 일정 조회"),
    "claude.ai Google Drive": ("Google 드라이브", "docs", EXTERNAL, "드라이브 파일 찾기·읽기"),
    "claude.ai Google Docs": ("Google 문서", "docs", EXTERNAL, "구글 문서 읽기·쓰기"),
    "claude.ai Google Sheets": ("Google 스프레드시트", "docs", EXTERNAL, "구글 시트 읽기·쓰기"),
    "claude.ai Google Slides": ("Google 프레젠테이션", "docs", EXTERNAL, "구글 슬라이드 읽기·쓰기"),
    "claude.ai Claude Docs": ("Claude Docs", "docs", EXTERNAL, "Claude 문서 만들기·고치기"),
    "claude.ai Notion": ("Notion", "docs", EXTERNAL, "노션 페이지 검색·작성"),
    "claude.ai Box": ("Box", "docs", EXTERNAL, "박스 파일 관리"),
    "claude.ai Linear": ("Linear", "docs", EXTERNAL, "리니어 이슈 관리"),
    "claude.ai Asana": ("Asana", "docs", EXTERNAL, "아사나 작업 관리"),
    "claude.ai monday.com": ("monday.com", "docs", EXTERNAL, "먼데이 보드 관리"),
    "claude.ai Canva": ("Canva", "docs", EXTERNAL, "캔바 디자인"),
    "claude.ai Figma": ("Figma", "docs", EXTERNAL, "피그마 디자인 읽기"),
    "tiro": ("Tiro", "docs", EXTERNAL, "티로 회의 노트·전사 검색"),
    # 개발
    "codex": ("Codex", "dev", EXTERNAL, "Codex 에이전트에 작업 맡기기"),
    "aside": ("Aside", "dev", EXTERNAL, "Aside 브라우저 프로필로 웹 작업 실행"),
    # 인프라·모니터링
    "whatap": ("와탭", "infra", EXTERNAL, "와탭 APM 지표·이상 탐지 조회"),
    "claude.ai Datadog (v1)": ("Datadog", "infra", EXTERNAL, "데이터독 지표·로그 조회"),
    # 데이터·사내 서비스
    "claude.ai HAI Connector (dev)": (
        "HAI Connector", "data", INHOUSE, "한국일보 사내 데이터 — 비용·GA4·서치콘솔·HMAP·인물사전 조회",
    ),
    # HMAP 은 한국일보 사내 분석 서비스(hk-hmap-server). 인증 전이라 낼 도구를 확인하지 못해 설명은 비운다
    "claude.ai hmap_2_mcp": ("HMAP 2", "data", INHOUSE, None),
    "claude.ai Claude Data": ("Claude Data", "data", EXTERNAL, "조직 인증 쿼리와 공유 결과 보기"),
    # 그 밖 — 용도는 알지만 위 분류에 들지 않는 것
    "claude.ai HubSpot": ("HubSpot", "etc", EXTERNAL, "허브스팟 CRM"),
    "claude.ai saleforce": ("Salesforce", "etc", EXTERNAL, "세일즈포스 CRM"),
}

# CLI — (이름, 실행 파일, 용도, 설명, 인증 확인 명령). 확인 명령의 종료 코드만 본다. 둘 다 외부 제작
KNOWN_CLI = (
    ("GitHub CLI", "gh", "dev", "PR·이슈·저장소 작업 (gh)", ["gh", "auth", "status"]),
    ("AWS CLI", "aws", "infra", "AWS 리소스 조회 (기본 프로파일로 확인)", ["aws", "sts", "get-caller-identity"]),
)

# `claude mcp list` 한 줄: '<이름>: <주소·명령> - <상태>'. 이름에도 ':' 가 들어가므로(plugin:discord:discord)
# 이름은 첫 ': ' 앞, 상태는 마지막 ' - ' 뒤
MCP_LINE = re.compile(r"^(?P<name>.+?): .* - (?P<status>.+)$")

_cache = {"at": 0.0, "external": None, "checked_at": None}
_lock = threading.Lock()
_refreshing = threading.Event()


def tools(manager_home, now=None, external_fn=None):
    """도구 목록. 외부 연결(MCP·CLI)은 캐시, 매니저 명령은 매번 docstring 에서.
    external_fn 은 테스트 주입점 — () -> (외부 연결 목록, 확인 시각)"""
    external, checked_at = (external_fn or cached_external)()
    try:
        commands = manager_commands(manager_home)
    except FileNotFoundError:
        commands = []  # 매니저가 없는 PC — 외부 연결은 그대로 보여 준다
    items = external + commands
    # 외부 연결이 먼저(연결된 것부터), 매니저 명령은 뒤
    items.sort(key=lambda item: (
        item["kind"] == "command", STATUS_ORDER.get(item["status"], 9),
        CATEGORIES.index(item["category"]), item["name"].lower(),
    ))
    for item in items:
        item["checked_at"] = checked_at if item["kind"] != "command" else None
    return items


def cached_external():
    """캐시가 비었으면 기다려 읽고, 오래됐으면 지난 결과를 주고 뒤에서 다시 읽는다"""
    with _lock:
        fresh = _cache["external"] is not None and time.time() - _cache["at"] < TOOLS_CACHE_SEC
        if _cache["external"] is None:
            _refresh()
        elif not fresh and not _refreshing.is_set():
            _refreshing.set()
            threading.Thread(target=_refresh_in_background, daemon=True).start()
        return [dict(item) for item in _cache["external"]], _cache["checked_at"]


def _refresh_in_background():
    # 읽는 15초 동안 잠금을 잡지 않는다 — 그 사이 들어온 요청은 지난 결과를 바로 받는다
    try:
        fresh = _read_external()
        with _lock:
            _store(fresh)
    finally:
        _refreshing.clear()


def _refresh():
    _store(_read_external())


def _read_external():
    return mcp_servers() + cli_tools()


def _store(external):
    _cache["external"] = external
    _cache["at"] = time.time()
    _cache["checked_at"] = datetime.now().astimezone().isoformat(timespec="seconds")


def clear_cache():
    with _lock:
        _cache.update(at=0.0, external=None, checked_at=None)


# ── MCP ─────────────────────────────────────────────────────────────────────


def mcp_servers(run=None):
    """`claude mcp list` → 서버마다 한 줄. 명령이 없거나 실패하면 그 사실을 한 줄로 드러낸다"""
    try:
        text = (run or _run_mcp_list)()
    except (OSError, subprocess.SubprocessError) as error:
        return [_unchecked("claude mcp list", f"MCP 목록을 읽지 못함 — {type(error).__name__}")]
    return parse_mcp_list(text)


def _run_mcp_list():
    claude = shutil.which("claude")
    if not claude:
        raise FileNotFoundError("claude")
    done = subprocess.run(
        [claude, "mcp", "list"], capture_output=True, text=True, timeout=TOOLS_MCP_TIMEOUT_SEC,
        cwd=os.path.expanduser("~"),
    )
    if done.returncode != 0:
        raise subprocess.SubprocessError(f"exit {done.returncode}")
    return done.stdout


def parse_mcp_list(text):
    items = []
    for line in text.splitlines():
        match = MCP_LINE.match(line.strip())
        if not match:
            continue
        raw = match["name"].strip()
        label, category, maker, desc = KNOWN_MCP.get(raw, (_plain_name(raw), "etc", None, None))
        items.append({
            "id": f"mcp:{raw}",
            "kind": "mcp",
            "name": label,
            "source": raw,
            "category": category,
            "maker": maker,
            "desc": desc,
            "status": mcp_status(match["status"]),
        })
    return items


def mcp_status(text):
    lowered = text.lower()
    if "connected" in lowered and "not" not in lowered:
        return CONNECTED
    if "auth" in lowered:
        return NEEDS_AUTH
    if "fail" in lowered or "error" in lowered or "✗" in text:
        return FAILED
    return UNKNOWN


def _plain_name(raw):
    if raw.startswith("plugin:"):
        return raw.split(":")[-1]
    return raw.removeprefix("claude.ai ").strip()


def _unchecked(source, desc):
    return {"id": f"mcp:{source}", "kind": "mcp", "name": source, "source": source,
            "category": "etc", "maker": None, "desc": desc, "status": UNKNOWN}


# ── CLI ─────────────────────────────────────────────────────────────────────


def cli_tools(which=None, run=None):
    """PATH 에 있는 CLI 만. 인증 확인 명령이 0 이면 연결됨, 아니면 인증 필요, 못 돌리면 확인 안 됨"""
    which = which or shutil.which
    items = []
    for name, binary, category, desc, check in KNOWN_CLI:
        if not which(binary):
            continue
        items.append({
            "id": f"cli:{binary}", "kind": "cli", "name": name, "source": binary,
            "category": category, "maker": EXTERNAL, "desc": desc, "status": cli_status(check, run),
        })
    return items


def cli_status(check, run=None):
    try:
        code = (run or _run_check)(check)
    except (OSError, subprocess.SubprocessError):
        return UNKNOWN
    return CONNECTED if code == 0 else NEEDS_AUTH


def _run_check(command):
    # 출력은 계정 id·토큰 앞자리를 담을 수 있어 받지도 않는다
    return subprocess.run(
        command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=TOOLS_CLI_TIMEOUT_SEC,
    ).returncode


# ── 매니저 명령 ───────────────────────────────────────────────────────────────

# docstring 의 명령 줄 '  manager.py <명령> [하위 명령] ...'. 하위 명령은 task·candidate 처럼 묶음일 때만 이름에 붙인다
COMMAND_LINE = re.compile(r"^  manager\.py (?P<rest>\S.*)$")
GROUPS = {"task", "candidate"}
# 설명 칸이 시작하는 열. 명령 줄의 사용법이 이 열을 넘으면 설명은 다음 줄부터다
DESC_COLUMN = 40


def manager_commands(manager_home):
    script = os.path.join(manager_home, "manager.py")
    if not os.path.isfile(script):
        raise FileNotFoundError(f"매니저가 없음: {script}")
    with open(script, encoding="utf-8") as handle:
        doc = ast.get_docstring(ast.parse(handle.read())) or ""
    return parse_commands(doc)


def parse_commands(doc):
    """명령마다 한 줄. 같은 명령이 여러 줄(용법이 둘)이면 처음 것의 설명을 쓴다.
    설명은 설명 칸에서 시작해 다음 명령 줄 전까지 이어지는 글을 합친 뒤 첫 문장만 — 전문은 detail"""
    items, seen, current, lines = [], set(), None, []

    def close():
        if current is not None and lines:
            text = " ".join(lines)
            current["desc"] = _first_clause(text)
            current["detail"] = text

    for line in doc.splitlines():
        match = COMMAND_LINE.match(line)
        if match or not line.strip():
            close()
            current, lines = None, []
        if match:
            name = _command_name(match["rest"])
            if name in seen:
                continue
            seen.add(name)
            current = {"id": f"cmd:{name}", "kind": "command", "name": f"manager.py {name}", "source": name,
                       "category": "command", "maker": INHOUSE, "desc": None, "detail": None, "status": AVAILABLE}
            items.append(current)
            first = _desc_on(line)
            if first:
                lines.append(first)
            continue
        if current is not None and _width(line) - _width(line.lstrip(" ")) >= DESC_COLUMN:
            lines.append(line.strip())
    close()
    return items


def _command_name(rest):
    words = rest.split()
    head = words[0]
    if head in GROUPS and len(words) > 1 and not words[1].startswith(("-", "<", "[")):
        return f"{head} {words[1].replace('|', '·')}"
    return head


def _desc_on(line):
    """명령 줄 끝의 설명 — 두 칸 이상 띄우고 설명 칸(표시 폭 기준)에서 시작한 글.
    한글은 두 칸을 차지해 글자 수로 세면 설명 칸보다 앞에 있는 것처럼 보인다"""
    match = re.search(r"\S(\s{2,})(\S.*)$", line)
    if not match or _width(line[: match.start(2)]) < DESC_COLUMN:
        return None
    return match[2].strip()


def _first_clause(text):
    """첫 문장(또는 ' — ' 앞). 화면은 한 줄이라 뒷말은 버린다"""
    text = re.split(r"\s+[—–]\s+|(?<=\.)\s", text, maxsplit=1)[0].strip()
    return text.rstrip(".") or None


def _width(text):
    return sum(2 if unicodedata.east_asian_width(char) in "WF" else 1 for char in text)
