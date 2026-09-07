"""期貨隱含機率的算法測試：反解、月底改用下月合約、機率拆檔。"""
import unittest
from datetime import date

from macro.compute.fedfunds import implied_path, split_probability
from macro.sources.fedfunds import contract_months, symbol_for


def price_for(avg: float) -> float:
    return 100.0 - avg


class TestSplitProbability(unittest.TestCase):
    def test_partial_hike(self):
        p = split_probability(15.0)
        self.assertAlmostEqual(p["hike25"], 0.6)
        self.assertAlmostEqual(p["hold"], 0.4)
        self.assertEqual(p["cut25"], 0.0)

    def test_between_one_and_two_cuts(self):
        p = split_probability(-37.5)
        self.assertAlmostEqual(p["cut25"], 0.5)
        self.assertAlmostEqual(p["cut50"], 0.5)

    def test_no_change(self):
        self.assertAlmostEqual(split_probability(0.0)["hold"], 1.0)


class TestImpliedPath(unittest.TestCase):
    def test_mid_month_meeting_uses_own_contract(self):
        # 9/16 決策，9 月 30 天：前 16 天 4.00、後 14 天 3.75
        avg = (16 * 4.00 + 14 * 3.75) / 30
        rows = implied_path({"2026-09": price_for(avg)}, 4.00,
                            [date(2026, 9, 16)], date(2026, 9, 7))
        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(rows[0]["after"], 3.75, places=3)
        self.assertAlmostEqual(rows[0]["change_bp"], -25.0, places=1)
        self.assertAlmostEqual(rows[0]["p_cut"], 1.0, places=3)
        self.assertEqual(rows[0]["basis"], "2026-09")

    def test_month_end_meeting_uses_next_month(self):
        rows = implied_path({"2026-10": price_for(4.0), "2026-11": price_for(4.25)},
                            4.00, [date(2026, 10, 28)], date(2026, 10, 1))
        self.assertEqual(rows[0]["basis"], "2026-11")
        self.assertAlmostEqual(rows[0]["after"], 4.25, places=3)
        self.assertAlmostEqual(rows[0]["p_hike"], 1.0, places=3)

    def test_chains_meetings_and_stops_without_contract(self):
        avg_sep = (16 * 4.00 + 14 * 3.75) / 30
        rows = implied_path({"2026-09": price_for(avg_sep), "2026-11": price_for(3.50)},
                            4.00, [date(2026, 9, 16), date(2026, 10, 28), date(2026, 12, 9)],
                            date(2026, 9, 7))
        self.assertEqual([r["label"] for r in rows], ["9/16", "10/28"])
        self.assertAlmostEqual(rows[1]["before"], 3.75, places=3)
        self.assertAlmostEqual(rows[1]["cumulative_bp"], -50.0, places=1)

    def test_past_meetings_skipped(self):
        rows = implied_path({"2026-09": 96.0}, 4.0, [date(2026, 9, 16)], date(2026, 9, 20))
        self.assertEqual(rows, [])


class TestContracts(unittest.TestCase):
    def test_symbol(self):
        self.assertEqual(symbol_for(2026, 9), "ZQU26.CBT")
        self.assertEqual(symbol_for(2027, 1), "ZQF27.CBT")

    def test_rolls_over_year(self):
        months = contract_months(date(2026, 11, 15), 3)
        self.assertEqual([ym for ym, _ in months], ["2026-11", "2026-12", "2027-01"])


if __name__ == "__main__":
    unittest.main()
