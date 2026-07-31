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
