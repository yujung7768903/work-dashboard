"""매니저 탭 — 사용자가 손대지 않아도 도는 자동화, 떠 있는 보조 세션, 사용자 결정 대기.

목록은 실제 설정에서 읽는다. 자동화는 crontab 과 매니저 점검 훅의 상수, 보조 세션은
`manager.py 보조 --json`, 결정 대기는 매니저 DB(state/manager.db)다. 매니저 DB 는 읽기
전용(mode=ro)으로만 열고 여기로 옮겨 담지 않는다 — 정본은 매니저 쪽 하나여야 두 곳이
어긋나지 않는다.

각 칸은 따로 실패한다. 매니저가 없는 PC 에서도 crontab 칸은 떠야 하므로 칸마다
{"items": [...], "error": 문장|None} 로 돌려준다.
"""
import ast
import json
import os
import re
import shlex
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta

from app.constants import (
    MANAGER_HOME_DEFAULT,
    MANAGER_HOME_ENV,
    MANAGER_HELPERS_TIMEOUT_SEC,
)
from app.services import cron

PARTS = ("automations", "helpers", "decisions")
STATUS_OK = "ok"
STATUS_FAIL = "fail"
STATUS_NODATA = "nodata"
# 로그 끝에서 실패를 읽을 때 보는 양. 마지막 실행의 출력만 보면 되므로 작게
LOG_TAIL_BYTES = 4096
# 마지막 줄이 이렇게 생겼으면 그 실행은 예외로 끝났다고 본다. 확신할 수 없는 줄은 판정하지 않는다
FAILURE_LINE = re.compile(r"^(Traceback \(most recent call last\):|[A-Za-z_.]*(Error|Exception)\b.*:)")
# 이름표가 아닌 주석 — 주석 처리해 둔 크론 줄('# ... : 0 11 * * * ...')
COMMENTED_ENTRY = re.compile(r"(^|:\s*)(@\w+|[\d*/,-]+(\s+[\d*/,-]+){4})\s+\S")
# 프로젝트 이름으로 쓰지 않는 디렉터리. 그 아래 칸이 사람이 지은 이름이다
CONTAINER_DIRS = {"work", "skills", "scripts", "bin", "backend", "src", "app", "home", ".claude"}
INTERPRETERS = re.compile(r"(^|/)(python3?|bash|sh|node|flock)$")
DECISION_KIND = "decision"
OPEN_STATUS = "open"
CONFIRM_STATUS = "confirm"


def snapshot(part=None, now=None, con=None, **sources):
    """part 하나만, 없으면 셋 다. con 은 대시보드 DB(자율 실행 tick 기록을 읽는다).
    sources 는 테스트 주입점(crontab_text, manager_home, helpers_fn)"""
    names = (part,) if part else PARTS
    unknown = [name for name in names if name not in PARTS]
    if unknown:
        raise ValueError(f"알 수 없는 칸: {unknown[0]}")
    now = now or datetime.now().astimezone()
    builders = {
        "automations": lambda: automations(
            now, con=con, **_pick(sources, "crontab_text", "manager_home")
        ),
        "helpers": lambda: helpers(**_pick(sources, "manager_home", "helpers_fn")),
        "decisions": lambda: decisions(now, **_pick(sources, "manager_home")),
    }
    return {name: _section(builders[name]) for name in names}


def _pick(sources, *keys):
    return {key: sources[key] for key in keys if key in sources}


def _section(build):
    try:
        return {"items": build(), "error": None}
    except Exception as error:  # 한 칸이 깨져도 나머지는 보여야 한다
        return {"items": [], "error": f"{type(error).__name__}: {error}"}


def manager_home():
    return os.environ.get(MANAGER_HOME_ENV) or MANAGER_HOME_DEFAULT


# ── 자동화 ──────────────────────────────────────────────────────────────────


def automations(now, crontab_text=None, manager_home=None, con=None):
    home = manager_home or globals()["manager_home"]()
    text = read_crontab() if crontab_text is None else crontab_text
    items = []
    for entry in crontab_entries(text):
        items.extend(_expand(entry, now, con))
    check = manager_check(home, now)
    if check:
        items.append(check)
    return sorted(items, key=lambda item: _by_next(item, now))


def _by_next(item, now=None):
    # 곧 도는 것이 위. 다음 실행을 모르는 것(@reboot·꺼진 것)은 맨 아래.
    # 매니저 점검처럼 'N초 안' 만 아는 줄은 그 끝 시각으로 놓는다
    at = item.get("next_at")
    if not at and item.get("next_within_sec") and now:
        at = _iso(now + timedelta(seconds=item["next_within_sec"]))
    return (at is None, at or "", item["name"])


def read_crontab():
    try:
        done = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout if done.returncode == 0 else ""


def crontab_entries(text):
    """crontab 원문 → 줄마다 {schedule, command, comment, key, sub}.

    이름표 주석은 바로 아래 줄과, 그 아래로 빈 줄 없이 이어지면서 같은 프로그램을 부르는
    줄에만 붙는다. 한 주석 아래 다른 프로그램이 이어 붙어 있는 일이 흔해서다
    """
    entries = []
    comment, comment_key, attached = None, None, False
    # 한 프로그램에 한 번 붙은 이름표는 같은 파일 안의 그 프로그램 줄 전부가 쓴다 —
    # 주석 아래 다른 프로그램이 끼어 이어짐이 끊겨도 같은 이름으로 묶인다
    known = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            comment, comment_key, attached = None, None, False
            continue
        if line.startswith("#"):
            body = line.lstrip("#").strip()
            if body and not COMMENTED_ENTRY.search(body):
                comment, comment_key, attached = body, None, False
            continue
        if _is_env_line(line):
            continue
        schedule, command = _split_entry(line)
        if not schedule:
            continue
        key, sub = program_of(command)
        label = None
        if comment and (not attached or key == comment_key):
            label, comment_key, attached = comment, key, True
            known.setdefault(key, comment)
        else:
            comment, comment_key, attached = None, None, False
        entries.append(
            {"schedule": schedule, "command": command, "comment": label, "key": key, "sub": sub}
        )
    for entry in entries:
        entry["comment"] = entry["comment"] or known.get(entry["key"])
    _name_entries(entries)
    _mark_shared_logs(entries)
    return entries


def _mark_shared_logs(entries):
    """로그 파일을 여러 줄이 같이 쓰면 그 파일의 수정 시각이 어느 줄 것인지 알 수 없다"""
    counts = {}
    for entry in entries:
        entry["log"] = log_path(entry["command"])
        if entry["log"]:
            counts[entry["log"]] = counts.get(entry["log"], 0) + 1
    for entry in entries:
        entry["log_shared"] = bool(entry["log"]) and counts[entry["log"]] > 1


def _is_env_line(line):
    return re.match(r"^[A-Za-z_][A-Za-z0-9_]*\s*=", line) is not None


def _split_entry(line):
    if line.startswith("@"):
        alias, _, command = line.partition(" ")
        return alias, command.strip()
    fields = line.split(None, 5)
    if len(fields) < 6:
        return None, None
    return " ".join(fields[:5]), fields[5]


def _name_entries(entries):
    """이름 = 주석 앞부분('—' 앞) 또는 프로그램 이름, 설명 = 주석의 '—' 뒤.
    같은 이름이 여럿이면 하위 명령을 덧붙인다"""
    for entry in entries:
        base = entry["comment"] or entry["key"]
        entry["name"], entry["desc"] = _split_desc(base)
    counts = {}
    for entry in entries:
        counts[entry["name"]] = counts.get(entry["name"], 0) + 1
    for entry in entries:
        if counts[entry["name"]] > 1 and entry["sub"]:
            entry["name"] = f"{entry['name']} · {entry['sub']}"


def _split_desc(text):
    parts = re.split(r"\s+[—–]\s+", text, maxsplit=1)
    return parts[0].strip(), (parts[1].strip() if len(parts) > 1 else None)


def program_of(command):
    """명령에서 (프로그램 이름, 하위 명령). 'cd X &&'·flock·인터프리터·리다이렉트는 걷어낸다.

    하위 명령은 스크립트 뒤 첫 인자(tick·report). 인자가 없으면 스크립트·모듈 이름, 옵션이 붙으면
    첫 옵션까지 — 같은 프로그램을 옵션만 달리 부르는 줄을 가르려면 그게 필요하다
    """
    cwd, tokens = _main_tokens(command)
    script, rest, module = None, [], False
    for index, token in enumerate(tokens):
        if token == "-m" and index + 1 < len(tokens):
            script, rest, module = tokens[index + 1], tokens[index + 2:], True
            break
        if INTERPRETERS.search(token) or token.startswith("-"):
            continue
        script, rest = token, tokens[index + 1:]
        break
    if script is None:
        words = command.split()
        return (words[0] if words else "?"), None
    key = cwd and module and _project_name(os.path.join(cwd, "_"), None) or _project_name(script, cwd)
    positional = []
    for token in rest:
        if token.startswith("-") or "$" in token:
            break
        positional.append(token)
    if positional:
        sub = positional[0]
    else:
        sub = script if module else os.path.splitext(os.path.basename(script))[0]
        if sub == key:
            sub = None
    flag = next((token for token in rest if token.startswith("-")), None)
    if flag and not positional:
        sub = f"{sub} {flag}" if sub else flag
    return key, sub


def _main_tokens(command):
    """'cd X && A && B' 면 (X, A 의 토큰). flock 의 잠금 파일 인자도 뗀다"""
    cwd = None
    head = command
    for part in re.split(r"\s*&&\s*", command):
        words = _safe_split(part)
        if words[:1] == ["cd"] and len(words) > 1:
            cwd = words[1]
            continue
        if words[:1] == ["sleep"]:
            continue
        head = part
        break
    words = _strip_redirects(_safe_split(head))
    if words and INTERPRETERS.search(words[0]) and words[0].endswith("flock"):
        words = _drop_flock(words)
    return cwd, words


def _drop_flock(words):
    rest = words[1:]
    while rest and rest[0].startswith("-"):
        flag = rest.pop(0)
        if flag in ("-w", "--wait", "-E") and rest:
            rest.pop(0)
    return rest[1:]  # 잠금 파일


def _safe_split(text):
    try:
        return shlex.split(text)
    except ValueError:
        return text.split()


def _strip_redirects(words):
    kept = []
    skip = False
    for word in words:
        if skip:
            skip = False
            continue
        if word in (">", ">>", "2>", "2>>", "<"):
            skip = True
            continue
        if re.match(r"^\d?>>?|^\d?>&\d$|^<", word):
            continue
        kept.append(word)
    return kept


def _project_name(script, cwd):
    """스크립트가 든 디렉터리 중 사람이 지은 이름. 홈 아래 공용 칸(.claude/scripts 등)뿐이면 스크립트 이름"""
    path = script if os.path.isabs(script) or not cwd else os.path.join(cwd, script)
    parts = [part for part in os.path.expanduser(path).split("/") if part]
    # 홈 디렉터리(/home/<사용자>, /root) 자체는 이름이 아니다
    if parts[:1] == ["home"]:
        parts = parts[2:]
    elif parts[:1] == ["root"]:
        parts = parts[1:]
    dirs = parts[:-1]
    for part in reversed(dirs):
        if part not in CONTAINER_DIRS and not part.startswith("."):
            return part
    return os.path.splitext(os.path.basename(script))[0]


def log_path(command):
    """명령이 출력을 남기는 파일. /dev/null 이면 None. 상대 경로는 'cd X' 기준"""
    cwd = None
    for part in re.split(r"\s*&&\s*", command):
        words = _safe_split(part)
        if words[:1] == ["cd"] and len(words) > 1:
            cwd = words[1]
    match = re.search(r"(?:^|\s)\d?>>?\s*(\S+)", command)
    if not match:
        return None
    target = os.path.expanduser(match.group(1))
    if target.startswith("&") or target == "/dev/null":
        return None
    if not os.path.isabs(target) and cwd:
        target = os.path.join(os.path.expanduser(cwd), target)
    return target


def last_from_log(path):
    """로그 파일의 마지막 수정 시각과, 끝줄로 확신할 수 있으면 실패 표시"""
    if not path or not os.path.isfile(path):
        return None
    mtime = datetime.fromtimestamp(os.path.getmtime(path)).astimezone()
    status = None
    try:
        with open(path, "rb") as handle:
            handle.seek(0, os.SEEK_END)
            handle.seek(max(0, handle.tell() - LOG_TAIL_BYTES))
            lines = [line for line in handle.read().decode("utf-8", "replace").splitlines() if line.strip()]
    except OSError:
        lines = []
    if lines and FAILURE_LINE.match(lines[-1].strip()):
        status = STATUS_FAIL
    return {"at": mtime.isoformat(timespec="seconds"), "status": status, "detail": None}


def _expand(entry, now, con=None):
    """크론 줄 하나 → 화면 줄(들). sre-watch 러너면 그 아래 체크마다 한 줄씩 덧붙인다"""
    base = {
        "source": "crontab",
        "name": entry["name"],
        "desc": entry["desc"],
        "cycle": cron.describe(entry["schedule"]),
        "expr": entry["schedule"],
        "next_at": _iso(cron.next_run(entry["schedule"], now)),
        "last": None if entry["log_shared"] else last_from_log(entry["log"]),
        "command": entry["command"],
    }
    if con is not None and AUTORUN_TICK.search(entry["command"]):
        base["last"] = _autorun_last(con)
    rows = [base]
    checks_dir = _sre_watch_dir(entry["command"])
    if checks_dir:
        checks = sre_watch_checks(checks_dir, entry, now)
        # 러너는 결과를 results.jsonl 에만 남기고 로그에는 거의 안 쓴다 — 마지막으로 돈 때는 체크 결과 시각
        stamps = [row["last"]["at"] for row in checks if row["last"]]
        if stamps:
            base["last"] = {"at": max(stamps), "status": None, "detail": None}
        rows.extend(checks)
    return rows


# 이 대시보드의 자율 실행 tick. 로그를 /dev/null 로 버리지만 tick 마다 DB 에 시각·판정을 남긴다
AUTORUN_TICK = re.compile(r"dash\.py\s+autorun-tick\b")


def _autorun_last(con):
    from app.repositories import autorun as autorun_repo

    state = autorun_repo.state(con)
    at = state.get("last_tick_at")
    if not at:
        return None
    moment = datetime.fromisoformat(at).astimezone().isoformat(timespec="seconds")
    return {"at": moment, "status": STATUS_OK, "detail": state.get("last_tick_reason")}


def _sre_watch_dir(command):
    """'<dir>/run.py run' 이고 <dir>/checks 가 있으면 sre-watch 러너로 본다"""
    _, words = _main_tokens(command)
    for index, word in enumerate(words):
        if word.endswith("run.py") and words[index + 1:index + 2] == ["run"]:
            root = os.path.dirname(os.path.expanduser(word))
            if os.path.isdir(os.path.join(root, "checks")):
                return root
    return None


SRE_META = re.compile(r"^# (\w+): (.+)$", re.M)


def sre_watch_checks(root, entry, now):
    """체크마다 한 줄. 주기는 체크의 every(일)이고 실제로는 러너 크론 시각에 돈다"""
    history = _sre_history(os.path.join(root, "results.jsonl"))
    rows = []
    checks_dir = os.path.join(root, "checks")
    for name in sorted(os.listdir(checks_dir)):
        if not name.endswith(".sh"):
            continue
        cid = name[:-3]
        with open(os.path.join(checks_dir, name), encoding="utf-8", errors="replace") as handle:
            meta = dict(SRE_META.findall(handle.read()))
        until = meta.get("until")
        if until and until < now.date().isoformat():
            continue  # 기한 지난 체크는 러너가 돌리지 않는다
        every = int(meta.get("every", 1) or 1)
        manual = bool(meta.get("manual"))
        last = history.get(cid)
        rows.append(
            {
                "source": "sre-watch",
                "name": _sre_name(cid, meta),
                "cycle": {"every_days": every, "manual": manual, "runner": cron.describe(entry["schedule"])},
                "expr": entry["schedule"],
                "next_at": None if manual else _iso(_sre_next(entry["schedule"], last, every, now)),
                "last": last and {
                    "at": last["at"],
                    "status": last.get("status"),
                    "detail": last.get("value"),
                },
                "command": f"{entry['command']}  # {cid}",
                "until": until,
            }
        )
    return rows


def _sre_name(cid, meta):
    """체크 목표 앞부분(괄호 앞). 'SRE 체크' 머리말은 화면이 언어에 맞춰 붙인다"""
    goal = (meta.get("goal") or "").split(" (")[0].strip()
    return goal or cid


def _sre_history(path):
    last = {}
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict) and row.get("id"):
                    last[row["id"]] = row
    except OSError:
        pass
    for row in last.values():
        try:
            row["at"] = datetime.fromisoformat(row["at"]).astimezone().isoformat(timespec="seconds")
        except (KeyError, TypeError, ValueError):
            pass
    return last


def _sre_next(expr, last, every, now):
    """러너가 다음에 이 체크를 돌릴 때 — 마지막 결과로부터 every 일이 지난 날의 첫 러너 실행"""
    after = now
    if last and last.get("at"):
        try:
            due_day = datetime.fromisoformat(last["at"]).date() + timedelta(days=every)
        except ValueError:
            due_day = None
        if due_day:
            due = datetime.combine(due_day, datetime.min.time()).astimezone() - timedelta(minutes=1)
            after = max(now, due)
    return cron.next_run(expr, after)


def _iso(moment):
    return moment.isoformat(timespec="seconds") if moment else None


# 매니저 주기 점검 — crontab 이 아니라 매니저 세션의 Stop 훅(hooks/inbox_wake.py)이 돈다.
# 주기는 그 파일의 상수를 읽는다(실행하지 않고 구문만 본다 — import 하면 훅 모듈이 매니저 경로를 건드린다)
CHECK_CONSTANTS = ("CHECK_SEC", "CHECK_HOURS")
WEEKDAY_LAST = 4  # inbox_wake.in_check_window: tm_wday < 5


def manager_check(home, now):
    hook = os.path.join(home, "hooks", "inbox_wake.py")
    if not os.path.isfile(hook):
        return None
    values = _literal_constants(hook, CHECK_CONSTANTS)
    seconds = int(os.environ.get("MANAGER_CHECK_SEC") or values.get("CHECK_SEC") or 0)
    hours = values.get("CHECK_HOURS")
    if not seconds or not hours:
        return None
    on_duty = _on_duty(home)
    return {
        "source": "manager",
        # 화면 이름은 화면이 언어에 맞춰 단다 (source 로 가른다)
        "name": "manager-check",
        "cycle": {
            "days": {"kind": "weekdays"},
            "time": {"kind": "interval", "minutes": seconds // 60, "hours": [hours[0], hours[1]]},
        },
        "expr": None,
        "next_at": _iso(_window_next(now, hours)) if on_duty else None,
        "next_within_sec": seconds if on_duty and _in_window(now, hours) else None,
        "off_duty": not on_duty,
        "last": _last_wake(home),
        "command": hook,
    }


def _literal_constants(path, names):
    with open(path, encoding="utf-8") as handle:
        tree = ast.parse(handle.read())
    found = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name) and target.id in names:
                try:
                    found[target.id] = ast.literal_eval(node.value)
                except ValueError:
                    pass
    return found


def _in_window(now, hours):
    return now.weekday() <= WEEKDAY_LAST and hours[0] <= now.hour <= hours[1]


def _window_next(now, hours):
    """창 밖이면 다음 창이 열리는 시각. 창 안이면 None (점검은 훅이 뜬 시각 기준 간격이라 정확한 시각이 없다)"""
    if _in_window(now, hours):
        return None
    day = now.replace(hour=hours[0], minute=0, second=0, microsecond=0)
    if now.hour >= hours[0]:
        day += timedelta(days=1)
    while day.weekday() > WEEKDAY_LAST:
        day += timedelta(days=1)
    return day


def _on_duty(home):
    try:
        with open(os.path.join(home, "state", "attendance.json"), encoding="utf-8") as handle:
            return json.load(handle).get("status") == "working"
    except (OSError, ValueError, AttributeError):
        return False


def _last_wake(home):
    """마지막으로 매니저를 깨운 점검 결과 시각. 알릴 것이 없던 점검은 기록이 남지 않는다"""
    folder = os.path.join(home, "state", "wake")
    try:
        names = [name for name in os.listdir(folder) if name.endswith(".json")]
    except OSError:
        return None
    if not names:
        return None
    newest = max(names, key=lambda name: os.path.getmtime(os.path.join(folder, name)))
    at = datetime.fromtimestamp(os.path.getmtime(os.path.join(folder, newest))).astimezone()
    return {"at": at.isoformat(timespec="seconds"), "status": None, "detail": "woke"}


# ── 보조 세션 ────────────────────────────────────────────────────────────────


def helpers(manager_home=None, helpers_fn=None):
    """manager.py 보조 --json 을 그대로 옮긴다. 상태·진행률 판정은 매니저 몫이다"""
    home = manager_home or globals()["manager_home"]()
    rows = (helpers_fn or _run_helpers)(home)
    return [
        {
            "name": row.get("name"),
            "status": row.get("status"),
            "percent": row.get("percent"),
            "percent_at": row.get("percent_at"),
            "doing": row.get("doing"),
            "moved_at": row.get("moved_at"),
        }
        for row in rows
    ]


def _run_helpers(home):
    script = os.path.join(home, "manager.py")
    if not os.path.isfile(script):
        raise FileNotFoundError(f"매니저가 없음: {script}")
    done = subprocess.run(
        [sys.executable, script, "보조", "--json"],
        cwd=home,
        capture_output=True,
        text=True,
        timeout=MANAGER_HELPERS_TIMEOUT_SEC,
    )
    if done.returncode != 0:
        raise RuntimeError((done.stderr or done.stdout).strip().splitlines()[-1:] or "보조 실패")
    try:
        return json.loads(done.stdout or "[]")
    except ValueError:
        # 보조 --json 이 없던 매니저는 사람용 글을 그대로 찍는다
        raise RuntimeError("매니저가 '보조 --json' 을 지원하지 않습니다 — 매니저 레포를 최신으로 맞춰 주세요")


# ── 결정 대기 ────────────────────────────────────────────────────────────────


def decisions(now, manager_home=None):
    """열린 결정(decision)과 사용자 확인 대기(confirm). 읽기 전용 연결로만 읽는다"""
    home = manager_home or globals()["manager_home"]()
    path = os.path.join(home, "state", "manager.db")
    if not os.path.isfile(path):
        raise FileNotFoundError(f"매니저 DB 가 없음: {path}")
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        columns = {row["name"] for row in con.execute("PRAGMA table_info(tasks)")}
        wanted = [
            name
            for name in ("id", "title", "kind", "status", "detail", "priority", "created_at",
                         "updated_at", "hold_until", "snooze_until", "open_target")
            if name in columns
        ]
        rows = con.execute(
            f"SELECT {', '.join(wanted)} FROM tasks"
            " WHERE (status=? AND kind=?) OR status=?"
            " ORDER BY priority DESC, created_at, id",
            (OPEN_STATUS, DECISION_KIND, CONFIRM_STATUS),
        ).fetchall()
    finally:
        con.close()
    stamp = now.isoformat(timespec="seconds")
    return [
        {
            "id": row["id"],
            "title": row["title"],
            "state": "confirm" if row["status"] == CONFIRM_STATUS else "decision",
            "detail": _first_line(row["detail"] if "detail" in row.keys() else None),
            "priority": row["priority"] if "priority" in row.keys() else None,
            "since": _utc_iso(row["updated_at"] if row["status"] == CONFIRM_STATUS else row["created_at"]),
            "held": _later(row, ("hold_until", "snooze_until"), stamp),
        }
        for row in rows
    ]


def _first_line(text, limit=200):
    line = next((part.strip() for part in (text or "").splitlines() if part.strip()), "")
    return line[:limit] + ("…" if len(line) > limit else "")


def _utc_iso(text):
    """매니저 DB 시각은 UTC ISO(Z) — 화면이 '얼마 전'으로 셀 수 있게 오프셋을 붙인 ISO 로"""
    if not text:
        return None
    try:
        return datetime.fromisoformat(str(text).replace("Z", "+00:00")).astimezone().isoformat(timespec="seconds")
    except ValueError:
        return None


def _later(row, keys, stamp):
    for key in keys:
        value = row[key] if key in row.keys() else None
        moment = _utc_iso(value)
        if moment and moment > stamp:
            return True
    return False
