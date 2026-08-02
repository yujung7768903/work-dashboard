"""귀속 사용량. /usage 의 "무엇에 얼마나 썼는지"를 트랜스크립트에서 뽑는다

한도 %도 토큰 로그도 이 질문에는 답하지 못한다 — 사이드카에는 창별 %만 있고, cost
로그에는 (세션, 모델)별 누적치만 있어 어느 스킬·플러그인이 썼는지가 없다. 그 이름표는
트랜스크립트 jsonl 의 assistant 줄에 attributionSkill / attributionPlugin /
attributionMcpServer 로만 붙는다.

무게는 Claude Code 가 /usage 에서 쓰는 것과 같은 식이다 — 토큰 종류마다 값이 다르므로
합계 토큰으로 나누면 캐시 읽기가 대부분을 먹어 실제 소모와 어긋난다.

줄을 json 으로 풀지 않고 정규식으로 필요한 키만 집는다. 도구 결과가 통째로 실린 줄은
한 줄이 수 MB 라, 7일치 400MB 를 파싱하면 초 단위로 늘어진다.
"""
import os
import re
import time
from datetime import datetime, timedelta, timezone

from app.constants import (
    ATTRIBUTION_CACHE_SECONDS,
    ATTRIBUTION_DAYS,
    ATTRIBUTION_GROUPS,
    ATTRIBUTION_MIN_PCT,
    ATTRIBUTION_TOP,
    MODEL_TIERS,
    MODEL_TIER_OTHER,
    TOKEN_WEIGHTS,
    TRANSCRIPT_ROOT,
)

PCT_DECIMALS = 1
PERCENT_FULL = 100
SECONDS_PER_DAY = 86_400
# assistant 줄만 본다. json 을 풀기 전에 이 두 조각으로 먼저 거른다
ASSISTANT_MARK = '"type":"assistant"'
USAGE_MARK = '"usage":{'
AGENT_KEY, SKILL_KEY, PLUGIN_KEY, MCP_KEY = (
    "attributionAgent",
    "attributionSkill",
    "attributionPlugin",
    "attributionMcpServer",
)
SKILLS_GROUP, PLUGINS_GROUP, MCP_GROUP = (key for key, _ in ATTRIBUTION_GROUPS)


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

_cache = None  # (만료 시각, 결과)


def attribution(root=TRANSCRIPT_ROOT, days=ATTRIBUTION_DAYS, cache_seconds=ATTRIBUTION_CACHE_SECONDS):
    """최근 구간의 귀속 사용량. 폴링마다 400MB 를 다시 훑지 않게 잠깐 물고 있는다"""
    global _cache
    now = time.monotonic()
    if _cache and _cache[0] > now:
        return _cache[1]
    result = _scan(root, days)
    _cache = (now + cache_seconds, result)
    return result


def _scan(root, days):
    files = _recent_files(root, days)
    floor = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat().replace("+00:00", "Z")
    buckets = {key: {} for key, _ in ATTRIBUTION_GROUPS}
    total, requests, seen = 0.0, 0, set()
    for path in files:
        for line in _lines(path):
            if USAGE_MARK not in line or ASSISTANT_MARK not in line:
                continue
            stamp = _match(STAMP_PATTERN, line)
            if stamp and stamp < floor:
                continue
            uuid = _match(UUID_PATTERN, line)
            if uuid:
                if uuid in seen:
                    continue  # 재개된 세션은 앞 세션의 줄을 그대로 복사해 온다
                seen.add(uuid)
            weight = _weight(line)
            total += weight
            requests += 1
            _attribute(buckets, line, weight)
    return {
        "available": bool(files),
        "days": days,
        "requests": requests,
        "source": root,
        "groups": [
            {"key": key, "label": label, "items": _ranked(buckets[key], total)}
            for key, label in ATTRIBUTION_GROUPS
        ],
    }


def _attribute(buckets, line, weight):
    """이름표를 무게에 더한다

    서브에이전트가 스킬을 물고 돈 줄에는 둘 다 붙는데, 그때 이름은 스킬 쪽이 구체적이다.
    플러그인·MCP 는 스킬과 겹쳐 세어진다 — 플러그인이 제공한 스킬의 무게는 양쪽에 다
    들어간다. 그래서 이 집계는 분할이 아니고, 합이 100%가 되지 않는다.
    """
    skill = _match(NAME_PATTERNS[SKILL_KEY], line)
    _add(buckets[SKILLS_GROUP], skill or _match(NAME_PATTERNS[AGENT_KEY], line), weight)
    _add(buckets[PLUGINS_GROUP], _match(NAME_PATTERNS[PLUGIN_KEY], line), weight)
    _add(buckets[MCP_GROUP], _match(NAME_PATTERNS[MCP_KEY], line), weight)


def _add(bucket, name, weight):
    if name:
        bucket[name] = bucket.get(name, 0.0) + weight


def _ranked(bucket, total):
    """몫이 큰 순으로. 반올림해서 0.0%가 되는 이름은 자리만 먹으므로 뺀다"""
    if not total:
        return []
    rows = [
        {"name": name, "pct": round(weight / total * PERCENT_FULL, PCT_DECIMALS)}
        for name, weight in bucket.items()
    ]
    rows = [row for row in rows if row["pct"] >= ATTRIBUTION_MIN_PCT]
    return sorted(rows, key=lambda row: row["pct"], reverse=True)[:ATTRIBUTION_TOP]


def _weight(line):
    tier = _tier(_match(MODEL_PATTERN, line))
    return sum(_number(field, line) * factor for field, factor in TOKEN_WEIGHTS.items()) * tier


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


def _recent_files(root, days):
    """최근에 손댄 트랜스크립트만. 오래된 파일까지 열면 스캔이 몇 배로 늘어난다"""
    floor = time.time() - days * SECONDS_PER_DAY
    if not os.path.isdir(root):
        return []
    found = []
    for name in os.listdir(root):
        folder = os.path.join(root, name)
        if not os.path.isdir(folder):
            continue
        for entry in os.scandir(folder):
            if entry.name.endswith(".jsonl") and entry.stat().st_mtime >= floor:
                found.append(entry.path)
    return found


def _lines(path):
    """읽는 도중 다른 프로세스가 덧붙이거나 지울 수 있다 — 실패한 파일은 건너뛴다"""
    try:
        with open(path, encoding="utf-8", errors="ignore") as handle:
            yield from handle
    except OSError:
        return
