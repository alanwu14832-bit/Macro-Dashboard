"""頁面上的東西對決策有沒有用——2026-10-10 用 59 份存檔量過之後改的五件事。

量到的問題：頁邊 58 天裡有 41 天是黃的，真正該看的變動只有 9 天；一條 VIX 訊號
在門檻上進出了 10 次；比率類序列的「年增率」算成變動率；產業貢獻把子行業跟母行業
並列；好幾句說明把「一起動」寫成「因為」。這些都不會報錯。

  1. 螢光筆只標該看的變動：判定、訊號、機構數據、政策利率。每天都動的市場價格不算。
  2. 門檻在雜訊區的要去抖動：連續一週在同一側才換邊；貼著門檻時不判定。
  3. 比率的變動是百分點，不是變動率。
  4. 子行業不跟母行業一起算。
  5. 相關不是原因：說明只寫觀察到什麼，原因列為「常見的解釋」。
"""
from __future__ import annotations

import os
import unittest
from datetime import date, timedelta

from macro import archive, paths
from macro.compute import labor, market, signals
from macro.data import Bundle
from macro.render.pages import front_blocks as front
from macro.series import Series


def read(*parts):
    with open(os.path.join(*parts), encoding="utf-8") as fh:
        return fh.read()


def daily(values, *, end=date(2026, 10, 7)):
    days = [end - timedelta(days=i) for i in range(len(values))][::-1]
    return Series.from_pairs("VIXCLS", list(zip(days, [float(v) for v in values])), frequency="d")


def monthly(series_id, values, *, end=(2026, 9)):
    year, month = end
    pairs = []
    for value in reversed(values):
        pairs.append((date(year, month, 1), float(value)))
        year, month = (year, month - 1) if month > 1 else (year - 1, 12)
    return Series.from_pairs(series_id, list(reversed(pairs)), frequency="m")


# ---------------------------------------------------------------- 1 螢光筆 ----

class Highlighter(unittest.TestCase):
    NOW = {"readings": {"core_pce": 3.0, "unemployment": 4.2, "policy_upper": 4.0,
                        "ten_year": 5.28, "real_ten_year": 2.92, "recession_gauge": 42.5}}
    WAS = {"readings": {"core_pce": 3.3, "unemployment": 4.2, "policy_upper": 4.0,
                        "ten_year": 5.21, "real_ten_year": 2.88, "recession_gauge": 42.1}}

    def test_market_prices_are_listed_but_not_decision_grade(self):
        changes = archive.reading_changes(self.NOW, self.WAS)
        kinds = {c["name"]: c["kind"] for c in changes}
        self.assertEqual(kinds, {"核心 PCE": "data", "10 年期公債": "market",
                                 "10 年實質利率": "market", "衰退風險刻度": "market"})
        self.assertEqual([c["name"] for c in archive.decision_grade(changes)], ["核心 PCE"])

    def test_a_day_with_only_yield_wiggles_leaves_the_margin_blank(self):
        quiet = {"readings": dict(self.NOW["readings"], core_pce=3.3)}
        only_market = archive.decision_grade(archive.reading_changes(quiet, self.WAS))
        self.assertEqual(only_market, [])
        scenario = {"employment_label": "中", "inflation_label": "高", "regime_label": "通膨優先"}
        self.assertEqual(front.since_items({}, only_market, scenario, None), [])

    def test_decision_grade_tolerates_missing_input(self):
        self.assertEqual(archive.decision_grade(None), [])
        self.assertEqual(archive.decision_grade([{"name": "舊格式沒有 kind"}]),
                         [{"name": "舊格式沒有 kind"}])

    def test_bond_row_shows_the_month_not_the_day_and_is_not_coloured(self):
        note = front._fact_note({"change": None, "gap": None,
                                 "trend": {"value": "+0.48", "what": "近一月", "unit": "個百分點"}},
                                "2026-10-09")
        self.assertIn("+0.48", note)
        self.assertIn("近一月", note)
        self.assertIn('class="mn"', note)
        self.assertNotIn("chg", note)

    def test_a_real_change_still_wins_over_the_trend(self):
        note = front._fact_note({"change": {"change": 0.25, "was": 3.75, "now": 4.0},
                                 "trend": {"value": "+0.48", "what": "近一月", "unit": "pp"}}, None)
        self.assertIn('class="mn chg"', note)


# ------------------------------------------------------------- 2 門檻去抖動 ----

class Persistence(unittest.TestCase):
    def test_needs_a_full_week_on_one_side(self):
        self.assertEqual(market.persistent_side(daily([16, 16, 14, 14, 14, 14, 14]), 15), "below")
        self.assertEqual(market.persistent_side(daily([14] * 5 + [16] * 5), 15), "above")

    def test_days_back_and_forth_keep_the_last_settled_side(self):
        """最近幾天在門檻上來回：維持上一次站穩的那一側，不跟著翻。"""
        settled_low = [14.5] * 5 + [15.2, 14.8, 15.1, 14.9]
        self.assertEqual(market.persistent_side(daily(settled_low), 15), "below")
        settled_high = [16] * 5 + [14.8, 15.2, 14.9, 14.7]
        self.assertEqual(market.persistent_side(daily(settled_high), 15), "above")

    def test_unknown_until_there_is_a_settled_week(self):
        self.assertIsNone(market.persistent_side(daily([14, 16, 14, 16]), 15))
        self.assertIsNone(market.persistent_side(daily([]), 15))

    def test_hovering_at_the_threshold_no_longer_flips_every_day(self):
        hover = [14.6, 14.3, 15.2, 14.9, 15.1, 14.8, 15.3, 14.5, 15.0, 15.2, 14.7, 15.4] * 5
        flips = lambda states: sum(1 for a, b in zip(states, states[1:]) if a != b)
        naive = [v <= 15 for v in hover]
        steady = [market.persistent_side(daily(hover[:i + 1]), 15) for i in range(len(hover))]
        self.assertGreater(flips(naive), 20)
        self.assertEqual(flips([s for s in steady if s is not None]), 0)

    def test_rule_follows_the_settled_state_not_todays_close(self):
        ctx = lambda low: {"market": {"volatility": {"vix": 14.9, "vix_low": low}}}
        self.assertIsNone(signals.volatility_complacent(ctx(False)))
        signal = signals.volatility_complacent(ctx(True))
        self.assertIn("連續 5 個交易日", signal["evidence"])
        self.assertNotIn("定價不足", signal["headline"] + signal["why"])

    def test_real_rate_on_the_threshold_is_not_classified(self):
        base = dict(lo=-0.5, hi=2.5, kind="threshold", ticks=[(1.0, "1.0")],
                    zones=[(-1.5, 1.0, "中性或偏寬鬆"), (1.0, 3.5, "限制性")])
        self.assertIn('class="rz on"', front.ruler(now=1.4, **base))
        self.assertNotIn('class="rz on"', front.ruler(now=0.99, undecided=True, **base))
        self.assertLess(front.NEAR_THRESHOLD, 0.25)


# --------------------------------------------------------- 3 比率的變動 ----

class RateChanges(unittest.TestCase):
    JS = read(paths.STATIC_DIR, "explore.js")

    def test_rate_series_take_a_difference_not_a_ratio(self):
        rate_branch = self.JS.split('(mode === "yoy" || mode === "ann3") && isRate(meta)')[1]
        rate_branch = rate_branch.split('if (mode === "yoy" || mode === "ann3") {')[0]
        self.assertIn("values[i] - base", rate_branch)
        self.assertNotIn("Math.pow", rate_branch)
        self.assertIn("monthsBefore(dates[i], months)", rate_branch)       # 一樣照日曆對齊

    def test_legend_says_which_one_was_computed(self):
        self.assertIn('isRate(meta) ? "一年變動，百分點" : "年增率 %"', self.JS)
        self.assertIn("不是變動率", self.JS)

    def test_which_units_count_as_a_rate(self):
        self.assertIn(r"/^(%|pp|bp|個百分點)$/", self.JS)


# ------------------------------------------------------------- 4 產業加總 ----

class Sectors(unittest.TestCase):
    def sectors(self):
        b = Bundle()
        moves = {"USEHS": 20, "CES6562000101": 17, "USGOVT": -17, "CES9091000001": -1,
                 "USCONS": 11, "MANEMP": 9, "USINFO": -10}
        for series_id, move in moves.items():
            b.add(series_id, monthly(series_id, [1000] * 14 + [1000 + move]))
        b.add("PAYEMS", monthly("PAYEMS", [150000] * 14 + [150014]))
        return labor.sector_contributions(b)

    def test_children_are_shown_but_not_added_twice(self):
        s = self.sectors()
        parents = {r["name"]: r["parent"] for r in s["rows"]}
        self.assertEqual(parents["醫療照護"], "教育與健康")
        self.assertEqual(parents["聯邦政府"], "政府")
        self.assertEqual(s["n"], 5)                                         # 七列裡只有五個互不重疊
        self.assertEqual(s["covered"], 20 - 17 + 11 + 9 - 10)               # 沒有把 17 與 −1 再加一次
        self.assertEqual(s["uncovered"], 14 - 13)

    def test_diffusion_and_ranking_use_the_non_overlapping_layer(self):
        s = self.sectors()
        self.assertAlmostEqual(s["diffusion"], 3 / 5 * 100)
        self.assertNotIn("醫療照護", [r["name"] for r in s["top"]])
        self.assertNotIn("聯邦政府", [r["name"] for r in s["bottom"]])

    def test_page_marks_the_children(self):
        from macro.render.pages import labor as page
        self.assertEqual(page._sector_name({"name": "醫療照護", "parent": "教育與健康"}),
                         "其中：醫療照護（屬教育與健康）")
        self.assertEqual(page._sector_name({"name": "營建", "parent": None}), "營建")


# ------------------------------------------------------------- 5 因果措辭 ----

class CorrelationIsNotCause(unittest.TestCase):
    GONE = {
        "macro/compute/market.py": ["市場對風險幾乎沒有定價", "波動率偏高，市場已在避險",
                                    "通膨主導，債券無法對沖股票"],
        "macro/compute/signals.py": ["市場對總經風險定價不足", "這是通膨主導的典型特徵"],
        "macro/compute/commodities.py": ["最乾淨的成長預期讀數", "多半是避險或央行買盤主導"],
        "macro/render/pages/market.py": ["百分位低＝市場對該資產的風險定價不足",
                                         "代表漲勢靠的是獲利或估值", "這是總經體制最直接的市場證據"],
        "macro/render/pages/commodities.py": ["比值是最乾淨的成長預期讀數", "市場定價的成長預期"],
        "macro/render/pages/equities.py": ["代表那個國家的貨幣正在貶值"],
        "macro/glossary.py": ["代表市場對總經風險定價不足", "它是判斷總經體制最直接的市場證據"],
    }

    def test_the_overclaims_are_gone(self):
        for path, phrases in self.GONE.items():
            source = read(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), path)
            for phrase in phrases:
                self.assertFalse(phrase in source, f"{path} 還留著：{phrase}")

    def test_verdicts_describe_and_name_what_they_cannot_tell(self):
        b = Bundle()
        b.add("VIXCLS", daily([14] * 6))
        verdict = market.volatility(b)["verdict"]
        self.assertIn("隱含波動處於低檔", verdict)
        rule = signals.stock_bond_correlation_positive({"market": {"stock_bond": {"latest": -0.33}}})
        self.assertIn("相關係數分不出原因", rule["why"])
        self.assertIn("常見的解釋", rule["why"])


if __name__ == "__main__":
    unittest.main()
