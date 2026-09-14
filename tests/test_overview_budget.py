"""總覽的版面預算。

這一頁在四個月內被抱怨過兩次「東西太多」。第一次的修法是把表格收進摺疊，
第二次（本案）是刪掉一半的區塊。第三次不該再靠記性——所以預算寫成會擋人的
程式：結構超標讓建置失敗，字數超標印警告。

這個測試釘的是計數邏輯本身。真正的把關在 build.py，因為它要拿真實資料
渲染出來的 body 去量。
"""
from __future__ import annotations

import unittest

from macro.render.pages import overview


SECTION = '<section id="x"><div class="section-head"><h2>t</h2></div>{}</section>'


class Measure(unittest.TestCase):
    def test_counts_the_five_dimensions(self):
        body = SECTION.format(
            '<table><tr></tr></table>'
            '<div class="stat"></div><div class="key"></div>'
            '<div class="mc-cell"></div>'
            '<details class="acc"><summary>s</summary>'
            '<div class="acc-body">收起來的內容</div></details>')
        used = overview.measure(body)
        self.assertEqual(used["sections"], 1)
        self.assertEqual(used["tables"], 1)
        self.assertEqual(used["cells"], 3)

    def test_collapsed_bodies_do_not_count_as_visible(self):
        """摺疊裡的字不算可見——否則「收起來」就能繞過字數預算。"""
        open_text = SECTION.format("<p>看得見的字</p>")
        hidden = SECTION.format(
            '<details class="acc"><summary>標題</summary>'
            '<div class="acc-body">' + "很長的內容" * 50 + '</div></details>')
        self.assertLess(overview.measure(hidden)["visible_chars"],
                        overview.measure(open_text)["visible_chars"] + 40)

    def test_news_disclosures_are_a_named_exception(self):
        """要聞是一份清單的行內展開，不是十二個獨立摺疊面板。

        把它們算進摺疊配額的話，配額會被一個「只出標題」的改動吃光——
        而那個改動正是為了讓頁面變短。所以具名扣除，不是偷偷放行。
        """
        body = SECTION.format('<details class="bf-d"></details>'
                              * overview.NEWS_DISCLOSURES)
        self.assertEqual(overview.measure(body)["accordions"], 0)


class Enforcement(unittest.TestCase):
    def test_structural_overflow_is_hard(self):
        body = SECTION.format("") * (overview.BUDGET["sections"] + 1)
        hard, _soft = overview.budget_report(body)
        self.assertTrue(any("sections" in h for h in hard))

    def test_text_overflow_is_only_a_warning(self):
        """字數隨訊號條數與新聞長度浮動。用硬失敗擋它，代價是網站因為版面
        預算而停止更新資料——那比版面變長嚴重得多。"""
        body = SECTION.format("<p>" + "字" * (overview.VISIBLE_CHARS_SOFT + 100) + "</p>")
        hard, soft = overview.budget_report(body)
        self.assertEqual(hard, [])
        self.assertTrue(soft)

    def test_within_budget_is_silent(self):
        hard, soft = overview.budget_report(SECTION.format("<p>短</p>"))
        self.assertEqual((hard, soft), ([], []))


if __name__ == "__main__":
    unittest.main()
