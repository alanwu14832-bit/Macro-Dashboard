"""樣式檔的 token 規矩。全部不連網，只讀 macro/render/static/ 底下的 CSS。

會靜默出錯的地方：狀態色（good／warning／serious／critical）是給圓點、色條、邊框用的，
直接拿來當文字在紙色上不到 4.5:1——頁面看起來正常，只是那幾個字偏淡。2026-11-25
實測：紅字日報 4.35、夜報 3.74，綠 3.0，黃 1.7。當字用要取 `-ink` 那一組。
"""
from __future__ import annotations

import os
import re
import unittest

STATIC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "macro", "render", "static")
STATUS = ("good", "warning", "serious", "critical")


def read(name: str) -> str:
    with open(os.path.join(STATIC, name), encoding="utf-8") as handle:
        return re.sub(r"/\*.*?\*/", "", handle.read(), flags=re.S)


def luminance(hex_color: str) -> float:
    channels = [int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(a: str, b: str) -> float:
    la, lb = luminance(a), luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def theme_blocks(css: str) -> dict[str, str]:
    """日報、夜報（跟著系統）、夜報（手動切換）三段 token 定義。"""
    light = css[css.index(":root {"):css.index("@media (prefers-color-scheme: dark)")]
    system = css[css.index(':root:not([data-theme="light"]) {'):css.index(':root[data-theme="dark"] {')]
    manual = css[css.index(':root[data-theme="dark"] {'):]
    return {"日報": light, "夜報（系統）": system, "夜報（手動）": manual[:manual.index("}")]}


def token(block: str, name: str) -> str | None:
    found = re.search(r"--%s:\s*(#[0-9a-fA-F]{6})\b" % re.escape(name), block)
    return found.group(1) if found else None


class TestStatusColoursAsText(unittest.TestCase):
    def test_status_colours_are_never_used_as_text(self):
        for name in ("style.css", "margin.css"):
            css = read(name)
            for status in STATUS:
                # 也擋 border-color：邊框跟字同色的地方（印、旗標）兩個要一起換
                hits = re.findall(r"[^{};]*color:\s*var\(--%s\)" % status, css)
                self.assertEqual(hits, [], f"{name}：--{status} 當文字用，改用 --{status}-ink")

    def test_ink_shades_pass_on_every_surface_in_every_theme(self):
        blocks = theme_blocks(read("style.css"))
        light = blocks["日報"]
        for theme, block in blocks.items():
            surfaces = [token(block, s) or token(light, s) for s in ("page", "surface", "surface-sunken")]
            for status in STATUS:
                ink = token(block, f"{status}-ink")
                self.assertIsNotNone(ink, f"{theme} 沒有定義 --{status}-ink")
                for surface in surfaces:
                    self.assertGreaterEqual(contrast(ink, surface), 4.5,
                                            f"{theme} --{status}-ink {ink} 在 {surface} 上不到 4.5:1")

    def test_text_on_the_good_fill_passes(self):
        light = theme_blocks(read("style.css"))["日報"]
        self.assertGreaterEqual(contrast(token(light, "on-good"), token(light, "good")), 4.5)


def declarations(css: str):
    """(選擇器, 屬性, 值)，不含 token 定義（-- 開頭的自訂屬性）。"""
    for selector, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        if selector.strip().startswith("@font-face"):      # 字型檔的字重範圍（200 800）不是樣式
            continue
        for item in body.split(";"):
            prop, sep, value = item.partition(":")
            prop, value = prop.strip().lower(), " ".join(value.split())
            if sep and prop and not prop.startswith("--"):
                yield " ".join(selector.split())[-60:], prop, value.replace(" !important", "")


SPACING = re.compile(r"^(margin|padding)(-(top|right|bottom|left|block|inline)(-(start|end))?)?$|^(row-|column-)?gap$")


class TestInnerPagesUseTokens(unittest.TestCase):
    """內頁（style.css）的字級、行高、字重、間距只能取 token。

    會靜默出錯的地方：寫死一個 13.5px 或 7px 不會壞任何東西，只是每多一個，全站就多一種
    字級或間距。2026-11-26 收斂前這份檔案有 16 種行高、8 種字重、39 種間距。
    """

    def setUp(self):
        self.rows = list(declarations(read("style.css")))

    def test_font_sizes(self):
        bad = [(sel, value) for sel, prop, value in self.rows if prop == "font-size"
               and not re.fullmatch(r"var\(--(t-\d+|d-\d)\)|inherit|[\d.]+em|clamp\(.+\)", value)
               and not (sel == "body" and value == "0.9375rem")]      # 根字級：跟著使用者的字體設定走
        self.assertEqual(bad, [], "字級要用 --t-*（em 的相對大小與 clamp() 的流動字級例外）")

    def test_line_heights(self):
        bad = [(sel, value) for sel, prop, value in self.rows if prop == "line-height"
               and not re.fullmatch(r"var\(--(lh-\d+|lead-[a-z]+)\)|inherit|normal", value)]
        self.assertEqual(bad, [], "行高要用 --lh-*（單行）或 --lead-*（會折行的段落）")

    def test_font_weights(self):
        bad = [(sel, value) for sel, prop, value in self.rows if prop == "font-weight"
               and not re.fullmatch(r"var\(--w-[a-z]+\)|inherit|normal", value)]
        self.assertEqual(bad, [], "字重只有 --w-regular／medium／semibold／bold 四類")

    def test_spacing(self):
        bad = []
        for sel, prop, value in self.rows:
            if not SPACING.match(prop):
                continue
            plain = re.sub(r"\b(?:calc|max|min|clamp|env)\((?:[^()]|\([^()]*\))*\)", "", value)
            for px in re.findall(r"(?<![\w.-])(\d+(?:\.\d+)?)px", plain):       # 負值是光學修正，不算
                if float(px) not in (0.0, 1.0) and float(px) <= 64:
                    bad.append((sel, prop, value))
        self.assertEqual(bad, [], "間距要用 --s*／--m*（0、1px、負值、calc()／max() 裡的例外）")

    def test_scales_are_what_the_docs_say(self):
        light = theme_blocks(read("style.css"))["日報"]
        sizes = sorted(int(x) for x in re.findall(r"--t-(\d+):", light))
        self.assertEqual(sizes, [12, 13, 14, 15, 16, 18, 22, 30])
        spaces = sorted(int(x) for x in re.findall(r"--(?:s\d+|m\d+):\s*(\d+)px", light))
        self.assertEqual(spaces, [2, 4, 6, 8, 10, 12, 14, 16, 24, 32, 48, 64])
        self.assertEqual(len(re.findall(r"--lead-[a-z]+:", light)), 7)
        self.assertEqual(len(re.findall(r"--w-[a-z]+:", light)), 4)


class TestSkeletonUsesTokens(unittest.TestCase):
    """頭版與內頁骨架（margin.css）：18px 以下的固定字級、行高、字重取 token。

    19px 以上的固定字級與 clamp() 是展示字級，跟著視窗寬度那一套走，不在此限；間距還沒收斂。
    會靜默出錯的地方跟內頁一樣：多寫一個 13.5px 不會壞任何東西，只是又多一種字級
    （2026-11-26 收斂前，這份檔案 10.5 到 17.5px 之間有 15 種，半像素一階）。
    """

    def setUp(self):
        self.rows = list(declarations(read("margin.css")))

    def test_fixed_sizes_up_to_18px(self):
        bad = []
        for sel, prop, value in self.rows:
            if prop == "font-size":
                found = re.fullmatch(r"([\d.]+)px", value)
            elif prop == "font":
                found = re.search(r"(?:^|\s)([\d.]+)px/", value)
            else:
                continue
            if found and float(found.group(1)) <= 18:
                bad.append((sel, prop, value))
        self.assertEqual(bad, [], "18px 以下的固定字級要用 --t-*")

    def test_line_heights_and_weights(self):
        bad = [(sel, prop, value) for sel, prop, value in self.rows
               if (prop == "line-height" and not re.fullmatch(r"var\(--(lh-\d+|lead-[a-z]+)\)|inherit|normal", value))
               or (prop == "font-weight" and not re.fullmatch(r"var\(--[\w-]+\)|inherit|normal", value))]
        self.assertEqual(bad, [], "行高用 --lead-*／--lh-*，字重用 --w-*")

    def test_tokens_come_from_style_css(self):
        # margin.css 不另立一套：它用到的字級、行高、字重 token 都定義在 style.css
        defined = set(re.findall(r"(--(?:t-\d+|lead-[a-z]+|w-[a-z]+)):", read("style.css")))
        used = set(re.findall(r"var\((--(?:t-\d+|lead-[a-z]+|w-[a-z]+))\)", read("margin.css")))
        self.assertEqual(used - defined, set())


class TestExpenseApp(unittest.TestCase):
    """記帳頁（expense-app.css）是另一套設計系統，但同樣不准寫死。

    它只載入自己這一份樣式，所以 token 定義在自己檔案裡；字級用 rem（跟著使用者的字體
    設定縮放）。會靜默出錯的地方：次要文字太淡——頁面沒壞，只是每一列的小字讀起來吃力
    （2026-11-26 實測 --ink-muted 在紙色上 3.2:1）。
    """

    def setUp(self):
        self.css = read("expense-app.css")
        self.rows = list(declarations(self.css))

    def test_font_sizes(self):
        allowed = {"16px",     # 輸入框：16px 以下 iOS 會自動放大
                   "34px",     # 金額輸入的大數字
                   "9px"}      # 甜甜圈圖裡的 SVG 字，單位是 viewBox 的
        bad = []
        for sel, prop, value in self.rows:
            if prop != "font-size" or value in allowed:
                continue
            rem = re.fullmatch(r"([\d.]+)rem", value)
            if rem and float(rem.group(1)) >= 1.5:          # 展示字級
                continue
            if not re.fullmatch(r"var\(--t-\d+\)|inherit|[\d.]+em", value):
                bad.append((sel, value))
        self.assertEqual(bad, [])

    def test_line_heights_weights_and_spacing(self):
        bad = []
        for sel, prop, value in self.rows:
            if prop == "line-height" and not re.fullmatch(r"var\(--lead-[a-z]+\)|inherit|normal", value):
                bad.append((sel, prop, value))
            if prop == "font-weight" and not re.fullmatch(r"var\(--w-[a-z]+\)|inherit|normal", value):
                bad.append((sel, prop, value))
            if SPACING.match(prop):
                plain = re.sub(r"\b(?:calc|max|min|clamp|env)\((?:[^()]|\([^()]*\))*\)", "", value)
                if any(float(px) not in (0.0, 1.0) and float(px) <= 64
                       for px in re.findall(r"(?<![\w.])-?(\d+(?:\.\d+)?)px", plain)):
                    bad.append((sel, prop, value))
        self.assertEqual(bad, [])

    def test_every_token_it_uses_is_defined_in_this_file(self):
        used = set(re.findall(r"var\((--[\w-]+)", self.css))
        defined = set(re.findall(r"(--[\w-]+)\s*:", self.css))
        self.assertEqual(used - defined, set(), "記帳頁不載入 style.css，token 要自己定義")

    def test_muted_ink_passes_on_every_surface(self):
        blocks = theme_blocks(self.css)
        light = blocks["日報"]
        for theme, block in blocks.items():
            ink = token(block, "ink-muted")
            for name in ("page", "surface", "sunken"):
                surface = token(block, name) or token(light, name)
                self.assertGreaterEqual(contrast(ink, surface), 4.5, f"{theme} --ink-muted 在 {name} 上")

    def test_dimmed_text_is_gone(self):
        # 備註那一行原本是 muted 再打八折，日報 2.6:1；要淡就換 token，不要疊透明度
        body = self.css[self.css.index(".row-note"):]
        self.assertNotIn("opacity", body[:body.index("}")])


class TestChartLabelInk(unittest.TestCase):
    """圖表線尾的數字標籤跟著線的顏色走，但用的是那個顏色的文字色（--series-N-ink）。

    會靜默出錯的地方：線的顏色直接當字，圖表照樣畫得出來，只是日報的橘、青綠、紅在紙色上
    2.6–3.6:1（2026-11-25 實測 14 處）。新增序列色卻忘了加 -ink，chart.js 會退回線的顏色。
    """

    def test_every_series_colour_has_a_passing_ink_in_every_theme(self):
        blocks = theme_blocks(read("style.css"))
        light = blocks["日報"]
        slots = sorted(set(re.findall(r"--series-(\d):", light)) - {"1"})        # 1 是墨色
        self.assertEqual(slots, [str(n) for n in range(2, 9)])
        for theme, block in blocks.items():
            surfaces = [token(block, name) or token(light, name) for name in ("page", "surface")]
            for name in [f"series-{n}-ink" for n in slots] + ["neutral-ink"]:
                ink = token(block, name)
                self.assertIsNotNone(ink, f"{theme} 沒有定義 --{name}")
                for surface in surfaces:
                    self.assertGreaterEqual(contrast(ink, surface), 4.5, f"{theme} --{name} {ink} 在 {surface} 上")

    def test_chart_js_labels_use_the_ink(self):
        with open(os.path.join(STATIC, "chart.js"), encoding="utf-8") as handle:
            js = handle.read()
        self.assertIn("fill:${label.ink}", js)
        self.assertNotIn("fill:${label.color}", js)
        self.assertIn('cssVar(name + "-ink")', js)


if __name__ == "__main__":
    unittest.main()
