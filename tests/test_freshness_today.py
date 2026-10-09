"""observed_updates：資料日期推進才算新、第一次建置不標、同一天持續標。

新加進目錄的序列第一次出現也不標，模型的預估永遠不標——這兩個是 2026-10-10
上線「公布前的預期」之後在正式站看到的：頭版「今天更新的序列」多了 GDPNow
（這一季的預估減上一季的預估，還上了黃色）和兩個月前就公布的招聘數。
"""
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

    def test_a_series_new_to_the_catalogue_is_not_an_update(self):
        """狀態檔裡有別的序列、沒有這一檔：它是剛加進目錄的，不是今天才公布的。"""
        state = {"OTHER": {"date": "2026-08-01", "seen": "2026-09-01"}}
        b = bundle_with([("2026-07-01", 1.0), ("2026-08-01", 1.5)])
        updates, new_state = observed_updates(b, state, date(2026, 9, 7))
        self.assertEqual(updates, [])
        self.assertEqual(new_state["X"], {"date": "2026-08-01", "seen": None})
        # 之後它的資料日期真的往前推，才算
        later = bundle_with([("2026-08-01", 1.5), ("2026-09-01", 1.6)])
        updates, _ = observed_updates(later, new_state, date(2026, 10, 7))
        self.assertEqual([u["id"] for u in updates], ["X"])

    def test_a_model_estimate_is_never_listed_as_a_data_update(self):
        """GDPNow 一季一個值：「3.59 對前值 1.54」是兩季的預估相減，不是誰公布了什麼。"""
        b = Bundle()
        b.add("GDPNOW", Series.from_pairs("GDPNOW", [("2026-04-01", 1.54), ("2026-07-01", 3.59)],
                                          label="GDPNow 即時預估", unit="%", frequency="q"))
        state = {"GDPNOW": {"date": "2026-04-01", "seen": None}}
        updates, new_state = observed_updates(b, state, date(2026, 10, 10))
        self.assertEqual(updates, [])
        self.assertEqual(new_state["GDPNOW"]["date"], "2026-07-01")   # 狀態照記

    def test_unchanged_is_not_new(self):
        state = {"X": {"date": "2026-07-01", "seen": "2026-09-01"}}
        updates, _ = observed_updates(bundle_with([("2026-07-01", 1.0)]), state, date(2026, 9, 7))
        self.assertEqual(updates, [])
