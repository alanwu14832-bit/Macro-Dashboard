"""發布落點頁。

最容易默默壞掉的是「追蹤清單加了新指標，但沒人幫它做落點頁」：推播照發、
使用者點開卻掉到索引頁。所以把兩份清單釘在一起。
"""
from __future__ import annotations

import unittest

from macro.compute import freshness
from macro.render.pages import release


SCENARIO = {
    "name": "通膨未解", "regime_label": "通膨優先",
    "employment_label": "放緩", "inflation_label": "偏高",
    "bands": {"inflation": {"low": 2.3, "high": 2.8}},
}


class TrackedAndLandingsStayInSync(unittest.TestCase):
    def test_every_tracked_series_has_a_landing_page(self):
        tracked = {sid for sid, _n, _m, _r in freshness.TRACKED}
        missing = tracked - set(release.SPECS)
        self.assertFalse(missing, f"這些追蹤指標沒有落點頁：{missing}")

    def test_no_landing_page_for_untracked_series(self):
        tracked = {sid for sid, _n, _m, _r in freshness.TRACKED}
        extra = set(release.SPECS) - tracked
        self.assertFalse(extra, f"這些落點頁沒有對應的追蹤指標：{extra}")

    def test_every_spec_declares_what_it_feeds(self):
        """「這個數字進到本站的哪裡」是這一頁存在的理由，不能留空。"""
        for sid, spec in release.SPECS.items():
            self.assertTrue(spec.get("feeds"), sid)
            self.assertIn(spec["mode"], ("level", "yoy", "diff"), sid)


class VerdictBand(unittest.TestCase):
    def test_says_unchanged_instead_of_rendering_an_empty_shell(self):
        same = {"scenario": {"employment": "放緩", "inflation": "偏高",
                             "regime": "通膨優先"}}
        html = release._verdict_band({}, SCENARIO, same)
        self.assertIn("判定未變", html)
        self.assertNotIn("判定換檔", html)

    def test_reports_the_move_without_claiming_causation(self):
        moved = {"scenario": {"employment": "持穩", "inflation": "偏高",
                              "regime": "通膨優先"}}
        html = release._verdict_band({}, SCENARIO, moved)
        self.assertIn("判定換檔", html)
        self.assertIn("持穩 → 放緩", html)
        # 不能說成「這個數字造成了換檔」
        self.assertIn("不是唯一原因", html)


class Thresholds(unittest.TestCase):
    def test_distance_rows_only_for_series_that_feed_a_band(self):
        reading = {"value": 3.3}
        self.assertIn("離門檻還差多少",
                      release._threshold_rows("PCEPILFE", release.SPECS["PCEPILFE"],
                                              reading, SCENARIO))
        self.assertEqual("",
                         release._threshold_rows("DGS10", release.SPECS["DGS10"],
                                                 reading, SCENARIO))


class HonestGaps(unittest.TestCase):
    def test_consensus_gap_is_stated(self):
        self.assertIn("沒有市場共識預期", release.NO_CONSENSUS)
        self.assertIn("不說", release.NO_CONSENSUS)


if __name__ == "__main__":
    unittest.main()
