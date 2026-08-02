"""귀속 사용량. 무게가 틀리면 순위가 통째로 뒤집히므로 그 셈부터 못박는다"""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services import attribution as mod


def _stamp(days_ago=0):
    return (
        (datetime.now(timezone.utc) - timedelta(days=days_ago))
        .isoformat()
        .replace("+00:00", "Z")
    )


def _line(uuid, model="claude-sonnet-5", output=0, cache_read=0, days_ago=0, **labels):
    row = {
        "type": "assistant",
        "uuid": uuid,
        "timestamp": _stamp(days_ago),
        **labels,
        "message": {
            "model": model,
            "usage": {
                "input_tokens": 0,
                "output_tokens": output,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": cache_read,
            },
        },
    }
    # 실제 트랜스크립트는 공백 없는 한 줄이다 — 스캔이 그 형태를 전제한다
    return json.dumps(row, ensure_ascii=False, separators=(",", ":"))


def _root(lines, folder="-Users-me-project"):
    root = tempfile.mkdtemp()
    os.makedirs(os.path.join(root, folder))
    with open(os.path.join(root, folder, "a.jsonl"), "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    return root


def _scan(lines):
    # 캐시를 태우면 앞 테스트의 결과가 넘어온다 — 스캔을 직접 부른다
    return mod._scan(_root(lines), mod.ATTRIBUTION_DAYS)


def _items(result, key):
    return {row["name"]: row["pct"] for group in result["groups"] if group["key"] == key
            for row in group["items"]}


class AttributionTest(unittest.TestCase):
    def test_share_is_weighted_by_token_kind_and_model(self):
        """출력 1개(=50)와 캐시 읽기 50개(=50)는 같은 무게다. 합계 토큰으로 세면 안 된다"""
        result = _scan(
            [
                _line("a", output=1, attributionSkill="alpha"),
                _line("b", cache_read=50, attributionSkill="beta"),
            ]
        )
        self.assertEqual(_items(result, "skills"), {"alpha": 50.0, "beta": 50.0})

    def test_opus_counts_more_than_sonnet(self):
        result = _scan(
            [
                _line("a", model="claude-opus-5", output=1, attributionSkill="opus-side"),
                _line("b", model="claude-sonnet-5", output=1, attributionSkill="sonnet-side"),
            ]
        )
        self.assertEqual(_items(result, "skills"), {"opus-side": 62.5, "sonnet-side": 37.5})

    def test_groups_overlap_and_do_not_partition(self):
        """플러그인이 준 스킬은 양쪽에 다 들어간다. 이름표가 없는 사용은 어디에도 안 들어간다"""
        result = _scan(
            [
                _line("a", output=1, attributionSkill="sp:brainstorm", attributionPlugin="sp"),
                _line("b", output=1, attributionMcpServer="figma"),
                _line("c", output=2),  # 이름표 없음 — 분모에만 들어간다
            ]
        )
        self.assertEqual(_items(result, "skills"), {"sp:brainstorm": 25.0})
        self.assertEqual(_items(result, "plugins"), {"sp": 25.0})
        self.assertEqual(_items(result, "mcp"), {"figma": 25.0})

    def test_agent_without_skill_label_keeps_the_agent_name(self):
        result = _scan([_line("a", output=1, attributionAgent="code-reviewer")])
        self.assertEqual(_items(result, "skills"), {"code-reviewer": 100.0})

    def test_skill_label_wins_over_agent_label(self):
        """서브에이전트가 스킬을 물고 돈 줄에는 둘 다 붙는다 — 구체적인 쪽이 이름이다"""
        result = _scan(
            [_line("a", output=1, attributionAgent="explore", attributionSkill="run")]
        )
        self.assertEqual(_items(result, "skills"), {"run": 100.0})

    def test_repeated_uuid_is_counted_once(self):
        """재개된 세션은 앞 세션의 줄을 그대로 복사해 온다"""
        result = _scan(
            [
                _line("dup", output=1, attributionSkill="alpha"),
                _line("dup", output=1, attributionSkill="alpha"),
                _line("b", output=1, attributionSkill="beta"),
            ]
        )
        self.assertEqual(_items(result, "skills"), {"alpha": 50.0, "beta": 50.0})

    def test_lines_older_than_the_window_are_dropped(self):
        result = _scan(
            [
                _line("a", output=1, attributionSkill="recent"),
                _line("b", output=99, days_ago=30, attributionSkill="ancient"),
            ]
        )
        self.assertEqual(_items(result, "skills"), {"recent": 100.0})
        self.assertEqual(result["requests"], 1)

    def test_non_assistant_lines_are_ignored(self):
        result = _scan(
            [
                json.dumps({"type": "user", "uuid": "u", "attributionSkill": "ghost"},
                           separators=(",", ":")),
                _line("a", output=1, attributionSkill="real"),
            ]
        )
        self.assertEqual(_items(result, "skills"), {"real": 100.0})

    def test_missing_transcript_root_is_reported_not_raised(self):
        result = mod._scan(os.path.join(tempfile.mkdtemp(), "nope"), mod.ATTRIBUTION_DAYS)
        self.assertFalse(result["available"])
        self.assertEqual(result["groups"][0]["items"], [])


if __name__ == "__main__":
    unittest.main()
