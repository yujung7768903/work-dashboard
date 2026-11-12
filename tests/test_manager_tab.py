"""매니저 탭 화면 검증. 동작이 JS 안에 있어 node 로 돌리고 결과만 여기서 본다"""
import json
import os
import re
import shutil
import subprocess
import unittest

from app.services import cron

HERE = os.path.dirname(__file__)
CHECK = os.path.join(HERE, "manager_tab_check.mjs")
CYCLE_CHECK = os.path.join(HERE, "cycle_format_check.mjs")

MANAGER_CHECK = {"days": {"kind": "weekdays"}, "time": {"kind": "interval", "minutes": 10, "hours": [8, 20]}}


def sre_check(expr, every_days=1):
    return {"every_days": every_days, "manual": False, "runner": cron.describe(expr)}


# 2026-11-12 매니저 탭 자동화 목록 27개(crontab 24 + 매니저 점검 1 + SRE 체크 2)와 그 표기.
# 칸 표기가 '11:30'·'매일(11:30)' 처럼 갈라지지 않게 전 항목을 고정한다
CURRENT = [
    ("*/15 * * * *", None, "15분마다"),
    ("*/5 * * * *", None, "5분마다"),
    ("*/5 * * * *", None, "5분마다"),
    ("*/5 * * * *", None, "5분마다"),
    ("*/10 * * * *", None, "10분마다"),
    ("*/10 * * * *", None, "10분마다"),
    (None, MANAGER_CHECK, "10분마다 (평일 08~20시)"),
    ("30 11 * * *", sre_check("30 11 * * *"), "매일 11:30"),
    ("30 11 * * *", None, "매일 11:30"),
    ("*/30 * * * *", None, "30분마다"),
    ("30 11 * * *", sre_check("30 11 * * *"), "매일 11:30"),
    ("0 9-20 * * 1-5", None, "매시 00분 (평일 09~20시)"),
    ("0 12 * * *", None, "매일 12:00"),
    ("0 12 * * 4", None, "매주 목 12:00"),
    ("7 * * * *", None, "매시 07분"),
    ("0 11,15 * * 1-5", None, "평일 11:00, 15:00"),
    ("3 18 * * 1-5", None, "평일 18:03"),
    ("0 4 * * *", None, "매일 04:00"),
    ("0 8,9,10 * * 1-5", None, "평일 08:00, 09:00, 10:00"),
    ("0 10 * * 1-5", None, "평일 10:00"),
    ("10,20,30,40,50 10 * * *", None, "매일 10:10, 10:20, 10:30, 10:40, 10:50"),
    ("0 11 * * *", None, "매일 11:00"),
    ("0 9 * * 1", None, "매주 월 09:00"),
    ("0 15 * * 3", None, "매주 수 15:00"),
    # 목록에 없는 '매월' — 시각형 틀(주기어 + HH:MM)을 그대로 따른다
    ("0 5 5 * *", None, "매월 5일 05:00"),
    ("@reboot", None, "부팅 시"),
    ("@reboot", None, "부팅 시"),
]

# 허용 형식. 반복형은 뒤 괄호에 요일·시간 범위, 시각형은 쉼표로 여러 시각
DOW = "[월화수목금토일]"
ALLOWED = re.compile(
    r"^(?:"
    r"(?:\d+분마다|\d+시간마다|매시 \d\d분)(?: \((?:평일|매주 " + DOW + r"(?:·" + DOW + r")*)?(?: ?\d\d~\d\d시)?\))?"
    r"|(?:매일|평일|매주 " + DOW + r"(?:·" + DOW + r")*|매월 \d+일) \d\d:\d\d(?:, \d\d:\d\d)*"
    r"|부팅 시"
    r")$"
)


def format_cycles(items):
    done = subprocess.run(
        ["node", CYCLE_CHECK], input=json.dumps(items), capture_output=True, text=True, cwd=os.path.dirname(HERE)
    )
    if done.returncode:
        raise AssertionError(done.stderr)
    return json.loads(done.stdout)


@unittest.skipUnless(shutil.which("node"), "node 없음")
class ManagerTabTest(unittest.TestCase):
    def test_rows_cycles_and_failed_part(self):
        done = subprocess.run(["node", CHECK], capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_helpers_section_first(self):
        # 보조 세션이 맨 위, 칸마다 바로 아래 페이지 넘김
        html = open(os.path.join(os.path.dirname(HERE), "static", "index.html"), encoding="utf-8").read()
        order = [html.index(f'id="mgr-{part}"') for part in ("helpers", "automations", "decisions")]
        self.assertEqual(order, sorted(order))
        for part in ("helpers", "automations", "decisions"):
            self.assertLess(html.index(f'id="mgr-{part}"'), html.index(f'id="mgr-{part}-pager"'))

    def test_current_automations_use_one_format(self):
        items = [{"expr": expr, "cycle": cycle or cron.describe(expr)} for expr, cycle, _ in CURRENT]
        texts = format_cycles(items)
        self.assertEqual(len(texts), 27)
        for (expr, _, expected), text in zip(CURRENT, texts):
            with self.subTest(expr=expr):
                self.assertEqual(text, expected)
                self.assertRegex(text, ALLOWED)

    def test_other_shapes(self):
        cases = [
            ({"days": {"kind": "dow", "values": [3, 4]}, "time": {"kind": "at", "times": ["15:00"]}}, "매주 수·목 15:00"),
            ({"days": {"kind": "every"}, "time": {"kind": "at", "times": ["08:00", "18:00"]}}, "매일 08:00, 18:00"),
            (cron.describe("0 */2 * * *"), "2시간마다"),
            (cron.describe("*/10 8-20 * * *"), "10분마다 (08~20시)"),
            (cron.describe("*/10 * * * 1-5"), "10분마다 (평일)"),
            (sre_check("30 11 * * *", every_days=3), "3일마다 11:30"),
        ]
        texts = format_cycles([{"expr": None, "cycle": cycle} for cycle, _ in cases])
        for (_, expected), text in zip(cases, texts):
            with self.subTest(expected=expected):
                self.assertEqual(text, expected)

    def test_old_shapes_rejected(self):
        for old in ("11:30", "매일 (11:30)", "매일(11:30)", "평일 · 8~20시 10분마다", "재부팅 시", "매주 수 · 15:00"):
            with self.subTest(old=old):
                self.assertNotRegex(old, ALLOWED)


if __name__ == "__main__":
    unittest.main()
