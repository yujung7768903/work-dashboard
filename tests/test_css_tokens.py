"""CSS 토큰 린트. 간격·글자 크기를 값으로 직접 박는 회귀를 막는다.

app.css 의 :root 가 유일한 출처이고, 아래 속성들은 var(...) 로만 쓴다.
width·height·box-shadow·border 같은 그래픽 치수는 격자와 무관하므로 검사하지 않는다.
"""
import pathlib
import re
import unittest

CSS_DIR = pathlib.Path(__file__).resolve().parent.parent / "static" / "css"
TOKEN_ONLY = ("font-size", "padding", "margin", "gap", "row-gap", "column-gap",
              "border-radius", "line-height")
COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
DECL = re.compile(r"(--)?([a-z][a-z0-9-]*)\s*:\s*([^;{}]+)")  # --sp-12 처럼 숫자가 든 이름 포함
# 스케일 토큰 접두어. 이 이름으로 정의된 것만 참조 검사 대상
SCALES = ("--sp-", "--fs-", "--lh-", "--r-", "--gap", "--pad-", "--icon-", "--side-")


def _body(name):
    return COMMENT.sub("", (CSS_DIR / name).read_text(encoding="utf-8"))


def raw_px(name):
    """토큰 없이 px 를 직접 쓴 선언을 모은다."""
    found = []
    for custom, prop, value in DECL.findall(_body(name)):
        if custom or not prop.startswith(TOKEN_ONLY):
            continue
        if "px" in value and "var(" not in value:
            found.append(f"{prop}: {value.strip()}")
    return found


def declared_scale(name):
    return {f"--{prop}" for custom, prop, _ in DECL.findall(_body(name))
            if custom and f"--{prop}".startswith(SCALES)}


def referenced_scale(name):
    return {token for token in re.findall(r"var\((--[a-z0-9-]+)", _body(name))
            if token.startswith(SCALES)}


class CssTokenTest(unittest.TestCase):
    def test_no_raw_px_in_spacing_and_type(self):
        for name in ("app.css", "usage.css"):
            with self.subTest(name):
                self.assertEqual(raw_px(name), [])

    def test_every_referenced_token_is_defined(self):
        defined = declared_scale("app.css")
        used = referenced_scale("app.css") | referenced_scale("usage.css")
        self.assertEqual(sorted(used - defined), [])

    def test_spacing_scale_stays_on_grid(self):
        """간격은 4px 격자 + 2px 반 칸만. 6·9·10·11·14 같은 사이값이 다시 늘면 실패한다."""
        steps = [int(px) for px in re.findall(r"--sp-\d+:\s*(\d+)px", _body("app.css"))]
        self.assertTrue(steps)
        self.assertTrue(all(step == 2 or step % 4 == 0 for step in steps), steps)

    def test_font_scale_stays_at_five_steps(self):
        """글자 단이 다섯 개를 넘어가면 실패한다."""
        sizes = re.findall(r"--fs-[a-z]+:\s*(\d+)px", _body("app.css"))
        self.assertEqual(sorted(int(size) for size in sizes), [9, 11, 13, 20, 32])

    def test_baseline_alignment_does_not_spread(self):
        """줄 정렬에 baseline 을 새로 쓰지 않는다.

        baseline 은 글자가 없는 요소(손잡이·아이콘)를 위로, 작은 글자(배지·경과)를
        아래로 밀어 한 줄로 안 읽힌다. 자율 수행 목록이 그렇게 어긋났고, DOM 구조
        검사로는 안 잡혀 사람이 화면을 보고서야 알았다 — 그래서 여기서 막는다.

        아래 목록은 그 전부터 있던 자리다. 화면을 보고 하나씩 정리할 대상이지
        옳다고 인정한 예외가 아니다. 줄이는 것은 되고 늘리는 것은 안 된다
        """
        legacy = {
            "app.css": {".ws-head", "#session-list li", ".log-list li"},
            "usage.css": {
                ".u-week-head", ".u-lim-row", ".u-lim-row .u-delta", ".u-reset",
                ".u-rows > div", ".u-tip-row", ".u-rail-head", ".u-sess-scope",
            },
        }
        for name, allowed in legacy.items():
            found = {
                selector.strip()
                for selector, body in re.findall(r"([^{}]+)\{([^{}]*)\}", _body(name))
                if "align-items: baseline" in body
            }
            with self.subTest(name):
                self.assertEqual(sorted(found - allowed), [])
