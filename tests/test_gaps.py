"""calendar_gaps 的測試：缺格偵測是防線，防線自己也要有測試。"""
import unittest

from macro.data import Bundle, calendar_gaps
from macro.series import Series


def bundle_with(series_id, pairs, freq="m"):
    b = Bundle()
    b.add(series_id, Series.from_pairs(series_id, pairs, frequency=freq))
    return b


class TestCalendarGaps(unittest.TestCase):
    def test_detects_interior_gap(self):
        pairs = [(f"2025-{m:02d}-01", 1.0) for m in (6, 7, 8, 9, 11, 12)]
        gaps = calendar_gaps(bundle_with("X", pairs))
        self.assertEqual(list(gaps), [(2025, 10)])
        self.assertEqual(gaps[(2025, 10)], ["X"])

    def test_trailing_lag_is_not_a_gap(self):
        """發布落後（尾端還沒到）不是缺格，不該誤報。"""
        pairs = [(f"2025-{m:02d}-01", 1.0) for m in range(1, 10)]
        self.assertEqual(calendar_gaps(bundle_with("X", pairs)), {})

    def test_non_monthly_ignored(self):
        pairs = [("2025-01-01", 1.0), ("2025-07-01", 2.0), ("2026-01-01", 3.0)]
        self.assertEqual(calendar_gaps(bundle_with("Q", pairs, freq="q")), {})


if __name__ == "__main__":
    unittest.main()
