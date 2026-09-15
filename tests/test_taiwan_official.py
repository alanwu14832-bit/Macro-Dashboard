"""台灣各部會統計資料庫、經濟部外銷訂單，以及它們在計算層的組合。

針對「壞了不會報錯、只會靜默給錯答案」那一類：

  - 統計資料庫的欄位靠位置選取，位置錯了照樣回 200，只是換成隔壁那一欄。
    計算層必須用標籤取序列，標籤對不上就留空。
  - 財政部的標籤被 HTML 跳脫兩層，沒還原就永遠對不上標籤。
  - 缺格寫成 '-' 或 '...'；當成 0 會讓年增率變成 -100%。
  - 經濟部的單位寫在每一列；單位改了還照數字收，會差一千倍而不報錯。
"""
from __future__ import annotations

import unittest
from datetime import date

from macro import clock
from macro.compute import taiwan
from macro.series import EMPTY, Series
from macro.sources import moea, statdb

XML = (
    '<?xml version="1.0" encoding="utf-8" ?><GenericData><DataSet>'
    '<Series item="按美元計算(千美元)_出口_&amp;lt;b&amp;gt;總計&amp;lt;/b&amp;gt;"'
    ' unit="單位：美金百萬元" freq="M">'
    '<Obs><period>2026M06</period><value>100</value><note></note></Obs>'
    '<Obs><period>2026M07</period><value>-</value><note></note></Obs>'
    '<Obs><period>2026M08</period><value>...</value><note></note></Obs>'
    '<Obs><period>2026M09</period><value>1,234</value><note></note></Obs>'
    '<Obs><period>2026M10</period><value>0</value><note></note></Obs>'
    '</Series>'
    '<Series item="年資料" unit="" freq="A">'
    '<Obs><period>2025</period><value>5</value><note></note></Obs>'
    '</Series></DataSet></GenericData>')


class Statdb(unittest.TestCase):
    def test_adjacent_positions_merge_into_one_span(self):
        self.assertEqual(statdb.spans([0, 3, 4, 13]), "0,1,3,2,13,1")
        self.assertEqual(statdb.spans([4, 3, 3]), "3,2")
        self.assertEqual(statdb.spans([]), "")

    def test_double_escaped_labels_are_restored(self):
        self.assertEqual(statdb.label("&amp;lt;b&amp;gt;總計&amp;lt;/b&amp;gt;"), "總計")
        self.assertEqual(statdb.label("經濟成長率(%)"), "經濟成長率(%)")

    def test_periods(self):
        self.assertEqual(statdb.period("2026M07"), date(2026, 7, 1))
        self.assertEqual(statdb.period("2026Q2"), date(2026, 4, 1))
        self.assertEqual(statdb.period("2025"), date(2025, 1, 1))
        for bad in ("2026M13", "115年7月", "2026Q5", ""):
            self.assertIsNone(statdb.period(bad), bad)

    def test_plain_text_error_is_a_failure_not_data(self):
        """參數錯誤回 HTTP 200 加一行純文字。"""
        with self.assertRaises(statdb.StatdbError):
            statdb.parse("功能代號不存在")

    def test_placeholders_are_gaps_and_thousands_separators_are_stripped(self):
        parsed = statdb.parse(XML)
        block = parsed["按美元計算(千美元)_出口_總計"]
        self.assertEqual(block["unit"], "美金百萬元")
        self.assertEqual([p[0].month for p in block["points"]], [6, 9, 10])
        self.assertEqual(block["points"][1][1], 1234.0)

    def test_build_drops_wrong_frequency_and_future_points(self):
        """頻率不符的序列是年月混排的產物；未來期別是預填的 0。"""
        out = statdb.build(statdb.parse(XML), "mof", "i9401", "m",
                           today=date(2026, 9, 15))
        self.assertEqual(list(out), ["按美元計算(千美元)_出口_總計"])
        series = out["按美元計算(千美元)_出口_總計"]
        self.assertEqual(series.last_date, date(2026, 9, 1))
        self.assertEqual(series.source, "財政部")

    def test_url_asks_for_far_future_end_and_keeps_commas(self):
        link = statdb.url("dgbas", "A018102060", fields=[1], codes0=[0, 3, 13],
                          freq="q", start_year=1981)
        self.assertIn(f"ymt={clock.today().year - 1911 + 5}12", link)
        self.assertIn("ymf=7001", link)
        self.assertIn("codspc0=0,1,3,1,13,1", link)
        self.assertIn("cycle=2", link)
        self.assertNotIn("%2C", link)


class ExportOrders(unittest.TestCase):
    CSV = ("﻿統計項目,資料期(民國年),統計值(美元),計量單位(美元),統計值(新台幣),計量單位(新台幣)\n"
           "外銷訂單金額,07301,2627,百萬美元,1056,新臺幣億元\n"
           "外銷訂單金額,11507,97939,千美元,31543,新臺幣億元\n"
           "外銷訂單指數,11507,120,指數,120,指數\n")

    def test_roc_period(self):
        self.assertEqual(moea._iso("11507"), "2026-07-01")
        self.assertEqual(moea._iso("07301"), "1984-01-01")
        self.assertIsNone(moea._iso("11513"))

    def test_unit_change_drops_the_value_instead_of_mixing_scales(self):
        out = moea._parse_export_orders(self.CSV)
        self.assertEqual(out["usd"].pairs(), [(date(1984, 1, 1), 2627.0)])
        self.assertEqual(len(out["twd"]), 2)


def _monthly(sid, values_by_month):
    return Series.from_pairs(sid, [(date(y, m, 1), v)
                                   for (y, m), v in values_by_month.items()],
                             frequency="m")


class Composition(unittest.TestCase):
    def test_every_official_series_names_a_known_table(self):
        for code, (table, name) in taiwan.OFFICIAL.items():
            self.assertIn(table, taiwan.TABLES, code)
            self.assertIn(table, taiwan.TABLE_GAPS, code)
            self.assertTrue(name, code)

    def test_combine_skips_months_missing_on_either_side(self):
        part = _monthly("P", {(2026, 6): 30.0, (2026, 7): 40.0, (2026, 8): 10.0})
        whole = _monthly("W", {(2026, 6): 100.0, (2026, 8): 0.0})
        share = taiwan._combine(part, whole, taiwan._share, "S")
        self.assertEqual(share.pairs(), [(date(2026, 6, 1), 30.0)])

    def test_m1b_m2_cross_counts_consecutive_negative_months(self):
        m1b = {(2024, m): 100.0 for m in range(1, 13)}
        m1b.update({(2025, m): 105.0 for m in range(1, 13)})
        m2 = {(2024, m): 100.0 for m in range(1, 13)}
        m2.update({(2025, m): 107.0 for m in range(1, 13)})
        gov = {"m1b": _monthly("M1B", m1b), "m2": _monthly("M2", m2)}
        empty = {"m1b": EMPTY, "credit": EMPTY, "loan_rate": EMPTY}
        rate = {"monthly": EMPTY, "changes": EMPTY}
        from macro.data import Bundle
        block = taiwan.money(empty, rate, Bundle(), gov)
        self.assertAlmostEqual(block["m1b_m2_spread"], -2.0)
        self.assertEqual(block["m1b_m2_negative_months"], 12)

    def test_gaps_name_each_missing_table_once(self):
        gov = {code: EMPTY for code in taiwan.OFFICIAL}
        gov["orders_usd"] = EMPTY
        full = {"signal_score": Series("X", [date(2026, 1, 1)], [1.0])}
        cpi = {"yoy": Series("C", [date(2026, 1, 1)], [1.0])}
        rate = {"changes": Series("R", [date(2026, 1, 1)], [1.0])}
        found = taiwan.gaps(full, cpi, rate, gov)
        self.assertEqual(len(found), len(taiwan.TABLES) + 1)
        self.assertEqual(taiwan.gaps(full, cpi, rate, None), [])


if __name__ == "__main__":
    unittest.main()
