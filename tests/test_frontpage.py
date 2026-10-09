"""頭版頭條的規則：有事報事，沒事報判定。

頭條是整頁最大的字。它選錯不會報錯——只會讓讀者第一眼看到次要的事，或在升息那天
看到「今天沒事」。所以順序釘死：遺漏 > 已公布的決議 > 已公布的頭條級數據 >
待公布的決議 > 待公布的頭條級數據 > 情境判定。
"""
from __future__ import annotations

import unittest
from datetime import date

from macro.data import Bundle
from macro.render.pages import frontpage
from macro.series import Series

SCENARIO = {"name": "通膨未解", "regime": "inflation_first",
            "regime_explain": "依本站規則通膨仍屬高（核心 PCE 年增 3.0%），但近三月年化 2.0% 已經降溫；這是本站的分類，不是聯準會的決策門檻"}


def ev(kind, tag, title, *, today=True, policy=None, sid=None, detail="細節。", href="/x/"):
    return {"kind": kind, "tag": tag, "title": title, "today": today, "policy": policy,
            "id": sid, "detail": detail, "href": href}


FOMC = ev("policy", "FOMC　政策轉向", "聯準會升息 1 碼　3.50%–3.75% → 3.75%–4.00%", policy="轉向")
CBC = ev("policy", "台灣央行　政策調整", "台灣央行利率不變（重貼現率 2%）；調整房貸信用管制", policy="調整")
GAP = ev("policy", "FOMC　決議遺漏", "9/16 FOMC決議本站沒有取得", policy="遺漏")
PENDING = ev("policy", "FOMC　今晚公布", "FOMC利率決議", policy="待公布")
CPI_OUT = ev("data", "美國數據　已公布", "CPI", sid="CPIAUCSL")
CPI_SOON = ev("data", "美國數據　今晚公布", "CPI", sid="CPIAUCSL", detail="約台北 20:30。")
CLAIMS = ev("data", "美國數據　已公布", "初領失業金", sid="ICSA")
PAYROLLS = ev("data", "美國數據　已公布", "非農就業", sid="PAYEMS")


def bundle():
    b = Bundle()
    cpi = [(date(2024 + (i // 12), i % 12 + 1, 1), 300.0 * (1.03 ** (i / 12))) for i in range(24)]
    cpi[-1] = (cpi[-1][0], cpi[-1][1] * 1.002)
    b.add("CPIAUCSL", Series.from_pairs("CPIAUCSL", cpi, frequency="m"))
    b.add("PAYEMS", Series.from_pairs("PAYEMS", [(date(2026, 6, 1), 160000.0), (date(2026, 7, 1), 160120.0),
                                                 (date(2026, 8, 1), 160171.0)], frequency="m"))
    return b


class Order(unittest.TestCase):
    def pick(self, *events):
        return frontpage.lede({"events": list(events), "verdict": "今天有…"}, SCENARIO, bundle())

    def test_quiet_day_falls_back_to_the_verdict(self):
        out = frontpage.lede({"events": [], "verdict": "今天沒有重大數據或政策決議。"}, SCENARIO)
        self.assertEqual(out["kind"], "verdict")
        self.assertEqual(out["headline"], "通膨未解，物價仍是主要矛盾。")
        self.assertEqual(out["deck"], "依本站規則通膨仍屬高（核心 PCE 年增 3.0%），但近三月年化 2.0% 已經降溫；這是本站的分類，不是聯準會的決策門檻。")
        self.assertEqual(out["quiet"], "今天沒有重大數據或政策決議。")

    def test_failed_calendar_wording_is_carried_not_replaced(self):
        """行事曆抓不到時不能說「今天沒事」。"""
        out = frontpage.lede({"events": [], "verdict": "今天沒有偵測到重大數據或政策決議（美國發布行事曆這一輪沒有取得，可能漏列）。"}, SCENARIO)
        self.assertIn("沒有偵測到", out["quiet"])

    def test_missing_decision_outranks_everything(self):
        self.assertEqual(self.pick(CPI_OUT, FOMC, GAP)["kind"], "gap")

    def test_announced_decision_outranks_data(self):
        out = self.pick(CPI_OUT, FOMC)
        self.assertEqual((out["kind"], out["headline"], out["figure"]),
                         ("policy", "聯準會升息 1 碼", "3.50%–3.75% → 3.75%–4.00%"))
        self.assertEqual(out["quiet"], "")

    def test_turn_outranks_adjustment(self):
        self.assertEqual(self.pick(CBC, FOMC)["headline"], "聯準會升息 1 碼")

    def test_published_data_outranks_a_pending_decision(self):
        self.assertEqual(self.pick(PENDING, CPI_OUT)["kind"], "data")

    def test_pending_decision_outranks_pending_data(self):
        self.assertEqual(self.pick(CPI_SOON, PENDING)["kind"], "pending")

    def test_weekly_claims_never_take_the_front_page(self):
        """初領失業金每週四都公布；它留在清單裡，不當頭條。"""
        self.assertEqual(self.pick(CLAIMS)["kind"], "verdict")

    def test_events_from_earlier_in_the_week_do_not_count(self):
        old = dict(FOMC, today=False)
        self.assertEqual(self.pick(old)["kind"], "verdict")

    def test_payrolls_outrank_cpi_on_the_same_day(self):
        self.assertEqual(self.pick(CPI_OUT, PAYROLLS)["headline"], "非農就業月增")


class DataLede(unittest.TestCase):
    def test_yoy_reading_with_change_against_prior(self):
        out = frontpage.lede({"events": [CPI_OUT]}, SCENARIO, bundle())
        self.assertEqual(out["headline"], "CPI年增")
        self.assertRegex(out["figure"], r"^\d\.\d%$")
        self.assertIn("前值", out["deck"])
        self.assertIn("個百分點", out["deck"])
        self.assertEqual(out["href"], "/release/CPIAUCSL/")

    def test_payrolls_are_shown_in_wan_with_a_sign(self):
        out = frontpage.lede({"events": [PAYROLLS]}, SCENARIO, bundle())
        self.assertEqual(out["figure"], "+5.1 萬人")
        self.assertIn("前值 +12.0 萬人，下降 6.9 萬人。", out["deck"])

    def test_missing_series_still_names_the_release(self):
        out = frontpage.lede({"events": [CPI_OUT]}, SCENARIO, Bundle())
        self.assertEqual((out["kind"], out["figure"]), ("data", ""))

    def test_upcoming_release_quotes_the_previous_reading(self):
        out = frontpage.lede({"events": [CPI_SOON]}, SCENARIO, bundle())
        self.assertEqual(out["kind"], "pending")
        self.assertIn("上一期", out["deck"])
        self.assertIn("約台北 20:30。", out["deck"])


class Clauses(unittest.TestCase):
    def test_every_regime_has_a_clause(self):
        from macro.compute.scenario import REGIME_LABELS
        self.assertEqual(set(frontpage.REGIME_CLAUSE), set(REGIME_LABELS))

    def test_lede_grade_series_all_have_release_specs(self):
        for series_id in frontpage.LEDE_GRADE:
            self.assertIn(series_id, frontpage.SPECS)


if __name__ == "__main__":
    unittest.main()
