"""사용량 집계. /usage 가 보여주는 한도 창과 일별 토큰 추이를 파일에서 읽어 모은다

한도 %는 Claude Code 가 statusline 페이로드로만 넘기는 값이다(훅 페이로드에는 rate_limits
가 없다). 그래서 token-optimizer statusline 이 떨어뜨린 사이드카 파일을 읽는다. 값이
statusline 이 그려질 때만 갱신된다는 뜻이라, 세션이 조용한 동안 낡는 건 정상이다.

토큰 추이는 트랜스크립트(500MB) 대신 cost 로그(수백KB)에서 뽑는다. 요청마다 원본
트랜스크립트를 파싱하면 응답이 초 단위로 늘어진다.
"""
import json
import os
from datetime import datetime, timedelta, timezone

from app.constants import (
    COST_FIELD,
    COST_LOG_PATH,
    CREDENTIALS_PATH,
    CREDENTIALS_TIER_PREFIX,
    MISSING_WINDOW_LABELS,
    MODEL_FAMILIES,
    MODEL_FAMILY_OTHER,
    RATE_LIMITS_PATH,
    TOKEN_FIELDS,
    USAGE_CRITICAL_PCT,
    USAGE_SAMPLE_BUCKET_MS,
    USAGE_SAMPLE_MIN_GAP_MS,
    USAGE_SAMPLE_RETENTION_DAYS,
    USAGE_SAMPLE_WINDOW_HOURS,
    USAGE_STALE_SECONDS,
    USAGE_TREND_DAYS,
    USAGE_WARN_PCT,
    USAGE_WINDOWS,
)
from app.db import now, transaction

MS_PER_SECOND = 1000
MS_PER_HOUR = 3_600_000
MS_PER_DAY = 86_400_000
DELTA_FIELDS = TOKEN_FIELDS + (COST_FIELD,)
OAUTH_KEY = "claudeAiOauth"
TIER_KEY = "rateLimitTier"
LEVEL_OK, LEVEL_WARN, LEVEL_CRITICAL = "ok", "warn", "critical"
COST_DECIMALS = 2
PCT_DECIMALS = 1


def snapshot(con, limits_path=RATE_LIMITS_PATH, cost_path=COST_LOG_PATH):
    """대시보드 한 화면에 필요한 전부

    조회면서 usage_samples 에 한 줄 쌓는다 — 사이드카는 매번 덮어써서 %의 이력이
    어디에도 남지 않으므로, 추이를 그리려면 읽는 김에 적립하는 수밖에 없다.
    """
    limits = _read_json(limits_path)
    if isinstance(limits, dict):
        _record_sample(con, limits)
    else:
        limits = None
    stale_seconds = _stale_seconds(limits)
    return {
        "plan": _plan_label(),
        "windows": _windows(limits),
        "snapshot_ts": (limits or {}).get("timestamp"),
        "stale_seconds": stale_seconds,
        "stale": stale_seconds is None or stale_seconds > USAGE_STALE_SECONDS,
        "limit_source": limits_path,
        "missing_windows": list(MISSING_WINDOW_LABELS),
        "pct_samples": pct_samples(con),
        "tokens": daily_tokens(cost_path=cost_path),
    }


def pct_samples(con, hours=USAGE_SAMPLE_WINDOW_HOURS):
    """최근 구간의 % 추이. 버킷 대표값은 최댓값 — 한도 미터에서 중요한 건 얼마나 찼는지다"""
    floor_ms = _epoch_ms() - hours * MS_PER_HOUR
    rows = con.execute(
        "SELECT (source_ts / ?) * ? AS bucket_ts,"
        "       MAX(five_hour_pct) AS five_hour_pct,"
        "       MAX(seven_day_pct) AS seven_day_pct"
        "  FROM usage_samples WHERE source_ts >= ?"
        " GROUP BY bucket_ts ORDER BY bucket_ts",
        (USAGE_SAMPLE_BUCKET_MS, USAGE_SAMPLE_BUCKET_MS, floor_ms),
    ).fetchall()
    return [dict(row) for row in rows]


def daily_tokens(days=USAGE_TREND_DAYS, cost_path=COST_LOG_PATH):
    """일별 토큰·비용. 빈 날도 자리를 남겨 추이가 끊겨 보이지 않게 한다"""
    rows = _read_cost_log(cost_path)
    today = datetime.now().astimezone().date()
    start = today - timedelta(days=days - 1)
    buckets, families = {}, set()
    for row, delta in _deltas(rows):
        day = _local_date(row.get("timestamp"))
        if day is None or day < start or day > today:
            continue
        family = _model_family(row.get("model"))
        families.add(family)
        bucket = buckets.setdefault(day, _empty_bucket())
        total = sum(delta[field] for field in TOKEN_FIELDS)
        bucket["by_model"][family] = bucket["by_model"].get(family, 0) + total
        bucket[COST_FIELD] += delta[COST_FIELD]
        for field in TOKEN_FIELDS:
            bucket[field] += delta[field]
    return {
        "source": cost_path,
        "available": bool(rows),
        "models": _ordered_families(families),
        "days": [_day_row(start + timedelta(days=offset), buckets) for offset in range(days)],
    }


def _day_row(day, buckets):
    bucket = buckets.get(day) or _empty_bucket()
    return {
        "date": day.isoformat(),
        "by_model": bucket["by_model"],
        "total": sum(bucket["by_model"].values()),
        "cost_usd": round(bucket[COST_FIELD], COST_DECIMALS),
        "breakdown": {field: bucket[field] for field in TOKEN_FIELDS},
    }


def _empty_bucket():
    return {"by_model": {}, COST_FIELD: 0.0, **{field: 0 for field in TOKEN_FIELDS}}


def _deltas(rows):
    """(원본 행, 증분) 쌍. cost 로그는 (세션, 모델)별 누적치를 덧붙이므로 증분으로 되돌린다

    값이 줄어든 행은 그 키의 집계가 새로 시작한 것으로 보고 행의 값을 그대로 증분으로 쓴다.
    """
    previous = {}
    for row in sorted(rows, key=lambda item: item.get("timestamp") or ""):
        key = (row.get("session_id"), row.get("model"))
        last = previous.get(key)
        current = {field: row.get(field) or 0 for field in DELTA_FIELDS}
        if last is None:
            delta = dict(current)
        else:
            delta = {
                field: current[field] - last[field]
                if current[field] >= last[field]
                else current[field]
                for field in DELTA_FIELDS
            }
        previous[key] = current
        yield row, delta


def _windows(limits):
    """/usage 와 같은 창을 같은 순서로. 값이 없는 창은 빼고 넘긴다"""
    if not limits:
        return []
    rows = []
    for key, title in USAGE_WINDOWS:
        window = limits.get(key)
        if not isinstance(window, dict):
            continue
        pct = window.get("used_percentage")
        if not isinstance(pct, (int, float)):
            continue
        rows.append(
            {
                "key": key,
                "title": title,
                "used_percentage": round(float(pct), PCT_DECIMALS),
                "resets_at": window.get("resets_at"),
                "level": _level(pct),
            }
        )
    return rows


def _level(pct):
    if pct >= USAGE_CRITICAL_PCT:
        return LEVEL_CRITICAL
    if pct >= USAGE_WARN_PCT:
        return LEVEL_WARN
    return LEVEL_OK


def _record_sample(con, limits):
    """추이용 스냅샷 적립. 같은 스냅샷은 PK 가 막고, 1분 안쪽으로 촘촘한 건 건너뛴다"""
    stamp = limits.get("timestamp")
    if not isinstance(stamp, (int, float)):
        return
    stamp = int(stamp)
    latest = con.execute("SELECT MAX(source_ts) AS last FROM usage_samples").fetchone()["last"]
    if latest is not None and stamp - latest < USAGE_SAMPLE_MIN_GAP_MS:
        return
    five = limits.get("five_hour") or {}
    seven = limits.get("seven_day") or {}
    with transaction(con):
        con.execute(
            "INSERT OR IGNORE INTO usage_samples("
            " source_ts, five_hour_pct, five_hour_resets_at,"
            " seven_day_pct, seven_day_resets_at, created_at) VALUES(?,?,?,?,?,?)",
            (
                stamp,
                five.get("used_percentage"),
                five.get("resets_at"),
                seven.get("used_percentage"),
                seven.get("resets_at"),
                now(),
            ),
        )
        con.execute(
            "DELETE FROM usage_samples WHERE source_ts < ?",
            (stamp - USAGE_SAMPLE_RETENTION_DAYS * MS_PER_DAY,),
        )


def _plan_label():
    """플랜 이름만 뽑는다

    이 파일에는 액세스 토큰도 같이 들어 있다. 그래서 이 한 키만 꺼내고, 파일의 다른
    내용은 읽지도 반환하지도 않는다.
    """
    oauth = (_read_json(CREDENTIALS_PATH) or {}).get(OAUTH_KEY)
    tier = oauth.get(TIER_KEY) if isinstance(oauth, dict) else None
    if not isinstance(tier, str) or not tier:
        return None
    words = tier.removeprefix(CREDENTIALS_TIER_PREFIX).split("_")
    return " ".join(word[:1].upper() + word[1:] for word in words if word) or None


def _stale_seconds(limits):
    stamp = (limits or {}).get("timestamp")
    if not isinstance(stamp, (int, float)):
        return None
    return max(0, int((_epoch_ms() - stamp) / MS_PER_SECOND))


def _epoch_ms():
    return int(datetime.now(timezone.utc).timestamp() * MS_PER_SECOND)


def _model_family(model):
    text = (model or "").lower()
    for token, label in MODEL_FAMILIES:
        if token in text:
            return label
    return MODEL_FAMILY_OTHER


def _ordered_families(present):
    """색 슬롯이 흔들리지 않게 고정 순서로. 모델이 빠졌다 들어와도 같은 색을 유지한다"""
    names = [label for _, label in MODEL_FAMILIES] + [MODEL_FAMILY_OTHER]
    return [name for name in names if name in present]


def _local_date(text):
    """로그는 UTC(Z)로 적힌다. 사용자가 보는 하루 경계는 로컬이라 로컬 날짜로 버킷팅한다"""
    if not isinstance(text, str):
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone().date()
    except ValueError:
        return None


def _read_json(path):
    """없거나 깨졌으면 None. 사용량은 보조 정보라 대시보드를 막지 않는다"""
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def _read_cost_log(path):
    """줄 단위 JSON. 깨진 줄은 건너뛴다 — 다른 프로세스가 덧붙이는 중일 수 있다"""
    if not os.path.isfile(path):
        return []
    rows = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                rows.append(json.loads(stripped))
            except ValueError:
                continue
    return rows
