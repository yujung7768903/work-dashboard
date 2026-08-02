"""사용량 집계. 실제 ~/.claude 를 읽지 않고 합성 파일 경로를 넣어 검증한다"""
import json
import os
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone

from app.constants import USAGE_SAMPLE_MIN_GAP_MS, USAGE_TREND_DAYS, WEEK_SECONDS
from app.services import usage
from tests.support import temp_db

MS = 1000


def _write(path, payload):
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(payload)
    return path


def _limits_file(five=35.0, seven=47.0, stamp=None):
    stamp = stamp if stamp is not None else int(time.time() * MS)
    body = {
        "five_hour": {"used_percentage": five, "resets_at": int(time.time()) + 600},
        "seven_day": {"used_percentage": seven, "resets_at": int(time.time()) + 86400},
        "timestamp": stamp,
        "source": "statusline",
    }
    return _write(os.path.join(tempfile.mkdtemp(), "rate-limits.json"), json.dumps(body))


def _cost_file(rows):
    lines = "\n".join(json.dumps(row) for row in rows)
    return _write(os.path.join(tempfile.mkdtemp(), "costs.jsonl"), lines + "\n")


def _cost_row(stamp, session="s1", model="claude-opus-5", **totals):
    row = {"timestamp": stamp, "session_id": session, "model": model}
    row.update({field: 0 for field in usage.DELTA_FIELDS})
    row.update(totals)
    return row


def _today_stamp(hour=1):
    moment = datetime.now().astimezone().replace(hour=hour, minute=0, second=0, microsecond=0)
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class WindowTest(unittest.TestCase):
    def test_windows_follow_usage_order_with_levels(self):
        con = temp_db()
        payload = usage.snapshot(
            con, limits_path=_limits_file(five=95.0, seven=75.0), cost_path=_cost_file([])
        )
        keys = [window["key"] for window in payload["windows"]]
        self.assertEqual(keys, ["five_hour", "seven_day"])
        self.assertEqual(payload["windows"][0]["level"], usage.LEVEL_CRITICAL)
        self.assertEqual(payload["windows"][1]["level"], usage.LEVEL_WARN)

    def test_missing_sidecar_does_not_break_snapshot(self):
        con = temp_db()
        payload = usage.snapshot(
            con, limits_path="/nonexistent/rate-limits.json", cost_path=_cost_file([])
        )
        self.assertEqual(payload["windows"], [])
        self.assertTrue(payload["stale"])

    def test_old_snapshot_is_marked_stale(self):
        con = temp_db()
        old = int((time.time() - 3600) * MS)
        payload = usage.snapshot(
            con, limits_path=_limits_file(stamp=old), cost_path=_cost_file([])
        )
        self.assertTrue(payload["stale"])
        self.assertGreater(payload["stale_seconds"], 3000)


class SampleTest(unittest.TestCase):
    def test_same_snapshot_is_not_stored_twice(self):
        con = temp_db()
        limits = _limits_file(stamp=int(time.time() * MS))
        usage.snapshot(con, limits_path=limits, cost_path=_cost_file([]))
        usage.snapshot(con, limits_path=limits, cost_path=_cost_file([]))
        stored = con.execute("SELECT COUNT(*) AS n FROM usage_samples").fetchone()["n"]
        self.assertEqual(stored, 1)

    def test_snapshot_within_min_gap_is_skipped(self):
        con = temp_db()
        base = int(time.time() * MS)
        usage.snapshot(con, limits_path=_limits_file(stamp=base), cost_path=_cost_file([]))
        near = base + USAGE_SAMPLE_MIN_GAP_MS - 1
        usage.snapshot(con, limits_path=_limits_file(stamp=near), cost_path=_cost_file([]))
        far = base + USAGE_SAMPLE_MIN_GAP_MS
        usage.snapshot(con, limits_path=_limits_file(stamp=far), cost_path=_cost_file([]))
        stamps = [
            row["source_ts"]
            for row in con.execute("SELECT source_ts FROM usage_samples ORDER BY source_ts")
        ]
        self.assertEqual(stamps, [base, far])


class DailyTokenTest(unittest.TestCase):
    def test_cumulative_rows_become_daily_increments(self):
        """cost 로그는 세션별 누적치라, 그대로 더하면 하루 사용량이 몇 배로 뛴다"""
        stamp = _today_stamp()
        rows = [
            _cost_row(stamp, output_tokens=100, estimated_cost_usd=1.0),
            _cost_row(stamp, output_tokens=250, estimated_cost_usd=2.5),
        ]
        result = usage.daily_tokens(cost_path=_cost_file(rows))
        today = result["days"][-1]
        self.assertEqual(today["total"], 250)
        self.assertEqual(today["cost_usd"], 2.5)

    def test_separate_sessions_are_summed(self):
        stamp = _today_stamp()
        rows = [
            _cost_row(stamp, session="a", output_tokens=100),
            _cost_row(stamp, session="b", output_tokens=40),
        ]
        result = usage.daily_tokens(cost_path=_cost_file(rows))
        self.assertEqual(result["days"][-1]["total"], 140)

    def test_shrinking_value_is_treated_as_a_fresh_start(self):
        rows = [
            _cost_row(_today_stamp(), output_tokens=500),
            _cost_row(_today_stamp(hour=2), output_tokens=30),
        ]
        result = usage.daily_tokens(cost_path=_cost_file(rows))
        self.assertEqual(result["days"][-1]["total"], 530)

    def test_model_families_keep_a_fixed_order(self):
        stamp = _today_stamp()
        rows = [
            _cost_row(stamp, session="h", model="claude-haiku-4-5-20251001", output_tokens=5),
            _cost_row(stamp, session="o", model="claude-opus-5", output_tokens=5),
        ]
        result = usage.daily_tokens(cost_path=_cost_file(rows))
        self.assertEqual(result["models"], ["Opus", "Haiku"])

    def test_days_are_dense_and_bounded(self):
        old = (datetime.now().astimezone() - timedelta(days=90)).astimezone(timezone.utc)
        rows = [_cost_row(old.isoformat().replace("+00:00", "Z"), output_tokens=999)]
        result = usage.daily_tokens(cost_path=_cost_file(rows))
        self.assertEqual(len(result["days"]), USAGE_TREND_DAYS)
        self.assertEqual(sum(day["total"] for day in result["days"]), 0)

    def test_missing_cost_log_reports_unavailable(self):
        result = usage.daily_tokens(cost_path="/nonexistent/costs.jsonl")
        self.assertFalse(result["available"])
        self.assertEqual(len(result["days"]), USAGE_TREND_DAYS)

    def test_broken_line_is_skipped(self):
        path = _write(
            os.path.join(tempfile.mkdtemp(), "costs.jsonl"),
            json.dumps(_cost_row(_today_stamp(), output_tokens=7)) + "\n{ not json\n",
        )
        result = usage.daily_tokens(cost_path=path)
        self.assertEqual(result["days"][-1]["total"], 7)


def _sample(con, source_ts, seven_pct, seven_reset):
    con.execute(
        "INSERT INTO usage_samples(source_ts, seven_day_pct, seven_day_resets_at, created_at)"
        " VALUES(?,?,?,?)",
        (source_ts, seven_pct, seven_reset, "2026-08-01T00:00:00+00:00"),
    )
    con.commit()


class WeeklyWindowTest(unittest.TestCase):
    """주차 비교. 계정이 여럿이면 주간 창도 여럿이 동시에 돈다"""

    def test_same_account_windows_land_in_one_track(self):
        con = temp_db()
        reset = int(time.time()) + 3600
        _sample(con, 1, 40.0, reset - WEEK_SECONDS)  # 지난 주차
        _sample(con, 2, 41.0, reset - WEEK_SECONDS)
        _sample(con, 3, 42.0, reset - WEEK_SECONDS)
        _sample(con, 4, 12.0, reset)  # 이번 주차
        _sample(con, 5, 15.0, reset)
        _sample(con, 6, 13.0, reset)
        result = usage.weekly_windows(con)
        self.assertEqual(len(result["tracks"]), 1)
        self.assertFalse(result["multi_account"])
        weeks = result["tracks"][0]["weeks"]
        self.assertEqual([week["peak_pct"] for week in weeks], [42.0, 15.0])
        self.assertEqual([week["in_progress"] for week in weeks], [False, True])

    def test_windows_off_the_seven_day_grid_are_separate_accounts(self):
        con = temp_db()
        reset = int(time.time()) + 3600
        for offset in range(3):
            _sample(con, 10 + offset, 40.0, reset)
            _sample(con, 20 + offset, 70.0, reset + 40 * 3600)  # 7일 배수가 아닌 경계
        result = usage.weekly_windows(con)
        self.assertEqual(len(result["tracks"]), 2)
        self.assertTrue(result["multi_account"])

    def test_track_below_sample_floor_is_dropped(self):
        con = temp_db()
        reset = int(time.time()) + 3600
        for offset in range(3):
            _sample(con, 10 + offset, 40.0, reset)
        _sample(con, 99, 43.0, reset + 17321)  # 정시가 아닌 한 줄짜리 잔여 기록
        result = usage.weekly_windows(con)
        self.assertEqual(len(result["tracks"]), 1)
        self.assertFalse(result["multi_account"])

    def test_tokens_are_not_attached_to_tracks(self):
        """cost 로그에는 계정이 없다. 트랙마다 같은 합계를 붙이면 계정별 사용량으로 읽힌다"""
        con = temp_db()
        reset = int(time.time()) + 3600
        for offset in range(3):
            _sample(con, 10 + offset, 40.0, reset)
            _sample(con, 20 + offset, 70.0, reset + 40 * 3600)
        result = usage.weekly_windows(con)
        for track in result["tracks"]:
            for week in track["weeks"]:
                self.assertNotIn("tokens", week)

    def test_no_samples_means_no_track(self):
        con = temp_db()
        self.assertEqual(usage.weekly_windows(con)["tracks"], [])


def _stamp_at(epoch_seconds):
    return datetime.fromtimestamp(epoch_seconds, timezone.utc).isoformat().replace("+00:00", "Z")


def _config_file(uuid="acc-1", five_reset=None, seven_reset=None, tier="default_claude_max_5x"):
    """~/.claude.json 흉내. 사용량 키 옆에 민감한 키를 같이 두어 그것까지 읽지 않는지 본다"""
    body = {
        "primaryApiKey": "건드리면 안 되는 값",
        "oauthAccount": {
            "accountUuid": uuid,
            "userRateLimitTier": tier,
            "seatTier": "team_tier_1",  # 좌석 등급. 한도 티어가 아니라 이걸 읽으면 안 된다
            "emailAddress": "건드리면 안 되는 값",
        },
        "cachedUsageUtilization": {
            "fetchedAtMs": int(time.time() * MS),
            "accountUuid": uuid,
            "utilization": {
                "five_hour": {"utilization": 10, "resets_at": _stamp_at(five_reset)}
                if five_reset
                else None,
                "seven_day": {"utilization": 69, "resets_at": _stamp_at(seven_reset)}
                if seven_reset
                else None,
                "seven_day_opus": None,
            },
        },
    }
    return _write(os.path.join(tempfile.mkdtemp(), ".claude.json"), json.dumps(body))


class AccountMatchTest(unittest.TestCase):
    """사이드카는 어느 계정이든 마지막에 그려진 statusline 이 덮는다 — 창이 맞을 때만 이름표를 단다"""

    def _stored_uuid(self, limits_path, config_path):
        con = temp_db()
        usage.snapshot(
            con, limits_path=limits_path, cost_path=_cost_file([]), config_path=config_path
        )
        return con.execute("SELECT account_uuid FROM usage_samples").fetchone()["account_uuid"]

    def test_uuid_is_attached_when_the_window_matches(self):
        limits = _limits_file()
        ours = usage._read_json(limits)["seven_day"]["resets_at"]
        self.assertEqual(self._stored_uuid(limits, _config_file(seven_reset=ours)), "acc-1")

    def test_one_second_skew_still_counts_as_the_same_window(self):
        """한쪽은 :59.66 을, 다른 쪽은 정시로 반올림한 값을 준다"""
        limits = _limits_file()
        ours = usage._read_json(limits)["seven_day"]["resets_at"]
        self.assertEqual(self._stored_uuid(limits, _config_file(seven_reset=ours - 1)), "acc-1")

    def test_other_account_snapshot_gets_no_label(self):
        limits = _limits_file()
        ours = usage._read_json(limits)["seven_day"]["resets_at"]
        # 사이드카에 남은 창이 이 계정의 창과 다르면 붙이지 않는다
        self.assertIsNone(self._stored_uuid(limits, _config_file(seven_reset=ours + 40 * 3600)))

    def test_missing_config_is_not_fatal(self):
        limits = _limits_file()
        self.assertIsNone(self._stored_uuid(limits, "/nonexistent/.claude.json"))

    def test_plan_rides_along_with_the_uuid(self):
        limits = _limits_file()
        ours = usage._read_json(limits)["seven_day"]["resets_at"]
        con = temp_db()
        usage.snapshot(
            con,
            limits_path=limits,
            cost_path=_cost_file([]),
            config_path=_config_file(seven_reset=ours),
        )
        row = con.execute("SELECT account_plan FROM usage_samples").fetchone()
        self.assertEqual(row["account_plan"], "Max 5x")

    def test_plan_is_dropped_when_the_usage_cache_names_another_account(self):
        """캐시가 낡아 계정 블록과 어긋나면 남의 플랜을 붙이게 된다"""
        limits = _limits_file()
        ours = usage._read_json(limits)["seven_day"]["resets_at"]
        path = _config_file(seven_reset=ours)
        body = json.loads(open(path, encoding="utf-8").read())
        body["cachedUsageUtilization"]["accountUuid"] = "acc-2"  # 계정 블록은 그대로 acc-1
        _write(path, json.dumps(body))
        con = temp_db()
        usage.snapshot(con, limits_path=limits, cost_path=_cost_file([]), config_path=path)
        row = con.execute("SELECT account_uuid, account_plan FROM usage_samples").fetchone()
        self.assertEqual(row["account_uuid"], "acc-2")  # 창은 맞으니 계정은 기록하고
        self.assertIsNone(row["account_plan"])  # 플랜은 어느 계정 것인지 못 가려 비운다

    def test_track_carries_the_plan(self):
        con = temp_db()
        reset = int(time.time()) + 3600
        for offset in range(3):
            _sample(con, 10 + offset, 40.0, reset)
        con.execute("UPDATE usage_samples SET account_uuid='a', account_plan='Max 5x'")
        con.commit()
        result = usage.weekly_windows(con)
        self.assertEqual(result["tracks"][0]["plan"], "Max 5x")

    def test_track_without_a_known_plan_reports_none(self):
        con = temp_db()
        reset = int(time.time()) + 3600
        for offset in range(3):
            _sample(con, 10 + offset, 40.0, reset)
        result = usage.weekly_windows(con)
        self.assertIsNone(result["tracks"][0]["plan"])


class PlanLabelTest(unittest.TestCase):
    def test_tier_becomes_a_readable_label(self):
        self.assertEqual(usage._tier_label("default_claude_max_5x"), "Max 5x")
        self.assertEqual(usage._tier_label("default_claude_pro"), "Pro")
        self.assertIsNone(usage._tier_label(""))
        self.assertIsNone(usage._tier_label(None))

    def test_uuid_beats_the_reset_remainder_when_they_disagree(self):
        """두 계정의 초기화가 같은 요일·시각에 걸리면 나머지는 둘을 못 가른다"""
        con = temp_db()
        reset = int(time.time()) + 3600
        for offset in range(3):
            _sample(con, 10 + offset, 40.0, reset)
            con.execute("UPDATE usage_samples SET account_uuid=? WHERE source_ts=?", ("a", 10 + offset))
            # 정확히 7일 뒤 — 나머지가 같아 예전 방식으로는 같은 트랙이 된다
            _sample(con, 20 + offset, 70.0, reset + WEEK_SECONDS)
            con.execute("UPDATE usage_samples SET account_uuid=? WHERE source_ts=?", ("b", 20 + offset))
        con.commit()
        result = usage.weekly_windows(con)
        self.assertEqual(len(result["tracks"]), 2)
        self.assertTrue(result["multi_account"])

    def test_weeks_recorded_before_the_uuid_column_join_that_account(self):
        con = temp_db()
        reset = int(time.time()) + 3600
        for offset in range(3):
            _sample(con, 10 + offset, 40.0, reset - WEEK_SECONDS)  # uuid 없던 시절
            _sample(con, 20 + offset, 70.0, reset)
            con.execute("UPDATE usage_samples SET account_uuid=? WHERE source_ts=?", ("a", 20 + offset))
        con.commit()
        result = usage.weekly_windows(con)
        self.assertEqual(len(result["tracks"]), 1)  # 갈라지지 않고 한 계정으로
        self.assertEqual(len(result["tracks"][0]["weeks"]), 2)


if __name__ == "__main__":
    unittest.main()
