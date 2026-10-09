"""內頁的骨架與表格對齊。

內頁跟頭版共用同一條直線與刊頭，頁邊放本頁目錄。這裡釘兩件「壞了不會報錯」的事：
頁邊目錄跟頁面實際的區塊對不對得上，以及表格的文字欄有沒有被當成數字靠右排。
"""
from __future__ import annotations

import unittest

from macro.render import layout
from macro.render.html import section, table


class MarginContents(unittest.TestCase):
    def page(self, path="/taiwan/", nav_path=""):
        body = section("cycle", "景氣循環位置", "<p>x</p>") + section("ext", "外需", "<p>x</p>", sub=True)
        sections = {path: layout.extract_sections(body)}
        return layout.page(title="台灣總經", path=path, body=body, heading="台灣總經",
                           updated="最後更新 2026-10-10 01:00", sections=sections, nav_path=nav_path)

    def test_inner_page_lists_its_own_sections_in_the_margin(self):
        html = self.page()
        toc = html[html.index('class="pg-toc"'):html.index("</nav>", html.index('class="pg-toc"'))]
        self.assertIn('<a href="#cycle">景氣循環位置</a>', toc)
        self.assertIn('<a href="#ext" class="sub2">外需</a>', toc)

    def test_page_number_matches_the_front_page_contents(self):
        """頁碼跟頭版目錄同一套：NAV 裡有組別的項目依序編號。"""
        numbered = [href for href, _label, _icon, group in layout.NAV if group]
        expected = f"{numbered.index('/taiwan/') + 1:02d}"
        self.assertEqual(layout._page_number("/taiwan/")[0], expected)
        self.assertIn(f"<i>{expected}</i>", self.page())

    def test_article_pages_point_back_to_their_parent(self):
        html = self.page(path="/deep-dive/some-article/", nav_path="/deep-dive/")
        self.assertIn('<a href="/deep-dive/">← 深度專題</a>', html)

    def test_every_page_carries_the_masthead_and_the_wordmark_only_in_english(self):
        html = self.page()
        self.assertIn('class="mast row"', html)
        self.assertIn("<title>台灣總經｜At the Margin</title>", html)
        self.assertNotIn("邊際", html)

    def test_front_page_is_not_wrapped_as_an_inner_page(self):
        html = layout.page(title="頭版", path="/", body='<div class="fp"></div>', updated="x")
        self.assertIn('class="mg is-front"', html)
        self.assertNotIn('class="pg"', html)
        self.assertIn("<title>At the Margin</title>", html)


class TableAlignment(unittest.TestCase):
    def classes(self, rows, headers=("指標", "讀數", "說明", "資料日期"), **kw):
        html = table(list(headers), rows, **kw)
        first = html[html.index("<tbody><tr>"):html.index("</tr>", html.index("<tbody>"))]
        return [c.split('"')[0] for c in first.split('<td class="')[1:]]

    def test_text_columns_go_left_and_numbers_go_right(self):
        rows = [["外銷訂單", "49.7", "看減家數多於看增", "2026-08"],
                ["海關出口", '<span class="pos num">+52.6%</span>', "2,656 十億元", "2026-08"],
                ["工業生產", "+23.5%", "指數 146.0", "2026-08"]]
        self.assertEqual(self.classes(rows), ["", "num", "txt", "num"])

    def test_numbers_with_units_or_signs_still_count_as_numbers(self):
        rows = [["a", "−0.88", "2,656 十億元", "10/28"], ["b", "+0.50", "979.4 億美元", "12/9"]]
        self.assertEqual(self.classes(rows), ["", "num", "num", "num"])

    def test_dashes_do_not_turn_a_numeric_column_into_text(self):
        """缺值的破折號不算文字——不然一欄數字裡有幾個缺口，整欄就翻到左邊去了。"""
        rows = [["a", "—", "x"], ["b", "3.85%", "y"], ["c", '<span class="na">—</span>', "z"]]
        self.assertEqual(self.classes(rows, headers=("會議", "隱含利率", "備註")), ["", "num", "txt"])

    def test_explicit_text_columns_are_respected(self):
        rows = [["今天", "數據", "2330"], ["5 天後", "央行", "0050"]]
        self.assertEqual(self.classes(rows, headers=("時間", "類型", "代號"), text_cols=(2,)),
                         ["", "txt", "txt"])


if __name__ == "__main__":
    unittest.main()
