"""深度專題：Markdown 轉換與報告解析。

報告是外部產生的檔案，抬頭寫法這半年換過三種，解析因此必須對格式寬容，
但有兩件事不能退讓：正文不能被吞掉，以及檔案裡的 HTML 不能原樣輸出。
"""
import os
import tempfile
import unittest

from macro import deepdive
from macro.render import markdown

REPORT = """# 測試標題：兩個分號

**類別 A｜產業結構性議題｜核心標的：1519 華城、1503 士電**
**資料期別：1H26 季報**

---

## 一、結論先行

五家毛利率與營收成長**完全反向**，Spearman ρ = −1.00。

## 二、量化佐證

| 標的 | 毛利率 | 來源 |
|---|---|---|
| 華城 | **43.55%** | TWSE |
| 士電 | 23.05% | TWSE |

- 一般項目
- [x] 自檢通過
"""


class MarkdownTest(unittest.TestCase):
    def test_inline_escapes_before_formatting(self):
        # 報告裡若出現 < 或 script，必須是文字，不是標記
        out = markdown.inline("<script>alert(1)</script> **粗**")
        self.assertNotIn("<script>", out)
        self.assertIn("<strong>粗</strong>", out)

    def test_table_and_list(self):
        out = markdown.to_html(REPORT)
        self.assertIn("<table>", out)
        self.assertIn('<td class="num"><strong>43.55%</strong></td>', out)
        self.assertIn("<li>一般項目</li>", out)
        self.assertIn("dd-task", out)

    def test_unknown_syntax_still_renders_as_text(self):
        out = markdown.to_html("::: 自訂語法 :::\n")
        self.assertIn("自訂語法", out)

    def test_split_h2(self):
        blocks = markdown.split_h2(REPORT)
        self.assertEqual(blocks[0][0], "")                 # 抬頭
        self.assertEqual([b[0] for b in blocks[1:]],
                         ["一、結論先行", "二、量化佐證"])

    def test_first_paragraph_skips_headings_and_tables(self):
        body = markdown.split_h2(REPORT)[1][1]
        self.assertTrue(markdown.first_paragraph(body).startswith("五家毛利率"))


class ParseTest(unittest.TestCase):
    def test_parse_fields(self):
        parsed = deepdive.parse(REPORT, "deep-dive-2026-09-10-grid-equipment.md")
        self.assertEqual(parsed["slug"], "2026-09-10-grid-equipment")
        self.assertEqual(parsed["path"], "/deep-dive/2026-09-10-grid-equipment/")
        self.assertEqual(parsed["date"].isoformat(), "2026-09-10")
        self.assertEqual(parsed["category"], "A")
        self.assertEqual(parsed["title"], "測試標題：兩個分號")
        self.assertIn("華城", parsed["targets"])
        self.assertTrue(parsed["summary"].startswith("五家毛利率"))
        self.assertFalse(parsed["backfill"])

    def test_backfill_only_on_declaration(self):
        # 「補做規則」這種提到補做的排程說明不算，宣告句才算
        note = "> 本篇原規劃於 09-04 撰寫，將依補做規則處理。\n\n" + REPORT
        self.assertFalse(deepdive.parse(note, "deep-dive-2026-09-05-x.md")["backfill"])
        declared = "> 本篇為 2026-09-08 的補做，資料截至 2026-09-11。\n\n" + REPORT
        self.assertTrue(deepdive.parse(declared, "deep-dive-2026-09-08-x.md")["backfill"])
        self.assertTrue(
            deepdive.parse(REPORT, "deep-dive-2026-09-08-x-backfill.md")["backfill"])

    def test_rejects_foreign_filenames(self):
        self.assertIsNone(deepdive.parse(REPORT, "README.md"))
        self.assertIsNone(deepdive.parse(REPORT, "deep-dive-2026-13-99-x.md"))


class LoadTest(unittest.TestCase):
    def test_load_all_sorts_and_uses_topic_log(self):
        with tempfile.TemporaryDirectory() as folder:
            for name in ("deep-dive-2026-09-10-a.md", "deep-dive-2026-09-11-b.md"):
                with open(os.path.join(folder, name), "w", encoding="utf-8") as fh:
                    fh.write("# 無抬頭類別的報告\n\n## 一、結論先行\n\n內文。\n")
            with open(os.path.join(folder, "topic-log.md"), "w", encoding="utf-8") as fh:
                fh.write("| 日期 | 類別 | 主題 | 標的 | 論點 | 狀態 |\n"
                         "|---|---|---|---|---|---|\n"
                         "| 2026-09-11 | D | t | x | y | done |\n"
                         "| 2026-09-10 | B | t | x | y | backfill |\n")
            reports = deepdive.load_all(folder)
        self.assertEqual([r["date"].isoformat() for r in reports],
                         ["2026-09-11", "2026-09-10"])
        self.assertEqual(reports[0]["category"], "D")
        self.assertEqual(reports[1]["category_label"], "總經傳導")
        self.assertTrue(reports[1]["backfill"])

    def test_sync_is_additive(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as dst:
            path = os.path.join(src, "deep-dive-2026-09-10-a.md")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("# 一\n")
            with open(os.path.join(src, "notes.md"), "w", encoding="utf-8") as fh:
                fh.write("不是報告\n")
            self.assertEqual(deepdive.sync(src, dst), ["deep-dive-2026-09-10-a.md"])
            self.assertEqual(deepdive.sync(src, dst), [])      # 沒變就不重寫
            os.remove(path)
            deepdive.sync(src, dst)
            # 來源端刪檔不會把網站上的報告拿掉
            self.assertTrue(os.path.exists(os.path.join(dst, "deep-dive-2026-09-10-a.md")))
            self.assertFalse(os.path.exists(os.path.join(dst, "notes.md")))

    def test_missing_source_is_not_an_error(self):
        self.assertEqual(deepdive.sync("/nonexistent/path", "/tmp"), [])
        self.assertEqual(deepdive.load_all("/nonexistent/path"), [])


if __name__ == "__main__":
    unittest.main()
