"""_is_macro 的字界迴歸測試：刑事新聞不該混進財金摘要。"""
import unittest

from macro.compute.news import _is_macro


class TestIsMacro(unittest.TestCase):
    def test_federal_case_is_not_fed(self):
        self.assertFalse(_is_macro(
            "Mangione guilty plea expected in federal case Friday"))

    def test_federal_reserve_matches(self):
        self.assertTrue(_is_macro("Federal Reserve holds rates steady"))

    def test_fed_word_matches(self):
        self.assertTrue(_is_macro("Fed signals a rate cut in September"))

    def test_credited_is_not_credit(self):
        self.assertFalse(_is_macro("Director credited for film revival"))

    def test_phrases(self):
        self.assertTrue(_is_macro("Oil price jumps on OPEC supply cut"))


class TestPlural(unittest.TestCase):
    def test_tariffs(self):
        import macro.compute.news as n
        self.assertTrue(n._is_macro("Countries dodge tariffs, White House says"))
