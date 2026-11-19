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
            "0 */2 * * *": {
                "days": {"kind": "every"},
                "time": {"kind": "interval", "every_hours": 2, "hours": None},
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


class DescriptionTest(unittest.TestCase):
    """crontab 주석에 '— 설명' 이 없으면 실행하는 스크립트 머리에서 읽는다. 둘 다 없으면 None"""

    def setUp(self):
        self.home = tempfile.mkdtemp()

    def _write(self, rel, text):
        path = os.path.join(self.home, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as handle:
            handle.write(text)
        return path

    def _row(self, line):
        rows = manager_panel.automations(NOW, crontab_text=line + "\n", manager_home=self.home)
        return rows[0]

    def test_crontab_comment_wins(self):
        script = self._write("work/a/a.py", '"""스크립트 설명."""\n')
        row = self._row(f"# 이름 — 주석 설명\n0 4 * * * /usr/bin/python3 {script}")
        self.assertEqual((row["desc"], row["desc_from"]), ("주석 설명", "crontab"))

    def test_python_docstring_first_paragraph(self):
        script = self._write(
            "work/crumble/crumble.py",
            '"""크럼블 — 메모장의 요청 줄을 처리한다.\n\n10분 크론으로 돈다."""\nimport os\n',
        )
        row = self._row(f"*/10 * * * * cd {self.home}/work/crumble && /usr/bin/flock -n x.lock /usr/bin/python3 crumble.py >> c.log 2>&1")
        self.assertEqual((row["desc"], row["desc_from"]), ("크럼블 — 메모장의 요청 줄을 처리한다.", "script"))

    def test_shell_head_comment_skips_shebang(self):
        script = self._write("bin/sync.sh", "#!/bin/bash\n# 볼트 동기화: pull 후 push.\nset -u\n")
        self.assertEqual(self._row(f"*/30 * * * * {script}")["desc"], "볼트 동기화: pull 후 push.")

    def test_long_paragraph_is_cut_at_sentence(self):
        long = "둘째 문장은 길다 " * 20
        script = self._write("bin/x.sh", f"#!/bin/bash\n# 첫 문장.\n# {long}.\n")
        self.assertEqual(self._row(f"0 1 * * * {script}")["desc"], "첫 문장.")

    def test_subcommand_argparse_help(self):
        script = self._write(
            "work/dash/dash.py",
            '"""대시보드 CLI"""\nsub.add_parser("autorun-tick", help="자율 실행 판정 (5분 크론)")\n',
        )
        row = self._row(f"*/5 * * * * /usr/bin/python3 {script} autorun-tick >/dev/null 2>&1")
        self.assertEqual(row["desc"], "자율 실행 판정 (5분 크론)")

    def test_subcommand_docstring_table(self):
        script = self._write(
            "work/pcwatch/pcwatch.py",
            '"""PC 점검.\n\n  fast   (15분) 과점유 프로세스\n  daily  (하루 1회) 디스크\n"""\n',
        )
        self.assertEqual(self._row(f"0 12 * * * /usr/bin/python3 {script} daily")["desc"], "(하루 1회) 디스크")
        # 표에 없는 하위 명령은 머리 첫 문단으로
        self.assertEqual(self._row(f"0 12 * * * /usr/bin/python3 {script} report")["desc"], "PC 점검.")

    def test_module_run_resolves_against_cd(self):
        self._write("work/cost/backend/app/collect.py", '"""수집 배치."""\n')
        row = self._row(f"0 4 * * * cd {self.home}/work/cost/backend && ./.venv/bin/python -m app.collect >> l.log 2>&1")
        self.assertEqual(row["desc"], "수집 배치.")

    def test_no_description_anywhere_is_none(self):
        script = self._write("bin/bare.sh", "#!/bin/bash\necho hi\n")
        row = self._row(f"0 1 * * * {script}")
        self.assertIsNone(row["desc"])
        self.assertIsNone(row["desc_from"])

    def test_missing_script_is_none(self):
        self.assertIsNone(self._row("0 1 * * * /nowhere/gone.py")["desc"])

    def test_head_line_repeating_the_name_is_not_a_description(self):
        script = self._write("work/jira-autopilot/autopilot.py", '"""Jira 자동화 파일럿.\n\n본문."""\n')
        row = self._row(f"# Jira 자동화 파일럿\n0 11 * * * /usr/bin/python3 {script} waitcheck")
        self.assertIsNone(row["desc"])

    def test_sre_check_description_from_free_comment(self):
        root = os.path.join(self.home, "sre-watch")
        self._write("sre-watch/run.py", "")
        self._write("sre-watch/checks/a.sh", "# type: effect\n# goal: 실패율 1% 미만\n# every: 1\n# 훅 24개 제거 효과.\npython3 -\n")
        rows = manager_panel.automations(
            NOW, crontab_text=f"30 11 * * * /usr/bin/python3 {root}/run.py run\n", manager_home=self.home
        )
        check = next(row for row in rows if row["source"] == "sre-watch")
        self.assertEqual(check["desc"], "훅 24개 제거 효과.")


class PrereqWaitsTest(unittest.TestCase):
    """선행 대기 — 다른 매니저 할일이 끝나야 할 수 있는 할일(after_ids)은 결정 대기가 아니라 따로 보인다"""

    def setUp(self):
        self.home = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.home, "state"))
        self.db = os.path.join(self.home, "state", "manager.db")
        con = sqlite3.connect(self.db)
        con.execute(
            "CREATE TABLE tasks (id INTEGER PRIMARY KEY, title TEXT, kind TEXT, detail TEXT, priority INTEGER,"
            " status TEXT, created_at TEXT, updated_at TEXT, next_step TEXT, after_ids TEXT)"
        )
        stamp = "2026-11-11T10:00:00"
        rows = [
            (9, "문의 자동화에 KT 로그 붙이기", "action", 3, "open", "168,169"),
            (168, "KT 서버 로그 경로", "action", 2, "open", None),
            (169, "KT 로그 Lambda 배포", "action", 2, "confirm", None),
            (20, "선행 남은 결정", "decision", 2, "open", "168"),
            (21, "선행 끝난 결정", "decision", 2, "open", "22"),
            (22, "끝난 선행", "action", 2, "done", None),
        ]
        con.executemany(
            "INSERT INTO tasks (id, title, kind, priority, status, after_ids, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?)",
            [(*row, stamp, stamp) for row in rows],
        )
        con.commit()
        con.close()

    def test_waits_lists_open_tasks_with_unfinished_prereqs(self):
        items = manager_panel.waits(NOW, manager_home=self.home)
        self.assertEqual([item["id"] for item in items], [9, 20])
        self.assertEqual({item["state"] for item in items}, {"prereq"})
        prereqs = items[0]["prereqs"]
        self.assertEqual([(p["id"], p["title"], p["status"], p["finished"]) for p in prereqs],
                         [(168, "KT 서버 로그 경로", "open", False), (169, "KT 로그 Lambda 배포", "confirm", False)])

    def test_decisions_exclude_prereq_waiting(self):
        items = manager_panel.decisions(NOW, manager_home=self.home)
        self.assertEqual([item["id"] for item in items], [21])
        self.assertEqual(items[0]["state"], "decision")
        self.assertTrue(items[0]["prereqs"][0]["finished"])

    def test_task_item_any_status(self):
        self.assertEqual(manager_panel.task_item(168, NOW, manager_home=self.home)["state"], "action")
        self.assertEqual(manager_panel.task_item(169, NOW, manager_home=self.home)["state"], "confirm")
        self.assertEqual(manager_panel.task_item(22, NOW, manager_home=self.home)["state"], "closed")
        self.assertEqual(manager_panel.task_item(9, NOW, manager_home=self.home)["state"], "prereq")
        from app.errors import NotFound

        with self.assertRaises(NotFound):
            manager_panel.task_item(999, NOW, manager_home=self.home)

    def test_old_manager_db_without_after_column_has_no_waits(self):
        home = tempfile.mkdtemp()
        os.makedirs(os.path.join(home, "state"))
        con = sqlite3.connect(os.path.join(home, "state", "manager.db"))
        con.execute("CREATE TABLE tasks (id INTEGER PRIMARY KEY, title TEXT, kind TEXT, priority INTEGER,"
                    " status TEXT, created_at TEXT, updated_at TEXT)")
        con.execute("INSERT INTO tasks VALUES (1, 'x', 'decision', 2, 'open', 'a', 'a')")
        con.commit()
        con.close()
        self.assertEqual(manager_panel.waits(NOW, manager_home=home), [])
        self.assertEqual([i["id"] for i in manager_panel.decisions(NOW, manager_home=home)], [1])


class StepsTest(unittest.TestCase):
    """진행 단계 — 매니저 tasks.steps(JSON)를 목록으로 실어 팝업이 멈춘 단계를 그린다. 칸이 없거나 못 읽으면 []"""

    def make(self, with_column, steps=None):
        home = tempfile.mkdtemp()
        os.makedirs(os.path.join(home, "state"))
        con = sqlite3.connect(os.path.join(home, "state", "manager.db"))
        extra = ", steps TEXT" if with_column else ""
        con.execute("CREATE TABLE tasks (id INTEGER PRIMARY KEY, title TEXT, kind TEXT, priority INTEGER,"
                    f" status TEXT, created_at TEXT, updated_at TEXT{extra})")
        values = (1, "범위", "decision", 2, "open", "a", "a") + ((steps,) if with_column else ())
        con.execute(f"INSERT INTO tasks VALUES ({','.join('?' * len(values))})", values)
        con.commit()
        con.close()
        return home

    def test_steps_parsed(self):
        steps = [{"name": "조사", "status": "done"}, {"name": "결정", "status": "current", "unblock": "A/B 고르기"}]
        home = self.make(True, json.dumps(steps, ensure_ascii=False))
        self.assertEqual(manager_panel.task_item(1, NOW, manager_home=home)["steps"], steps)

    def test_missing_or_broken_steps_are_empty(self):
        self.assertEqual(manager_panel.task_item(1, NOW, manager_home=self.make(True, "{깨짐"))["steps"], [])
        self.assertEqual(manager_panel.task_item(1, NOW, manager_home=self.make(True, None))["steps"], [])
        self.assertEqual(manager_panel.task_item(1, NOW, manager_home=self.make(False))["steps"], [])


class PermissionWaitsTest(unittest.TestCase):
    """권한 대기 — 칸은 매니저 권한대기 --json 목록(걸린 권한 요청 + 권한 막힘 할일)을 그대로 보인다. 보조 세션 '권한 대기'
    배지가 같은 목록으로 정해진다 — 칸이 DB blocked 할일만 읽어 배지는 권한 대기인데 칸은 0건이었다(사용자 11-18)"""

    SID_REQUEST = "aaaaaaaa-1111-2222-3333-444444444444"
    SID_TASK = "bbbbbbbb-1111-2222-3333-444444444444"
    SID_IDLE = "cccccccc-1111-2222-3333-444444444444"

    def setUp(self):
        self.home = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.home, "state"))
        con = sqlite3.connect(os.path.join(self.home, "state", "manager.db"))
        con.execute(
            "CREATE TABLE tasks (id INTEGER PRIMARY KEY, title TEXT, kind TEXT, detail TEXT, priority INTEGER,"
            " status TEXT, created_at TEXT, updated_at TEXT, next_step TEXT, after_ids TEXT, blocked TEXT,"
            " session_id TEXT)"
        )
        stamp = "2026-11-18T10:00:00"
        rows = [
            (223, "에이전트 크롬에서 OpenSearch Dashboards 로그인해 주기", "decision", 2, "open", None, "permission"),
            (224, "Confluence 재로그인", "action", 1, "open", None, "permission"),
            (225, "배포 방식 고르기", "decision", 2, "open", None, None),
            (226, "권한 표시 해제한 결정", "decision", 2, "open", None, "none"),
            (227, "선행 남은 막힘", "action", 2, "open", "225", "permission"),
            (228, "닫힌 막힘", "decision", 2, "done", None, "permission"),
        ]
        con.executemany(
            "INSERT INTO tasks (id, title, kind, priority, status, after_ids, blocked, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            [(*row, stamp, stamp) for row in rows],
        )
        con.execute("UPDATE tasks SET session_id=? WHERE id=223", (self.SID_TASK,))
        con.commit()
        con.close()
        # 매니저 perm_grant.waits 모양 — 걸린 요청이 먼저, 그다음 막힘 할일(끝난 세션이면 ended·note)
        self.waits = [
            {"source": "request", "request_id": "0412", "session_id": self.SID_REQUEST, "tool_name": "Bash",
             "preview": '{"command": "aws s3 ls s3://bucket"}', "created_at": "2026-11-18T10:05:00",
             "deliver": "terminal", "answer": "manager.py perm-answer 0412 yes|no"},
            {"source": "task", "task_id": 223, "title": "로그인", "kind": "decision", "session_id": self.SID_TASK,
             "created_at": "2026-11-18T10:00:00", "ended": True, "note": "세션 종료됨 — 허용하면 되살려 재시도",
             "answer": "manager.py answer-send 223 '<allow|deny>'"},
            {"source": "task", "task_id": 224, "title": "재로그인", "kind": "action", "session_id": None,
             "created_at": "2026-11-18T10:00:00", "ended": False, "note": None, "answer": "manager.py task done 224"},
            {"source": "task", "task_id": 999, "title": "그 사이 지운 할일", "kind": "action", "session_id": None,
             "ended": False, "note": None},
        ]
        self.waits_fn = lambda _home: self.waits

    def test_permissions_follow_manager_list(self):
        items = manager_panel.permissions(NOW, manager_home=self.home, waits_fn=self.waits_fn)
        self.assertEqual([(item["source"], item["id"]) for item in items],
                         [("request", "0412"), ("task", 223), ("task", 224)])
        request, task, action = items
        # 세션 이름·명령 요약. 세션 기록에서 전문을 못 찾으면 매니저 미리보기로 보이고 허용은 막힌다(카드 규칙)
        self.assertEqual(request["summary"], '{"command": "aws s3 ls s3://bucket"}')
        self.assertEqual(request["permission"]["mode"], "gate")
        self.assertEqual(request["permission"]["request"]["id"], "0412")
        self.assertFalse(request["permission"]["verified"])
        self.assertEqual(request["permission"]["session"]["claude_session_id"], self.SID_REQUEST)
        self.assertEqual((task["state"], task["kind"], task["ended"]), ("permission", "decision", True))
        self.assertEqual(task["note"], "세션 종료됨 — 허용하면 되살려 재시도")
        self.assertEqual((action["state"], action["ended"], action["note"]), ("permission", False, None))

    def test_section_count_and_helper_badge_use_the_same_list(self):
        rows = [{"session_id": sid, "name": name, "status": "권한 대기" if sid != self.SID_IDLE else "쉼"}
                for sid, name in ((self.SID_REQUEST, "보조2"), (self.SID_TASK, "보조3"), (self.SID_IDLE, "보조4"))]
        calls = []

        def waits_fn(home):
            calls.append(home)
            return self.waits

        sources = dict(now=NOW, manager_home=self.home, helpers_fn=lambda _home: rows, waits_fn=waits_fn)
        section = manager_panel.snapshot("permissions", **sources)["permissions"]
        helpers = manager_panel.snapshot("helpers", **sources)["helpers"]
        self.assertIsNone(section["error"])
        self.assertEqual(len(calls), 2)  # 두 칸 모두 권한대기 목록 하나를 원천으로 본다
        in_section = {item.get("session_id") or item["popup"]["session_id"] for item in section["items"]} - {None}
        badged = {row["session_id"] for row in helpers["items"] if row["waiting"] == "permission"}
        self.assertEqual(in_section, {self.SID_REQUEST, self.SID_TASK})
        self.assertEqual(badged, in_section)

    def test_manager_without_permission_waits_command(self):
        # 권한대기 명령이 없는 매니저는 사용법을 찍고 0 으로 끝난다 — 칸은 이유를 보이고, 보조 칸은 예전 신호로 돈다
        home = tempfile.mkdtemp()
        with open(os.path.join(home, "manager.py"), "w", encoding="utf-8") as handle:
            handle.write("print('매니저 CLI — 사용법')\n")
        with self.assertRaisesRegex(RuntimeError, "권한대기 --json"):
            manager_panel.permissions(NOW, manager_home=home)
        self.assertEqual(manager_panel.permission_sessions(home), frozenset())

    def test_decisions_exclude_permission_wait(self):
        self.assertEqual([item["id"] for item in manager_panel.decisions(NOW, manager_home=self.home)], [225, 226])

    def test_prereq_wins_over_permission(self):
        self.assertEqual([item["id"] for item in manager_panel.waits(NOW, manager_home=self.home)], [227])
        self.assertEqual(manager_panel.task_item(223, NOW, manager_home=self.home)["state"], "permission")
        self.assertEqual(manager_panel.task_item(228, NOW, manager_home=self.home)["state"], "closed")

    def test_old_manager_db_without_blocked_column_still_lists_decisions(self):
        home = tempfile.mkdtemp()
        os.makedirs(os.path.join(home, "state"))
        con = sqlite3.connect(os.path.join(home, "state", "manager.db"))
        con.execute("CREATE TABLE tasks (id INTEGER PRIMARY KEY, title TEXT, kind TEXT, priority INTEGER,"
                    " status TEXT, created_at TEXT, updated_at TEXT)")
        con.execute("INSERT INTO tasks VALUES (1, 'x', 'decision', 2, 'open', 'a', 'a')")
        con.commit()
        con.close()
        self.assertEqual(manager_panel.permissions(NOW, manager_home=home, waits_fn=lambda _home: []), [])
        self.assertEqual([i["id"] for i in manager_panel.decisions(NOW, manager_home=home)], [1])


class DecisionsTest(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.home, "state"))
        self.db = os.path.join(self.home, "state", "manager.db")
        con = sqlite3.connect(self.db)
        con.execute(
            "CREATE TABLE tasks (id INTEGER PRIMARY KEY, title TEXT, kind TEXT, detail TEXT,"
            " priority INTEGER, status TEXT, created_at TEXT, updated_at TEXT, hold_until TEXT,"
            " next_step TEXT, reason TEXT, session_id TEXT)"
        )
        rows = [
            (1, "열린 결정", "decision", "고를 것\n둘째 줄", 2, "open", "2026-11-11T10:00:00", "2026-11-11T10:00:00", None),
            (2, "직접 할 일", "action", None, 3, "open", "2026-11-11T10:00:00", "2026-11-11T10:00:00", None),
            (3, "확인 대기", "action", None, 3, "confirm", "2026-11-10T10:00:00", "2026-11-11T12:00:00", None),
            (4, "닫힌 결정", "decision", None, 3, "done", "2026-11-10T10:00:00", "2026-11-11T12:00:00", None),
            (5, "미룬 결정", "decision", None, 1, "open", "2026-11-10T10:00:00", "2026-11-10T10:00:00", "2026-11-20T09:00:00"),
        ]
        con.executemany(
            "INSERT INTO tasks (id, title, kind, detail, priority, status, created_at, updated_at, hold_until)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            rows,
        )
        con.execute("UPDATE tasks SET next_step='A·B 중 고르기', session_id='sess-1' WHERE id=1")
        con.execute("UPDATE tasks SET reason='master abc123 반영' WHERE id=3")
        con.commit()
        con.close()

    def test_lists_open_decisions_only_by_priority(self):
        items = manager_panel.decisions(NOW, manager_home=self.home)
        self.assertEqual([item["title"] for item in items], ["열린 결정", "미룬 결정"])
        self.assertEqual([item["state"] for item in items], ["decision", "decision"])
        self.assertEqual(items[0]["detail"], "고를 것")
        self.assertTrue(items[1]["held"])
        self.assertFalse(items[0]["held"])

    def test_confirms_list_confirm_waits_of_any_kind(self):
        # 확인 대기는 결정(decision)이든 직접 할 일(action)이든 confirm 상태면 모두. 시각은 끝낸 시각(updated_at)
        con = sqlite3.connect(self.db)
        con.execute(
            "INSERT INTO tasks (id, title, kind, priority, status, created_at, updated_at)"
            " VALUES (6, '결정 확인 대기', 'decision', 1, 'confirm', '2026-11-09T10:00:00', '2026-11-11T13:00:00')"
        )
        con.commit()
        con.close()
        items = manager_panel.confirms(NOW, manager_home=self.home)
        self.assertEqual([item["id"] for item in items], [3, 6])
        self.assertEqual({item["state"] for item in items}, {"confirm"})
        self.assertEqual(items[0]["popup"]["reason"], "master abc123 반영")
        self.assertEqual(items[0]["since"], manager_panel._utc_iso("2026-11-11T12:00:00"))

    def test_priority_max_counts_open_tasks_only(self):
        # 보드의 '2/3' 분모처럼 열린 할일(open·confirm) 중 최고. 닫힌 할일은 아무리 높아도 빼고,
        # 결정 대기에 안 뜨는 직접 할 일(action)은 센다
        con = sqlite3.connect(self.db)
        con.execute("UPDATE tasks SET priority=9 WHERE id=4")
        con.commit()
        con.close()
        items = {item["id"]: item for item in manager_panel.decisions(NOW, manager_home=self.home)}
        self.assertEqual(items[1]["priority"], 2)
        self.assertEqual({item["priority_max"] for item in items.values()}, {3})

    def test_popup_carries_recorded_fields_only(self):
        items = {item["id"]: item for item in manager_panel.decisions(NOW, manager_home=self.home)}
        popup = items[1]["popup"]
        # 목록 줄은 첫 줄만, 팝업은 전문
        self.assertEqual(popup["detail"], "고를 것\n둘째 줄")
        self.assertEqual(popup["next_step"], "A·B 중 고르기")
        # 없는 칸(plan 등)은 None — 지어내지 않는다
        self.assertIsNone(popup["plan"])
        self.assertIsNone(items[5]["popup"]["reply_tail"])
        self.assertIsNone(items[5]["popup"]["session_name"])

    def test_popup_session_name_from_transcript(self):
        # /rename 이름이 자동 제목보다 앞서고, 나중 이름이 이긴다 (매니저 session_name 과 같은 순서)
        root = tempfile.mkdtemp()
        os.makedirs(os.path.join(root, "proj"))
        lines = [
            {"type": "ai-title", "aiTitle": "자동 제목"},
            {"type": "custom-title", "customTitle": "보조1 | 옛 이름"},
            {"type": "user", "message": {"content": "해 줘"}},
            {"type": "custom-title", "customTitle": "보조1 | 새 이름"},
        ]
        path = os.path.join(root, "proj", "sess-1.jsonl")
        with open(path, "w") as handle:
            handle.write("\n".join(json.dumps(line, ensure_ascii=False) for line in lines) + "\n")
        from app.services import transcript
        old_find = transcript.find_path
        transcript.find_path = lambda sid, root_=None: old_find(sid, root)
        self.addCleanup(setattr, transcript, "find_path", old_find)
        item = next(item for item in manager_panel.decisions(NOW, manager_home=self.home) if item["id"] == 1)
        self.assertEqual(item["popup"]["session_name"], "보조1 | 새 이름")
        # 이름을 붙인 적 없는 세션은 자동 제목
        with open(path, "w") as handle:
            handle.write(json.dumps(lines[0], ensure_ascii=False) + "\n")
        os.utime(path, (1, 1))
        item = next(item for item in manager_panel.decisions(NOW, manager_home=self.home) if item["id"] == 1)
        self.assertEqual(item["popup"]["session_name"], "자동 제목")

    def test_popup_reply_tail_from_transcript_end(self):
        root = tempfile.mkdtemp()
        os.makedirs(os.path.join(root, "proj"))
        reply = "앞부분 " * 400 + "\n결정: A 를 추천합니다."
        lines = [
            {"type": "user", "message": {"content": "해 줘"}},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": reply}]}},
            {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Bash"}]}},
        ]
        with open(os.path.join(root, "proj", "sess-1.jsonl"), "w") as handle:
            handle.write("\n".join(json.dumps(line, ensure_ascii=False) for line in lines) + "\n")
        from app.services import transcript
        old_find = transcript.find_path
        transcript.find_path = lambda sid, root_=None: old_find(sid, root)
        self.addCleanup(setattr, transcript, "find_path", old_find)
        item = next(item for item in manager_panel.decisions(NOW, manager_home=self.home) if item["id"] == 1)
        tail = item["popup"]["reply_tail"]
        self.assertTrue(tail.endswith("결정: A 를 추천합니다."))
        self.assertLessEqual(len(tail), manager_panel.REPLY_TAIL_CHARS + 2)
        self.assertEqual(item["popup"]["reply_from"], "transcript")

    def test_popup_falls_back_to_dashboard_reply_head(self):
        from app.services import transcript
        old_find = transcript.find_path
        transcript.find_path = lambda sid, root_=None: None
        self.addCleanup(setattr, transcript, "find_path", old_find)
        con = temp_db()
        con.execute(
            "INSERT INTO sessions (claude_session_id, cwd, state, started_at, last_seen_at, last_reply)"
            " VALUES ('sess-1', '/x', 'active', '2026-11-11T00:00:00', '2026-11-11T00:00:00', '답 앞부분')"
        )
        con.commit()
        item = next(item for item in manager_panel.decisions(NOW, manager_home=self.home, con=con) if item["id"] == 1)
        self.assertEqual((item["popup"]["reply_tail"], item["popup"]["reply_from"]), ("답 앞부분", "dashboard_head"))

    def test_reads_without_writing(self):
        before = os.path.getmtime(self.db)
        os.chmod(self.db, 0o444)
        self.addCleanup(os.chmod, self.db, 0o644)
        manager_panel.decisions(NOW, manager_home=self.home)
        manager_panel.confirms(NOW, manager_home=self.home)
        self.assertEqual(os.path.getmtime(self.db), before)
        # 읽기 전용 연결은 저널·WAL 파일도 만들지 않는다
        self.assertEqual(os.listdir(os.path.dirname(self.db)), ["manager.db"])


class DonesTest(unittest.TestCase):
    """최근 완료 — 매니저 DB done_reports 최신 3건(읽기 전용)"""

    def setUp(self):
        self.home = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.home, "state"))
        con = sqlite3.connect(os.path.join(self.home, "state", "manager.db"))
        con.execute(
            "CREATE TABLE done_reports (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, name TEXT, summary TEXT,"
            " commits TEXT DEFAULT '', open_target TEXT, restart TEXT DEFAULT '', created_at TEXT, auto INTEGER DEFAULT 0)"
        )
        rows = [
            ("s1", "보조1 | 첫째", "첫째 결과", "", None, "2026-11-19T10:00:00", 0),
            ("s2", "보조2 | 둘째", "| 표 | 머리 |\n| --- | --- |\n- **둘째** 결과\n자세히", "abc def", "https://x/pr/1",
             "2026-11-19T11:00:00", 0),
            ("s3", "보조1 | 셋째", "## 셋째 결과", "", None, "2026-11-19T12:00:00", 1),
            ("s4", "넷째", "넷째 결과", "", "/home/u/a", "2026-11-19T13:00:00", 0),
        ]
        con.executemany(
            "INSERT INTO done_reports (session_id, name, summary, commits, open_target, created_at, auto)"
            " VALUES (?,?,?,?,?,?,?)",
            rows,
        )
        con.commit()
        con.close()

    def test_latest_three_newest_first(self):
        items = manager_panel.dones(manager_home=self.home)
        self.assertEqual([item["session_id"] for item in items], ["s4", "s3", "s2"])
        # '보조N | ' 는 제목에서 떼고, 원래 이름은 name 에 남는다
        self.assertEqual([item["title"] for item in items], ["넷째", "셋째", "둘째"])
        self.assertEqual(items[2]["name"], "보조2 | 둘째")
        # 결과 한 줄 — 표·머리 기호·굵게 표시를 건너뛴 첫 문장 줄
        self.assertEqual([item["result"] for item in items], ["넷째 결과", "셋째 결과", "둘째 결과"])
        self.assertEqual(items[2]["commits"], ["abc", "def"])
        self.assertEqual(items[2]["open_target"], "https://x/pr/1")
        self.assertIsNone(items[1]["open_target"])
        self.assertTrue(items[1]["auto"])
        self.assertTrue(items[0]["at"].startswith("2026-11-19T13:00:00"))

    def test_old_manager_without_reports_table_is_empty(self):
        home = tempfile.mkdtemp()
        os.makedirs(os.path.join(home, "state"))
        sqlite3.connect(os.path.join(home, "state", "manager.db")).close()
        self.assertEqual(manager_panel.dones(manager_home=home), [])

    def test_snapshot_part(self):
        payload = manager_panel.snapshot("dones", now=NOW, manager_home=self.home)
        self.assertIsNone(payload["dones"]["error"])
        self.assertEqual(len(payload["dones"]["items"]), 3)


class SnapshotTest(unittest.TestCase):
    def test_each_part_fails_alone(self):
        home = tempfile.mkdtemp()

        def broken(_home):
            raise RuntimeError("claude agents 응답 없음")

        payload = manager_panel.snapshot(
            now=NOW, crontab_text="", manager_home=home, helpers_fn=broken, tools_external_fn=lambda: ([], None)
        )
        self.assertIn("claude agents 응답 없음", payload["helpers"]["error"])
        # 매니저가 없는 PC 에서도 도구 칸은 외부 연결만으로 뜬다
        self.assertEqual(payload["tools"], {"items": [], "error": None})
        self.assertIsNone(payload["automations"]["error"])
        self.assertIn("manager.db", payload["decisions"]["error"])
        self.assertIn("manager.db", payload["confirms"]["error"])

    def test_helpers_keep_manager_fields(self):
        rows = [{"name": "보조1 | 일", "status": "작업 중", "percent": 40, "percent_at": None,
                 "doing": "판정 중", "moved_at": "2026-11-11T19:50:00+09:00", "session_id": "s"}]
        payload = manager_panel.snapshot("helpers", now=NOW, helpers_fn=lambda _home: rows)
        item = payload["helpers"]["items"][0]
        self.assertEqual((item["doing"], item["percent"]), ("판정 중", 40))
        # 세션 id 는 트리 카드·첫 요청을 찾는 열쇠라 함께 싣는다. 대시보드 DB 가 없으면 카드는 없다
        self.assertEqual(item["session_id"], "s")
        self.assertIsNone(item["card"])

    def test_route_rejects_unknown_part(self):
        with self.assertRaises(Validation):
            server.route(temp_db(), "GET", "/api/manager", {"part": ["없는 칸"]}, {})


if __name__ == "__main__":
    unittest.main()
