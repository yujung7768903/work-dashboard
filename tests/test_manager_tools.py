"""매니저 탭 도구 목록 — 실제 설정을 옮기는지, 주소·토큰이 화면 데이터에 새지 않는지"""
import json
import os
import tempfile
import threading
import time
import unittest
from unittest import mock

from app.services import manager_panel, manager_tools

# claude mcp list 출력 모양. 주소·명령줄에 토큰이 섞여도 이름과 상태만 남아야 한다
MCP_LIST = """Checking MCP server health…

claude.ai Atlassian Rovo: https://mcp.atlassian.com/v1/sse?token=SECRET123 - ✔ Connected
claude.ai Slack: https://mcp.slack.com/mcp - ! Needs authentication
plugin:discord:discord: bun run --cwd /x/discord/0.0.4 --shell=bun --silent start - ✔ Connected
whatap: npx -y github:whatap/whatap-open-mcp - ✗ Failed to connect
mystery: http://10.0.0.1:8080/mcp?key=SECRET456 (HTTP) - ✔ Connected
"""

DOC = """매니저 CLI

  manager.py wake [--chat]                  메인이 깨어났을 때 한 번. 사용량 확인·알림 목록·
                                            보낼 곳 판정
  manager.py fail "<무엇이 실패했는지>"        자동화 실패를 남긴다(예: 디스코드 발신 실패)
  manager.py open [--dry-run] <URL|경로>
                                            사용자 PC 에 띄운다 — URL 은 기본 브라우저
  manager.py task add --title .. [--kind ..]
                      [--priority N]   --priority N: 1 이상 정수
  manager.py task done <id> [근거]          세션·매니저가 끝냄 → 사용자 확인 대기(confirm)
  manager.py task done <id> --by-user "<말>"    사용자가 직접 한 일 — 바로 완료
  manager.py candidate show|accept|decline [메모]
                                            열린 제안에 대한 사용자 답
  manager.py 보조 [--json]                  떠 있는 보조 세션마다 이름·상태·진행률

환경변수: MANAGER_HOME
"""


class McpListTest(unittest.TestCase):
    def test_names_status_category_without_addresses(self):
        items = manager_tools.parse_mcp_list(MCP_LIST)
        by_source = {item["source"]: item for item in items}
        self.assertEqual(len(items), 5)
        rovo = by_source["claude.ai Atlassian Rovo"]
        self.assertEqual((rovo["name"], rovo["category"], rovo["maker"], rovo["status"]),
                         ("Jira·Confluence", "docs", "external", "connected"))
        self.assertEqual(by_source["claude.ai Slack"]["status"], "auth")
        self.assertEqual(by_source["plugin:discord:discord"]["name"], "디스코드")
        self.assertEqual(by_source["whatap"]["status"], "failed")
        # 표에 없는 서버는 지어내지 않는다 — 이름 그대로, 설명 없음, 기타
        mystery = by_source["mystery"]
        self.assertEqual((mystery["name"], mystery["desc"], mystery["category"], mystery["maker"]),
                         ("mystery", None, "etc", None))
        dumped = json.dumps(items, ensure_ascii=False)
        for leak in ("SECRET", "http", "bun run", "npx"):
            self.assertNotIn(leak, dumped)

    def test_list_failure_is_shown_not_hidden(self):
        def broken():
            raise FileNotFoundError("claude")

        [item] = manager_tools.mcp_servers(run=broken)
        self.assertEqual(item["status"], "unknown")
        self.assertIn("읽지 못함", item["desc"])


class ClassificationTableTest(unittest.TestCase):
    """서버 이름별 분류표 — 용도는 칩에 있는 것만, 제작 주체는 사내·외부·모름(None)만"""

    def test_every_entry_uses_known_category_and_maker(self):
        makers = {manager_tools.INHOUSE, manager_tools.EXTERNAL, None}
        for source, (_label, category, maker, _desc) in manager_tools.KNOWN_MCP.items():
            self.assertIn(category, manager_tools.CATEGORIES, source)
            self.assertIn(maker, makers, source)
        for _name, _binary, category, _desc, _check in manager_tools.KNOWN_CLI:
            self.assertIn(category, manager_tools.CATEGORIES)

    def test_inhouse_and_external_examples(self):
        known = manager_tools.KNOWN_MCP
        self.assertEqual(known["claude.ai HAI Connector (dev)"][1:3], ("data", "inhouse"))
        self.assertEqual(known["claude.ai Google Slides"][1:3], ("docs", "external"))
        self.assertEqual(known["whatap"][1:3], ("infra", "external"))
        self.assertEqual(known["codex"][1:3], ("dev", "external"))
        # claude mcp list 가 내는 실제 이름 그대로(밑줄) — 띄어 쓴 키로는 맞지 않아 기타로 빠졌다
        self.assertEqual(known["claude.ai hmap_2_mcp"][1:3], ("data", "inhouse"))
        # 누가 만들었는지 확인하지 못한 서버는 표에 없다 — 기타·제작 주체 없음으로 나간다
        [athena] = manager_tools.parse_mcp_list("athena: https://x/mcp (HTTP) - ✔ Connected")
        self.assertEqual((athena["category"], athena["maker"]), ("etc", None))

    def test_cli_is_external(self):
        items = manager_tools.cli_tools(which=lambda _b: True, run=lambda _c: 0)
        self.assertEqual({item["source"]: (item["category"], item["maker"]) for item in items},
                         {"gh": ("dev", "external"), "aws": ("infra", "external")})


class CliTest(unittest.TestCase):
    def test_only_installed_and_exit_code_decides(self):
        codes = {"gh": 0, "aws": 253}
        items = manager_tools.cli_tools(which=lambda binary: binary == "gh" or binary == "aws",
                                        run=lambda command: codes[command[0]])
        self.assertEqual({item["source"]: item["status"] for item in items}, {"gh": "connected", "aws": "auth"})
        self.assertEqual(manager_tools.cli_tools(which=lambda _b: None), [])

    def test_check_that_cannot_run_is_unknown(self):
        def timeout(_command):
            raise manager_tools.subprocess.TimeoutExpired("aws", 15)

        self.assertEqual(manager_tools.cli_status(["aws"], run=timeout), "unknown")


class CommandsTest(unittest.TestCase):
    def test_parse_doc(self):
        items = manager_tools.parse_commands(DOC)
        names = [item["name"] for item in items]
        self.assertEqual(names, [
            "manager.py wake", "manager.py fail", "manager.py open", "manager.py task add", "manager.py task done",
            "manager.py candidate show·accept·decline", "manager.py 보조",
        ])
        desc = {item["source"]: item["desc"] for item in items}
        self.assertEqual(desc["wake"], "메인이 깨어났을 때 한 번")
        # 한글 사용법은 두 칸씩 차지한다 — 글자 수로 재면 설명을 놓쳤다
        self.assertEqual(desc["fail"], "자동화 실패를 남긴다(예: 디스코드 발신 실패)")
        self.assertEqual(desc["open"], "사용자 PC 에 띄운다")
        self.assertIsNone(desc["task add"], "사용법 줄은 설명이 아니다")
        self.assertEqual(desc["task done"], "세션·매니저가 끝냄 → 사용자 확인 대기(confirm)", "같은 명령은 처음 것")
        self.assertEqual(desc["보조"], "떠 있는 보조 세션마다 이름·상태·진행률")
        wake = items[0]
        self.assertIn("보낼 곳 판정", wake["detail"], "이어지는 줄은 detail 에 합친다")
        self.assertTrue(all(item["status"] == "available" and item["category"] == "command" for item in items))
        self.assertTrue(all(item["maker"] == "inhouse" for item in items), "매니저 명령은 사내 제작")

    @unittest.skipUnless(os.path.isfile(os.path.expanduser("~/work/manager/manager.py")), "매니저 없음")
    def test_real_manager_has_named_commands(self):
        names = {item["source"] for item in manager_tools.manager_commands(os.path.expanduser("~/work/manager"))}
        for name in ("open", "clip", "spawn", "보조", "task done", "ask", "퇴근-보조"):
            self.assertIn(name, names)


class ToolsTest(unittest.TestCase):
    def test_order_external_first_then_commands(self):
        home = tempfile.mkdtemp()
        with open(os.path.join(home, "manager.py"), "w", encoding="utf-8") as handle:
            handle.write(f'"""{DOC}"""\n')
        external = manager_tools.parse_mcp_list(MCP_LIST)
        items = manager_tools.tools(home, external_fn=lambda: (external, "2026-11-12T10:00:00+09:00"))
        kinds = [item["kind"] for item in items]
        self.assertEqual(kinds, sorted(kinds, key=lambda kind: kind == "command"))
        statuses = [item["status"] for item in items if item["kind"] == "mcp"]
        self.assertEqual(statuses[:3], ["connected"] * 3, "연결된 것부터")
        self.assertEqual(statuses[-1], "failed")
        self.assertEqual(items[0]["checked_at"], "2026-11-12T10:00:00+09:00")
        self.assertIsNone(items[-1]["checked_at"], "명령은 확인 시각이 없다")

    def test_snapshot_part(self):
        payload = manager_panel.snapshot("tools", manager_home=tempfile.mkdtemp(),
                                         tools_external_fn=lambda: (manager_tools.parse_mcp_list(MCP_LIST), None))
        self.assertIsNone(payload["tools"]["error"])
        self.assertEqual(len(payload["tools"]["items"]), 5)


class CacheTest(unittest.TestCase):
    def setUp(self):
        manager_tools.clear_cache()
        self.addCleanup(manager_tools.clear_cache)
        self.calls = 0
        self.gate = threading.Event()

        def fake_mcp():
            self.calls += 1
            if self.calls > 1:
                self.gate.wait(5)
            return [{"id": f"mcp:{self.calls}", "kind": "mcp", "name": str(self.calls), "source": "x",
                     "category": "etc", "desc": None, "status": "connected"}]

        patches = [mock.patch.object(manager_tools, "mcp_servers", fake_mcp),
                   mock.patch.object(manager_tools, "cli_tools", lambda: [])]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def test_stale_served_while_refreshing(self):
        first, _ = manager_tools.cached_external()
        self.assertEqual(first[0]["name"], "1")
        again, _ = manager_tools.cached_external()
        self.assertEqual((again[0]["name"], self.calls), ("1", 1), "한 시간 안에는 다시 읽지 않는다")
        manager_tools._cache["at"] -= manager_tools.TOOLS_CACHE_SEC + 1
        stale, _ = manager_tools.cached_external()
        self.assertEqual(stale[0]["name"], "1", "오래된 결과를 먼저 주고 기다리지 않는다")
        started = time.monotonic()
        during, _ = manager_tools.cached_external()
        self.assertEqual(during[0]["name"], "1")
        self.assertLess(time.monotonic() - started, 1, "다시 읽는 동안 들어온 요청도 기다리지 않는다")
        self.gate.set()
        for _ in range(50):
            if not manager_tools._refreshing.is_set():
                break
            time.sleep(0.05)
        fresh, _ = manager_tools.cached_external()
        self.assertEqual(fresh[0]["name"], "2")


if __name__ == "__main__":
    unittest.main()
