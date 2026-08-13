"""화면 언어 저장·API·CLI와 문구 사전 대조.

화면 문구는 코드에 두지 않고 static/lang/<코드>.json 에 키-값으로 모아 둔다. 그래서
문구를 하나 늘리면 사전 네 개가 같이 늘어야 하는데, 빠뜨려도 화면은 원문(한국어)이나
키 문자열로 그냥 떠서 아무도 모른다 — 그 누락을 여기서 잡는다. 목록을 손으로 적지 않고
JS·HTML 에서 뽑아 대조하므로 화면에 새 문구가 생기면 이 테스트가 자동으로 같이 늘어난다.
"""
import glob
import json
import os
import pathlib
import re
import subprocess
import sys
import unittest

import server
from app.constants import DB_PATH_ENV, DEFAULT_LANGUAGE, LANGUAGES
from app.errors import Validation
from app.repositories import settings as settings_repo
from tests.support import temp_db, temp_db_path

ROOT = pathlib.Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"
LANG_DIR = STATIC / "lang"
INDEX = STATIC / "index.html"
DASH = ROOT / "dash.py"

# t("키") 호출. 여러 줄로 감싼 호출도 있어 파일 전체에서 찾는다
T_CALL = re.compile(r"""\bt\(\s*(["'])([\w.]+)\1""", re.S)
LINE_COMMENT = re.compile(r"^\s*//.*$", re.M)
# index.html 의 data-i18n="키" 와 data-i18n-<속성>="키"
HTML_KEY = re.compile(r'data-i18n(?:-[a-z-]+)?="([\w.]+)"')
# static/js/i18n.js 의 언어 코드 목록
CODE = re.compile(r'code:\s*"([a-z]+)"')
PLACEHOLDER = re.compile(r"\{(\w+)\}")


def js_keys():
    found = []
    for path in sorted(glob.glob(str(STATIC / "js" / "*.js"))):
        text = LINE_COMMENT.sub("", pathlib.Path(path).read_text(encoding="utf-8"))
        found += [match.group(2) for match in T_CALL.finditer(text)]
    return found


def html_keys():
    return HTML_KEY.findall(INDEX.read_text(encoding="utf-8"))


def used_keys():
    return sorted(set(js_keys() + html_keys()))


def dictionary(code):
    return json.loads((LANG_DIR / f"{code}.json").read_text(encoding="utf-8"))


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.con = temp_db()

    def test_defaults_to_source_language(self):
        self.assertEqual(settings_repo.language(self.con), DEFAULT_LANGUAGE)

    def test_set_and_read_back(self):
        for code in LANGUAGES:
            with self.subTest(code=code):
                settings_repo.set_language(self.con, code)
                self.assertEqual(settings_repo.language(self.con), code)

    def test_rejects_unknown_code(self):
        for code in ("", None, "kr", "en-US", "ko ko"):
            with self.subTest(code=code):
                with self.assertRaises(Validation):
                    settings_repo.set_language(self.con, code)

    def test_broken_value_falls_back_instead_of_blanking_the_screen(self):
        """meta 를 손으로 고쳐도 화면은 떠야 한다 — 없는 사전을 부르면 문구가 다 사라진다"""
        settings_repo.set_language(self.con, "en")
        self.con.execute("UPDATE meta SET value='xx' WHERE key='language'")
        self.assertEqual(settings_repo.language(self.con), DEFAULT_LANGUAGE)


class RouteTest(unittest.TestCase):
    def setUp(self):
        self.con = temp_db()

    def test_get_returns_current_language(self):
        payload = server.route(self.con, "GET", "/api/settings", {}, {})
        self.assertEqual(payload, {"language": DEFAULT_LANGUAGE})

    def test_patch_saves_and_returns_same_shape(self):
        payload = server.route(self.con, "PATCH", "/api/settings", {}, {"language": "ja"})
        self.assertEqual(payload, {"language": "ja"})
        self.assertEqual(settings_repo.language(self.con), "ja")

    def test_patch_rejects_unknown_code(self):
        with self.assertRaises(Validation):
            server.route(self.con, "PATCH", "/api/settings", {}, {"language": "kr"})

    def test_dictionaries_are_served(self):
        """화면이 fetch 로 읽는다. 확장자가 막혀 있으면 문구가 통째로 안 나온다"""
        for code in LANGUAGES:
            with self.subTest(code=code):
                resolved = server.resolve_static(f"/lang/{code}.json")
                self.assertTrue(resolved and os.path.isfile(resolved))


class CliTest(unittest.TestCase):
    """초기 설정 때 Claude 가 부르는 경로. 웹과 같은 값을 보는지까지 본다"""

    def setUp(self):
        self.path = temp_db_path()

    def _run(self, *args):
        return subprocess.run(
            [sys.executable, str(DASH), "language", *args],
            capture_output=True,
            text=True,
            env={**os.environ, DB_PATH_ENV: self.path},
            cwd=str(ROOT),
        )

    def test_prints_current_and_sets(self):
        self.assertEqual(self._run().stdout.strip(), DEFAULT_LANGUAGE)
        self.assertEqual(self._run("zh").stdout.strip(), "zh")
        self.assertEqual(self._run().stdout.strip(), "zh")
        self.assertEqual(settings_repo.language(temp_db(self.path)), "zh")

    def test_rejects_unknown_code(self):
        self.assertNotEqual(self._run("kr").returncode, 0)


class DictionaryTest(unittest.TestCase):
    def test_language_codes_match_between_python_and_screen(self):
        """둘이 갈라지면 설정 탭에 고를 수 있는데 서버가 거부하는 언어가 생긴다"""
        found = CODE.findall((STATIC / "js" / "i18n.js").read_text(encoding="utf-8"))
        self.assertEqual(tuple(found), LANGUAGES)

    def test_regex_still_finds_the_keys(self):
        """작성 방식이 바뀌어 0 건을 검사하게 되면 아래 테스트가 조용히 통과한다"""
        self.assertGreater(len(used_keys()), 100)
        self.assertGreater(len(html_keys()), 10)

    def test_every_used_key_exists_in_every_language(self):
        keys = used_keys()
        for code in LANGUAGES:
            entries = dictionary(code)
            missing = [key for key in keys if key not in entries]
            with self.subTest(code=code):
                self.assertEqual(missing, [], f"{code}.json 에 없는 키: {missing}")

    def test_languages_have_the_same_keys(self):
        """한 언어에만 넣고 잊는 것을 막는다. 화면이 안 쓰는 키(서버 오류 문구)도 함께 본다"""
        base = sorted(dictionary(DEFAULT_LANGUAGE))
        for code in LANGUAGES:
            with self.subTest(code=code):
                self.assertEqual(sorted(dictionary(code)), base)

    def test_no_unused_key(self):
        """서버 오류 문구(error.*)는 화면 코드에 없다 — api.js 가 한국어 응답을 사전에서
        되짚어 찾기 때문이다. 그 외에 안 쓰는 키가 쌓이면 사전이 화면과 어긋난 채 자란다"""
        unused = [
            key
            for key in dictionary(DEFAULT_LANGUAGE)
            if key not in set(used_keys()) and not key.startswith("error.")
        ]
        self.assertEqual(unused, [])

    def test_placeholders_survive_translation(self):
        """{count} 를 빠뜨리면 그 언어에서만 숫자가 사라진다"""
        korean = dictionary(DEFAULT_LANGUAGE)
        for code in LANGUAGES:
            for key, value in dictionary(code).items():
                with self.subTest(code=code, key=key):
                    self.assertEqual(
                        sorted(PLACEHOLDER.findall(value)),
                        sorted(PLACEHOLDER.findall(korean[key])),
                        f"{code}.json: {key}",
                    )

    def test_nothing_is_left_untranslated(self):
        """복사만 해두고 번역을 안 한 항목 찾기. 사람 이름·고유명사는 같아도 되지만
        문장이 통째로 한국어면 그건 빠뜨린 것이다"""
        korean = dictionary(DEFAULT_LANGUAGE)
        for code in LANGUAGES:
            if code == DEFAULT_LANGUAGE:
                continue
            same = [
                key
                for key, value in dictionary(code).items()
                if re.search(r"[가-힣]", value) and value == korean[key]
            ]
            with self.subTest(code=code):
                self.assertEqual(same, [], f"{code}.json 이 한국어 그대로인 키: {same}")


if __name__ == "__main__":
    unittest.main()
