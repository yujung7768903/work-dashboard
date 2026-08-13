"""사용량 집계. /usage 가 보여주는 한도 창과 일별 토큰 추이를 파일에서 읽어 모은다

한도 %는 Claude Code 가 statusline 페이로드로만 넘기는 값이다(훅 페이로드에는 rate_limits
가 없다). 그래서 `dash.py statusline` 이 그려질 때 record_limits() 로 사이드카에 떨어뜨려
두고 여기서는 그 파일만 읽는다. 값이 statusline 이 그려질 때만 갱신된다는 뜻이라, 세션이
조용한 동안 낡는 건 정상이다.

토큰 추이는 트랜스크립트(500MB) 대신 cost 로그(수백KB)에서 뽑는다. 요청마다 원본
트랜스크립트를 파싱하면 응답이 초 단위로 늘어진다.
"""
import json
import os
from datetime import datetime, timedelta, timezone

from app.constants import (
    CLAUDE_CONFIG_PATH,
    CONFIG_ACCOUNT_KEY,
    CONFIG_TIER_KEY,
    COST_FIELD,
    COST_LOG_PATH,
    CREDENTIALS_PATH,
    CREDENTIALS_TIER_PREFIX,
    RESET_MATCH_SECONDS,
    MISSING_WINDOW_LABELS,
    MODEL_FAMILIES,
    MODEL_FAMILY_OTHER,
    RATE_LIMITS_KEY,
    RATE_LIMITS_PATH,
    TOKEN_FIELDS,
    USAGE_CRITICAL_PCT,
    USAGE_SAMPLE_BUCKET_MS,
    USAGE_SAMPLE_MIN_GAP_MS,
    USAGE_SAMPLE_RETENTION_DAYS,
    USAGE_SAMPLE_WINDOW_HOURS,
    USAGE_STALE_SECONDS,
    USAGE_CACHE_KEY,
    USAGE_TRACK_MIN_SAMPLES,
    USAGE_TREND_DAYS,
    USAGE_WARN_PCT,
    USAGE_WEEK_LIMIT,
    USAGE_WINDOWS,
    WEEK_SECONDS,
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


def record_limits(raw, limits_path=RATE_LIMITS_PATH):
    """statusline 페이로드(JSON 한 덩어리)에서 한도 %만 떼어 사이드카에 남긴다

    한도 %가 실려오는 곳이 statusline 페이로드뿐이라, 상태줄이 그려질 때 주워두지 않으면
    화면에서는 영영 볼 수 없다. 페이로드에는 전사·경로 등 다른 값도 있으므로 rate_limits
    키 하나만 꺼낸다. 못 읽거나 그 키가 없으면 아무것도 쓰지 않고 False — 상태줄은 사용량
    때문에 깨지면 안 된다
    """
    try:
        payload = json.loads(raw or "")
    except ValueError:
        return False
    limits = payload.get(RATE_LIMITS_KEY) if isinstance(payload, dict) else None
    if not isinstance(limits, dict):
        return False
    body = {**limits, "timestamp": _epoch_ms(), "source": "statusline"}
    try:
        os.makedirs(os.path.dirname(limits_path) or ".", exist_ok=True)
        # 같은 파일을 화면이 동시에 읽는다. 덮어쓰는 중간 상태를 보이지 않게 rename 으로 바꾼다
        temp = f"{limits_path}.tmp"
        with open(temp, "w", encoding="utf-8") as handle:
            json.dump(body, handle)
        os.replace(temp, limits_path)
    except OSError:
        return False
    return True


def snapshot(
    con, limits_path=RATE_LIMITS_PATH, cost_path=COST_LOG_PATH, config_path=CLAUDE_CONFIG_PATH
):
    """대시보드 한 화면에 필요한 전부

    조회면서 usage_samples 에 한 줄 쌓는다 — 사이드카는 매번 덮어써서 %의 이력이
    어디에도 남지 않으므로, 추이를 그리려면 읽는 김에 적립하는 수밖에 없다.
    """
    limits = _read_json(limits_path)
    if isinstance(limits, dict):
        _record_sample(con, limits, config_path=config_path)
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
        "weekly": weekly_windows(con, cost_path=cost_path),
    }


def weekly_windows(con, cost_path=COST_LOG_PATH, limit=USAGE_WEEK_LIMIT):
    """닫힌 주간 창을 주차별로 모아 비교 가능한 형태로 돌려준다

    주간 %는 7일 내내 쌓이기만 하다 초기화되므로 시각 축에 올려두면 거의 평평한 선이
    된다. 의미가 있는 건 "이번 주차가 지난 주차보다 빨리 찼는지"라, 창 하나를 한 칸으로
    접어 세운다. 칸의 값은 그 주차가 초기화 직전에 도달한 최고치다.

    창은 resets_at 으로 가른다. 계정이 여럿이면 주간 창도 여럿이 동시에 도는데, 같은
    계정의 다음 창은 정확히 7일 뒤에 열리므로 resets_at 을 7일로 나눈 나머지가 계정별
    트랙이 된다.

    토큰은 트랙에 붙이지 않는다 — cost 로그에 계정 정보가 없어 계정별로 나눌 수 없고,
    같은 합계를 트랙마다 되풀이하면 계정별 사용량으로 오해된다. 대신 주 트랙의 경계로만
    잘라 token_weeks 로 한 번 내려보낸다. 그쪽은 %가 없는 지난 주차도 채우므로,
    한도 %를 모으기 시작하기 전의 과거도 토큰으로는 볼 수 있다.
    """
    current = _epoch_ms() // MS_PER_SECOND
    tracks = _pct_tracks(con, current, limit)
    events = _spend_events(cost_path)
    return {
        "tracks": tracks,
        "multi_account": len(tracks) > 1,
        # 주 경계는 %에서만 알 수 있다. 트랙이 없으면 어디서 주가 끊기는지도 모른다
        "token_weeks": _token_weeks(tracks, events, current, limit),
        "token_shared": len(tracks) > 1,
        "token_source": cost_path,
        "token_available": bool(events),
    }


def _pct_tracks(con, current, limit):
    """계정별 주차 %. 지금 쓰는 계정이 위로 온다 — 마지막 실측이 늦은 트랙이 앞"""
    rows = con.execute(
        "SELECT seven_day_resets_at AS reset_at,"
        "       MAX(seven_day_pct) AS peak_pct,"
        "       COUNT(*) AS samples,"
        "       MIN(source_ts) AS first_ts,"
        "       MAX(source_ts) AS last_ts,"
        # 한 주차에 이름표가 붙은 행과 안 붙은 행이 섞이면 붙은 쪽을 그 주차의 계정으로 본다
        "       MAX(account_uuid) AS account_uuid,"
        "       MAX(account_plan) AS account_plan"
        "  FROM usage_samples"
        " WHERE seven_day_resets_at IS NOT NULL AND seven_day_pct IS NOT NULL"
        " GROUP BY seven_day_resets_at ORDER BY seven_day_resets_at",
    ).fetchall()
    key_of = _track_key(rows)
    tracks, plans = {}, {}
    for row in rows:
        track = key_of(row)
        tracks.setdefault(track, []).append(_week_row(row, current))
        # reset_at 오름차순이라 늦은 주차의 플랜이 이긴다 — 플랜은 바뀔 수 있다
        if row["account_plan"]:
            plans[track] = row["account_plan"]
    return sorted(
        (
            {"track": str(track), "plan": plans.get(track), "weeks": weeks[-limit:]}
            for track, weeks in tracks.items()
            if sum(week["samples"] for week in weeks) >= USAGE_TRACK_MIN_SAMPLES
        ),
        key=lambda item: item["weeks"][-1]["last_ts"],
        reverse=True,
    )


def _track_key(rows):
    """주차 그룹 → 트랙 키

    uuid 가 붙어 있으면 그게 계정이다. 없으면 초기화 시각의 7일 나머지로 대신한다 —
    같은 계정의 다음 창은 정확히 7일 뒤에 열리므로 나머지가 계정 구실을 한다. 다만
    두 계정의 초기화가 같은 요일·시각에 걸리면 나머지는 둘을 못 가르므로, uuid 를
    받은 뒤에는 그쪽이 이긴다.

    uuid 를 받기 전에 쌓인 주차는 나머지를 열쇠로 uuid 쪽에 이어 붙인다. 그러지 않으면
    한 계정이 "uuid 트랙"과 "나머지 트랙" 둘로 갈라져 보인다.
    """
    known = {}
    for row in rows:
        if row["account_uuid"]:
            known[int(row["reset_at"]) % WEEK_SECONDS] = row["account_uuid"]

    def key(row):
        remainder = int(row["reset_at"]) % WEEK_SECONDS
        return row["account_uuid"] or known.get(remainder) or remainder

    return key


def _week_row(row, current):
    """주차 한 칸. 기간은 초기화 시각에서 7일을 되짚어 잡는다"""
    reset_at = int(row["reset_at"])
    return {
        "reset_at": reset_at,
        "starts_at": reset_at - WEEK_SECONDS,
        "peak_pct": round(float(row["peak_pct"]), PCT_DECIMALS),
        "samples": row["samples"],
        "first_ts": row["first_ts"],
        "last_ts": row["last_ts"],
        "in_progress": reset_at > current,
    }


def _token_weeks(tracks, events, current, limit):
    """주 트랙의 초기화 시각을 기준으로 7일씩 되짚어 자른 토큰·비용

    로그가 시작된 주차까지 채운다. %는 소급되지 않지만 토큰은 로그에 남아 있어,
    한도 %를 모으기 전의 주차도 여기서는 값이 나온다.
    """
    if not tracks or not events:
        return []
    oldest = min(event[0] for event in events)
    weeks = []
    reset_at = tracks[0]["weeks"][-1]["reset_at"]
    while len(weeks) < limit:
        starts_at = reset_at - WEEK_SECONDS
        spent = [event for event in events if starts_at <= event[0] < reset_at]
        # 값이 없는 주차도 자리를 남긴다 — 일별 토큰과 같은 규칙
        weeks.append(
            {
                "reset_at": reset_at,
                "starts_at": starts_at,
                "tokens": sum(event[1] for event in spent),
                "cost_usd": round(sum(event[2] for event in spent), COST_DECIMALS),
                "in_progress": reset_at > current,
            }
        )
        if starts_at <= oldest:
            break
        reset_at = starts_at
    return list(reversed(weeks))


def _spend_events(cost_path):
    """(초 단위 epoch, 토큰 합, 비용). 주 경계로 자르는 데 필요한 최소 형태만 남긴다"""
    events = []
    for row, delta in _deltas(_read_cost_log(cost_path)):
        stamp = _parse_stamp(row.get("timestamp"))
        if stamp is None:
            continue
        events.append(
            (int(stamp.timestamp()), sum(delta[field] for field in TOKEN_FIELDS), delta[COST_FIELD])
        )
    return events


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


def _record_sample(con, limits, config_path=CLAUDE_CONFIG_PATH):
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
            " seven_day_pct, seven_day_resets_at, account_uuid, account_plan, created_at)"
            " VALUES(?,?,?,?,?,?,?,?)",
            (
                stamp,
                five.get("used_percentage"),
                five.get("resets_at"),
                seven.get("used_percentage"),
                seven.get("resets_at"),
                *_account_of(limits, config_path),
                now(),
            ),
        )
        con.execute(
            "DELETE FROM usage_samples WHERE source_ts < ?",
            (stamp - USAGE_SAMPLE_RETENTION_DAYS * MS_PER_DAY,),
        )


def _account_of(limits, config_path=CLAUDE_CONFIG_PATH):
    """사이드카가 지금 담고 있는 창의 (계정 uuid, 플랜). 가릴 수 없으면 (None, None)

    사이드카는 계정을 가리지 않고 마지막에 그려진 statusline 이 덮는다. 그래서 지금
    로그인한 계정의 이름표를 무조건 붙이면 남의 계정 값에 엉뚱한 표를 다는 셈이 된다.
    두 소스의 초기화 시각이 같은 창을 가리킬 때만 붙인다.

    이 파일에는 계정 설정 전부가 들어 있다. 필요한 키만 꺼내고 나머지는 손대지 않는다.
    """
    config = _read_json(config_path) or {}
    cache = config.get(USAGE_CACHE_KEY)
    if not isinstance(cache, dict):
        return None, None
    uuid = cache.get("accountUuid")
    windows = cache.get("utilization")
    if not isinstance(uuid, str) or not uuid or not isinstance(windows, dict):
        return None, None
    if not _same_window(limits, windows):
        return None, None
    return uuid, _plan_of(config, uuid)


def _same_window(limits, windows):
    """사이드카와 설정 캐시가 같은 한도 창을 가리키는지"""
    for key, _ in USAGE_WINDOWS:
        cached = _parse_stamp((windows.get(key) or {}).get("resets_at"))
        ours = (limits.get(key) or {}).get("resets_at")
        if cached is None or not isinstance(ours, (int, float)):
            continue
        if abs(int(ours) - int(cached.timestamp())) <= RESET_MATCH_SECONDS:
            return True
    return False


def _plan_of(config, uuid):
    """계정 블록의 플랜. 사용량 캐시와 계정이 어긋나면(캐시가 낡음) 붙이지 않는다"""
    account = config.get(CONFIG_ACCOUNT_KEY)
    if not isinstance(account, dict) or account.get("accountUuid") != uuid:
        return None
    return _tier_label(account.get(CONFIG_TIER_KEY))


def _plan_label():
    """플랜 이름만 뽑는다

    ~/.claude.json 의 계정 블록을 먼저 본다. 예전에는 .credentials.json 에 있었는데
    로그인 방식에 따라 그 키가 사라지므로(키체인으로 옮겨감) 양쪽을 다 본다.

    두 파일 모두 액세스 토큰·이메일이 같이 들어 있다. 그래서 티어 키 하나만 꺼내고,
    파일의 다른 내용은 읽지도 반환하지도 않는다.
    """
    for path, holder, key in (
        (CLAUDE_CONFIG_PATH, CONFIG_ACCOUNT_KEY, CONFIG_TIER_KEY),
        (CREDENTIALS_PATH, OAUTH_KEY, TIER_KEY),
    ):
        block = (_read_json(path) or {}).get(holder)
        label = _tier_label(block.get(key) if isinstance(block, dict) else None)
        if label:
            return label
    return None


def _tier_label(tier):
    """default_claude_max_5x → Max 5x"""
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
    stamp = _parse_stamp(text)
    return None if stamp is None else stamp.astimezone().date()


def _parse_stamp(text):
    """ISO8601(Z 표기 포함) → tz 를 가진 datetime. 못 읽으면 None"""
    if not isinstance(text, str):
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
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
