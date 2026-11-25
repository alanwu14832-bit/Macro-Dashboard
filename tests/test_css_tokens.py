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


if __name__ == "__main__":
    unittest.main()
