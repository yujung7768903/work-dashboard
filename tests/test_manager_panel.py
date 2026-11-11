"""매니저 탭 — crontab 해석, 매니저 점검 주기, 결정 대기(읽기 전용), 보조 세션"""
import json
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

import server
from app.errors import Validation
from app.repositories import autorun as autorun_repo
from app.services import cron, manager_panel
from tests.support import temp_db

KST = timezone(timedelta(hours=9))
# 수요일 저녁
NOW = datetime(2026, 11, 11, 19, 58, tzinfo=KST)

CRONTAB = """MAILTO=""
*/5 * * * * /usr/bin/python3 /home/u/.claude/scripts/resume-limited-jobs.py >/dev/null 2>&1
# Claude Code 스킬 동기화 (skill-sync) office
0 8,9,10 * * 1-5 /home/u/.claude/skills/skill-sync/pull.sh
0 9-20 * * 1-5 /home/u/.claude/skills/skill-sync/apply.sh
# Jira 자동화 파일럿
*/10 * * * * /usr/bin/python3 /home/u/work/jira-autopilot/autopilot.py tick >> /tmp/x/tick.log 2>&1
0 4 * * * cd /home/u/work/cost-monitor/backend && ./.venv/bin/python -m app.collect >> /tmp/x/c.log 2>&1
0 11 * * 1-5 /usr/bin/python3 /home/u/work/jira-autopilot/autopilot.py waitcheck >> /tmp/x/tick.log 2>&1

# delivery 버킷 만료 절감 확인
# sre-watch 로 이관 (checks/s3.sh): 0 11 * * * /home/u/x/check.sh >> /home/u/x/check.log 2>&1
# pcwatch — PC 느림 점검
*/15 * * * * cd /home/u/work/pcwatch && flock -n /tmp/p.lock /usr/bin/python3 /home/u/work/pcwatch/pcwatch.py fast >> scan.log 2>&1
7 * * * * cd /home/u/work/skill-prune && /usr/bin/python3 prune.py tick >> tick.log 2>&1
@reboot sleep 120 && cd /home/u/work/skill-prune && /usr/bin/python3 prune.py tick >> tick.log 2>&1
0 15 * * 3 /home/u/.claude/skills/weekly-report/auto.sh
"""


class CronTest(unittest.TestCase):
    def test_next_run_takes_earliest_slot_of_the_day(self):
        self.assertEqual(
            cron.next_run("10,20,30 10 * * *", NOW), datetime(2026, 11, 12, 10, 10, tzinfo=KST)
        )

    def test_weekday_only_skips_weekend(self):
        friday_night = datetime(2026, 11, 13, 22, 0, tzinfo=KST)
        self.assertEqual(
            cron.next_run("0 8 * * 1-5", friday_night), datetime(2026, 11, 16, 8, 0, tzinfo=KST)
        )

    def test_day_of_month_and_weekday_both_set_means_either(self):
        # 일·요일 칸이 둘 다 제한되면 둘 중 하나만 맞아도 돈다 (cron 규칙)
        self.assertEqual(
            cron.next_run("0 0 1 * 1", NOW), datetime(2026, 11, 16, 0, 0, tzinfo=KST)
        )

    def test_reboot_and_garbage_have_no_next_run(self):
        self.assertIsNone(cron.next_run("@reboot", NOW))
        self.assertIsNone(cron.next_run("ㄱ ㄴ", NOW))

    def test_describe_shapes(self):
        cases = {
            "*/5 * * * *": {
                "days": {"kind": "every"},
                "time": {"kind": "interval", "minutes": 5, "hours": None},
            },
            "*/10 8-20 * * 1-5": {
                "days": {"kind": "weekdays"},
                "time": {"kind": "interval", "minutes": 10, "hours": [8, 20]},
            },
            "0 9-20 * * 1-5": {
                "days": {"kind": "weekdays"},
                "time": {"kind": "hourly", "minute": 0, "hours": [9, 20]},
            },
            "0 15 * * 3": {
                "days": {"kind": "dow", "values": [3]},
                "time": {"kind": "at", "times": ["15:00"]},
            },
            "0 5 5 * *": {
                "days": {"kind": "dom", "values": [5]},
                "time": {"kind": "at", "times": ["05:00"]},
            },
            "@reboot": {"reboot": True},
            "nope": {"raw": "nope"},
        }
        for expr, expected in cases.items():
            with self.subTest(expr=expr):
                self.assertEqual(cron.describe(expr), expected)


class CrontabNameTest(unittest.TestCase):
    def setUp(self):
        self.entries = manager_panel.crontab_entries(CRONTAB)
        self.names = [entry["name"] for entry in self.entries]

    def test_env_and_commented_out_lines_are_not_entries(self):
        self.assertEqual(len(self.entries), 10)

    def test_comment_names_the_program_lines_below_it(self):
        self.assertIn("Claude Code 스킬 동기화 (skill-sync) office · pull", self.names)
        self.assertIn("Claude Code 스킬 동기화 (skill-sync) office · apply", self.names)

    def test_comment_follows_the_same_program_after_interruption(self):
        # 주석 아래 다른 프로그램(cost-monitor)이 끼어도 같은 프로그램 줄은 같은 이름
        self.assertIn("Jira 자동화 파일럿 · waitcheck", self.names)

    def test_comment_does_not_leak_to_other_programs(self):
        self.assertIn("pcwatch", self.names)
        self.assertIn("skill-prune · tick", self.names)
        self.assertIn("cost-monitor", self.names)

    def test_dash_splits_name_and_description(self):
        pcwatch = next(entry for entry in self.entries if entry["name"] == "pcwatch")
        self.assertEqual(pcwatch["desc"], "PC 느림 점검")

    def test_program_name_without_comment(self):
        self.assertIn("resume-limited-jobs", self.names)
        self.assertIn("weekly-report", self.names)

    def test_shared_log_is_not_attributed(self):
        tick = [entry for entry in self.entries if entry["key"] == "jira-autopilot"]
        self.assertTrue(tick and all(entry["log_shared"] for entry in tick))

    def test_relative_log_resolves_against_cd(self):
        pcwatch = next(entry for entry in self.entries if entry["name"] == "pcwatch")
        self.assertEqual(pcwatch["log"], "/home/u/work/pcwatch/scan.log")


class AutomationRowsTest(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()

    def _rows(self, text, con=None, now=NOW):
        return manager_panel.automations(now, crontab_text=text, manager_home=self.home, con=con)

    def _write(self, rel, text):
        path = os.path.join(self.home, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as handle:
            handle.write(text)
        return path

    def test_rows_are_sorted_by_next_run_and_reboot_goes_last(self):
        rows = self._rows(CRONTAB)
        nexts = [row["next_at"] for row in rows if row["next_at"]]
        self.assertEqual(nexts, sorted(nexts))
        self.assertIsNone(rows[-1]["next_at"])

    def test_failure_read_from_last_log_line(self):
        log = self._write("job.log", "시작\nTraceback (most recent call last):\n  File x\nValueError: 깨짐\n")
        rows = self._rows(f"0 4 * * * /x/work/job/run.py >> {log} 2>&1\n")
        self.assertEqual(rows[0]["last"]["status"], manager_panel.STATUS_FAIL)

    def test_clean_log_has_time_but_no_verdict(self):
        log = self._write("job.log", "끝\n")
        rows = self._rows(f"0 4 * * * /x/work/job/run.py >> {log} 2>&1\n")
        self.assertIsNotNone(rows[0]["last"]["at"])
        self.assertIsNone(rows[0]["last"]["status"])

    def test_autorun_tick_reads_dashboard_state(self):
        con = temp_db()
        autorun_repo.state(con)
        con.execute(
            "UPDATE autorun_state SET last_tick_at=?, last_tick_reason=?",
            ("2026-11-11T10:55:00+00:00", "할일 없음"),
        )
        con.commit()
        rows = self._rows(
            "*/5 * * * * /usr/bin/python3 /x/dash.py autorun-tick >/dev/null 2>&1\n", con
        )
        self.assertEqual(rows[0]["last"]["status"], manager_panel.STATUS_OK)
        self.assertEqual(rows[0]["last"]["detail"], "할일 없음")

    def test_sre_watch_runner_expands_to_checks(self):
        root = os.path.join(self.home, "sre-watch")
        self._write("sre-watch/run.py", "")
        self._write("sre-watch/checks/a.sh", "# type: effect\n# goal: 실패율 1% 미만 (기준선 7%)\n# every: 2\n")
        self._write("sre-watch/checks/old.sh", "# goal: 끝난 것\n# until: 2026-01-01\n")
        self._write(
            "sre-watch/results.jsonl",
            json.dumps({"id": "a", "at": "2026-11-11T11:30:00", "status": "fail", "value": "4%"}) + "\n",
        )
        rows = self._rows(f"30 11 * * * /usr/bin/python3 {root}/run.py run >> {root}/cron.log 2>&1\n")
        checks = [row for row in rows if row["source"] == "sre-watch"]
        self.assertEqual([row["name"] for row in checks], ["실패율 1% 미만"])
        self.assertEqual(checks[0]["last"]["status"], "fail")
        # every 2일 — 11일에 돌았으니 다음은 13일 러너 시각
        self.assertTrue(checks[0]["next_at"].startswith("2026-11-13T11:30"), checks[0]["next_at"])

    def _manager(self, status="working"):
        self._write("hooks/inbox_wake.py", "import os\nCHECK_SEC = 600\nCHECK_HOURS = (8, 20)\n")
        self._write("state/attendance.json", json.dumps({"status": status}))

    def test_manager_check_reads_hook_constants(self):
        self._manager()
        row = next(row for row in self._rows("") if row["source"] == "manager")
        self.assertEqual(row["cycle"]["time"], {"kind": "interval", "minutes": 10, "hours": [8, 20]})
        self.assertEqual(row["next_within_sec"], 600)
        self.assertFalse(row["off_duty"])

    def test_manager_check_within_window_sorts_by_its_interval(self):
        self._manager()
        rows = self._rows("*/30 * * * * /x/work/a/a.py\n0 4 * * * /x/work/b/b.py\n")
        # 19:58 기준 — 30분 주기(20:00)가 먼저, 10분 안의 점검, 새벽 4시 순
        self.assertEqual([row["source"] for row in rows], ["crontab", "manager", "crontab"])

    def test_manager_check_outside_window_points_to_next_window(self):
        self._manager()
        friday_night = datetime(2026, 11, 13, 22, 0, tzinfo=KST)
        rows = self._rows("", now=friday_night)
        self.assertTrue(rows[0]["next_at"].startswith("2026-11-16T08:00"), rows[0]["next_at"])

    def test_manager_off_duty_has_no_next(self):
        self._manager(status="off")
        row = self._rows("")[0]
        self.assertTrue(row["off_duty"])
        self.assertIsNone(row["next_at"])
        self.assertIsNone(row["next_within_sec"])

    def test_no_manager_no_check_row(self):
        self.assertEqual(self._rows(""), [])


class DecisionsTest(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.home, "state"))
        self.db = os.path.join(self.home, "state", "manager.db")
        con = sqlite3.connect(self.db)
        con.execute(
            "CREATE TABLE tasks (id INTEGER PRIMARY KEY, title TEXT, kind TEXT, detail TEXT,"
            " priority INTEGER, status TEXT, created_at TEXT, updated_at TEXT, hold_until TEXT)"
        )
        rows = [
            (1, "열린 결정", "decision", "고를 것\n둘째 줄", 2, "open", "2026-11-11T10:00:00", "2026-11-11T10:00:00", None),
            (2, "직접 할 일", "action", None, 3, "open", "2026-11-11T10:00:00", "2026-11-11T10:00:00", None),
            (3, "확인 대기", "action", None, 3, "confirm", "2026-11-10T10:00:00", "2026-11-11T12:00:00", None),
            (4, "닫힌 결정", "decision", None, 3, "done", "2026-11-10T10:00:00", "2026-11-11T12:00:00", None),
            (5, "미룬 결정", "decision", None, 1, "open", "2026-11-10T10:00:00", "2026-11-10T10:00:00", "2026-11-20T09:00:00"),
        ]
        con.executemany("INSERT INTO tasks VALUES (?,?,?,?,?,?,?,?,?)", rows)
        con.commit()
        con.close()

    def test_lists_open_decisions_and_confirm_waits_by_priority(self):
        items = manager_panel.decisions(NOW, manager_home=self.home)
        self.assertEqual([item["title"] for item in items], ["확인 대기", "열린 결정", "미룬 결정"])
        self.assertEqual([item["state"] for item in items], ["confirm", "decision", "decision"])
        self.assertEqual(items[1]["detail"], "고를 것")
        self.assertTrue(items[2]["held"])
        self.assertFalse(items[1]["held"])

    def test_reads_without_writing(self):
        before = os.path.getmtime(self.db)
        os.chmod(self.db, 0o444)
        self.addCleanup(os.chmod, self.db, 0o644)
        manager_panel.decisions(NOW, manager_home=self.home)
        self.assertEqual(os.path.getmtime(self.db), before)
        # 읽기 전용 연결은 저널·WAL 파일도 만들지 않는다
        self.assertEqual(os.listdir(os.path.dirname(self.db)), ["manager.db"])


class SnapshotTest(unittest.TestCase):
    def test_each_part_fails_alone(self):
        home = tempfile.mkdtemp()

        def broken(_home):
            raise RuntimeError("claude agents 응답 없음")

        payload = manager_panel.snapshot(now=NOW, crontab_text="", manager_home=home, helpers_fn=broken)
        self.assertIn("claude agents 응답 없음", payload["helpers"]["error"])
        self.assertIsNone(payload["automations"]["error"])
        self.assertIn("manager.db", payload["decisions"]["error"])

    def test_helpers_keep_manager_fields(self):
        rows = [{"name": "보조1 | 일", "status": "작업 중", "percent": 40, "percent_at": None,
                 "doing": "판정 중", "moved_at": "2026-11-11T19:50:00+09:00", "session_id": "s"}]
        payload = manager_panel.snapshot("helpers", now=NOW, helpers_fn=lambda _home: rows)
        item = payload["helpers"]["items"][0]
        self.assertEqual((item["doing"], item["percent"]), ("판정 중", 40))
        self.assertNotIn("session_id", item)

    def test_route_rejects_unknown_part(self):
        with self.assertRaises(Validation):
            server.route(temp_db(), "GET", "/api/manager", {"part": ["없는 칸"]}, {})


if __name__ == "__main__":
    unittest.main()
