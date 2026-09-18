"""雙目標卡的判定測試。

完整的就業／通膨卡（含 `_employment_headline` 產生的標題）已經移除：它們只在
「當天有新公布」時才出現，而那正好會讓總覽撞上版面預算的硬上限、建置失敗、
CI 跳過提交——網站在最該更新的那一天停住。那些內容留在 /labor/ 與 /inflation/。
"""
import unittest

from macro.render.pages.mandate_cards import _gap_note, _wan


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
