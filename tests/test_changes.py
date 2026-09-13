"""總覽最上面那疊「變動」的排序規則。

排序是判斷的輕重，不是時間。這個順序一旦悄悄變了，第一眼看到的就不再是
最重要的那件事，而整個區塊存在的理由就是「第一眼」。所以釘死。
"""
from __future__ import annotations

import unittest

from macro.render.pages.overview import _change_items, changes_top


SCENARIO = {
    "employment_label": "放緩",
    "inflation_label": "偏高",
    "regime_label": "通膨優先",
}
PRIOR = {"scenario": {"employment": "持穩", "inflation": "偏高",
                      "regime": "通膨優先"}}


class ChangeOrdering(unittest.TestCase):
    def test_regime_change_outranks_everything(self):
        items = _change_items(
            {"added": [{"headline": "高嚴重訊號", "severity": "high"}]},
            [{"name": "核心 PCE", "unit": "%", "was": 2.9, "now": 2.7, "change": -0.2}],
            SCENARIO, PRIOR)
        self.assertEqual(items[0]["tag"], "換格")
        self.assertIn("持穩 → 放緩", items[0]["title"])

    def test_high_severity_signal_before_reading_change(self):
        items = _change_items(
            {"added": [{"headline": "訊號", "severity": "high"}]},
            [{"name": "10 年期公債", "unit": "%", "was": 4.1, "now": 4.3, "change": 0.2}],
            SCENARIO, None)
        self.assertEqual([i["tag"] for i in items], ["新增訊號", "讀數變動"])

    def test_removed_signals_rank_last(self):
        items = _change_items(
            {"added": [{"headline": "新", "severity": "low"}],
             "removed": [{"headline": "舊"}]},
            [], SCENARIO, None)
        self.assertEqual(items[-1]["tag"], "不再觸發")

    def test_unchanged_scenario_produces_no_regime_item(self):
        same = {"scenario": {"employment": "放緩", "inflation": "偏高",
                             "regime": "通膨優先"}}
        items = _change_items({}, [], SCENARIO, same)
        self.assertEqual(items, [])

    def test_reading_delta_is_rendered_with_sign(self):
        items = _change_items(
            {}, [{"name": "失業率", "unit": "%", "was": 4.1, "now": 4.3,
                  "change": 0.2}], SCENARIO, None)
        self.assertIn("4.10 → 4.30%", items[0]["title"])
        self.assertIn("+0.20", items[0]["delta"])


class ChangeRendering(unittest.TestCase):
    def test_first_run_says_so_instead_of_claiming_no_change(self):
        html = changes_top({}, {"first_run": True}, [], SCENARIO, None)
        self.assertIn("第一次建置", html)
        self.assertNotIn("沒有變動", html)

    def test_overflow_links_to_the_full_list(self):
        added = [{"headline": f"訊號 {i}", "severity": "low"} for i in range(9)]
        html = changes_top({}, {"added": added}, [], SCENARIO, None)
        self.assertIn("看全部 9 項變動", html)
        self.assertIn('href="#changed"', html)
        # 只露出前 5 筆，其餘收在下面的完整比對區塊
        self.assertEqual(html.count('class="chg-row"'), 5)

    def test_scope_footer_is_always_present(self):
        for diff in ({}, {"added": [{"headline": "x", "severity": "high"}]}):
            self.assertIn("偵測範圍", changes_top({}, diff, [], SCENARIO, None))


if __name__ == "__main__":
    unittest.main()
