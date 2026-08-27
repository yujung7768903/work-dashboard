"""착수 조건 문장을 항목으로 쪼개고, 코드가 판정할 수 있는 것만 판정한다.

문법은 새로 만들지 않는다 — PRECONDITION_HINT 가 이미 정해 둔 그대로다.
줄 하나가 항목 하나이고, '확인:' 으로 시작하는 줄은 바로 위 항목의 검증 명령이다.

항목은 판정 방법으로 세 갈래다.
  todo    — `#57` 처럼 다른 할일을 가리킨다. 상태 조회로 코드가 판정한다
  command — '확인: <명령>' 만 있다. 명령을 돌려야 알 수 있어 사람이 버튼으로 돌린다
  manual  — 자유 문장. 코드가 참·거짓을 가릴 수 없다

#id 와 확인 명령이 한 항목에 같이 오면 todo 로 본다 — 명령은 사람이 눈으로 더 볼
근거일 뿐이고, 판정 자체는 할일 상태로 끝난다. 이걸 command 로 내리면 힌트의
표준 예시(#57 + 확인 명령)가 영영 자동 판정되지 않는다.
"""
import os
import re
import subprocess

from app.constants import STATUS_DONE
from app.errors import NotFound, Validation
from app.repositories import todos as todo_repo

CHECK_PREFIX = "확인:"
TODO_REF = re.compile(r"#(\d+)")

KIND_TODO = "todo"
KIND_COMMAND = "command"
KIND_MANUAL = "manual"

# 명령 판정은 셸 관행을 따른다 — exit 0 이면 충족
COMMAND_TIMEOUT_SEC = 10
OUTPUT_CHARS = 500  # 팝업 한 칸에 들어갈 만큼만. 전문이 필요하면 터미널에서 돌린다


def parse(text):
    """조건 문장 → 항목 목록. 빈 문자열이면 빈 목록"""
    items = []
    for line in (text or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(CHECK_PREFIX) and items:
            items[-1]["command"] = stripped[len(CHECK_PREFIX) :].strip()
            continue
        items.append({"text": stripped, "command": "", "todo_ids": _refs(stripped)})
    return [_typed(item) for item in items]


def items(con, text):
    """항목 + 충족 여부. met 은 True/False, 판정 못 하는 항목은 None"""
    return [dict(item, met=_met(con, item)) for item in parse(text)]


def all_met(con, text):
    """자율 실행 게이트. 항목이 전부 자동 판정 가능하고 전부 충족일 때만 참.

    자유 문장이나 확인 명령이 하나라도 섞이면 거짓이다 — 코드가 모르는 조건을
    '아마 됐겠지' 로 넘기면 사람이 판단하라고 조건을 적은 뜻이 없어진다
    """
    parsed = items(con, text)
    if not parsed:
        return False
    return all(item["kind"] == KIND_TODO and item["met"] for item in parsed)


def summary(con, text):
    """칩에 쓸 요약. 조건이 없으면 None"""
    parsed = items(con, text)
    if not parsed:
        return None
    return {
        "total": len(parsed),
        "met": sum(1 for item in parsed if item["met"]),
        "manual": sum(1 for item in parsed if item["kind"] != KIND_TODO),
    }


def command_of(text, index):
    """index 번째 항목의 확인 명령. 명령을 화면에서 받지 않는 이유 —

    받으면 그 엔드포인트가 곧 임의 명령 실행 창구가 된다. 화면은 몇 번째 항목인지만
    보내고, 무엇을 돌릴지는 저장된 조건 문장에서 서버가 다시 읽는다
    """
    parsed = parse(text)
    if index < 0 or index >= len(parsed):
        return ""
    return parsed[index]["command"]


def check(con, todo_id, index):
    """확인 명령을 한 번 돌린다. 사람이 버튼을 눌렀을 때만 부른다 —

    폴링이 부르면 임의 셸 명령이 몇 초마다 돌게 된다. 판정은 셸 관행대로 exit 0 이
    충족이고, 출력은 사람이 눈으로 볼 몫이라 앞부분만 돌려준다
    """
    todo = todo_repo.get(con, int(todo_id))
    command = command_of(todo["precondition"], int(index))
    if not command:
        raise Validation("그 항목에는 확인 명령이 없습니다")
    try:
        done = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=COMMAND_TIMEOUT_SEC,
            cwd=os.path.expanduser("~"),
        )
    except subprocess.TimeoutExpired:
        return {"command": command, "exit_code": None, "output": "시간 초과"}
    output = (done.stdout + done.stderr).strip()
    return {
        "command": command,
        "exit_code": done.returncode,
        "output": output[:OUTPUT_CHARS],
    }


def _typed(item):
    if item["todo_ids"]:
        kind = KIND_TODO
    elif item["command"]:
        kind = KIND_COMMAND
    else:
        kind = KIND_MANUAL
    return dict(item, kind=kind)


def _refs(line):
    return [int(found) for found in TODO_REF.findall(line)]


def _met(con, item):
    if item["kind"] != KIND_TODO:
        return None
    return all(_is_done(con, todo_id) for todo_id in item["todo_ids"])


def _is_done(con, todo_id):
    """없어진 할일은 충족으로 보지 않는다 — 지워졌는지 끝났는지 알 수 없다"""
    try:
        return todo_repo.get(con, todo_id)["status"] == STATUS_DONE
    except NotFound:
        return False
