"""화면이 부르는 것과 서버가 내주는 것이 맞는지.

엔드포인트를 하나 만들고 server.py 라우트 등록을 빠뜨리면, 브라우저에서만 404 가
나고 단위 테스트는 전부 통과한다 — /api/worktrees 를 실제로 그렇게 놓쳤다.
탭 경로(/board 등)도 같은 종류다. 그래서 목록을 손으로 적지 않고 api.js·index.html
에서 뽑아 대조한다. 화면에 새 호출이 늘면 이 테스트가 자동으로 같이 늘어난다.
"""
import pathlib
import re
import unittest

import server
from app.errors import UnknownEndpoint
from tests.support import temp_db

STATIC = pathlib.Path(__file__).resolve().parent.parent / "static"
API_JS = STATIC / "js" / "api.js"
INDEX = STATIC / "index.html"
INDEX_FILE = "index.html"

# api.js 의 호출은 전부 request("<메서드>", "/<머리>...") 한 가지 모양이다
CALL = re.compile(r"""request\(\s*["'](GET|POST|PATCH|DELETE)["']\s*,\s*[`"']/([A-Za-z0-9_-]+)""")
TAB = re.compile(r'data-tab="([a-z-]+)"')
# server.py 의 라우터는 메서드마다 함수 하나, 그 안은 `if head == "..."` 사슬이다
ROUTER = re.compile(r"^def _route_(get|post|patch|delete)\(", re.M)
# GET·POST·PATCH 는 `if head == "x"` 사슬, DELETE 는 이름표를 키로 갖는 표를 쓴다
HEAD = re.compile(r'head == "([A-Za-z0-9_-]+)"|^\s{8}"([A-Za-z0-9_-]+)": ', re.M)


def api_calls():
    return sorted(set(CALL.findall(API_JS.read_text(encoding="utf-8"))))


def routed_heads():
    """server.py 소스에서 메서드별 등록 목록을 읽는다. 부르지 않고 확인만 한다"""
    source = pathlib.Path(server.__file__).read_text(encoding="utf-8")
    starts = [(m.group(1).upper(), m.start()) for m in ROUTER.finditer(source)]
    found = {}
    for index, (method, start) in enumerate(starts):
        end = starts[index + 1][1] if index + 1 < len(starts) else len(source)
        pairs = HEAD.findall(source[start:end])
        found[method] = {chain or table for chain, table in pairs}
    return found


ROUTED = routed_heads()


def tab_paths():
    return sorted(set(TAB.findall(INDEX.read_text(encoding="utf-8"))))


class ApiContractTest(unittest.TestCase):
    def setUp(self):
        self.con = temp_db()

    def _is_routed(self, method, head):
        """등록 여부만 본다. 핸들러를 부르지 않는다.

        예전에는 실제로 route() 를 실행해 UnknownEndpoint 만 '없음' 으로 쳤다. 그러면
        등록 확인을 핑계로 모든 엔드포인트가 한 번씩 진짜로 돈다 — DB 는 temp_db 로
        갈렸지만 파일 경로는 전역이라, POST /api/gtasks-disconnect 가 사용자의 실제
        gtasks.json 에서 refresh_token 을 지웠다. 되돌리려면 구글 재인증뿐이다
        """
        return head in ROUTED[method]

    def test_regex_still_matches_api_js(self):
        """api.js 의 작성 방식이 바뀌면 아래 테스트가 조용히 0 건을 검사하게 된다"""
        self.assertGreater(len(api_calls()), 10)

    def test_router_extraction_still_matches_server(self):
        """server.py 의 라우터 모양이 바뀌면 위 대조가 조용히 빈 집합을 보게 된다"""
        self.assertEqual(sorted(ROUTED), ["DELETE", "GET", "PATCH", "POST"])
        for method, heads in ROUTED.items():
            self.assertGreater(len(heads), 2, f"{method} 라우트를 못 읽었다")

    def test_every_endpoint_api_js_calls_is_routed(self):
        missing = [
            f"{method} /api/{head}"
            for method, head in api_calls()
            if not self._is_routed(method, head)
        ]
        self.assertEqual(missing, [], f"api.js 가 부르는데 서버에 없는 엔드포인트: {missing}")

    def test_unknown_endpoint_is_distinguishable(self):
        """이 구분이 무너지면 위 테스트가 아무것도 못 잡는다"""
        with self.assertRaises(UnknownEndpoint):
            server.route(self.con, "GET", "/api/nope", {}, {})
        with self.assertRaises(UnknownEndpoint):
            server.route(self.con, "PATCH", "/api/nope/1", {}, {})


class TabPathTest(unittest.TestCase):
    def test_every_tab_path_serves_the_app_shell(self):
        """레일 메뉴의 탭마다 주소가 하나씩 있다. 새로고침·직접 진입이 404 면 안 된다"""
        tabs = tab_paths()
        self.assertGreater(len(tabs), 2)
        for tab in tabs:
            resolved = server.resolve_page(f"/{tab}")
            self.assertTrue(
                resolved and resolved.endswith(INDEX_FILE), f"/{tab} 이 앱 화면으로 안 떨어짐"
            )


if __name__ == "__main__":
    unittest.main()
