"""台灣總經：解析與門檻。

針對的是「壞了不會報錯、只會靜默給錯答案」那一類：

  - 國發會每月重新上傳 ZIP、偶爾改寫欄名。欄名對不上時必須留空，
    不能悄悄用鄰近欄位頂替——那會讓失業率圖上畫的是單位產出勞動成本。
  - 燈號分界是國發會定義的，寫錯一分就整段判斷偏一格。
  - 重貼現率是階梯函數。把它當成連續序列內插，會在兩次決策之間畫出
    一條從來沒有存在過的斜線。
"""
from __future__ import annotations

import io
import unittest
import zipfile
from datetime import date

from macro.compute import taiwan
from macro.series import Series
from macro.sources import cbc, ndc


def _zip(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, text in files.items():
            archive.writestr(name, text.encode("utf-8-sig"))
    return buffer.getvalue()


class Lights(unittest.TestCase):
    def test_official_band_edges(self):
        """國發會的分界：9–16 藍、17–22 黃藍、23–31 綠、32–37 黃紅、38–45 紅。"""
        for score, expected in [(9, "藍"), (16, "藍"), (17, "黃藍"), (22, "黃藍"),
                                (23, "綠"), (31, "綠"), (32, "黃紅"), (37, "黃紅"),
                                (38, "紅"), (45, "紅")]:
            self.assertEqual(ndc.light_for(score), expected, f"{score} 分")

    def test_no_light_without_a_score(self):
        self.assertIsNone(ndc.light_for(None))

    def test_every_light_has_a_meaning(self):
        for _ceiling, name in ndc.LIGHT_BANDS:
            self.assertIn(name, ndc.LIGHT_MEANING)


class Parsing(unittest.TestCase):
    def test_roc_style_period_becomes_iso(self):
        self.assertEqual(ndc._iso("202607"), "2026-07-01")
        for bad in ("2026", "202613", "202600", "20260x", ""):
            self.assertIsNone(ndc._iso(bad), bad)

    def test_renamed_column_leaves_the_series_empty(self):
        """欄名對不上就留空。用鄰近欄位頂替會讓圖上畫的是別的指標。"""
        blob = _zip({"落後指標構成項目.csv":
                     "Date,失業率百分比,五大銀行新承做放款平均利率(年息百分比)\n"
                     "202607,3.39,2.167\n"})
        out = ndc._parse_archive(zipfile.ZipFile(io.BytesIO(blob)))
        self.assertEqual(len(out["unemployment"]), 0)
        self.assertEqual(out["loan_rate"].last, 2.167)

    def test_blank_and_dash_cells_are_gaps_not_zeros(self):
        """國發會用空字串與 '-' 表示尚未公布。當成 0 會讓年增率變成 -100%。"""
        blob = _zip({"落後指標構成項目.csv":
                     "Date,失業率(%)\n202605,3.27\n202606,\n202607,-\n"})
        out = ndc._parse_archive(zipfile.ZipFile(io.BytesIO(blob)))
        self.assertEqual(out["unemployment"].pairs(), [(date(2026, 5, 1), 3.27)])


class PolicyRate(unittest.TestCase):
    HTML = ("<table><tr><th>調整日期</th><th>重貼現率</th></tr>"
            "<tr><td>2024/3/22</td><td>2</td></tr>"
            "<tr><td>2023/3/24</td><td>1.875</td></tr></table>")

    def test_table_rows_parse_newest_first(self):
        rows = cbc._rows(self.HTML)
        self.assertEqual(rows[1][:2], ["2024/3/22", "2"])

    def test_monthly_expansion_is_a_staircase(self):
        """兩次決策之間利率就是不動。月度展開必須重複前值，不是內插。"""
        changes = [(date(2023, 3, 24), 1.875), (date(2024, 3, 22), 2.0)]
        monthly = {}
        current, cursor = changes[0][1], 0
        year, month = 2023, 3
        while (year, month) <= (2024, 4):
            month_end = date(year + (month == 12), month % 12 + 1, 1)
            while cursor < len(changes) and changes[cursor][0] < month_end:
                current = changes[cursor][1]
                cursor += 1
            monthly[(year, month)] = current
            year, month = (year + 1, 1) if month == 12 else (year, month + 1)
        # 2023-04 到 2024-02 之間沒有任何中間值
        self.assertEqual({monthly[(2023, m)] for m in range(4, 13)}, {1.875})
        self.assertEqual(monthly[(2024, 2)], 1.875)
        self.assertEqual(monthly[(2024, 3)], 2.0)


class Streaks(unittest.TestCase):
    def _series(self, values):
        return Series.from_pairs(
            "X", [(date(2025, 1, 1).replace(month=(i % 12) + 1,
                                            year=2025 + i // 12), v)
                  for i, v in enumerate(values)], frequency="m")

    def test_counts_only_the_final_run(self):
        rising = self._series([5, 4, 3, 4, 5, 6])
        self.assertEqual(taiwan._streak(rising, rising=True), 3)
        self.assertEqual(taiwan._streak(rising, rising=False), 0)

    def test_flat_breaks_a_run(self):
        self.assertEqual(taiwan._streak(self._series([1, 2, 2, 3]),
                                        rising=True), 1)

    def test_light_streak_counts_the_current_colour(self):
        # 31 分是綠燈，32 起是黃紅：連續三個綠之後兩個黃紅 → 黃紅連 2 個月
        scores = self._series([25, 28, 31, 33, 35])
        light, streak = taiwan._light_streak(scores)
        self.assertEqual((light, streak), ("黃紅", 2))


class Rules(unittest.TestCase):
    """台灣規則不得改寫美國的判斷。"""

    def test_taiwan_rules_are_direction_neutral(self):
        from macro.compute import signals
        ctx = {"taiwan": {
            "cycle": {"light": "藍", "score": 12.0, "light_streak": 9,
                      "leading": 95.0, "leading_down": 6,
                      "leading_falling": True},
            "external": {"orders": 44.0, "exports_negative_months": 7,
                         "exports_yoy": -12.3},
            "labour": {"unemployment": 4.1, "unemployment_low_12m": 3.5,
                       "unemployment_gap": 0.6},
            "money": {"m1b_yoy": 1.2},
        }}
        fired = [fn(ctx) for fn in signals.RULES
                 if fn.__name__.startswith("tw_")]
        fired = [s for s in fired if s]
        self.assertEqual(len(fired), 6, "六條台灣規則在這個情境下應全部觸發")
        for signal in fired:
            self.assertEqual(signal["direction"], "neutral", signal["key"])
            self.assertEqual(signal["module"], "台灣", signal["key"])
        # 全部 neutral ⇒ 不影響聯準會傾向的加權分數
        self.assertEqual(signals.summarise(fired)["score"], 0)

    def test_quiet_taiwan_fires_nothing(self):
        from macro.compute import signals
        ctx = {"taiwan": {
            "cycle": {"light": "綠", "score": 27.0, "light_streak": 4,
                      "leading": 101.0, "leading_down": 0,
                      "leading_falling": False},
            "external": {"orders": 53.0, "exports_negative_months": 0,
                         "exports_yoy": 8.1},
            "labour": {"unemployment": 3.4, "unemployment_low_12m": 3.35,
                       "unemployment_gap": 0.05},
            "money": {"m1b_yoy": 6.0},
        }}
        fired = [fn(ctx) for fn in signals.RULES
                 if fn.__name__.startswith("tw_")]
        self.assertEqual([s for s in fired if s], [])

    def test_rules_survive_a_missing_taiwan_block(self):
        """整包抓不到時規則要沉默，不是讓建置掛掉。"""
        from macro.compute import signals
        for ctx in ({}, {"taiwan": {}}, {"taiwan": {"cycle": {}}}):
            for fn in signals.RULES:
                if fn.__name__.startswith("tw_"):
                    self.assertIsNone(fn(ctx), f"{fn.__name__} on {ctx}")


class Page(unittest.TestCase):
    def test_renders_without_any_data(self):
        """來源全掛時頁面要說「留白」，不能印出 None 或 nan。"""
        from macro.render.pages import taiwan as page
        empty = {code: Series(f"TW_{code}", [], [], frequency="m")
                 for block in ndc.LAYOUT.values() for code in block}
        from macro.data import Bundle
        ctx = {"taiwan": {
            "cycle": taiwan.cycle(empty),
            "external": taiwan.external(empty, Bundle()),
            "output": taiwan.output(empty),
            "labour": taiwan.labour_prices(
                empty, {"yoy": Series("C", [], [], frequency="m")}),
            "money": taiwan.money(
                empty, {"monthly": Series("P", [], [], frequency="m"),
                        "changes": Series("P", [], [], frequency="d")},
                Bundle()),
            "series": empty, "gaps": ["測試缺口"], "as_of": None,
        }}
        html = page.render(ctx, [])
        self.assertNotIn("None", html)
        self.assertNotIn("nan", html)
        self.assertIn("測試缺口", html)
        self.assertIn("留白", html)


if __name__ == "__main__":
    unittest.main()
