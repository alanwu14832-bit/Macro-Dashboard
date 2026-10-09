"""2026-10-10 外部審閱報告的八個 P0（D-01～D-06、M-01、M-02）的回歸測試。

這幾個錯有一個共同點：頁面上的數字看起來都很正常，沒有任何東西報錯。
職缺少一個位數、外國持有佔比是 0.0%、一個月前的指數漲跌印在「今日價格」、
表決從 9–3 變 12–0 卻寫成「看法不再一致」——全部是單位、期間或文字寫反。
所以這裡釘的是語義，不是「程式有沒有跑完」。

固定輸入來自審閱當時的讀數（7,079 千個職缺、9,355.0 十億美元…），只當測試案例用，
不是正式環境的常數。
"""
from __future__ import annotations

import os
import unittest
from datetime import date, datetime, timedelta

from macro import catalogue, clock, paths
from macro.compute import debt, equities, labor, rates, scenario, signals
from macro.data import Bundle
from macro.render.pages import front_blocks as front
from macro.render.pages import frontpage
from macro.render.pages import labor as labor_page
from macro.series import Series
from macro.sources import fomc_text


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def monthly(series_id, values, *, end=(2026, 8), skip=(), unit=""):
    """以 end 為最後一個月往回排；skip 裡的 (年, 月) 不放（模擬停發的月份）。"""
    year, month = end
    pairs = []
    for value in reversed(values):
        if (year, month) not in skip:
            pairs.append((date(year, month, 1), float(value)))
        year, month = (year, month - 1) if month > 1 else (year - 1, 12)
    return Series.from_pairs(series_id, list(reversed(pairs)), frequency="m", unit=unit)


def quarterly(series_id, pairs):
    return Series.from_pairs(series_id, [(date(y, m, 1), float(v)) for (y, m), v in pairs], frequency="q")


def bundle(**series):
    b = Bundle()
    for series_id, s in series.items():
        b.add(series_id, s)
    return b


# ------------------------------------------------------------------ D-01 ----

class Jolts(unittest.TestCase):
    def test_t01_thousands_become_wan_without_losing_a_digit(self):
        b = bundle(JTSJOL=monthly("JTSJOL", [7335, 7079]), JTSHIL=monthly("JTSHIL", [5100, 5192]),
                   JTSHIR=monthly("JTSHIR", [3.2, 3.3]), UNEMPLOY=monthly("UNEMPLOY", [7000, 7109]))
        j = labor.jolts(b)
        self.assertEqual((j["openings"], j["hires"]), (7079.0, 5192.0))      # 原值不四捨五入
        self.assertAlmostEqual(labor.to_wan(j["openings"]), 707.9)
        self.assertAlmostEqual(labor.to_wan(j["hires"]), 519.2)
        self.assertAlmostEqual(j["vu_ratio"], 7079 / 7109)
        self.assertEqual(j["hires_rate"], 3.3)                               # 率是率，不是人數

    def test_catalogue_no_longer_calls_the_hires_rate_a_headcount(self):
        self.assertEqual(catalogue_unit("JTSHIR"), "%")
        self.assertEqual(catalogue_unit("JTSHIL"), "千人")
        self.assertEqual(catalogue_unit("JTSJOL"), "千個")

    def test_t02_missing_is_not_zero(self):
        b = bundle(JTSJOL=monthly("JTSJOL", [7335, 7079]), UNEMPLOY=monthly("UNEMPLOY", [7000, 7109]))
        j = labor.jolts(b)                                                   # 招聘數整檔沒抓到
        self.assertIsNone(j["hires"])
        self.assertIsNone(labor.to_wan(j["hires"]))
        none = labor.jolts(bundle(UNEMPLOY=monthly("UNEMPLOY", [7000, 7109])))
        self.assertIsNone(none["openings"])
        self.assertIsNone(none["vu_ratio"])                                  # 不是 0.00
        ctx = {"labor": {"jolts": none, "wages": {"yoy": 4.5}}}
        self.assertIsNone(signals.labor_market_tight(ctx))                   # 缺資料不產生訊號

    def test_t02_a_real_zero_stays_a_zero(self):
        b = bundle(JTSJOL=monthly("JTSJOL", [10, 0]), JTSHIL=monthly("JTSHIL", [5, 0]),
                   UNEMPLOY=monthly("UNEMPLOY", [7000, 7109]))
        j = labor.jolts(b)
        self.assertEqual((labor.to_wan(j["openings"]), labor.to_wan(j["hires"])), (0.0, 0.0))
        self.assertEqual(j["vu_ratio"], 0.0)

    def test_page_prints_the_right_magnitude_and_a_dash_when_missing(self):
        source = read(labor_page.__file__)
        self.assertNotIn("/ 100, 1, suffix=\" 萬", source)                    # 千 → 萬是除以 10
        self.assertIn("to_wan(jolts[\"openings\"])", source)
        self.assertNotIn("or 0)", source.split("# ---- JOLTS ----")[1].split("body.append")[0])


def catalogue_unit(series_id):
    for group in vars(catalogue).values():
        if isinstance(group, dict) and series_id in group and isinstance(group[series_id], tuple):
            return group[series_id][1]
    raise AssertionError(f"{series_id} 不在目錄裡")


# ------------------------------------------------------------------ D-02 ----

class DebtHolders(unittest.TestCase):
    TOTAL = [((2021, 1), 28_132_570), ((2025, 10), 38_800_000), ((2026, 1), 39_065_421), ((2026, 4), 39_462_398)]
    FOREIGN = [((2021, 1), 7_038.0), ((2025, 10), 9_269.5), ((2026, 1), 9_355.0)]
    PRIVATE = [((2026, 1), 27_041.1), ((2026, 4), 27_189.3)]

    def holders(self, total=None, foreign=None, private=None):
        return debt.holders(bundle(GFDEBTN=quarterly("GFDEBTN", total or self.TOTAL),
                                   FDHBFIN=quarterly("FDHBFIN", foreign or self.FOREIGN),
                                   FDHBPIN=quarterly("FDHBPIN", private or self.PRIVATE)))

    def test_t03_billions_and_millions_both_become_trillions(self):
        h = self.holders()
        self.assertAlmostEqual(h["foreign"], 9.355)
        self.assertAlmostEqual(h["private"], 27.1893)
        self.assertAlmostEqual(h["total"], 39.462398)

    def test_t04_share_uses_the_same_quarter_for_both_sides(self):
        """外國持有只到 Q1，債務總額到 Q2：佔比用 Q1 對 Q1，不是各拿最新一季。"""
        h = self.holders()
        self.assertEqual(h["foreign_share_as_of"], date(2026, 1, 1))
        self.assertAlmostEqual(h["foreign_share"], 9_355.0 * 1000 / 39_065_421 * 100)
        self.assertGreater(h["foreign_share"], 20)                           # 不是 0.0%
        self.assertAlmostEqual(h["foreign_share_5y_ago"], 7_038.0 * 1000 / 28_132_570 * 100)
        self.assertEqual((h["foreign_as_of"], h["private_as_of"], h["total_as_of"]),
                         (date(2026, 1, 1), date(2026, 4, 1), date(2026, 4, 1)))

    def test_t04_no_common_quarter_means_no_share(self):
        h = self.holders(total=[((2026, 4), 39_462_398)], foreign=[((2026, 1), 9_355.0)])
        self.assertIsNone(h["foreign_share"])
        self.assertIsNone(h["foreign_share_5y_ago"])

    def test_units_in_the_catalogue(self):
        self.assertEqual(catalogue_unit("FDHBFIN"), "十億美元")
        self.assertEqual(catalogue_unit("FDHBPIN"), "十億美元")
        self.assertEqual(catalogue_unit("GFDEBTN"), "百萬美元")


# ------------------------------------------------------------------ D-03 ----

class FomcVote(unittest.TestCase):
    def test_t05_fewer_dissents_is_not_more_disagreement(self):
        text = fomc_text.describe_vote_change("12–0", "9–3", [], ["lower"])
        self.assertIn("異議票由 3 票減為 0 票", text)
        self.assertIn("表決一致", text)
        self.assertNotIn("不再一致", text)

    def test_t05_more_dissents(self):
        text = fomc_text.describe_vote_change("9–3", "12–0", ["lower", "hold"], [])
        self.assertIn("異議票由 0 票增為 3 票", text)
        self.assertIn("偏好更低的利率、偏好維持利率不變", text)
        self.assertIn("出現分歧", text)

    def test_t05_same_count_but_the_direction_changed(self):
        text = fomc_text.describe_vote_change("10–2", "10–2", ["higher"], ["lower"])
        self.assertIn("票數相同（2 票）", text)
        self.assertIn("上次是偏好更低的利率，這次是偏好更高的利率", text)

    def test_never_extrapolates_to_the_next_meeting(self):
        for args in (("12–0", "9–3", [], ["lower"]), ("9–3", "12–0", ["lower"], []),
                     ("10–2", "10–2", ["higher"], ["lower"])):
            self.assertIn("不能據此推論委員會對下一次決議的看法", fomc_text.describe_vote_change(*args))

    def test_nothing_to_say_when_nothing_changed_or_unreadable(self):
        self.assertEqual(fomc_text.describe_vote_change("12–0", "12–0", [], []), "")
        self.assertEqual(fomc_text.describe_vote_change("10–2", "10–2", ["lower"], ["lower"]), "")
        self.assertEqual(fomc_text.describe_vote_change("", "9–3"), "")
        self.assertIsNone(fomc_text.dissent_count("十二比零"))

    def test_dissent_direction_is_read_from_the_statement(self):
        statement = ("Voting for the monetary policy action were Jerome H. Powell, Chair; and others. "
                     "Voting against this action were Stephen I. Miran, who preferred to lower the target "
                     "range by 1/2 percentage point; and Jeffrey R. Schmid, who preferred to maintain the "
                     "target range. For media inquiries, call 202-452-2955.")
        self.assertEqual(fomc_text.dissent_directions(statement), ["lower", "hold"])
        self.assertEqual(fomc_text.dissent_directions("approved by a 12 – 0 vote."), [])
        self.assertEqual(fomc_text.dissent_directions(
            "Voting against this action was A B, who favored a slower pace of runoff."), ["other"])


# ------------------------------------------------------------------ D-04 ----

class UnemploymentDecomposition(unittest.TestCase):
    def rows(self, u1, l1):
        """L0=1000、U0=50、u0=5%；最後一個月換成 (U1, L1)。"""
        rate1 = u1 / l1 * 100
        b = bundle(UNEMPLOY=monthly("UNEMPLOY", [50, 50, 50, 50, u1]),
                   CLF16OV=monthly("CLF16OV", [1000, 1000, 1000, 1000, l1]),
                   UNRATE=monthly("UNRATE", [5.0, 5.0, 5.0, 5.0, rate1]))
        return next(r for r in labor.unemployment_decomposition(b)["rows"] if r["window"] == "上月")

    def test_t06_more_unemployed(self):
        r = self.rows(60, 1000)
        self.assertAlmostEqual(r["numerator"], 1.0)
        self.assertAlmostEqual(r["denominator"], 0.0)
        self.assertAlmostEqual(r["total"], 1.0)

    def test_t06_a_shrinking_labour_force_pushes_the_rate_up(self):
        """分母變小，同樣的失業人數算出來的比率變高——勞動力效果是正的，不是負的。"""
        r = self.rows(50, 990)
        self.assertAlmostEqual(r["numerator"], 0.0)
        self.assertAlmostEqual(r["denominator"], 0.05)
        self.assertAlmostEqual(r["total"], 0.050505, places=5)

    def test_t06_unemployed_leaving_shows_up_as_both_effects(self):
        r = self.rows(40, 990)
        self.assertAlmostEqual(r["numerator"], -1.0)
        self.assertAlmostEqual(r["denominator"], 0.05)
        self.assertAlmostEqual(r["total"], -0.959596, places=5)
        self.assertAlmostEqual(r["numerator"] + r["denominator"] + r["residual"], r["total"])
        self.assertAlmostEqual(r["residual"], -0.009596, places=5)           # 近似的差額列得出來

    def test_a_growing_labour_force_is_the_negative_effect(self):
        self.assertLess(self.rows(50, 1010)["denominator"], 0)

    def test_page_no_longer_reads_a_negative_effect_as_people_leaving(self):
        source = read(labor_page.__file__)
        self.assertNotIn("勞動力效果為負＝有人退出", source)
        self.assertIn("勞動力<strong>減少</strong>為正", source)
        self.assertIn('"差額"', source)

    def test_windows_are_calendar_months_not_row_counts(self):
        """2025-10 停發：往回數 12 筆是 13 個月前。"""
        values = list(range(100, 114))                                       # 2025-07 … 2026-08
        s = monthly("X", values, skip={(2025, 10)})
        self.assertEqual(s.months_ago(12), 101.0)                            # 2025-08
        self.assertEqual(s.at(-13), 100.0)                                   # 往回數 12 筆數到 2025-07
        self.assertEqual(s.change_over(12), 113.0 - 101.0)
        self.assertIsNone(s.months_ago(10))                                  # 2025-10 沒有資料
        self.assertIsNone(monthly("Y", [1, 2, 3]).change_over(12))


class UnemploymentRule(unittest.TestCase):
    def signal(self, total, rate_change, epop_change):
        ctx = {"labor": {"participation": {"rate_change": rate_change, "emratio_change": epop_change,
                                           "rate_change_3m": 0.3, "emratio_change_3m": 0.2},
                         "decomposition": {"rows": [{"window": "一年", "total": total}]}}}
        return signals.unemployment_falling_for_wrong_reason(ctx)

    def test_needs_all_three_rates_in_the_same_twelve_months(self):
        self.assertIsNotNone(self.signal(-0.2, -0.7, -0.5))
        self.assertIsNone(self.signal(+0.1, -0.7, -0.5))                     # 失業率在升：不是這條的事
        self.assertIsNone(self.signal(0.0, -0.7, -0.5))
        self.assertIsNone(self.signal(-0.2, +0.1, -0.5))                     # 勞參率沒有下降
        self.assertIsNone(self.signal(-0.2, -0.7, +0.2))                     # 就業人口比上升＝有人找到工作

    def test_states_what_happened_without_naming_a_cause(self):
        s = self.signal(-0.2, -0.7, -0.5)
        self.assertEqual(s["severity"], "medium")
        self.assertNotIn("來自", s["headline"])
        self.assertIn("只陳述現象，不說原因", s["why"])
        self.assertIn("近 3 個月勞參率 +0.3", s["evidence"])                  # 相反的近況一起講

    def test_missing_inputs_do_not_trigger(self):
        self.assertIsNone(self.signal(-0.2, None, -0.5))
        self.assertIsNone(signals.unemployment_falling_for_wrong_reason(
            {"labor": {"participation": {}, "decomposition": {}}}))


# ------------------------------------------------------------------ D-05 ----

NOW = datetime(2026, 10, 10, 2, 45, tzinfo=clock.TAIPEI)


def quote(symbol, *, stale, days_old, name=None):
    return {"symbol": symbol, "name": name or symbol, "price": 100.0, "change_percent": 1.06,
            "previous_close": 99.0, "stale": stale,
            "quoted_at": None if days_old is None else NOW - timedelta(days=days_old)}


class StaleQuotes(unittest.TestCase):
    def test_t07_a_month_old_snapshot_leaves_todays_analysis(self):
        live, expired = equities.split_expired(
            [quote("^GSPC", stale=True, days_old=36), quote("AAPL", stale=False, days_old=0)], NOW)
        self.assertEqual([r["symbol"] for r in live], ["AAPL"])
        self.assertEqual([r["symbol"] for r in expired], ["^GSPC"])
        self.assertTrue(expired[0]["expired"])
        self.assertEqual(expired[0]["price"], 100.0)                         # 歷史值還看得到

    def test_t08_weekend_and_holiday_quotes_are_not_a_failure(self):
        """這次有抓到的報價不判過期：週末拿到的就是週五的資料。"""
        live, expired = equities.split_expired([quote("^TWII", stale=False, days_old=3),
                                                quote("2330", stale=False, days_old=9)], NOW)
        self.assertEqual(len(live), 2)
        self.assertEqual(expired, [])

    def test_recent_snapshot_fill_is_still_the_last_session(self):
        live, expired = equities.split_expired([quote("SPY", stale=True, days_old=3)], NOW)
        self.assertEqual((len(live), len(expired)), (1, 0))

    def test_snapshot_without_a_time_cannot_be_trusted_as_today(self):
        live, expired = equities.split_expired([quote("^DJI", stale=True, days_old=None)], NOW)
        self.assertEqual((len(live), len(expired)), (0, 1))

    def test_front_page_falls_back_to_dated_closes(self):
        closes = Series.from_pairs("SP500", [(date(2026, 10, 7), 7801.77), (date(2026, 10, 8), 7765.36)],
                                   frequency="d")
        rows = front.price_rows({"equities": {"us": {"indices": []}}, "_bundle": bundle(SP500=closes)})
        sp = next(r for r in rows if r["name"] == "標普 500")
        self.assertEqual(sp["level"], "7,765.36")
        self.assertIn("10/8 收盤", sp["cap"])
        self.assertAlmostEqual(sp["chg"][0], (7765.36 / 7801.77 - 1) * 100)
        self.assertFalse(any(r["name"] == "那斯達克綜合" for r in rows))       # 沒有資料就沒有這一列

    def test_front_page_prefers_a_live_quote(self):
        live = {"name": "標普 500", "price": 7800.0, "previous_close": 7765.36, "change_percent": 0.45}
        rows = front.price_rows({"equities": {"us": {"indices": [live]}}, "_bundle": Bundle()})
        self.assertEqual(rows[0]["cap"], "昨收 7,765.36")


# ------------------------------------------------------------------ D-06 ----

class YearOverYear(unittest.TestCase):
    def test_t09_python_side_matches_on_the_calendar(self):
        values = [100 * 1.002 ** i for i in range(14)]
        full = monthly("CPILFESL", values)
        gap = monthly("CPILFESL", values, skip={(2025, 10)})
        self.assertAlmostEqual(full.yoy().last, gap.yoy().last)
        self.assertAlmostEqual(full.yoy().last, (1.002 ** 12 - 1) * 100)

    def test_t09_explore_uses_the_same_rule(self):
        """自選比較是瀏覽器端算的。它曾經往回數 12 筆，核心 CPI 年增顯示 2.76%，
        通膨頁是 2.45%。這裡沒有 JS 執行環境，只能釘住它用的是日曆對齊。"""
        js = read(os.path.join(paths.STATIC_DIR, "explore.js"))
        self.assertIn("byMonth.get(monthsBefore(dates[i], months))", js)
        calendar = js.split('meta.freq === "m" || meta.freq === "q" || meta.freq === "a"')[1]
        self.assertLess(calendar.index("monthsBefore(dates[i], months)"), calendar.index("values[i - periods]"))


# ------------------------------------------------------------------ M-01 ----

class PolicyWording(unittest.TestCase):
    LABOR = {"unemployment": {"rate": 4.2, "low12": 4.1}}

    def evidence(self, core, ann3, regime="inflation_first"):
        inflation = {"headline": {"core_pce": core}, "momentum": {"core_pce_3m": ann3}}
        return scenario.regime_evidence(regime, self.LABOR, inflation)

    def test_t10_level_and_momentum_are_both_reported(self):
        text = self.evidence(3.01, 2.05)
        self.assertIn("核心 PCE 年增 3.0%", text)
        self.assertIn("近三月年化 2.0% 已經降溫", text)
        self.assertIn("不是聯準會的決策門檻", text)

    def test_t10_no_sentence_promises_what_the_fed_will_do(self):
        texts = [self.evidence(3.01, 2.05), self.evidence(3.0, 3.6), self.evidence(2.9, 2.9),
                 self.evidence(2.5, 2.4, "employment_first"), self.evidence(2.5, 2.4, "balanced"),
                 *scenario.REGIME_EXPLAIN.values()]
        for text in texts:
            for word in ("降息", "升息", "不會", "一定", "必然"):
                self.assertNotIn(word, text, text)

    def test_headline_speaks_for_the_site_not_for_the_fed(self):
        for regime in frontpage.REGIME_PHRASES:
            lede = frontpage.verdict_lede({"name": "通膨未解", "regime": regime, "regime_explain": "x"})
            self.assertNotIn("聯準會", lede["headline"])
        self.assertEqual(frontpage.verdict_lede({"name": "通膨未解", "regime": "inflation_first"})["headline"],
                         "通膨未解，物價仍是主要矛盾。")

    def test_chart_says_whose_thresholds_these_are(self):
        source = read(front.__file__)
        self.assertIn("是本站的分類門檻，不是聯準會的決策門檻", source)
        self.assertIn("目標指的是整體 PCE", source)


# ------------------------------------------------------------------ M-02 ----

class NotATermPremium(unittest.TestCase):
    def decomposition(self):
        daily = lambda sid, v: Series.from_pairs(sid, [(date(2026, 10, 6), v), (date(2026, 10, 7), v)],
                                                 frequency="d")
        return rates.long_end_decomposition(bundle(
            DGS10=daily("DGS10", 5.28), DFII10=daily("DFII10", 2.92), T10YIE=daily("T10YIE", 2.35),
            DGS30=daily("DGS30", 5.67), DFII30=daily("DFII30", 3.36), DFEDTARU=daily("DFEDTARU", 4.00)))

    def test_t11_the_number_is_named_for_what_it_is(self):
        d = self.decomposition()
        self.assertAlmostEqual(d["ten_minus_policy"], 1.28)                  # 就是 5.28 − 4.00
        self.assertNotIn("term_premium", d)

    def test_t11_no_rule_draws_a_supply_conclusion_from_it(self):
        names = {fn.__name__ for fn in signals.RULES}
        self.assertNotIn("term_premium_elevated", names)
        checks = rates.health_checks.__code__.co_consts
        self.assertFalse(any(isinstance(c, str) and "供給壓力" in c for c in checks))

    def test_glossary_admits_the_site_has_no_estimate(self):
        from macro import glossary
        entry = next(v for v in vars(glossary).values()
                     if isinstance(v, dict) and "term_premium" in v)["term_premium"]
        self.assertIn("本站沒有接這類來源", entry["how"])
        self.assertNotIn("發債量與財政疑慮——", entry["why"])


if __name__ == "__main__":
    unittest.main()
