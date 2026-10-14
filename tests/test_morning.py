"""每日晨報（data/morning/ 與 tools/morning_brief.py）。

晨報是語言模型寫的。程式檢查不了它寫得好不好，只能釘住「壞了不會報錯、只會讓頁面說謊」
的那幾件事。全部不連網、不呼叫 API（寫稿那一段用假的客戶端）：

  1. 市場與判定四欄的數字對不上素材就不出刊；四捨五入可以，換算、自己算不行
  2. 新聞來源只認這次網頁搜尋真的回傳的網址
  3. 週末與美國假日不准把前一個交易日寫成「昨夜」
  4. 「優於／不如預期」「市場共識」不准出現；固定欄目不准寫「市場預期」
  5. 長度、則數、段數、欄目齊全
  6. 沒有今天這一期時，/morning/ 照登上一期並在開頭講明是哪一天的
  7. 同一期只寫一次、只推一次；花過錢沒寫成的那天排程不再重試
  8. 頭版的入口是一行，不是區塊，不吃版面預算
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import date, datetime
from types import SimpleNamespace

from macro import clock, morning
from macro.clock import TAIPEI
from macro.render import layout
from macro.render.pages import morning as page
from macro.render.pages import overview

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import morning_brief  # noqa: E402

DAY = date(2026, 10, 15)          # 週四：前一天（美東週三）有開盤
MATERIAL = morning.session_note(DAY) + """

========================================================================
1. 情境判定與訊號
========================================================================
九宮格　　：軟著陸（就業 穩健 × 通膨 偏高）
訊號分布　：共 7 條／偏升息 3、偏降息 2、中性 2
-- 情境與摘要 ---
     九宮格：軟著陸（同）
    訊號數：7（原 7）
    10 年期       4.1234 %　← 原 4.0811
========================================================================
4. 市場快照
========================================================================
    標普 500       6,712.35    +1.2%    +8.4%
    VIX 16.42　低檔
  ［台股］加權指數 48,626.40　+285.10　+0.59%
========================================================================
6. 今天的事件
  [今天] 待公布｜美國 PPI　（台北 10/15 20:30）
8. 公布前的預期
  下一次　模型預估 2.31%（克里夫蘭聯準銀行）
"""

LONG = "這一段把來龍去脈交代清楚，說明它為什麼跟市場有關，也講出報導者引述的說法與背景。"


def sample(**over) -> dict:
    """一份合格的晨報：每個欄目的數字都在 MATERIAL 裡，長度在範圍內。"""
    raw = {
        "date": DAY.isoformat(),
        "written_at": "2026-10-15T06:52:00+08:00",
        "model": "claude-opus-5-5",
        "title": "台積電法說會登場",
        "lede": "今天的重點是台積電法說會與美國 PPI。" + LONG,
        "stories": [
            {"headline": f"要聞 {i}", "paragraphs": [LONG * 2, LONG * 2],
             "sources": [{"title": f"原文標題 {i}", "outlet": "路透",
                          "url": f"https://www.reuters.com/markets/story-{i}/"}]}
            for i in range(1, 4)
        ],
        "sections": {
            "us": {"heading": "昨夜美國市場", "paragraphs": [
                "標普 500 收在 6,712.35 點，漲 1.2%；VIX 16.42。10 年期殖利率 4.12%。" + LONG]},
            "markets": {"paragraphs": ["加權指數收 48,626 點，漲 285.10 點、0.59%。" + LONG]},
            "watch": {"paragraphs": ["台北晚上 8 點半公布美國 PPI。核心 CPI 的模型預估（克里夫蘭聯準銀行"
                                     " Inflation Nowcasting）是 2.31%。" + LONG]},
            "verdict": {"paragraphs": ["本站判定維持軟著陸，訊號共 7 條，偏升息 3、偏降息 2，跟上一份相同。"
                                       + LONG]},
        },
        "session": {"us_date": "2026-10-14", "overnight": True},
        "checks": {"numbers": 14, "sources": 3, "searches": 3},
        "usage": {"input_tokens": 60000, "output_tokens": 6000, "web_search_requests": 3,
                  "cost_usd": 0.39, "attempts": 1},
    }
    raw.update(over)
    return morning.normalise(raw)


class Session(unittest.TestCase):
    def test_a_weekday_morning_follows_an_overnight_session(self):
        s = morning.session(DAY)
        self.assertTrue(s["overnight"])
        self.assertEqual(s["us_date"], "2026-10-14")
        self.assertEqual(s["heading"], "昨夜美國市場")

    def test_monday_and_sunday_mornings_have_no_overnight_session(self):
        for issue_day in (date(2026, 10, 19), date(2026, 10, 18)):     # 台北週一、週日
            s = morning.session(issue_day)
            self.assertFalse(s["overnight"], issue_day)
            self.assertEqual(s["us_date"], "2026-10-16")                 # 週五
            self.assertIn("10/16 週五", s["heading"])
            self.assertNotIn("昨夜", s["heading"])

    def test_the_morning_after_a_us_holiday(self):
        s = morning.session(date(2026, 11, 27))                          # 感恩節隔天
        self.assertFalse(s["overnight"])
        self.assertEqual(s["us_date"], "2026-11-25")

    def test_the_note_tells_the_model_not_to_say_last_night(self):
        self.assertIn("不能寫「昨夜」", morning.session_note(date(2026, 10, 19)))
        self.assertIn("就是昨夜", morning.session_note(DAY))


class Numbers(unittest.TestCase):
    allowed = morning.material_numbers(MATERIAL)

    def found(self, raw):
        return morning.number_found(raw, self.allowed)

    def test_exact_and_rounded_numbers_pass(self):
        for raw in ("6,712.35", "6,712", "6712.4", "16.42", "4.12", "4.1234", "48,626", "0.59", "2.31"):
            self.assertTrue(self.found(raw), raw)

    def test_numbers_not_in_the_material_fail(self):
        for raw in ("6,800", "4.15", "1.5", "0.7"):
            self.assertFalse(self.found(raw), raw)

    def test_small_integers_must_be_exact_not_rounded(self):
        """失業率 4.3% 寫成 4% 算四捨五入，讀起來卻是另一個數字。"""
        self.assertFalse(self.found("4"))
        self.assertTrue(self.found("7"))                 # 訊號 7 條，素材裡有

    def test_clock_times_can_be_written_in_twelve_hour_form(self):
        self.assertTrue(self.found("8"))                 # 素材 20:30 → 晚上 8 點半
        self.assertTrue(self.found("20"))

    def test_names_are_not_numbers(self):
        self.assertEqual(morning.article_numbers("S&P 500 與 10 年期、M1B、Q3"), [])

    def test_a_good_issue_has_no_unmatched_numbers(self):
        self.assertEqual(morning.unmatched_numbers(sample(), MATERIAL), {})
        self.assertGreater(morning.count_numbers(sample()), 10)

    def test_an_invented_number_is_reported_by_section(self):
        bad = sample()
        bad["sections"]["markets"]["paragraphs"] = ["加權指數收 49,100 點，台積電漲 1.8%。" + LONG]
        self.assertEqual(morning.unmatched_numbers(bad, MATERIAL), {"markets": ["49,100", "1.8"]})

    def test_story_numbers_are_not_checked_against_the_material(self):
        story = sample()
        story["stories"][0]["paragraphs"][0] = "路透報導，營收年增 39.1%。" + LONG
        self.assertEqual(morning.unmatched_numbers(story, MATERIAL), {})


class Shape(unittest.TestCase):
    def test_the_sample_passes(self):
        self.assertEqual(morning.problems(sample()), [])
        self.assertTrue(morning.LENGTH_HARD[0] <= morning.body_length(sample()) <= morning.LENGTH_HARD[1])

    def test_too_few_or_too_many_stories(self):
        two = sample()
        two["stories"] = two["stories"][:2]
        self.assertTrue(any("要聞 2 則" in p for p in morning.problems(two)))

    def test_a_story_without_a_source_blocks_the_issue(self):
        bad = sample()
        bad["stories"][1]["sources"] = []
        self.assertIn("第 2 則要聞沒有來源", morning.problems(bad))

    def test_every_fixed_section_is_required(self):
        bad = sample()
        bad["sections"]["watch"]["paragraphs"] = []
        self.assertTrue(any("今天要看什麼" in p for p in morning.problems(bad)))

    def test_length_bounds(self):
        short = sample()
        for story in short["stories"]:
            story["paragraphs"] = ["短。"]
        for block in short["sections"].values():
            block["paragraphs"] = ["短。"]
        self.assertTrue(any("全文" in p for p in morning.problems(short)))
        long = sample()
        long["lede"] = "字" * 2100
        self.assertTrue(any("全文" in p for p in morning.problems(long)))

    def test_banned_phrases(self):
        bad = sample()
        bad["stories"][0]["paragraphs"][0] = "CPI 優於預期。" + LONG
        self.assertIn("出現「優於預期」", morning.problems(bad))

    def test_market_expectation_is_banned_in_fixed_sections_only(self):
        quoted = sample()
        quoted["stories"][0]["paragraphs"][0] = "路透報導，市場預期聯準會按兵不動。" + LONG
        self.assertEqual(morning.problems(quoted), [])
        ours = sample()
        ours["sections"]["watch"]["paragraphs"][0] += "市場預期不變。"
        self.assertIn("固定欄目出現「市場預期」", morning.problems(ours))

    def test_last_night_is_banned_when_there_was_no_session(self):
        monday = sample(date="2026-10-19", written_at="2026-10-19T06:50:00+08:00")
        monday["sections"]["us"]["paragraphs"][0] = "昨夜美股收高。" + LONG
        self.assertIn("上一個美股交易日不是昨夜，卻寫了「昨夜」", morning.problems(monday))
        self.assertEqual(morning.problems(sample()), [])          # 週四寫昨夜沒問題

    def test_written_time_must_carry_a_zone_and_fall_on_the_issue_date(self):
        self.assertTrue(any("帶時區" in p for p in morning.problems(sample(written_at="2026-10-15T06:52:00"))))
        self.assertTrue(any("不在出刊日" in p
                            for p in morning.problems(sample(written_at="2026-10-14T23:00:00+08:00"))))


class Sources(unittest.TestCase):
    def test_only_urls_returned_by_the_search_count(self):
        issue = sample()
        issue["stories"][0]["sources"].append({"title": "x", "outlet": "彭博",
                                               "url": "https://www.bloomberg.com/made-up"})
        seen = {"https://www.reuters.com/markets/story-1", "https://WWW.REUTERS.COM/markets/story-2/",
                "https://www.reuters.com/markets/story-3/#top"}
        kept, dropped = morning.verify_sources(issue, seen)
        self.assertEqual(dropped, ["https://www.bloomberg.com/made-up"])
        self.assertEqual([len(s["sources"]) for s in kept["stories"]], [1, 1, 1])

    def test_urls_are_collected_only_from_tool_results(self):
        blocks = [
            {"type": "text", "text": "https://invented.example/"},
            {"type": "web_search_tool_result", "content": [
                {"type": "web_search_result", "url": "https://www.reuters.com/a", "title": "A"}]},
            {"type": "bash_code_execution_tool_result",
             "content": {"nested": [{"type": "web_search_result", "url": "https://cna.com.tw/b"}]}},
            {"type": "tool_use", "name": "submit_brief",
             "input": {"sources": [{"type": "web_search_result", "url": "https://self.example/"}]}},
        ]
        self.assertEqual(morning_brief.search_urls(blocks),
                         {"https://www.reuters.com/a", "https://cna.com.tw/b"})


class Storage(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self._saved = morning.MORNING_DIR
        morning.MORNING_DIR = self.dir

    def tearDown(self):
        morning.MORNING_DIR = self._saved
        shutil.rmtree(self.dir)

    def put(self, name, payload):
        with open(os.path.join(self.dir, name), "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False)

    def test_load_keeps_good_issues_newest_first_and_reports_bad_ones(self):
        self.put("2026-10-15.json", sample())
        self.put("2026-10-14.json", sample(date="2026-10-14", written_at="2026-10-14T06:40:00+08:00"))
        self.put("2026-10-13.json", sample(date="2026-10-12"))
        self.put("2026-10-12.json", {"date": "2026-10-12"})
        self.put("failed-2026-10-16.json", {"reason": "x"})
        self.put("notes.txt", {})
        issues, bad = morning.load_all()
        self.assertEqual([i["date"] for i in issues], ["2026-10-15", "2026-10-14"])
        self.assertEqual(issues[0]["path"], "/morning/2026-10-15/")
        self.assertEqual(set(bad), {"2026-10-13.json", "2026-10-12.json"})
        self.assertIn("檔名是 2026-10-13", bad["2026-10-13.json"][0])

    def test_published_issues_do_not_vanish_when_content_rules_tighten(self):
        """用語、長度這類寫稿時的關卡，不回頭把已經登過的一期從網站上拿掉。"""
        stricter = sample()
        stricter["stories"][0]["paragraphs"][0] = "CPI 優於預期。" + LONG
        self.put("2026-10-15.json", stricter)
        issues, bad = morning.load_all()
        self.assertEqual([i["date"] for i in issues], ["2026-10-15"])
        self.assertEqual(bad, {})

    def test_month_spend_counts_published_and_failed_runs_of_that_month(self):
        self.put("2026-10-15.json", sample())
        self.put("failed-2026-10-16.json", {"usage": {"cost_usd": 0.5}})
        self.put("2026-09-30.json", sample(date="2026-09-30"))
        self.assertAlmostEqual(morning.month_spend(2026, 10), 0.89)

    def test_due_writes_each_issue_once(self):
        ok, _ = morning_brief.due(DAY, scheduled=True, hour=7)
        self.assertTrue(ok)
        self.put("2026-10-15.json", sample())
        ok, why = morning_brief.due(DAY, scheduled=False, hour=7)
        self.assertFalse(ok)
        self.assertIn("已經出刊", why)

    def test_scheduled_runs_stay_in_the_morning_window(self):
        self.assertFalse(morning_brief.due(DAY, scheduled=True, hour=15)[0])
        self.assertTrue(morning_brief.due(DAY, scheduled=False, hour=15)[0])

    def test_a_failure_that_cost_money_is_not_retried_by_the_schedule(self):
        self.put("failed-2026-10-15.json", {"reason": "檢查沒過", "usage": {"cost_usd": 0.7}})
        self.assertFalse(morning_brief.due(DAY, scheduled=True, hour=7)[0])
        self.assertTrue(morning_brief.due(DAY, scheduled=False, hour=7)[0])      # 手動可以
        self.put("failed-2026-10-15.json", {"reason": "沒有金鑰", "usage": {"cost_usd": 0}})
        self.assertTrue(morning_brief.due(DAY, scheduled=True, hour=7)[0])       # 沒花錢就再試


class Cost(unittest.TestCase):
    def test_estimate_uses_the_price_table(self):
        usage = {"input_tokens": 100_000, "output_tokens": 10_000, "cache_read_input_tokens": 50_000,
                 "cache_creation_input_tokens": 20_000, "web_search_requests": 4}
        # 0.4 + 0.2 + 0.01 + 0.1 + 0.04
        self.assertAlmostEqual(morning.estimate_cost(usage, "claude-opus-5-5"), 0.75)
        self.assertIsNone(morning.estimate_cost(usage, "unknown-model"))


class Digest(unittest.TestCase):
    def test_trim_drops_the_long_headline_lists_but_keeps_the_rest(self):
        text = ("5. 新聞\n-- 今日焦點 ---\n  [4家] 焦點\n-- 與總經相關 ---\n  · 一則\n"
                "-- 依分類 ---\n  ［科技］\n    · 兩則\n========\n6. 今天的事件\n  [今天] PPI")
        out = morning_brief.trim_digest(text)
        self.assertIn("焦點", out)
        self.assertNotIn("一則", out)
        self.assertNotIn("兩則", out)
        self.assertIn("PPI", out)

    def test_material_starts_with_the_session_note(self):
        self.assertTrue(morning_brief.material_for(DAY, "x").startswith("出刊日：2026-10-15"))


# --------------------------------------------------- 寫稿：假的 API 客戶端 --

def block(**fields):
    data = dict(fields)
    return SimpleNamespace(**fields, to_dict=lambda: data)


def response(stop, content, searches=0):
    usage = SimpleNamespace(input_tokens=1000, output_tokens=500, cache_creation_input_tokens=0,
                            cache_read_input_tokens=0,
                            server_tool_use=SimpleNamespace(web_search_requests=searches))
    return SimpleNamespace(stop_reason=stop, content=content, usage=usage, stop_details=None)


def submission(issue: dict) -> dict:
    return {"title": issue["title"], "lede": issue["lede"], "stories": issue["stories"],
            **{k: issue["sections"][k]["paragraphs"] for k, _ in morning.SECTIONS}}


class FakeClient:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.calls.append(json.loads(json.dumps(kwargs["messages"], default=str)))
        return self.replies.pop(0)


def search_results():
    return block(type="web_search_tool_result", content=[
        {"type": "web_search_result", "url": f"https://www.reuters.com/markets/story-{i}/", "title": "t"}
        for i in range(1, 4)])


class Writer(unittest.TestCase):
    def setUp(self):
        self._now = clock.now
        clock.now = lambda: datetime(2026, 10, 15, 6, 52, tzinfo=TAIPEI)

    def tearDown(self):
        clock.now = self._now

    def test_a_clean_draft_is_published_with_its_checks(self):
        good = submission(sample())
        client = FakeClient([response("tool_use", [search_results(), block(
            type="tool_use", name="submit_brief", id="t1", input=good)], searches=3)])
        issue, usage = morning_brief.write_issue(client, DAY, MATERIAL)
        self.assertEqual(issue["sections"]["us"]["heading"], "昨夜美國市場")
        self.assertEqual(issue["checks"]["sources"], 3)
        self.assertEqual(usage["web_search_requests"], 3)
        self.assertEqual(usage["attempts"], 1)
        self.assertEqual(morning.problems(issue), [])

    def test_a_bad_draft_goes_back_once_with_the_problems_then_passes(self):
        bad = submission(sample())
        bad["markets"] = ["加權指數收 49,100 點。" + LONG]
        good = submission(sample())
        client = FakeClient([
            response("tool_use", [search_results(), block(type="tool_use", name="submit_brief", id="t1", input=bad)]),
            response("tool_use", [block(type="tool_use", name="submit_brief", id="t2", input=good)]),
        ])
        issue, usage = morning_brief.write_issue(client, DAY, MATERIAL)
        self.assertEqual(usage["attempts"], 2)
        feedback = client.calls[1][-1]["content"][0]
        self.assertEqual(feedback["type"], "tool_result")
        self.assertTrue(feedback["is_error"])
        self.assertIn("49,100", feedback["content"])

    def test_still_bad_after_the_repair_round_means_no_issue(self):
        bad = submission(sample())
        bad["markets"] = ["加權指數收 49,100 點。" + LONG]
        reply = lambda i: response("tool_use", [search_results(), block(
            type="tool_use", name="submit_brief", id=f"t{i}", input=bad)])
        client = FakeClient([reply(1), reply(2)])
        with self.assertRaises(morning_brief.Failed) as caught:
            morning_brief.write_issue(client, DAY, MATERIAL)
        self.assertIn("檢查沒過", str(caught.exception))
        self.assertEqual(caught.exception.usage["requests"], 2)

    def test_a_paused_search_loop_is_resumed(self):
        good = submission(sample())
        client = FakeClient([
            response("pause_turn", [search_results()]),
            response("tool_use", [block(type="tool_use", name="submit_brief", id="t1", input=good)]),
        ])
        issue, usage = morning_brief.write_issue(client, DAY, MATERIAL)
        self.assertEqual(usage["requests"], 2)
        self.assertEqual(client.calls[1][-1]["role"], "assistant")      # 原樣接續，不加「繼續」

    def test_refusal_and_no_submission_are_failures(self):
        for reply in (response("refusal", []), response("end_turn", [block(type="text", text="好")])):
            with self.assertRaises(morning_brief.Failed):
                morning_brief.write_issue(FakeClient([reply]), DAY, MATERIAL)

    def test_fake_sources_are_dropped_and_block_the_story(self):
        fake = submission(sample())
        fake["stories"][0]["sources"] = [{"title": "x", "outlet": "路透", "url": "https://invented.example/"}]
        reply = lambda i: response("tool_use", [search_results(), block(
            type="tool_use", name="submit_brief", id=f"t{i}", input=fake)])
        with self.assertRaises(morning_brief.Failed) as caught:
            morning_brief.write_issue(FakeClient([reply(1), reply(2)]), DAY, MATERIAL)
        self.assertIn("第 1 則要聞沒有來源", str(caught.exception))

    def test_the_weekend_heading_comes_from_the_code_not_the_model(self):
        monday = date(2026, 10, 19)
        issue = morning_brief.to_issue(monday, submission(sample()),
                                       datetime(2026, 10, 19, 6, 50, tzinfo=TAIPEI))
        self.assertIn("10/16 週五", issue["sections"]["us"]["heading"])
        self.assertFalse(issue["session"]["overnight"])


# ------------------------------------------------------------------ 頁面 --

class Pages(unittest.TestCase):
    def issues(self):
        older = sample(date="2026-10-14", written_at="2026-10-14T06:40:00+08:00", title="昨天那一期")
        out = []
        for issue in (sample(), older):
            issue["day"] = date.fromisoformat(issue["date"])
            issue["path"] = f"/morning/{issue['date']}/"
            out.append(issue)
        return out

    def test_index_shows_the_latest_issue_in_full_and_the_past_list(self):
        html = page.render_index(self.issues(), today=DAY)
        self.assertIn("台積電法說會登場", html)
        self.assertIn('class="seal s-sum"', html)                     # 摘：語言模型寫的
        self.assertIn("台北 <time", html)
        self.assertIn('href="https://www.reuters.com/markets/story-1/"', html)
        self.assertIn("昨天那一期", html)
        self.assertNotIn("mb-stale", html)
        anchors = [a for a, _t, _l in layout.extract_sections(html)]
        self.assertEqual(anchors, ["stories", "us", "markets", "watch", "verdict", "method", "past"])

    def test_without_todays_issue_the_page_says_whose_issue_it_is(self):
        html = page.render_index(self.issues(), today=date(2026, 10, 16),
                                 reason="寫好的稿沒過自動檢查，所以沒有登")
        self.assertIn("這是 10/15 週四 的晨報。今天（10/16 週五）的還沒有出刊", html)
        self.assertIn("沒過自動檢查", html)

    def test_failure_reasons_are_shown_in_plain_words(self):
        saved = morning.MORNING_DIR
        morning.MORNING_DIR = tempfile.mkdtemp()
        try:
            with open(morning.failed_path(DAY), "w", encoding="utf-8") as fh:
                json.dump({"reason": "檢查沒過：「台股美股」裡的 49,100 在素材裡找不到"}, fh,
                          ensure_ascii=False)
            self.assertEqual(page.failure_reason(DAY), "寫好的稿沒過自動檢查，所以沒有登")
        finally:
            shutil.rmtree(morning.MORNING_DIR)
            morning.MORNING_DIR = saved

    def test_no_issues_yet_is_said_not_left_blank(self):
        self.assertIn("還沒有任何一期", page.render_index([], today=DAY))

    def test_weekend_heading_is_rendered_as_stored(self):
        monday = sample(date="2026-10-19", written_at="2026-10-19T06:50:00+08:00")
        monday["sections"]["us"]["heading"] = morning.session(date(2026, 10, 19))["heading"]
        monday["day"], monday["path"] = date(2026, 10, 19), "/morning/2026-10-19/"
        html = page.render_index([monday], today=date(2026, 10, 19))
        self.assertIn("最近一個交易日的美國市場（10/16 週五）", html)

    def test_issue_page_links_to_its_neighbours(self):
        newer, older = self.issues()
        html = page.render_issue(older, newer=newer)
        self.assertIn('href="/morning/2026-10-15/"', html)
        self.assertIn('href="/morning/"', html)

    def test_front_row_is_one_line_and_not_a_section(self):
        row = page.front_row(self.issues(), today=DAY)
        self.assertIn('href="/morning/"', row)
        self.assertIn("今天", row)
        used = overview.measure(row)
        self.assertEqual((used["sections"], used["tables"], used["cells"], used["accordions"]), (0, 0, 0, 0))
        self.assertIn("10/15 週四", page.front_row(self.issues(), today=date(2026, 10, 16)))
        self.assertEqual(page.front_row(self.issues(), today=date(2026, 10, 17)), "")
        self.assertEqual(page.front_row([], today=DAY), "")

    def test_morning_is_in_the_navigation(self):
        self.assertIn("/morning/", [href for href, *_ in layout.NAV])


class Push(unittest.TestCase):
    def test_push_points_to_the_morning_page_once_per_issue(self):
        import send_push
        saved = morning.MORNING_DIR
        morning.MORNING_DIR = tempfile.mkdtemp()
        try:
            with open(morning.path_for(DAY), "w", encoding="utf-8") as fh:
                json.dump(sample(), fh, ensure_ascii=False)
            payload = send_push.compose_morning(DAY)
            self.assertEqual(payload["url"], "/morning/")
            self.assertEqual(payload["tag"], "morning-2026-10-15")
            self.assertIn("晨報｜10/15 週四", payload["title"])
            self.assertIsNone(send_push.compose_morning(date(2026, 10, 16)))
        finally:
            shutil.rmtree(morning.MORNING_DIR)
            morning.MORNING_DIR = saved


if __name__ == "__main__":
    unittest.main()
