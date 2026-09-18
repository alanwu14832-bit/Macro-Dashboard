"""HTTP 層的兩道防線。

  - validate：央行新聞稿頁還沒上線時會 302 轉到首頁、最後回 200。沒有檢查的話，
    首頁會以那篇新聞稿的網址被快取一週，整週都讀不到決議。
  - OFFLINE：--offline 原本靠各來源自己把 TTL 設成無限，新加的來源各有短 TTL，
    結果「離線」建置照樣連網。現在在 HTTP 層一刀切。
"""
from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock

from macro import http


class _Response:
    def __init__(self, body: str):
        self._body = body.encode("utf-8")
        self.headers = {}

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class Guard(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patches = [mock.patch.object(http, "CACHE_DIR", self.tmp.name),
                        mock.patch.object(http, "_throttle", lambda host: None),
                        mock.patch.object(http.time, "sleep", lambda s: None)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        http.OFFLINE = False
        self.tmp.cleanup()

    def test_invalid_response_is_not_cached(self):
        url = "https://www.cbc.gov.tw/tw/cp-302-1-x-1.html"
        with mock.patch.object(http.urllib.request, "urlopen",
                               return_value=_Response("<html>中央銀行首頁</html>")):
            with self.assertRaises(http.FetchError):
                http.get(url, validate=lambda body: "發布日期" in body, retries=1)
        self.assertFalse(os.path.exists(http._cache_path(url, "http")))

        with mock.patch.object(http.urllib.request, "urlopen",
                               return_value=_Response("發布日期：2026-09-17 決議")):
            self.assertIn("決議", http.get(url, validate=lambda body: "發布日期" in body, retries=1))

    def test_offline_never_touches_the_network(self):
        http.OFFLINE = True
        with mock.patch.object(http.urllib.request, "urlopen",
                               side_effect=AssertionError("offline 不准連網")):
            with self.assertRaises(http.FetchError):
                http.get("https://example.com/none", ttl=0)
            path = http._cache_path("https://example.com/old", "http")
            http._write_cache(path, "https://example.com/old", "舊資料")
            os.utime(path, (0, 0))
            self.assertEqual(http.get("https://example.com/old", ttl=1), "舊資料")


if __name__ == "__main__":
    unittest.main()
