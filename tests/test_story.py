"""今日導讀：頭條底下那篇短文（data/brief.json 的 article）。

它是全站唯一不是由程式從資料算出來的文字——由每日排程（一個語言模型）寫。
程式沒辦法檢查它寫得對不對，但有幾件事是機械的，而且壞了不會報錯，只會讓版面說謊：

  1. 一定帶著寫的時間；不知道什麼時候寫的、或寫了超過一天的，不登。
  2. 寫完之後才公布的決議或數據，文章不可能提到——要點名講出來。
  3. 它有自己的印（摘），不借「實」「判」的印。
  4. 太長就不上版，原因留給建置印出來；其餘的要聞不受影響。
  5. 沒有導讀時這一塊整個不出現，版面跟原本一樣。
"""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from macro import brief, clock
from macro.clock import TAIPEI
from macro.render.pages import front_blocks as front
from macro.render.pages import front_tw

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=TAIPEI)
WRITTEN = "2026-10-10T08:52:00+08:00"


def raw(article=None, generated_at=WRITTEN):
    out = {"date": "2026-10-10", "generated_at": generated_at,
           "sections": [{"key": "macro", "items": [{"headline": "美國 CPI 高於預期"}]}]}
    if article is not None:
        out["article"] = article
    return out


class Loading(unittest.TestCase):
    def test_brief_without_an_article_still_loads(self):
        loaded = brief.normalise(raw())
        self.assertEqual(loaded["article"], {})
        self.assertEqual(loaded["article_problems"], [])
        self.assertIsNone(brief.story(loaded, "us", NOW))

    def test_two_paragraphs_per_edition(self):
        loaded = brief.normalise(raw({"us": ["數據。", "新聞。"], "tw": ["台灣數據。", "台灣新聞。"]}))
        self.assertEqual(loaded["article"]["us"], ["數據。", "新聞。"])
        self.assertEqual(loaded["article"]["tw"], ["台灣數據。", "台灣新聞。"])
        self.assertEqual(loaded["article_problems"], [])

    def test_whitespace_is_collapsed_and_empty_paragraphs_dropped(self):
        loaded = brief.normalise(raw({"us": ["  數據\n  一段。 ", "", "   "]}))
        self.assertEqual(loaded["article"]["us"], ["數據 一段。"])

    def test_a_single_string_is_one_paragraph(self):
        self.assertEqual(brief.normalise(raw({"tw": "只有一段。"}))["article"]["tw"], ["只有一段。"])

    def test_too_long_is_dropped_with_a_reason_and_the_other_edition_survives(self):
        loaded = brief.normalise(raw({"us": ["字" * 200, "字" * 200], "tw": ["短的。"]}))
        self.assertNotIn("us", loaded["article"])
        self.assertEqual(loaded["article"]["tw"], ["短的。"])
        self.assertEqual(len(loaded["article_problems"]), 1)
        self.assertIn("美國版導讀沒有上版", loaded["article_problems"][0])
        self.assertIn("400", loaded["article_problems"][0])
        self.assertTrue(loaded["sections"])                 # 要聞不受影響

    def test_three_paragraphs_is_not_a_small_block_any_more(self):
        loaded = brief.normalise(raw({"us": ["一。", "二。", "三。"]}))
        self.assertEqual(loaded["article"], {})
        self.assertIn("3 段", loaded["article_problems"][0])

    def test_wrong_shapes_are_reported_not_crashed_on(self):
        for bad in (["直接給一串"], "一句話", 3):
            loaded = brief.normalise(raw(bad))
            self.assertEqual(loaded["article"], {}, bad)
            self.assertTrue(loaded["article_problems"], bad)
        loaded = brief.normalise(raw({"us": {"body": "x"}, "tw": [1, 2]}))
        self.assertEqual(loaded["article"], {})
        self.assertEqual(len(loaded["article_problems"]), 2)

    def test_hard_limit_is_above_the_target_the_routine_is_given(self):
        self.assertGreater(brief.STORY_HARD, brief.STORY_TARGET)


class Freshness(unittest.TestCase):
    def loaded(self, **kwargs):
        return brief.normalise(raw({"us": ["數據。", "新聞。"]}, **kwargs))

    def test_fresh_article_is_shown_with_its_time(self):
        story = brief.story(self.loaded(), "us", NOW)
        self.assertEqual(story["paragraphs"], ["數據。", "新聞。"])
        self.assertEqual(story["written"], datetime(2026, 10, 10, 8, 52, tzinfo=TAIPEI))

    def test_older_than_a_day_is_not_shown(self):
        """文章裡的「今天」已經不是今天了。"""
        self.assertIsNotNone(brief.story(self.loaded(), "us", NOW + timedelta(hours=20)))
        self.assertIsNone(brief.story(self.loaded(), "us", NOW + timedelta(hours=21)))

    def test_unknown_or_naive_time_is_not_shown(self):
        for stamp in ("", "昨天", "2026-10-10", "2026-10-10T08:52:00"):
            self.assertIsNone(brief.story(self.loaded(generated_at=stamp), "us", NOW), stamp)

    def test_time_in_the_future_is_not_trusted(self):
        self.assertIsNone(brief.story(self.loaded(generated_at="2026-10-10T18:00:00+08:00"), "us", NOW))

    def test_edition_without_an_article_gets_nothing(self):
        self.assertIsNone(brief.story(self.loaded(), "tw", NOW))

    def test_article_can_carry_its_own_time(self):
        """只補導讀、沒重寫要聞的時候，兩個時間不同——導讀用自己的。"""
        loaded = brief.normalise(raw({"us": ["數據。"], "written_at": "2026-10-10T11:30:00+08:00"},
                                     generated_at="2026-10-09T21:50:00+08:00"))
        self.assertEqual(brief.story(loaded, "us", NOW)["written"].hour, 11)

    def test_build_is_told_why_nothing_was_shown(self):
        stale = brief.problems(self.loaded(), NOW + timedelta(days=2))
        self.assertTrue(any("超過 24 小時" in line for line in stale))
        naive = brief.problems(self.loaded(generated_at="2026-10-10T08:52:00"), NOW)
        self.assertTrue(any("帶時區" in line for line in naive))
        self.assertEqual(brief.problems(self.loaded(), NOW), [])
        self.assertEqual(brief.problems(brief.normalise(raw()), NOW), [])
        self.assertEqual(brief.problems(None, NOW), [])


def story(hour=8, minute=52, day=None):
    today = day or clock.today()
    return {"paragraphs": ["核心 PCE 年增 3.0%。", "原油回落約 1%。"],
            "written": datetime(today.year, today.month, today.day, hour, minute, tzinfo=TAIPEI)}


def event(title, hour, *, tag="美國數據　已公布", policy=None, today=True):
    now = clock.today()
    return {"kind": "data", "tag": tag, "title": title, "today": today, "policy": policy,
            "at": datetime(now.year, now.month, now.day, hour, 30, tzinfo=TAIPEI)}


class Block(unittest.TestCase):
    def test_no_story_means_no_block_at_all(self):
        self.assertEqual(front.story_block(None), "")
        self.assertEqual(front.lead_note("<div class=\"gist\">x</div>"),
                         '<div class="lead-note"><div class="gist">x</div></div>')

    def test_block_has_its_own_seal_and_its_time(self):
        html = front.story_block(story())
        self.assertIn(">摘</span>", html)
        self.assertNotIn(">實</span>", html)
        self.assertNotIn(">判</span>", html)
        self.assertIn("寫於 08:52", html)
        self.assertIn("<p>核心 PCE 年增 3.0%。</p><p>原油回落約 1%。</p>", html)
        self.assertIn("只轉述，不另下判斷", html)

    def test_time_carries_the_date_when_it_was_not_written_today(self):
        yesterday = clock.today() - timedelta(days=1)
        html = front.story_block(story(21, 50, day=yesterday))
        self.assertIn(f"寫於 {yesterday.month}/{yesterday.day} 21:50", html)

    def test_text_from_the_file_is_escaped(self):
        html = front.story_block({**story(), "paragraphs": ["<script>alert(1)</script>"]})
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_news_after_the_article_is_named(self):
        """文章 08:52 寫的，CPI 20:30 才公布：文章不可能提到它，不准讓讀者以為有。"""
        html = front.story_block(story(), {"events": [event("CPI", 20)]})
        self.assertIn("寫在「CPI」公布之前，沒有提到它", html)

    def test_decision_after_the_article_is_named_without_the_figures(self):
        decision = event("聯準會升息 1 碼　3.50%–3.75% → 3.75%–4.00%", 14, tag="FOMC　政策轉向", policy="轉向")
        html = front.story_block(story(), {"events": [decision]})
        self.assertIn("寫在「聯準會升息 1 碼」公布之前", html)

    def test_earlier_or_still_pending_events_are_not_flagged(self):
        earlier = event("初領失業金", 2)
        pending = event("CPI", 20, tag="美國數據　今晚公布")
        old = event("PPI", 20, today=False)
        html = front.story_block(story(), {"events": [earlier, pending, old]})
        self.assertNotIn("公布之前", html)

    def test_story_takes_the_main_column_and_the_short_notes_move_aside(self):
        html = front.lead_note('<div class="gist">規則</div>', front.story_block(story()))
        self.assertIn('class="lead-note has-story"', html)
        self.assertLess(html.index('class="story"'), html.index('class="gists"'))
        self.assertIn('<div class="gists"><div class="gist">規則</div></div>', html)


class InBothEditions(unittest.TestCase):
    SCENARIO = {"name": "通膨未解", "regime": "inflation_first", "regime_explain": "x",
                "employment_label": "中", "inflation_label": "高", "regime_label": "通膨優先",
                "transitions": []}
    SUMMARY = {"total": 12, "dovish": 7, "hawkish": 4, "neutral": 1}

    def us(self, story_):
        from macro.data import Bundle
        ctx = {"events": {"events": []}, "_bundle": Bundle(), "rates": {"stance": {}}, "fedfunds": None}
        return front.hero(ctx, self.SCENARIO, self.SUMMARY, {}, [], {"date": "2026-10-09"},
                          story=story_)[0]

    def tw(self, story_):
        taiwan = {"cycle": {"score": 41.0, "light": "紅", "light_streak": 9, "light_meaning": "景氣熱絡",
                            "score_date": clock.today()}, "money": {"policy": 2.0}}
        return front_tw.hero({"taiwan": taiwan, "equities": {}}, [], {}, [], {"date": "2026-10-09"},
                             {"events": []}, story=story_)[0]

    def test_both_editions_place_it_under_the_headline(self):
        for html in (self.us(story()), self.tw(story())):
            self.assertIn('class="lead-note has-story"', html)
            self.assertLess(html.index("</h1>"), html.index('class="story"'))
            self.assertIn("本站規則", html)                 # 原本那幾句還在，只是排到旁邊

    def test_without_a_story_the_hero_is_what_it_was(self):
        for html in (self.us(None), self.tw(None)):
            self.assertNotIn("story", html)
            self.assertIn('class="lead-note"', html)


if __name__ == "__main__":
    unittest.main()
