"""側欄目錄抽取的測試：小標／小小標層級來自渲染完的 HTML。"""
import unittest

from macro.render.html import section
from macro.render.layout import extract_sections


class TestExtractSections(unittest.TestCase):
    def test_levels(self):
        body = (section("us", "美股", "<p>x</p>")
                + section("us-etf", "大盤 ETF", "<p>x</p>", sub=True)
                + section("tw", "台灣股市", "<p>x</p>"))
        self.assertEqual(extract_sections(body), [
            ("us", "美股", 1), ("us-etf", "大盤 ETF", 2), ("tw", "台灣股市", 1)])

    def test_title_unescaped(self):
        body = section("a", "A & B", "<p>x</p>")
        self.assertEqual(extract_sections(body)[0][1], "A & B")


if __name__ == "__main__":
    unittest.main()
