"""頭版頁邊「自上一期以來」的排序與措辭。

排序是判斷的輕重，不是時間：換格 > 新訊號 > 讀數 > 訊號退場。這個順序一旦悄悄變了，
第一眼看到的就不再是最重要的那件事——而頁邊那一欄存在的理由就是「第一眼」。

另一件要釘住的事：頁邊是黃的＝有東西變了。沒變動的那一天不准出現任何變動項目，
第一次建置也不准說成「沒有變動」。
"""
from __future__ import annotations

import unittest

from macro.render.pages import front_blocks as front

SCENARIO = {"employment_label": "放緩", "inflation_label": "偏高", "regime_label": "通膨優先"}
PRIOR = {"date": "2026-09-13",
         "scenario": {"employment": "持穩", "inflation": "偏高", "regime": "通膨優先"}}
READING = {"name": "10 年期公債", "unit": "%", "was": 4.1, "now": 4.3, "change": 0.2}


class Ordering(unittest.TestCase):
    def names(self, diff, readings, prior=None):
        return [i["name"] for i in front.since_items(diff, readings, SCENARIO, prior)]

    def test_regime_change_outranks_everything(self):
        items = front.since_items({"added": [{"headline": "高嚴重訊號", "severity": "high"}]},
                                  [READING], SCENARIO, PRIOR)
        self.assertEqual(items[0]["name"], "就業換格")
        self.assertEqual(items[0]["big"], "持穩→放緩")

    def test_new_signals_before_reading_changes(self):
        self.assertEqual(self.names({"added": [{"headline": "訊號"}]}, [READING]),
                         ["新增訊號", "10 年期公債"])

    def test_removed_signals_rank_last(self):
        self.assertEqual(self.names({"added": [{"headline": "新"}], "removed": [{"headline": "舊"}]},
                                    [READING])[-1], "不再觸發")

    def test_unchanged_scenario_produces_nothing(self):
        same = {"scenario": {"employment": "放緩", "inflation": "偏高", "regime": "通膨優先"}}
        self.assertEqual(front.since_items({}, [], SCENARIO, same), [])

    def test_several_new_signals_collapse_into_one_count(self):
        """頁邊一列一件事。九條新訊號是「+9」一列，不是九列。"""
        added = [{"headline": f"訊號 {i}"} for i in range(9)]
        items = front.since_items({"added": added}, [], SCENARIO, None)
        self.assertEqual((len(items), items[0]["big"]), (1, "+9"))
        self.assertIn("等 9 條", items[0]["ft"])


class Figures(unittest.TestCase):
    def test_delta_carries_its_sign_and_a_real_minus(self):
        up = front.since_items({}, [READING], SCENARIO, None)[0]
        down = front.since_items({}, [dict(READING, change=-0.2, now=3.9)], SCENARIO, None)[0]
        self.assertEqual(up["big"], "+0.20")
        self.assertEqual(down["big"], "−0.20")
        self.assertIn("4.10 →", up["ft"])
        self.assertIn("4.30%", up["ft"])

    def test_large_moves_drop_pointless_decimals(self):
        """兩千人的變動寫成「−2,000」，不是「−2,000.00」。"""
        item = front.since_items({}, [{"name": "初領失業金", "unit": "", "was": 199000,
                                       "now": 197000, "change": -2000}], SCENARIO, None)[0]
        self.assertEqual(item["big"], "−2,000")


class Wording(unittest.TestCase):
    def test_first_run_says_so_instead_of_claiming_no_change(self):
        html = front.since_block([], None, True)
        self.assertIn("第一期", html)
        self.assertNotIn("相同", html)

    def test_no_change_names_the_comparison_date(self):
        """比的是哪一天要寫出來——archive.previous() 取的是上一個存檔日，
        每小時建置會同日覆寫，不寫日期會讓人以為比的是一小時前。"""
        html = front.since_block([], PRIOR, False)
        self.assertIn("與 2026-09-13 相同", html)
        self.assertNotIn("<ol>", html)

    def test_overflow_links_to_the_full_list(self):
        items = [{"big": "+0.01", "name": f"讀數 {i}", "ft": ""} for i in range(6)]
        html = front.since_block(items, PRIOR, False)
        self.assertEqual(html.count("<li>"), 4)
        self.assertIn("看全部 6 項", html)
        self.assertIn('href="/archive/#today"', html)


if __name__ == "__main__":
    unittest.main()
