"""귀속 사용량. 무게·문턱이 틀리면 순위가 통째로 뒤집히므로 그 셈부터 못박는다"""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services import attribution as mod


def _stamp(hours_ago=0):
    return (
        (datetime.now(timezone.utc) - timedelta(hours=hours_ago))
        .isoformat()
        .replace("+00:00", "Z")
    )


def _line(
    uuid,
    model="claude-sonnet-5",
    output=0,
    cache_read=0,
    uncached=0,
    hours_ago=0,
    session="s1",
    sidechain=False,
    **labels
):
    row = {
        "type": "assistant",
        "uuid": uuid,
        "sessionId": session,
        "isSidechain": sidechain,
        "timestamp": _stamp(hours_ago),
        **labels,
        "message": {
            "model": model,
            "usage": {
                "input_tokens": uncached,
                "output_tokens": output,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": cache_read,
            },
        },
    }
    # 실제 트랜스크립트는 공백 없는 한 줄이다 — 스캔이 그 형태를 전제한다
    return json.dumps(row, ensure_ascii=False, separators=(",", ":"))


def _write(root, relative, lines):
    path = os.path.join(root, relative)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def _scan(lines, subagent_lines=()):
    """캐시를 태우면 앞 테스트 결과가 넘어온다 — 스캔을 직접 부른다"""
    root = tempfile.mkdtemp()
    _write(root, os.path.join("-Users-me-project", "s1.jsonl"), lines)
    if subagent_lines:
        # 실제 경로 모양: <프로젝트>/<세션>/subagents/agent-*.jsonl
        _write(
            root,
            os.path.join("-Users-me-project", "s1", "subagents", "agent-a1.jsonl"),
            subagent_lines,
        )
    return mod._scan(root)


def _items(window, key):
    return {
        row["name"]: row["pct"]
        for group in window["groups"]
        if group["key"] == key
        for row in group["items"]
    }


def _behaviors(window):
    return {row["key"]: row["pct"] for row in window["behaviors"]}


def _week(lines, subagent_lines=()):
    return _scan(lines, subagent_lines)["windows"]["week"]


class WeightTest(unittest.TestCase):
    def test_share_is_weighted_by_token_kind(self):
        """출력 1개(=50)와 캐시 읽기 50개(=50)는 같은 무게다. 합계 토큰으로 세면 안 된다"""
        window = _week(
            [
                _line("a", output=1, attributionSkill="alpha"),
                _line("b", cache_read=50, attributionSkill="beta"),
            ]
        )
        self.assertEqual(_items(window, "skills"), {"alpha": 50, "beta": 50})

    def test_opus_counts_more_than_sonnet(self):
        window = _week(
            [
                _line("a", model="claude-opus-5", output=1, attributionSkill="opus-side"),
                _line("b", model="claude-sonnet-5", output=1, attributionSkill="sonnet-side"),
            ]
        )
        self.assertEqual(_items(window, "skills"), {"opus-side": 62, "sonnet-side": 38})


class LabelTest(unittest.TestCase):
    def test_groups_overlap_and_do_not_partition(self):
        """플러그인이 준 스킬은 양쪽에 다 들어간다. 이름표가 없는 사용은 어디에도 안 들어간다"""
        window = _week(
            [
                _line("a", output=1, attributionSkill="sp:brainstorm", attributionPlugin="sp"),
                _line("b", output=1, attributionMcpServer="figma"),
                _line("c", output=2),  # 이름표 없음 — 분모에만 들어간다
            ]
        )
        self.assertEqual(_items(window, "skills"), {"sp:brainstorm": 25})
        self.assertEqual(_items(window, "plugins"), {"sp": 25})
        self.assertEqual(_items(window, "mcp"), {"figma": 25})

    def test_subagent_is_its_own_group_not_a_skill(self):
        """/usage 도 스킬과 서브에이전트를 따로 세운다"""
        window = _week(
            [
                _line("a", output=1, attributionSkill="run"),
                _line("b", output=1, attributionAgent="general-purpose"),
            ]
        )
        self.assertEqual(_items(window, "skills"), {"run": 50})
        self.assertEqual(_items(window, "agents"), {"general-purpose": 50})

    def test_agent_running_a_skill_is_named_by_the_skill(self):
        """줄에 이름표가 둘 다 붙으면 무게는 서브에이전트 몫이고 이름은 구체적인 쪽을 쓴다"""
        window = _week(
            [_line("a", output=1, attributionAgent="explore", attributionSkill="run")]
        )
        self.assertEqual(_items(window, "skills"), {})
        self.assertEqual(_items(window, "agents"), {"run": 100})

    def test_names_rounding_to_zero_are_dropped(self):
        """/usage 와 같이 정수로 접는다 — 잔챙이까지 세우면 큰 것이 안 보인다"""
        window = _week(
            [
                _line("a", output=1000, attributionSkill="big"),
                _line("b", output=1, attributionSkill="crumb"),
            ]
        )
        self.assertEqual(_items(window, "skills"), {"big": 100})


class BehaviorTest(unittest.TestCase):
    def test_long_context_counts_input_not_output(self):
        """출력이 아무리 커도 컨텍스트가 길어진 것은 아니다"""
        window = _week([_line("a", cache_read=200_000, attributionSkill="x")])
        self.assertEqual(_behaviors(window).get("long_context"), 100)
        window = _week([_line("a", output=200_000, attributionSkill="x")])
        self.assertNotIn("long_context", _behaviors(window))

    def test_cache_miss_counts_only_uncached_input(self):
        window = _week([_line("a", uncached=200_000)])
        self.assertEqual(_behaviors(window).get("cache_miss"), 100)
        # 같은 양이 캐시를 탔으면 미스가 아니다 (컨텍스트는 길다)
        window = _week([_line("a", cache_read=200_000)])
        self.assertNotIn("cache_miss", _behaviors(window))

    def test_subagent_heavy_when_subagents_carry_the_session(self):
        window = _week(
            [_line("a", output=1)],
            [_line("sub", output=9, sidechain=True)],
        )
        self.assertEqual(_behaviors(window).get("subagent_heavy"), 100)

    def test_high_parallel_needs_four_sessions_in_one_bucket(self):
        three = [_line(f"a{index}", output=1, session=f"s{index}") for index in range(3)]
        self.assertNotIn("high_parallel", _behaviors(_week(three)))
        four = three + [_line("a9", output=1, session="s9")]
        self.assertEqual(_behaviors(_week(four)).get("high_parallel"), 100)

    def test_cron_when_one_session_spans_eight_hours(self):
        spread = [_line(f"a{hour}", output=1, hours_ago=hour) for hour in range(8)]
        self.assertEqual(_behaviors(_week(spread)).get("cron"), 100)
        short = [_line(f"a{hour}", output=1, hours_ago=hour) for hour in range(4)]
        self.assertNotIn("cron", _behaviors(_week(short)))

    def test_behaviors_below_the_floor_are_folded(self):
        window = _week(
            [_line("a", cache_read=200_000)] + [_line(f"b{i}", output=200_000) for i in range(20)]
        )
        self.assertNotIn("long_context", _behaviors(window))


class WindowTest(unittest.TestCase):
    def test_day_window_is_cut_out_of_the_week_scan(self):
        windows = _scan(
            [
                _line("a", output=1, attributionSkill="today"),
                _line("b", output=1, hours_ago=48, attributionSkill="earlier"),
            ]
        )["windows"]
        self.assertEqual(_items(windows["day"], "skills"), {"today": 100})
        self.assertEqual(
            _items(windows["week"], "skills"), {"today": 50, "earlier": 50}
        )


class ScanTest(unittest.TestCase):
    def test_subagent_transcripts_in_nested_folders_are_scanned(self):
        """서브에이전트는 <세션>/subagents/ 아래에 남는다 — 깊이를 고정하면 통째로 빠진다"""
        window = _week(
            [_line("a", output=1, attributionSkill="parent")],
            [_line("sub", output=1, sidechain=True, attributionAgent="general-purpose")],
        )
        self.assertEqual(_items(window, "agents"), {"general-purpose": 50})

    def test_repeated_uuid_is_counted_once(self):
        """재개된 세션은 앞 세션의 줄을 그대로 복사해 온다"""
        window = _week(
            [
                _line("dup", output=1, attributionSkill="alpha"),
                _line("dup", output=1, attributionSkill="alpha"),
                _line("b", output=1, attributionSkill="beta"),
            ]
        )
        self.assertEqual(_items(window, "skills"), {"alpha": 50, "beta": 50})

    def test_non_assistant_lines_are_ignored(self):
        window = _week(
            [
                json.dumps(
                    {"type": "user", "uuid": "u", "attributionSkill": "ghost"},
                    separators=(",", ":"),
                ),
                _line("a", output=1, attributionSkill="real"),
            ]
        )
        self.assertEqual(_items(window, "skills"), {"real": 100})

    def test_missing_transcript_root_is_reported_not_raised(self):
        result = mod._scan(os.path.join(tempfile.mkdtemp(), "nope"))
        self.assertFalse(result["available"])
        self.assertEqual(result["windows"]["week"]["behaviors"], [])


if __name__ == "__main__":
    unittest.main()
