"""사용량 집계. 실제 ~/.claude 를 읽지 않고 합성 파일 경로를 넣어 검증한다"""
import json
import os
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone

from app.constants import USAGE_SAMPLE_MIN_GAP_MS, USAGE_TREND_DAYS
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


if __name__ == "__main__":
    unittest.main()
