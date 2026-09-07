"""observed_updates：資料日期推進才算新、第一次建置不標、同一天持續標。"""
import unittest
from datetime import date

from macro.compute.freshness import observed_updates
from macro.data import Bundle
from macro.series import Series


def bundle_with(pairs, freq="m"):
    b = Bundle()
    b.add("X", Series.from_pairs("X", pairs, label="測試", unit="%", frequency=freq))
    return b


class TestObservedUpdates(unittest.TestCase):
    def test_first_run_marks_nothing(self):
        updates, state = observed_updates(bundle_with([("2026-07-01", 1.0)]), {}, date(2026, 9, 7))
        self.assertEqual(updates, [])
        self.assertEqual(state["X"], {"date": "2026-07-01", "seen": None})

    def test_advanced_date_is_new_and_sticks_for_the_day(self):
        state = {"X": {"date": "2026-07-01", "seen": None}}
        b = bundle_with([("2026-07-01", 1.0), ("2026-08-01", 1.5)])
        updates, state = observed_updates(b, state, date(2026, 9, 7))
        self.assertEqual(len(updates), 1)
        self.assertAlmostEqual(updates[0]["change"], 0.5)
        self.assertEqual(state["X"]["seen"], "2026-09-07")
        # 同一天再建置一次：日期沒再推進，但還是「今天到的」
        again, _ = observed_updates(b, state, date(2026, 9, 7))
        self.assertEqual(len(again), 1)
        # 隔天就不算了
        tomorrow, _ = observed_updates(b, state, date(2026, 9, 8))
        self.assertEqual(tomorrow, [])

    def test_unchanged_is_not_new(self):
        state = {"X": {"date": "2026-07-01", "seen": "2026-09-01"}}
        updates, _ = observed_updates(bundle_with([("2026-07-01", 1.0)]), state, date(2026, 9, 7))
        self.assertEqual(updates, [])
