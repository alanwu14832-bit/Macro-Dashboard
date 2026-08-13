"""Series 轉換的迴歸測試。

這裡的重點案例是 2025-10：政府關門讓 BLS 史上第一次整月停發 CPI，
FRED 的月頻序列出現缺格。位置型的「往回數 N 筆」在缺格序列上會
默默除錯基期——2026-07 的 CPI 年增率就這樣顯示成 3.5%（正確是 3.3%）。
數字看起來完全合理，不會有任何錯誤訊息，只有測試守得住這種錯。

    python3 -m unittest discover -s tests
"""
import unittest

from macro.series import Series


def monthly(pairs):
    return Series.from_pairs("TEST", pairs, frequency="m")


# 真實的 CPIAUCSL 片段：缺 2025-10（政府關門停發）
CPI_WITH_GAP = [
    ("2025-06-01", 321.435), ("2025-07-01", 322.169), ("2025-08-01", 323.291),
    ("2025-09-01", 324.245),                           # ← 2025-10 缺
    ("2025-11-01", 325.063), ("2025-12-01", 326.031), ("2026-01-01", 326.588),
    ("2026-02-01", 327.460), ("2026-03-01", 330.293), ("2026-04-01", 332.407),
    ("2026-05-01", 333.979), ("2026-06-01", 332.568), ("2026-07-01", 332.813),
]


class TestYoy(unittest.TestCase):
    def test_gap_regression(self):
        """缺格序列的年增率必須對齊去年同月，不是往回數 12 筆。

        位置型的算法會把 2026-07 除到 2025-06 的基期，得出 3.54%。
        """
        y = monthly(CPI_WITH_GAP).yoy()
        self.assertAlmostEqual(y.last, 3.304, places=2)
        self.assertEqual(y.last_date.isoformat(), "2026-07-01")

    def test_missing_base_leaves_blank(self):
        """基期缺格的月份要留白，不能拿別的月份充數。"""
        pairs = CPI_WITH_GAP + [("2026-08-01", 333.0), ("2026-09-01", 333.5),
                                ("2026-10-01", 334.0)]
        y = monthly(pairs).yoy()
        # 2026-10 的基期是缺格的 2025-10 → 這一點不該存在
        self.assertNotIn("2026-10-01", [d.isoformat() for d in y.dates])
        # 前後兩個月都正常
        self.assertIn("2026-09-01", [d.isoformat() for d in y.dates])

    def test_complete_series_unchanged(self):
        """沒有缺格時，結果跟單純的同月相除一致。"""
        pairs = [(f"{y}-{m:02d}-01", 100 + (y - 2024) * 12 + m)
                 for y in (2024, 2025) for m in range(1, 13)]
        y = monthly(pairs).yoy()
        self.assertEqual(len(y), 12)
        # 2025-01（113）對 2024-01（101）
        self.assertAlmostEqual(y.values[0], 12 / 101 * 100, places=6)

    def test_quarterly(self):
        pairs = [("2024-01-01", 100), ("2024-04-01", 102), ("2024-07-01", 104),
                 ("2024-10-01", 106), ("2025-01-01", 110)]
        y = Series.from_pairs("Q", pairs, frequency="q").yoy()
        self.assertEqual(len(y), 1)
        self.assertAlmostEqual(y.last, 10.0)

    def test_daily_keeps_positional(self):
        """日頻沒有「同月對齊」的語意，維持原本的位置近似。"""
        pairs = [(f"2024-01-{d:02d}", 100 + d) for d in range(1, 20)]
        s = Series.from_pairs("D", pairs, frequency="d")
        self.assertEqual(len(s.yoy()), 0)   # 不足 252 筆 → 空，不是亂算


class TestAnnualised(unittest.TestCase):
    def test_gap_skips_stretched_window(self):
        """跨缺格的年化窗要跳過：3 筆的窗實際跨了 4 個月，按 3 個月年化必偏高。"""
        a3 = monthly(CPI_WITH_GAP).annualised(3)
        dates = [d.isoformat() for d in a3.dates]
        # 2026-01 的 3 個月基期是缺格的 2025-10 → 留白
        self.assertNotIn("2026-01-01", dates)
        # 沒跨缺格的月份照常
        self.assertIn("2026-07-01", dates)

    def test_complete_series(self):
        pairs = [(f"2024-{m:02d}-01", 100 * 1.01 ** m) for m in range(1, 13)]
        a3 = Series.from_pairs("A", pairs, frequency="m").annualised(3)
        # 每月 +1% → 年化約 12.68%
        self.assertAlmostEqual(a3.last, (1.01 ** 12 - 1) * 100, places=6)


class TestDiffMonths(unittest.TestCase):
    def test_gap_regression(self):
        """diff(12) 的位置版在缺格序列上跟 yoy 犯同樣的錯。"""
        pairs = [("2025-06-01", 4.1), ("2025-07-01", 4.2), ("2025-08-01", 4.3),
                 ("2025-09-01", 4.3),  # 2025-10 缺
                 ("2025-11-01", 4.4), ("2025-12-01", 4.4), ("2026-01-01", 4.5),
                 ("2026-02-01", 4.5), ("2026-03-01", 4.6), ("2026-04-01", 4.6),
                 ("2026-05-01", 4.7), ("2026-06-01", 4.7), ("2026-07-01", 4.8)]
        d12 = monthly(pairs).diff_months(12)
        self.assertAlmostEqual(d12.last, 0.6, places=6)          # 4.8 − 4.2
        self.assertEqual(d12.last_date.isoformat(), "2026-07-01")
        # 位置版會算成 4.8 − 4.1 = 0.7


class TestPositionalStillWork(unittest.TestCase):
    """diff(1)/pct_change(1) 的語意是「跟上一筆發布比」，缺格時照舊。"""

    def test_diff_1(self):
        d1 = monthly(CPI_WITH_GAP).diff(1)
        self.assertEqual(len(d1), len(CPI_WITH_GAP) - 1)


if __name__ == "__main__":
    unittest.main()
