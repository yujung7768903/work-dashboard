"""세션 결과물 수집. 세션 transcript 의 쓰기 호출과 완료 보고(--open)에서 그 세션이 만들거나 고친 것을 뽑아
세션 → 문서 결과 관계로 잇는다(app/repositories/graph.py add_result). 트리는 그 세션이 맡던 할일 밑에
결과물 카드로 그린다(app/services/todo_tree.py).

뽑는 것 — 읽기만 한 문서는 결과가 아니다
- Confluence  MCP 페이지 생성·수정
- Jira        MCP 이슈 생성·수정·상태 변경·댓글
- PR          gh pr create 성공. Claude Code 가 결과에 붙이는 gitOperation.pr(action=created)을 먼저 보고,
              없으면(옛 transcript) 출력에 찍힌 PR 주소
- 아티팩트    Artifact 발행(publish). 읽기·목록·삭제는 아니다
- 사이트·파일 manager.py ask·퇴근-보조 의 --open. 권한 막힘(--blocked) 질문의 --open 은 산출물이 아니다
- 파일        Write 로 새로 만든 파일 중 코드 레포 밖·에이전트 작업 폴더 밖·숨김·앱 데이터 폴더 밖이고 아직 있는 것.
              레포 안 코드 수정은 파일로 잡지 않는다 — 커밋·PR 로 보인다

실패한 호출(훅 차단 포함 is_error)은 뽑지 않는다. 서브에이전트 transcript(<세션>/subagents/*.jsonl)도
읽고 부모 세션 몫으로 둔다. Bash 로 REST 를 직접 부른 Confluence·Jira 쓰기는 읽기와 섞여 있어 뽑지 않는다.

훅은 턴마다 transcript 에 새로 붙은 꼬리만 읽는다(transcript_scans 오프셋). 결과를 아직 못 받은 쓰기 호출이
꼬리 가까이에 있으면 그 줄부터 다시 읽도록 오프셋을 멈춘다
"""
import glob
import json
import os
import re
import shlex
from datetime import datetime, timezone

from app import evidence as evidence_refs
from app.constants import (
    RESULT_CONFLUENCE_CREATE,
    RESULT_CONFLUENCE_UPDATE,
    RESULT_FILE_SKIP_DIRS,
    RESULT_FILE_SKIP_PARTS,
    RESULT_JIRA_COMMENT,
    RESULT_JIRA_CREATE,
    RESULT_JIRA_EDIT,
    RESULT_PENDING_HOLD_BYTES,
    TRANSCRIPT_ROOT,
)
from app.db import now, transaction
from app.repositories import graph as graph_repo
from app.services import browse

CREATE, EDIT, COMMENT, PUBLISH, REPORT = "생성", "수정", "댓글", "발행", "보고"
JIRA_KEY = re.compile(r"^[A-Z][A-Z0-9]{1,9}-\d+$")
JIRA_KEY_IN_RESULT = re.compile(r'"key"\s*:\s*"([A-Z][A-Z0-9]{1,9}-\d+)"')
PAGE_ID_IN_RESULT = re.compile(r'"id"\s*:\s*"(\d{5,})"')
PUBLISHED_AT = re.compile(r"Published \S+ at (https://claude\.ai/\S+)")
PR_CREATE = re.compile(r"\bgh\b[^\n|;&]*?\bpr\s+create\b")
TITLE_FLAG = re.compile(r"""(?:--title|-t)[ =](?:"((?:[^"\\]|\\.)*)"|'([^']*)')""")
TOOL_USE_ID = re.compile(rb'"tool_use_id"\s*:\s*"([^"]+)"')
# 줄 하나를 통째로 json 으로 읽기 전에 거르는 글자. 관심 없는 도구 호출 줄은 읽지 않는다
CALL_HINTS = (b'"Write"', b'"Artifact"', b'"Bash"', b"Confluence", b"Jira")
MANAGER_SCRIPT = "manager.py"
REPORT_COMMANDS = ("ask", "퇴근-보조")
OPEN_FLAG = "--open"
BLOCKED_FLAG = "--blocked"
SUBAGENT_GLOB = os.path.join("subagents", "*.jsonl")

# 결과 하나 = {"ref", "action", "at", "title", "url"}


# ── 수집 ────────────────────────────────────────────────────────────────


def collect(con, claude_session_id, root=None, max_bytes=None, dry_run=False):
    """그 세션의 transcript(본 + 서브에이전트)에서 지난번 뒤로 붙은 부분을 읽어 결과를 잇는다.
    → 이번에 찾은 결과 목록(이미 있던 관계도 들어 있다 — add_result 가 합친다)"""
    found = []
    for path in transcript_paths(claude_session_id, root):
        found += scan_file(con, path, claude_session_id, max_bytes=max_bytes, dry_run=dry_run)
    return found


def backfill(con, root=None, dry_run=False, sessions=None):
    """대시보드가 아는 세션 전부를 처음부터(오프셋 이후) 읽는다. → {세션 id: [결과]}"""
    index = _transcript_index(root)
    ids = sessions or [
        row["claude_session_id"] for row in con.execute("SELECT claude_session_id FROM sessions")
    ]
    found = {}
    for claude_session_id in ids:
        rows = []
        for path in index.get(claude_session_id, []):
            rows += scan_file(con, path, claude_session_id, dry_run=dry_run)
        if rows:
            found[claude_session_id] = rows
    return found


def transcript_paths(claude_session_id, root=None):
    """본 transcript 와 그 세션의 서브에이전트 transcript. 없으면 []"""
    matches = glob.glob(os.path.join(root or TRANSCRIPT_ROOT, "*", f"{claude_session_id}.jsonl"))
    if not matches:
        return []
    main = matches[0]
    subs = sorted(glob.glob(os.path.join(main[: -len(".jsonl")], SUBAGENT_GLOB)))
    return [main, *subs]


def _transcript_index(root):
    base = root or TRANSCRIPT_ROOT
    index = {}
    for path in glob.glob(os.path.join(base, "*", "*.jsonl")):
        index.setdefault(os.path.basename(path)[: -len(".jsonl")], []).insert(0, path)
    for path in glob.glob(os.path.join(base, "*", "*", SUBAGENT_GLOB)):
        owner = os.path.basename(os.path.dirname(os.path.dirname(path)))
        index.setdefault(owner, []).append(path)
    return index


def scan_file(con, path, claude_session_id, max_bytes=None, dry_run=False):
    """transcript 하나를 지난 오프셋부터 끝(또는 max_bytes)까지 읽는다. 끝의 반쪽 줄은 다음에 읽는다"""
    row = con.execute("SELECT offset FROM transcript_scans WHERE path=?", (path,)).fetchone()
    start = row["offset"] if row else 0
    try:
        size = os.path.getsize(path)
    except OSError:
        return []
    if size < start:
        start = 0  # 다시 쓰인 파일. 처음부터 읽어도 add_result 가 겹치지 않게 합친다
    if size == start:
        return []
    extractor = Extractor()
    position = start
    with open(path, "rb") as handle:
        handle.seek(start)
        while max_bytes is None or position - start < max_bytes:
            raw = handle.readline()
            if not raw or not raw.endswith(b"\n"):
                break
            extractor.feed(raw, position)
            position += len(raw)
    offset = extractor.resume_offset(position)
    if dry_run:
        return extractor.found
    for item in extractor.found:
        graph_repo.add_result(
            con, claude_session_id, item["ref"], item["action"], item["at"],
            title=item.get("title"), url=item.get("url"),
        )
    with transaction(con):
        con.execute(
            "INSERT INTO transcript_scans(path, claude_session_id, offset, scanned_at) VALUES(?,?,?,?)"
            " ON CONFLICT(path) DO UPDATE SET offset=excluded.offset, scanned_at=excluded.scanned_at",
            (path, claude_session_id, offset, now()),
        )
    return extractor.found


def open_folder(con, node_id):
    """결과물로 등록된 파일 노드의 폴더를 탐색기로 연다. 경로는 요청이 아니라 DB 에서 꺼낸다"""
    node = graph_repo.result_file(con, node_id)
    return browse.reveal(node["ref"].partition(":")[2])


# ── 추출 ────────────────────────────────────────────────────────────────


class Extractor:
    """transcript 줄을 차례로 받아 쓰기 호출과 그 결과를 짝지어 결과물을 뽑는다.
    쓰기 호출(tool_use)은 결과(tool_result)가 올 때까지 들고 있다가 결과를 보고 성공한 것만 남긴다"""

    def __init__(self, is_result_file=None):
        self.pending = {}  # tool_use id → (처리기 목록, 입력, 시각, 줄 시작 위치)
        self.found = []
        self.is_result_file = is_result_file or result_file_ok

    def feed(self, raw, position=0):
        if b'"tool_use"' in raw and any(hint in raw for hint in CALL_HINTS):
            self._calls(raw, position)
        if self.pending and b'"tool_result"' in raw:
            ids = {match.decode("utf-8", "ignore") for match in TOOL_USE_ID.findall(raw)}
            if ids & self.pending.keys():
                self._results(raw)

    def resume_offset(self, end):
        """다음에 읽기 시작할 곳. 결과를 못 받은 호출이 꼬리 가까이 있으면 그 줄부터"""
        waiting = [start for *_, start in self.pending.values() if end - start <= RESULT_PENDING_HOLD_BYTES]
        return min(waiting) if waiting else end

    def _calls(self, raw, position):
        entry = _json(raw)
        if not entry:
            return
        at = _stamp(entry.get("timestamp"))
        for block in _blocks(entry):
            if block.get("type") != "tool_use":
                continue
            data = block.get("input") or {}
            handlers = _handlers(block.get("name") or "", data)
            if handlers and block.get("id"):
                self.pending[block["id"]] = (handlers, data, at, position)

    def _results(self, raw):
        entry = _json(raw)
        if not entry:
            return
        blocks = [block for block in _blocks(entry) if block.get("type") == "tool_result"]
        # 줄 하나에 결과가 하나일 때만 줄의 toolUseResult 가 그 결과의 것이다
        extra = entry.get("toolUseResult") if len(blocks) == 1 else None
        for block in blocks:
            call = self.pending.pop(block.get("tool_use_id"), None)
            if call is None or _failed(block, extra):
                continue
            handlers, data, at, _ = call
            text = _text(block.get("content"))
            for handler in handlers:
                for item in handler(data, text, extra if isinstance(extra, dict) else {}, self) or []:
                    item.setdefault("at", at)
                    self.found.append(item)


def _handlers(name, data):
    short = name.rsplit("__", 1)[-1]
    if short in RESULT_CONFLUENCE_CREATE:
        return (_confluence_create,)
    if short in RESULT_CONFLUENCE_UPDATE:
        return (_confluence_update,)
    if short in RESULT_JIRA_CREATE:
        return (_jira_create,)
    if short in RESULT_JIRA_EDIT:
        return (_jira_touch(EDIT),)
    if short in RESULT_JIRA_COMMENT:
        return (_jira_touch(COMMENT),)
    if name == "Artifact" and (data.get("action") or "publish") == "publish" and not data.get("asset"):
        return (_artifact,)
    if name == "Write" and data.get("file_path"):
        return (_write,)
    if name == "Bash":
        command = data.get("command") or ""
        found = []
        if PR_CREATE.search(command):
            found.append(_pull_request)
        if MANAGER_SCRIPT in command and OPEN_FLAG in command:
            found.append(_report)
        return tuple(found)
    return ()


# ── 종류별 ──────────────────────────────────────────────────────────────


def _confluence_create(data, text, extra, extractor):
    payload = _json_text(text)
    page = str(payload.get("id") or "") if isinstance(payload, dict) else ""
    if not page.isdigit():
        match = PAGE_ID_IN_RESULT.search(text)
        page = match.group(1) if match else ""
    if not page:
        return []
    title = data.get("title") or (payload.get("title") if isinstance(payload, dict) else None)
    return [{"ref": f"{evidence_refs.CONFLUENCE}:{page}", "action": CREATE, "title": title}]


def _confluence_update(data, text, extra, extractor):
    page = str(data.get("pageId") or data.get("contentId") or data.get("id") or "").strip()
    if not page.isdigit():
        return []
    payload = _json_text(text)
    title = data.get("title") or (payload.get("title") if isinstance(payload, dict) else None)
    return [{"ref": f"{evidence_refs.CONFLUENCE}:{page}", "action": EDIT, "title": title}]


def _jira_create(data, text, extra, extractor):
    match = JIRA_KEY_IN_RESULT.search(text)
    if not match:
        return []
    return [{"ref": f"{evidence_refs.JIRA}:{match.group(1)}", "action": CREATE,
             "title": _jira_title(match.group(1), data.get("summary"))}]


def _jira_touch(action):
    def handler(data, text, extra, extractor):
        key = str(data.get("issueIdOrKey") or data.get("issueKey") or "").strip().upper()
        if not JIRA_KEY.match(key):
            return []
        summary = (data.get("fields") or {}).get("summary") if isinstance(data.get("fields"), dict) else None
        return [{"ref": f"{evidence_refs.JIRA}:{key}", "action": action, "title": _jira_title(key, summary)}]
    return handler


def _jira_title(key, summary):
    # Jira 카드는 키가 먼저 읽혀야 한다 — 요약을 알면 '키 요약'
    return f"{key} {summary}".strip() if summary else None


def _artifact(data, text, extra, extractor):
    url = extra.get("url")
    if not url:
        match = PUBLISHED_AT.search(text)
        url = match.group(1).rstrip(").,") if match else None
    ref = evidence_refs.artifact_ref(url)
    if not ref:
        return []
    return [{"ref": ref, "action": PUBLISH, "title": extra.get("title"), "url": url}]


def _pull_request(data, text, extra, extractor):
    git = extra.get("gitOperation") if isinstance(extra.get("gitOperation"), dict) else {}
    pr = git.get("pr") if isinstance(git.get("pr"), dict) else {}
    if pr:
        if pr.get("action") != "created" or not pr.get("url"):
            return []
        urls = [pr["url"]]
    else:
        urls = evidence_refs.PR_URL.findall(text)
        urls = [f"https://github.com/{org}/{repo}/pull/{number}" for org, repo, number in urls[-1:]]
    refs = [ref for url in urls for ref in evidence_refs.extract(url)]
    if not refs:
        return []
    match = TITLE_FLAG.search(data.get("command") or "")
    title = (match.group(1) or match.group(2)) if match else None
    label = evidence_refs.label_of(refs[0])
    return [{"ref": refs[0], "action": CREATE, "title": f"{label} {title}" if title else None}]


def _report(data, text, extra, extractor):
    """manager.py ask·퇴근-보조 의 --open. 같은 명령에 manager.py 호출이 여럿이면 각각 본다"""
    found = []
    for words in _manager_calls(data.get("command") or ""):
        if not words or words[0] not in REPORT_COMMANDS:
            continue
        if words[0] == "ask" and BLOCKED_FLAG in words:
            continue
        for target in _flag_values(words, OPEN_FLAG):
            ref = evidence_refs.target_ref(target)
            if not ref:
                continue
            kind, _, key = ref.partition(":")
            if kind == evidence_refs.FILE and not os.path.exists(key):
                continue
            found.append({"ref": ref, "action": REPORT, "url": target if kind == evidence_refs.ARTIFACT else None})
    return found


def _write(data, text, extra, extractor):
    created = extra.get("type") == "create" if extra else text.startswith("File created successfully")
    path = os.path.normpath(data.get("file_path") or "")
    if not created or not extractor.is_result_file(path):
        return []
    return [{"ref": f"{evidence_refs.FILE}:{path}", "action": CREATE}]


# ── 파일 판정 ───────────────────────────────────────────────────────────

_repo_cache = {}


def result_file_ok(path):
    """Write 로 만든 파일이 결과물인지. 절대 경로 · 아직 있음 · 에이전트 작업 폴더(~/.claude)·임시 폴더 밖 ·
    숨김 폴더 밖 · 코드 레포 밖"""
    if not path.startswith("/") or not os.path.isfile(path):
        return False
    for skip in RESULT_FILE_SKIP_DIRS:
        if path == skip or path.startswith(skip.rstrip("/") + "/"):
            return False
    if any(part.startswith(".") or part in RESULT_FILE_SKIP_PARTS for part in path.split("/") if part):
        return False
    return not in_git_repo(os.path.dirname(path))


def in_git_repo(directory):
    """위로 올라가며 .git(폴더 또는 워크트리의 파일)을 찾는다. 같은 폴더는 한 번만 본다"""
    seen = []
    current = directory
    while True:
        if current in _repo_cache:
            answer = _repo_cache[current]
            break
        seen.append(current)
        if os.path.exists(os.path.join(current, ".git")):
            answer = True
            break
        parent = os.path.dirname(current)
        if parent == current:
            answer = False
            break
        current = parent
    for folder in seen:
        _repo_cache[folder] = answer
    return answer


# ── 조각 ────────────────────────────────────────────────────────────────


def _manager_calls(command):
    """명령 줄에서 manager.py 뒤의 인자 묶음들. 셸 연결자(&& ; |)에서 끊는다"""
    try:
        words = shlex.split(command, comments=False)
    except ValueError:
        return []
    calls, current = [], None
    for word in words:
        if word.endswith(MANAGER_SCRIPT):
            current = []
            calls.append(current)
        elif word in ("&&", "||", ";", "|"):
            current = None
        elif current is not None:
            current.append(word)
    return calls


def _flag_values(words, flag):
    values = []
    for index, word in enumerate(words):
        if word == flag and index + 1 < len(words):
            values.append(words[index + 1])
        elif word.startswith(flag + "="):
            values.append(word.split("=", 1)[1])
    return values


def _failed(block, extra):
    if block.get("is_error"):
        return True
    return isinstance(extra, str) and extra.startswith("Error")


def _blocks(entry):
    content = (entry.get("message") or {}).get("content")
    return [block for block in content if isinstance(block, dict)] if isinstance(content, list) else []


def _text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(part.get("text") or "" for part in content if isinstance(part, dict))
    return ""


def _json(raw):
    try:
        entry = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return None
    return entry if isinstance(entry, dict) else None


def _json_text(text):
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return None


def _stamp(value):
    """transcript 시각(…Z) → DB 시각 모양(+00:00, 초 단위). 할일 연결 시각과 글자로 견준다"""
    if not value:
        return now()
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return now()
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds")
