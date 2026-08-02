"""귀속 사용량. /usage 의 "무엇에 얼마나 썼는지"를 트랜스크립트에서 뽑는다

한도 %도 토큰 로그도 이 질문에는 답하지 못한다 — 사이드카에는 창별 %만 있고, cost
로그에는 (세션, 모델)별 누적치만 있어 어느 스킬·플러그인이 썼는지가 없다. 그 이름표는
트랜스크립트 jsonl 의 assistant 줄에 attributionSkill / attributionAgent /
attributionPlugin / attributionMcpServer 로만 붙는다.

무게·문턱·창은 Claude Code 가 /usage 에서 쓰는 것과 같은 값이다. 토큰 종류마다 값이
다르므로 합계 토큰으로 나누면 캐시 읽기가 대부분을 먹어 실제 소모와 어긋난다.

내려보내는 것은 두 가지다. 이름표별 몫과, 요청·세션의 행동 특성(긴 컨텍스트·캐시
미스·서브에이전트·병렬·상시). 둘 다 서로 겹쳐 세어지므로 합이 100%가 되지 않는다.

줄을 json 으로 풀지 않고 정규식으로 필요한 키만 집는다. 도구 결과가 통째로 실린 줄은
한 줄이 수 MB 라, 7일치 400MB 를 파싱하면 초 단위로 늘어진다.
"""
import os
import re
import time
from datetime import datetime, timezone

from app.constants import (
    ATTRIBUTION_BEHAVIORS,
    CONTEXT_FIELDS,
    ATTRIBUTION_BEHAVIOR_MIN_PCT,
    ATTRIBUTION_CACHE_SECONDS,
    ATTRIBUTION_DAYS,
    ATTRIBUTION_GROUPS,
    ATTRIBUTION_TOP,
    ATTRIBUTION_WINDOWS,
    CACHE_MISS_TOKENS,
    CRON_SESSION_HOURS,
    LONG_CONTEXT_TOKENS,
    MODEL_TIERS,
    MODEL_TIER_OTHER,
    PARALLEL_BUCKET_MS,
    PARALLEL_SESSIONS,
    SUBAGENT_HEAVY_COUNT,
    SUBAGENT_HEAVY_SHARE,
    TOKEN_WEIGHTS,
    UNCACHED_FIELD,
    TRANSCRIPT_ROOT,
)

PERCENT_FULL = 100
MS_PER_SECOND = 1000
MS_PER_HOUR = 3_600_000
SECONDS_PER_DAY = 86_400
# assistant 줄만 본다. 정규식을 돌리기 전에 이 두 조각으로 먼저 거른다
ASSISTANT_MARK = '"type":"assistant"'
USAGE_MARK = '"usage":{'
SIDECHAIN_MARK = '"isSidechain":true'  # 서브에이전트가 돌린 줄
AGENT_KEY, SKILL_KEY, PLUGIN_KEY, MCP_KEY = (
    "attributionAgent",
    "attributionSkill",
    "attributionPlugin",
    "attributionMcpServer",
)
SKILLS_GROUP, AGENTS_GROUP, PLUGINS_GROUP, MCP_GROUP = (key for key, _ in ATTRIBUTION_GROUPS)
# ATTRIBUTION_BEHAVIORS 는 표시 순서라 위치로 뽑으면 라벨이 어긋난다 — 이름으로 못박는다
CACHE_MISS, LONG_CONTEXT = "cache_miss", "long_context"
SUBAGENT_HEAVY, HIGH_PARALLEL, CRON = "subagent_heavy", "high_parallel", "cron"


def _text_pattern(key):
    return re.compile(r'"%s":"([^"]*)"' % key)


def _number_pattern(key):
    return re.compile(r'"%s":(\d+)' % key)


# "ephemeral_5m_input_tokens" 는 여는 따옴표가 없어 input_tokens 에 걸리지 않는다
TOKEN_PATTERNS = {field: _number_pattern(field) for field in TOKEN_WEIGHTS}
NAME_PATTERNS = {key: _text_pattern(key) for key in (AGENT_KEY, SKILL_KEY, PLUGIN_KEY, MCP_KEY)}
MODEL_PATTERN = _text_pattern("model")
UUID_PATTERN = _text_pattern("uuid")
STAMP_PATTERN = _text_pattern("timestamp")
SESSION_PATTERN = _text_pattern("sessionId")

_cache = None  # (만료 시각, 결과)


def attribution(root=TRANSCRIPT_ROOT, cache_seconds=ATTRIBUTION_CACHE_SECONDS):
    """창별 귀속 사용량. 폴링마다 400MB 를 다시 훑지 않게 잠깐 물고 있는다"""
    global _cache
    now = time.monotonic()
    if _cache and _cache[0] > now:
        return _cache[1]
    result = _scan(root)
    _cache = (now + cache_seconds, result)
    return result


def _scan(root):
    """가장 넓은 창으로 한 번만 읽고, 짧은 창은 그 안에서 같이 접는다"""
    files = _recent_files(root, ATTRIBUTION_DAYS)
    now_ms = int(datetime.now(timezone.utc).timestamp() * MS_PER_SECOND)
    windows = [
        (key, label, now_ms - hours * MS_PER_HOUR, _empty_window())
        for key, label, hours in ATTRIBUTION_WINDOWS
    ]
    floor_ms = min(window[2] for window in windows)
    seen = set()
    for path in files:
        for line in _lines(path):
            record = _record(line, floor_ms, seen)
            if record is None:
                continue
            for _, _, window_floor, state in windows:
                if record["ts"] >= window_floor:
                    _absorb(state, record)
    return {
        "available": bool(files),
        "source": root,
        "windows": {key: _finish(state, label) for key, label, _, state in windows},
    }


def _record(line, floor_ms, seen):
    """assistant 줄 하나 → 집계에 필요한 값. 볼 필요가 없는 줄이면 None"""
    if USAGE_MARK not in line or ASSISTANT_MARK not in line:
        return None
    stamp = _epoch_ms(_match(STAMP_PATTERN, line))
    if stamp is None or stamp < floor_ms:
        return None
    uuid = _match(UUID_PATTERN, line)
    if uuid:
        if uuid in seen:
            return None  # 재개된 세션은 앞 세션의 줄을 그대로 복사해 온다
        seen.add(uuid)
    tokens = {field: _number(field, line) for field in TOKEN_PATTERNS}
    return {
        "ts": stamp,
        "session": _match(SESSION_PATTERN, line),
        "weight": _weight(tokens, _match(MODEL_PATTERN, line)),
        "tokens": tokens,
        "labels": {key: _match(pattern, line) for key, pattern in NAME_PATTERNS.items()},
        "subagent": SIDECHAIN_MARK in line,
    }


def _empty_window():
    return {
        "total": 0.0,
        "requests": 0,
        "names": {key: {} for key, _ in ATTRIBUTION_GROUPS},
        # 요청 하나로 판정되는 특성은 여기서 바로 쌓인다
        "flags": {CACHE_MISS: [0.0, 0], LONG_CONTEXT: [0.0, 0]},
        # 세션·시간 단위 특성은 다 읽은 뒤에야 판정할 수 있다
        "sessions": {},
        "buckets": {},
    }


def _absorb(state, record):
    weight = record["weight"]
    state["total"] += weight
    state["requests"] += 1
    _label(state["names"], record["labels"], weight)
    _flag(state["flags"], record["tokens"], weight)
    _session(state["sessions"], record, weight)
    _bucket(state["buckets"], record, weight)


def _label(names, labels, weight):
    """이름표별 몫

    서브에이전트가 스킬을 물고 돈 줄에는 둘 다 붙는데, 그 무게는 서브에이전트 몫이고
    이름은 구체적인 스킬 것을 쓴다. 플러그인·MCP 는 스킬과 겹쳐 세어진다 — 플러그인이
    제공한 스킬의 무게는 양쪽에 다 들어간다.
    """
    agent, skill = labels[AGENT_KEY], labels[SKILL_KEY]
    if agent:
        _add(names[AGENTS_GROUP], skill or agent, weight)
    else:
        _add(names[SKILLS_GROUP], skill, weight)
    _add(names[PLUGINS_GROUP], labels[PLUGIN_KEY], weight)
    _add(names[MCP_GROUP], labels[MCP_KEY], weight)


def _flag(flags, tokens, weight):
    if tokens[UNCACHED_FIELD] > CACHE_MISS_TOKENS:
        _bump(flags[CACHE_MISS], weight)
    if sum(tokens[field] for field in CONTEXT_FIELDS) > LONG_CONTEXT_TOKENS:
        _bump(flags[LONG_CONTEXT], weight)


def _session(sessions, record, weight):
    """세션별 누적. 서브에이전트 비중과 걸쳐 있는 시각대를 같이 센다"""
    state = sessions.setdefault(
        record["session"], {"cost": 0.0, "sub_cost": 0.0, "sub_count": 0, "hours": set()}
    )
    state["cost"] += weight
    if record["subagent"]:
        state["sub_cost"] += weight
        state["sub_count"] += 1
    state["hours"].add(record["ts"] // MS_PER_HOUR)


def _bucket(buckets, record, weight):
    """5분 구간별로 어느 세션이 함께 돌았는지"""
    state = buckets.setdefault(
        record["ts"] // PARALLEL_BUCKET_MS, {"sessions": set(), "cost": 0.0, "count": 0}
    )
    state["sessions"].add(record["session"])
    state["cost"] += weight
    state["count"] += 1


def _finish(state, label):
    total = state["total"]
    return {
        "label": label,
        "requests": state["requests"],
        "sessions": len(state["sessions"]),
        "behaviors": _behaviors(state, total),
        "groups": [
            {"key": key, "label": name, "items": _ranked(state["names"][key], total)}
            for key, name in ATTRIBUTION_GROUPS
        ],
    }


def _behaviors(state, total):
    """몫이 큰 순으로. 문턱 아래는 접는다 — 잔챙이까지 세우면 큰 것이 안 보인다"""
    counted = dict(state["flags"])
    counted[SUBAGENT_HEAVY] = _sum_sessions(state["sessions"].values(), _is_subagent_heavy)
    counted[CRON] = _sum_sessions(state["sessions"].values(), _is_cron)
    counted[HIGH_PARALLEL] = _sum_parallel(state["buckets"].values())
    rows = [
        {
            "key": key,
            "label": name,
            "advice": advice,
            "pct": _pct(counted[key][0], total),
            "count": counted[key][1],
        }
        for key, name, advice in ATTRIBUTION_BEHAVIORS
    ]
    rows = [row for row in rows if row["pct"] >= ATTRIBUTION_BEHAVIOR_MIN_PCT]
    return sorted(rows, key=lambda row: row["pct"], reverse=True)


def _is_subagent_heavy(session):
    if session["sub_count"] >= SUBAGENT_HEAVY_COUNT:
        return True
    return bool(session["cost"]) and session["sub_cost"] / session["cost"] > SUBAGENT_HEAVY_SHARE


def _is_cron(session):
    return len(session["hours"]) >= CRON_SESSION_HOURS


def _sum_sessions(sessions, matches):
    """세션 단위 특성. 셈은 세션 수다 — 요청 수를 세면 특성마다 단위가 달라진다"""
    picked = [session for session in sessions if matches(session)]
    return [sum(session["cost"] for session in picked), len(picked)]


def _sum_parallel(buckets):
    picked = [bucket for bucket in buckets if len(bucket["sessions"]) >= PARALLEL_SESSIONS]
    return [sum(bucket["cost"] for bucket in picked), sum(bucket["count"] for bucket in picked)]


def _bump(slot, weight):
    slot[0] += weight
    slot[1] += 1


def _add(bucket, name, weight):
    if name:
        bucket[name] = bucket.get(name, 0.0) + weight


def _ranked(bucket, total):
    """몫이 큰 순으로. /usage 와 같이 정수로 접고 0%가 되는 이름은 뺀다"""
    rows = [{"name": name, "pct": _pct(weight, total)} for name, weight in bucket.items()]
    rows = [row for row in rows if row["pct"]]
    return sorted(rows, key=lambda row: row["pct"], reverse=True)[:ATTRIBUTION_TOP]


def _pct(weight, total):
    return round(weight / total * PERCENT_FULL) if total else 0


def _weight(tokens, model):
    tier = _tier(model)
    return sum(tokens[field] * factor for field, factor in TOKEN_WEIGHTS.items()) * tier


def _tier(model):
    text = (model or "").lower()
    for token, tier in MODEL_TIERS:
        if token in text:
            return tier
    return MODEL_TIER_OTHER


def _number(field, line):
    found = TOKEN_PATTERNS[field].search(line)
    return int(found.group(1)) if found else 0


def _match(pattern, line):
    found = pattern.search(line)
    return found.group(1) if found else None


def _epoch_ms(text):
    """ISO8601(Z 표기) → ms epoch. 못 읽으면 None"""
    if not isinstance(text, str):
        return None
    try:
        stamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return int(stamp.timestamp() * MS_PER_SECOND)


def _recent_files(root, days):
    """최근에 손댄 트랜스크립트만. 오래된 파일까지 열면 스캔이 몇 배로 늘어난다"""
    floor = time.time() - days * SECONDS_PER_DAY
    if not os.path.isdir(root):
        return []
    found = []
    # 서브에이전트는 <프로젝트>/<세션>/subagents/agent-*.jsonl 에 따로 남는다.
    # 깊이를 고정하면 그게 빠지고, 그러면 서브에이전트 몫이 통째로 사라진다
    for folder, _, names in os.walk(root):
        for name in names:
            if not name.endswith(".jsonl"):
                continue
            path = os.path.join(folder, name)
            try:
                if os.path.getmtime(path) >= floor:
                    found.append(path)
            except OSError:
                continue
    return found


def _lines(path):
    """읽는 도중 다른 프로세스가 덧붙이거나 지울 수 있다 — 실패한 파일은 건너뛴다"""
    try:
        with open(path, encoding="utf-8", errors="ignore") as handle:
            yield from handle
    except OSError:
        return
