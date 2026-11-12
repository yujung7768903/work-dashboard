"""crontab 한 줄을 읽어 다음 실행 시각과 사람 말로 옮길 주기 묘사를 만든다.

외부 패키지 없이 표준 5칸(분 시 일 월 요일)과 @reboot·@daily 같은 별칭만 다룬다.
요일 이름(mon)·월 이름(jan)·L·W·# 같은 확장은 쓰지 않으므로 받지 않는다 — 못 읽는 줄은
None 을 돌려주고 화면이 원문 표현식을 그대로 보인다.

주기 묘사는 문장이 아니라 구조(dict)다. 화면이 네 언어로 문장을 만든다 (static/js/manager.js)
"""
from datetime import datetime, timedelta

REBOOT = "@reboot"
ALIASES = {
    "@yearly": "0 0 1 1 *",
    "@annually": "0 0 1 1 *",
    "@monthly": "0 0 1 * *",
    "@weekly": "0 0 * * 0",
    "@daily": "0 0 * * *",
    "@midnight": "0 0 * * *",
    "@hourly": "0 * * * *",
}
# (최소, 최대). 요일 7 은 일요일(0)로 접는다
BOUNDS = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 7))
WEEKDAYS = frozenset({1, 2, 3, 4, 5})
ALL_DOW = frozenset(range(7))
# 다음 실행을 찾을 때 볼 최대 일수. 2월 29일 같은 표현식도 4년 안에는 걸린다
SEARCH_DAYS = 366 * 4 + 1


class Schedule:
    """5칸 표현식 하나. *_any 는 그 칸이 '*' 로 시작했는지 — 일·요일 칸 판정에 쓴다"""

    def __init__(self, expr):
        fields = expr.split()
        if len(fields) != 5:
            raise ValueError(f"cron 칸 수가 5 가 아님: {expr}")
        self.expr = expr
        parsed = [_field(text, low, high) for text, (low, high) in zip(fields, BOUNDS)]
        self.minutes, self.hours, self.days, self.months, dow = parsed
        self.dow = frozenset(0 if day == 7 else day for day in dow)
        self.days_any = fields[2].startswith("*")
        self.dow_any = fields[4].startswith("*")

    def day_matches(self, day):
        # cron 규칙: 일·요일 칸이 둘 다 제한돼 있으면 둘 중 하나만 맞아도 돈다
        in_days = day.day in self.days
        in_dow = (day.isoweekday() % 7) in self.dow
        if self.days_any or self.dow_any:
            return (self.days_any or in_days) and (self.dow_any or in_dow)
        return in_days or in_dow

    def next_after(self, after):
        """after 보다 뒤의 첫 실행 시각(분 단위, after 의 tzinfo 를 따름). 없으면 None"""
        start = after.replace(second=0, microsecond=0) + timedelta(minutes=1)
        day = start.replace(hour=0, minute=0)
        for _ in range(SEARCH_DAYS):
            if day.month in self.months and self.day_matches(day):
                # frozenset 은 순서가 없다 — 정렬해야 그날의 첫 실행이 먼저 걸린다
                for hour in sorted(self.hours):
                    for minute in sorted(self.minutes):
                        candidate = day.replace(hour=hour, minute=minute)
                        if candidate >= start:
                            return candidate
            day = (day + timedelta(days=1)).replace(hour=0, minute=0)
        return None


def parse(expr):
    """표현식 → Schedule. @reboot 은 시각이 없어 None, 못 읽으면 ValueError"""
    expr = expr.strip()
    if expr == REBOOT:
        return None
    return Schedule(ALIASES.get(expr, expr))


def next_run(expr, after=None):
    """다음 실행 시각. @reboot·못 읽는 표현식은 None"""
    after = after or datetime.now().astimezone()
    try:
        schedule = parse(expr)
    except ValueError:
        return None
    return schedule.next_after(after) if schedule else None


def describe(expr):
    """화면이 문장으로 옮길 주기 구조.

    {"reboot": True} 이거나 {"days": {...}, "time": {...}}. 못 읽으면 {"raw": expr}
      days: every · weekdays · dow(values) · dom(values) · custom
      time: interval(minutes | every_hours, hours) · hourly(minute, hours) · at(times) · custom
    hours 가 None 이면 하루 종일, 아니면 [시작, 끝] (연속 범위일 때만)
    """
    expr = expr.strip()
    if expr == REBOOT:
        return {"reboot": True}
    try:
        schedule = parse(expr)
    except ValueError:
        return {"raw": expr}
    return {"days": _describe_days(schedule), "time": _describe_time(schedule)}


def _describe_days(schedule):
    if schedule.months != frozenset(range(1, 13)):
        return {"kind": "custom"}
    if schedule.days_any and schedule.dow_any:
        return {"kind": "every"}
    if schedule.days_any:
        if schedule.dow == ALL_DOW:
            return {"kind": "every"}
        if schedule.dow == WEEKDAYS:
            return {"kind": "weekdays"}
        return {"kind": "dow", "values": sorted(schedule.dow)}
    if schedule.dow_any:
        return {"kind": "dom", "values": sorted(schedule.days)}
    return {"kind": "custom"}


def _describe_time(schedule):
    minutes = sorted(schedule.minutes)
    hours = sorted(schedule.hours)
    span = None if len(hours) == 24 else _span(hours)
    step = _even_step(minutes)
    if step and (len(hours) == 24 or span):
        return {"kind": "interval", "minutes": step, "hours": span}
    hour_step = _even_step(hours, 24)
    if minutes == [0] and hour_step and hour_step > 1:
        return {"kind": "interval", "every_hours": hour_step, "hours": None}
    if len(minutes) == 1 and len(hours) > 3 and (len(hours) == 24 or span):
        return {"kind": "hourly", "minute": minutes[0], "hours": span}
    times = [f"{hour:02d}:{minute:02d}" for hour in hours for minute in minutes]
    if len(times) <= 6:
        return {"kind": "at", "times": times}
    return {"kind": "custom"}


def _span(values):
    """연속 정수면 [처음, 끝], 아니면 None"""
    if values and values == list(range(values[0], values[-1] + 1)):
        return [values[0], values[-1]]
    return None


def _even_step(values, cycle=60):
    """0 부터 같은 간격으로 cycle(분 60·시 24)을 나눠 떨어지게 채운 목록이면 그 간격 (빠짐없으면 1)"""
    if len(values) < 2 or values[0] != 0:
        return None
    step = values[1] - values[0]
    if values == list(range(0, cycle, step)) and cycle % step == 0:
        return step
    return None


def _field(text, low, high):
    values = set()
    for part in text.split(","):
        values |= _part(part, low, high)
    if not values:
        raise ValueError(f"빈 cron 칸: {text}")
    return frozenset(values)


def _part(part, low, high):
    base, _, step_text = part.partition("/")
    step = int(step_text) if step_text else 1
    if step < 1:
        raise ValueError(f"cron 간격이 1 미만: {part}")
    if base == "*":
        start, end = low, high
    elif "-" in base:
        start, end = (int(value) for value in base.split("-", 1))
    else:
        start = int(base)
        end = high if step_text else start
    if not (low <= start <= end <= high):
        raise ValueError(f"cron 범위 밖: {part}")
    return set(range(start, end + 1, step))
