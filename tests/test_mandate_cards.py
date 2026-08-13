"""雙目標卡的判定測試。標題是規則產生的，規則要有測試守。"""
import unittest

from macro.render.pages.mandate_cards import _employment_headline, _gap_note, _wan


class TestEmploymentHeadline(unittest.TestCase):
    def test_negative_payrolls_and_flat_unrate(self):
        self.assertEqual(_employment_headline(-23.0, 20.0, 83.0, 4.1, 4.1),
                         "非農轉負，失業率持穩")

    def test_falling_unrate(self):
        self.assertEqual(_employment_headline(-23.0, 20.0, 83.0, 4.1, 4.2),
                         "非農轉負，失業率下行")

    def test_rising_unrate(self):
        self.assertEqual(_employment_headline(150.0, 100.0, 83.0, 4.3, 4.1),
                         "非農回升，失業率上行")

    def test_slowing(self):
        self.assertIn("非農放緩", _employment_headline(50.0, 100.0, 83.0, 4.1, 4.1))


class TestHelpers(unittest.TestCase):
    def test_wan_signed(self):
        self.assertEqual(_wan(-23.0), "-2.3 萬人")
        self.assertEqual(_wan(20.0), "+2.0 萬人")

    def test_wan_unsigned(self):
        self.assertEqual(_wan(83.27, signed=False), "8.3 萬人")

    def test_wan_none(self):
        self.assertEqual(_wan(None), "—")

    def test_gap_note(self):
        self.assertEqual(_gap_note(20.0, 83.0), "三月均低於門檻")
        self.assertEqual(_gap_note(100.0, 83.0), "三月均高於門檻")
        self.assertEqual(_gap_note(None, 83.0), "—")


if __name__ == "__main__":
    unittest.main()
