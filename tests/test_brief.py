"""brief.json 的載入：格式容錯、過期不用、連結只放行 http(s)。"""
import json
import os
import tempfile
import unittest
from datetime import date

from macro.brief import load, normalise

SAMPLE = {
    "date": "2026-09-07",
    "sections": [
        {"key": "macro", "items": [
            {"headline": "美國 8 月非農 +16.2 萬遠超預期", "detail": "推升 9 月升息定價",
             "source": "4 家", "link": "javascript:alert(1)"},
            {"headline": ""},
        ]},
        {"key": "unknown", "items": [{"headline": "x"}]},
        {"key": "taiwan", "items": []},
    ],
    "synthesis": "油價與通膨優先一致",
}


class TestNormalise(unittest.TestCase):
    def test_keeps_known_sections_in_order_and_drops_bad_links(self):
        brief = normalise(SAMPLE)
        self.assertEqual([s["key"] for s in brief["sections"]], ["macro", "taiwan"])
        self.assertEqual(len(brief["sections"][0]["items"]), 1)
        self.assertEqual(brief["sections"][0]["items"][0]["link"], "")
        self.assertEqual(brief["synthesis"], "油價與通膨優先一致")

    def test_empty_is_none(self):
        self.assertIsNone(normalise({"date": "2026-09-07", "sections": []}))
        self.assertIsNone(normalise({"sections": []}))


class TestLoad(unittest.TestCase):
    def _write(self, payload):
        fd, path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
        return path

    def test_fresh_loads_and_stale_does_not(self):
        path = self._write(SAMPLE)
        self.assertIsNotNone(load(date(2026, 9, 8), path))
        self.assertIsNone(load(date(2026, 9, 10), path))

    def test_missing_file(self):
        self.assertIsNone(load(date(2026, 9, 7), "/nonexistent/brief.json"))
