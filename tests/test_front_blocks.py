"""頭版的三條規矩。壞了不會報錯，只會讓版面說謊，所以釘在這裡。

  1. 螢光筆只標「跟上一期不一樣」。離門檻多遠、幾天後公布也寫在頁邊，但不准上色；
     沒有變動的那一天，頁邊不准是黃的。
  2. 尺有兩種：有寫死門檻的才有刻度與格位；區間尺沒有刻度，也不准塗「移動」以外的東西。
  3. 頭版的段落標題帶責任印，側欄目錄與站內搜尋靠 data-title 找到它們。
"""
from __future__ import annotations

import unittest

from macro.render.layout import extract_sections
from macro.render.pages import front_blocks as front

BASE = dict(lo=1.5, hi=4.0, kind="threshold", step=0.1, ticks=[(2.3, "2.3"), (2.8, "2.8")],
            zones=[(1.5, 2.3, "低"), (2.3, 2.8, "中"), (2.8, 5.0, "高")])


class Highlighter(unittest.TestCase):
    def test_unchanged_reading_is_never_highlighted(self):
        html = front.ruler(now=3.0, prev=3.0, **BASE)
        self.assertNotIn("rm-move", html)
        self.assertNotIn("rm-prev", html)

    def test_missing_prior_is_not_treated_as_a_change(self):
        self.assertNotIn("rm-move", front.ruler(now=3.0, prev=None, **BASE))

    def test_a_move_is_drawn_between_the_two_readings(self):
        html = front.ruler(now=3.0, prev=2.9, **BASE)
        self.assertIn("rm-move", html)
        self.assertIn("rm-prev", html)

    def test_margin_note_is_coloured_only_for_a_change(self):
        gap = {"value": "0.21", "what": "離下一格", "unit": "個百分點"}
        changed = {"change": {"change": 0.07, "was": 5.21, "now": 5.28}, "gap": gap}
        distance = {"change": None, "gap": gap}
        nothing = {"change": None, "gap": None}
        self.assertIn('class="mn chg"', front._fact_note(changed, "2026-10-09"))
        self.assertIn("+0.07", front._fact_note(changed, "2026-10-09"))
        self.assertIn('class="mn"', front._fact_note(distance, "2026-10-09"))
        self.assertNotIn("chg", front._fact_note(distance, "2026-10-09"))
        self.assertIn("未變", front._fact_note(nothing, "2026-10-09"))

    def test_quiet_day_has_no_list_and_no_yellow(self):
        html = front.since_block([], {"date": "2026-10-09"}, False)
        self.assertNotIn('class="d"', html)
        self.assertIn("相同", html)


class Rulers(unittest.TestCase):
    def test_threshold_ruler_has_graduations_and_marks_the_current_zone(self):
        html = front.ruler(now=3.0, **BASE)
        self.assertIn("--step:", html)
        self.assertIn('<i class="rz on"', html)
        self.assertEqual(html.count('class="rz on"'), 1)
        self.assertIn(">高</i>", html[html.index('class="rz on"'):])

    def test_range_ruler_has_no_graduations(self):
        """區間的兩端不是規則。畫上刻度，它看起來就像一道門檻。"""
        html = front.ruler(lo=3.9, hi=5.4, now=5.28, kind="range", step=0.1,
                           ticks=[(3.97, "3.97 一年低點"), (5.31, "5.31 一年高點")])
        self.assertIn("ruler-range", html)
        self.assertNotIn("--step:", html)

    def test_missing_reading_draws_a_dash_not_an_empty_ruler(self):
        html = front.ruler(lo=0, hi=1, now=None)
        self.assertIn("—", html)
        self.assertNotIn("rm-now", html)

    def test_reference_label_yields_to_the_reading_when_they_collide(self):
        """參考點（2% 目標）跟現在的讀數太近時，只留讀數的小旗；空心刻度還在。"""
        far = front.ruler(now=3.0, refs=[(2.0, "目標 2%")], **BASE)
        near = front.ruler(now=2.05, refs=[(2.0, "目標 2%")], **BASE)
        self.assertIn("目標 2%", far)
        self.assertNotIn("目標 2%", near)
        self.assertIn('class="rr', near)


class Sections(unittest.TestCase):
    def test_front_page_sections_are_found_by_their_data_title(self):
        body = (front.sec_open("facts", "四個數字", kind="實") + "</section>"
                + front.sec_open("voices", "別人怎麼說", kind="聞", cls="said") + "</section>")
        self.assertEqual(extract_sections(body), [("facts", "四個數字", 1), ("voices", "別人怎麼說", 1)])

    def test_each_responsibility_has_its_own_seal(self):
        self.assertEqual(len({front.seal(k) for k in "實判市聞缺"}), 5)

    def test_empty_margin_emits_nothing(self):
        """空的頁邊就是「沒變」——連一個空的 .m 都不輸出。"""
        self.assertNotIn('class="m"', front.row("<p>正文</p>"))
        self.assertIn('class="m"', front.row("<p>正文</p>", front.note("還差 <i>0.21</i>")))


if __name__ == "__main__":
    unittest.main()


class HeroRendersEveryKindOfLede(unittest.TestCase):
    """頭條有六種來源。平常只走得到「情境判定」那一條，其餘五條要等到決議日或數據日
    才會執行——那正是網站最不能壞的日子，所以每一種都先在這裡畫一遍。"""

    SCENARIO = {"name": "通膨未解", "regime": "inflation_first",
                "regime_explain": "依本站規則通膨仍屬高（核心 PCE 年增 3.0%），但近三月年化 2.0% 已經降溫；這是本站的分類，不是聯準會的決策門檻",
                "employment_label": "中", "inflation_label": "高", "regime_label": "通膨優先",
                "transitions": [{"name": "通膨由「高」轉「中」", "need": "核心 PCE 需降至 2.8% 以下",
                                 "gap": 0.21, "unit": "個百分點"}]}
    SUMMARY = {"total": 15, "dovish": 7, "hawkish": 4, "neutral": 4}

    def render(self, *events, verdict="今天沒有重大數據或政策決議。"):
        from macro.data import Bundle
        ctx = {"events": {"events": list(events), "verdict": verdict}, "_bundle": Bundle(),
               "rates": {"stance": {"market_implies": "市場定價未來一至二年升息"}}, "fedfunds": None}
        return front.hero(ctx, self.SCENARIO, self.SUMMARY, {}, [], {"date": "2026-10-09"})

    @staticmethod
    def event(kind, tag, title, **extra):
        return {"kind": kind, "tag": tag, "title": title, "today": True, "detail": "細節。",
                "href": "/fed/", **extra}

    def test_quiet_day_is_the_verdict_with_the_quiet_line(self):
        html, changed = self.render()
        self.assertIn("lede-verdict", html)
        self.assertIn("今天沒有重大數據或政策決議。", html)
        self.assertIn(">判</span>", html)
        self.assertFalse(changed)

    def test_decision_takes_the_headline_and_the_verdict_moves_below(self):
        html, _ = self.render(self.event("policy", "FOMC　政策轉向",
                                         "聯準會升息 1 碼　3.50%–3.75% → 3.75%–4.00%", policy="轉向"))
        self.assertIn("lede-policy", html)
        self.assertIn("聯準會升息 1 碼", html)
        self.assertIn("3.50%–3.75% → 3.75%–4.00%", html)
        self.assertIn(">實</span>", html)
        self.assertIn("目前情境", html)                 # 常設的判定沒有消失，退到頭條底下
        self.assertIn("通膨未解，物價仍是主要矛盾。", html)

    def test_missing_decision_is_marked_as_a_gap(self):
        html, _ = self.render(self.event("policy", "FOMC　決議遺漏", "9/16 FOMC決議本站沒有取得",
                                         policy="遺漏"))
        self.assertIn("lede-gap", html)
        self.assertIn(">缺</span>", html)

    def test_pending_decision_and_data_days_render(self):
        for event in (self.event("policy", "FOMC　今晚公布", "FOMC利率決議", policy="待公布"),
                      self.event("data", "美國數據　已公布", "CPI", id="CPIAUCSL"),
                      self.event("data", "美國數據　今晚公布", "非農就業", id="PAYEMS")):
            html, _ = self.render(event)
            self.assertIn(event["title"], html)
            self.assertIn('id="lede"', html)
