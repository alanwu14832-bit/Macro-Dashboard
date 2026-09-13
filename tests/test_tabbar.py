"""四分頁的歸屬規則。

歸屬錯了不會報錯，只會讓底部那一排的高亮指向錯的地方——使用者對「我在哪」
的感覺整個歪掉，而這是行動版唯一的主要導覽。
"""
from __future__ import annotations

import re
import unittest

from macro.render.layout import TABS, _tabbar


def current_of(html: str) -> list[str]:
    return re.findall(r'<a class="tab" href="([^"]+)"[^>]*aria-current', html)


class TabOwnership(unittest.TestCase):
    def test_each_tab_owns_its_own_root(self):
        for href, _label, _icon in TABS:
            self.assertEqual(current_of(_tabbar(href)), [href], href)

    def test_exactly_one_tab_is_current(self):
        for path in ("/", "/scenario/", "/tw/", "/find/", "/inflation/",
                     "/deep-dive/", "/guide/", "/archive/"):
            self.assertEqual(len(current_of(_tabbar(path))), 1, path)

    def test_unowned_destinations_belong_to_find(self):
        """18 個目的地是從「尋找」瀏覽進去的，所以高亮留在尋找。"""
        for path in ("/inflation/", "/fed/", "/commodities/", "/explore/"):
            self.assertEqual(current_of(_tabbar(path)), ["/find/"], path)

    def test_uses_links_not_tablist(self):
        """這是文件導覽，不是頁內分頁：每次點擊都是整頁載入。"""
        html = _tabbar("/")
        self.assertIn('aria-label="主要分頁"', html)
        self.assertNotIn("tablist", html)
        self.assertNotIn('role="tab"', html)
        self.assertEqual(html.count("<a class=\"tab\""), 4)


if __name__ == "__main__":
    unittest.main()
