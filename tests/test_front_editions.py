"""頭版的兩個版：美國｜台灣。

兩版同一個網址、段落一一對應，但有幾件事不能混，混了不會報錯，只會讓版面說謊：

  1. 各版只看自己那一邊的事件。台灣央行的決議不能搶走美國版的頭條，反過來也是。
  2. 台灣沒有九宮格。台灣版的頭條退回的是國發會的燈號（機構事實），永遠不是本站的
     判定；「本站的判定」不標升降息方向，也沒有「情境傾向」那一格。
  3. 尺：只有國發會的燈號有寫死的分界，其餘三個數字一律是區間尺。圖上官方的區間
     塗灰底，斜線留給本站規則。
  4. 上一期的存檔沒有記台灣讀數時，是「比不了」，不是「沒變」。
  5. 版面預算一版一份，不是兩版加起來。
"""
from __future__ import annotations

import html
import json
import re
import unittest
from datetime import date, datetime, time

from macro import archive
from macro.clock import TAIPEI
from macro.compute import events
from macro.render.pages import front_tw, frontpage, overview
from macro.series import Series

NOW = datetime(2026, 10, 10, 9, 0, tzinfo=TAIPEI)


def ev(kind, region, tag, title, *, today=True, policy=None, **extra):
    return {"kind": kind, "region": region, "tag": tag, "title": title, "today": today,
            "policy": policy, "detail": "細節。", "href": "/x/", "sev": "medium", **extra}


FOMC = ev("policy", "美國", "FOMC　政策轉向", "聯準會升息 1 碼　3.50%–3.75% → 3.75%–4.00%", policy="轉向")
CBC = ev("policy", "台灣", "台灣央行　政策調整", "台灣央行利率不變（重貼現率 2%）；調整房貸信用管制",
         policy="調整")
CBC_GAP = ev("policy", "台灣", "台灣央行　決議遺漏", "9/17 台灣央行決議本站沒有取得", policy="遺漏")
CBC_SOON = ev("policy", "台灣", "台灣央行　16:30 公布", "台灣央行利率決議", policy="待公布")
LIGHT_OUT = ev("data", "台灣", "台灣數據　已公布", "景氣對策信號", period="11508")
LIGHT_SOON = ev("data", "台灣", "台灣數據　16:00 公布", "景氣對策信號", period="11509")
JOBLESS = ev("data", "台灣", "台灣數據　已公布", "失業率", period="11508")
US_CPI = ev("data", "美國", "美國數據　已公布", "CPI", id="CPIAUCSL")


def scores(*values, end=(2026, 8)):
    """以 end 為最後一個月，往回排出一條月頻的分數序列。"""
    year, month = end
    pairs = []
    for value in reversed(values):
        pairs.append((date(year, month, 1), float(value)))
        year, month = (year, month - 1) if month > 1 else (year - 1, 12)
    return Series.from_pairs("TW_SIGNAL", list(reversed(pairs)), frequency="m")


def taiwan(**overrides):
    series = scores(*([20] * 20), 30, 34, 37, 38, 39, 41, 41, 41)
    data = {
        "cycle": {"score": 41.0, "score_date": date(2026, 8, 1), "light": "紅",
                  "light_meaning": "景氣熱絡", "light_streak": 9, "leading_up": 13,
                  "leading_down": 0, "score_series": series},
        "external": {"customs_yoy": 60.9, "customs_date": date(2026, 9, 1),
                     "customs_yoy_series": scores(20.6, 33.0, 69.9, 60.9, end=(2026, 9)),
                     "orders_amount_yoy": 61.9, "orders_amount_date": date(2026, 7, 1)},
        "labour": {"cpi_yoy": 1.62, "cpi_date": date(2026, 9, 1),
                   "cpi_series": scores(1.4, 1.5, 1.7, 1.62, end=(2026, 9)),
                   "unemployment": 3.41, "unemployment_low_12m": 3.27},
        "money": {"policy": 2.0, "policy_unchanged_months": 31, "spread_vs_fed": -2.0,
                  "fed_upper": 4.0, "policy_series": scores(1.125, 1.5, 1.875, 2.0)},
        "output": {"gdp_growth": 12.93},
        "gaps": [], "cbc_schedule": [date(2026, 12, 17)],
    }
    for key, value in overrides.items():
        data[key] = {**data[key], **value} if isinstance(value, dict) else value
    return data


class EachEditionSeesItsOwnEvents(unittest.TestCase):
    ALL = {"events": [FOMC, CBC, LIGHT_OUT, US_CPI], "date": NOW.date(), "weekday": "六",
           "calendar_ok": False, "us_calendar_ok": False, "us_calendar_failed": ["BLS"]}

    def test_events_are_split_by_region(self):
        tw = events.for_region(self.ALL, "台灣")
        us = events.for_region(self.ALL, "美國")
        self.assertEqual([e["title"] for e in tw["events"]], [CBC["title"], "景氣對策信號"])
        self.assertEqual([e["title"] for e in us["events"]], [FOMC["title"], "CPI"])

    def test_first_sentence_names_the_region(self):
        quiet = events.for_region({"events": [FOMC], "calendar_ok": True, "us_calendar_ok": True},
                                  "台灣")
        self.assertEqual(quiet["verdict"], "今天台灣沒有重大數據或政策決議。")
        busy = events.for_region(self.ALL, "台灣")
        self.assertTrue(busy["verdict"].startswith("今天台灣有政策調整 1 項、重大數據 1 項"))

    def test_only_its_own_calendar_failure_is_reported(self):
        """美國行事曆抓不到不關台灣版的事；它會在美國版被講出來。"""
        tw = events.for_region(self.ALL, "台灣")
        us = events.for_region(self.ALL, "美國")
        self.assertIn("台灣統計發布看板", tw["verdict"])
        self.assertNotIn("美國發布行事曆", tw["verdict"])
        self.assertTrue(tw["us_calendar_ok"])
        self.assertIn("美國發布行事曆", us["verdict"])
        self.assertNotIn("台灣統計發布看板", us["verdict"])
        self.assertTrue(us["calendar_ok"])

    def test_us_decision_never_becomes_the_taiwan_headline(self):
        lede = frontpage.lede_tw(events.for_region({"events": [FOMC]}, "台灣"), taiwan())
        self.assertEqual(lede["kind"], "state")

    def test_upcoming_taiwan_releases_are_future_major_ones_only(self):
        board = [
            {"label": "外銷訂單", "date": date(2026, 10, 20), "time": time(16), "dept": "經濟部", "period": "11509"},
            {"label": "外銷訂單", "date": date(2026, 10, 20), "time": time(16), "dept": "經濟部", "period": "11509"},
            {"label": None, "date": date(2026, 10, 15), "time": time(16), "dept": "財政部", "period": "11509"},
            {"label": "失業率", "date": date(2026, 10, 10), "time": time(16), "dept": "主計總處", "period": "11509"},
        ]
        out = events.taiwan_upcoming(board, NOW)
        self.assertEqual([(i["label"], i["days"]) for i in out], [("外銷訂單", 10)])


class TaiwanHeadline(unittest.TestCase):
    def pick(self, *listed, data=None):
        return frontpage.lede_tw({"events": list(listed)}, taiwan() if data is None else data)

    def test_order_is_gap_decision_data_pending_then_the_light(self):
        self.assertEqual(self.pick(CBC_GAP, CBC, LIGHT_OUT)["kind"], "gap")
        self.assertEqual(self.pick(CBC, LIGHT_OUT, CBC_SOON)["kind"], "policy")
        self.assertEqual(self.pick(LIGHT_OUT, CBC_SOON)["headline"], "景氣對策信號")
        self.assertEqual(self.pick(CBC_SOON, LIGHT_SOON)["headline"], "台灣央行利率決議")
        self.assertEqual(self.pick(LIGHT_SOON)["kind"], "pending")
        self.assertEqual(self.pick()["kind"], "state")

    def test_quiet_day_reports_the_official_light_not_a_site_verdict(self):
        lede = self.pick()
        self.assertEqual(lede["headline"], "景氣紅燈，已連續 9 個月。")
        self.assertTrue(lede["fallback"])
        self.assertIn("今天台灣沒有", lede["quiet"])
        self.assertIn("2026-08", lede["deck"])               # 帶自己的資料期
        for listed in ([], [CBC], [LIGHT_OUT], [CBC_SOON], [CBC_GAP]):
            self.assertNotEqual(self.pick(*listed)["kind"], "verdict")

    def test_unemployment_is_listed_but_never_the_headline(self):
        self.assertEqual(self.pick(JOBLESS)["kind"], "state")

    def test_figure_only_when_the_month_on_hand_is_the_month_released(self):
        """看板說已公布，本站不一定已經抓到那一期。對不上就不准把舊數字印成頭條。"""
        same = self.pick(LIGHT_OUT)
        self.assertEqual(same["figure"], "41 分　紅燈")
        stale = self.pick(dict(LIGHT_OUT, period="11509"))
        self.assertEqual(stale["figure"], "")
        self.assertIn("本站手上最新的是 2026-08", stale["deck"])
        self.assertIn("這一期還沒有進來", stale["deck"])
        unknown = self.pick(dict(LIGHT_OUT, period="115年第3季"))
        self.assertEqual(unknown["figure"], "")
        self.assertNotIn("還沒有進來", unknown["deck"])       # 認不得資料期就不下這個斷言

    def test_pending_release_shows_last_period_in_the_deck(self):
        lede = self.pick(LIGHT_SOON)
        self.assertEqual(lede["figure"], "")
        self.assertIn("上一期（2026-08）41 分", lede["deck"])

    def test_missing_ndc_data_is_a_gap_not_a_blank(self):
        lede = self.pick(data=taiwan(cycle={"score": None, "light": None}))
        self.assertEqual(lede["kind"], "gap")
        self.assertIn("沒有取得", lede["headline"])


class LightGate(unittest.TestCase):
    def test_distance_to_the_nearest_change_of_light(self):
        red = front_tw.light_gate(41, "紅")
        self.assertEqual((red["word"], red["value"], red["line"], red["to"]), ("高出", 3, 38, "黃紅"))
        rising = front_tw.light_gate(30, "綠")
        self.assertEqual((rising["word"], rising["value"], rising["line"], rising["to"]),
                         ("還差", 2, 32, "黃紅"))
        falling = front_tw.light_gate(24, "綠")
        self.assertEqual((falling["word"], falling["value"], falling["to"]), ("高出", 1, "黃藍"))
        blue = front_tw.light_gate(12, "藍")
        self.assertEqual((blue["word"], blue["value"], blue["to"]), ("還差", 5, "黃藍"))

    def test_unknown_light_has_no_gate(self):
        self.assertIsNone(front_tw.light_gate(None, None))
        self.assertIsNone(front_tw.light_gate(41, "紫"))

    def test_floors_come_from_the_official_bands(self):
        self.assertEqual(front_tw.FLOORS, {"藍": 9, "黃藍": 17, "綠": 23, "黃紅": 32, "紅": 38})


class SinceLastIssue(unittest.TestCase):
    CTX = {"taiwan": taiwan()}

    def test_prior_without_taiwan_readings_is_not_comparable(self):
        readings = archive.taiwan_readings(self.CTX)
        self.assertIsNone(archive.taiwan_changes(readings, {"date": "2026-10-09", "readings": {}}))
        self.assertIsNone(archive.taiwan_changes(readings, None))

    def test_same_readings_are_no_change(self):
        readings = archive.taiwan_readings(self.CTX)
        self.assertEqual(archive.taiwan_changes(readings, {"readings_tw": dict(readings)}), [])

    def test_light_change_and_reading_change(self):
        readings = archive.taiwan_readings(self.CTX)
        was = dict(readings, light="黃紅", score=37.0, policy=1.875)
        changes = archive.taiwan_changes(readings, {"readings_tw": was})
        self.assertEqual(changes[0], {"name": "景氣燈號", "text": "黃紅→紅"})
        by_name = {c["name"]: c for c in changes[1:]}
        self.assertEqual(by_name["景氣對策信號"]["change"], 4.0)
        self.assertAlmostEqual(by_name["重貼現率"]["change"], 0.125)
        items = front_tw.since_items({}, changes)
        self.assertEqual(items[0]["big"], "黃紅→紅")
        self.assertIn("+4", [i["big"] for i in items])
        self.assertIn("+0.125", [i["big"] for i in items])

    def test_hero_says_cannot_compare_instead_of_unchanged(self):
        body, changed = front_tw.hero({"taiwan": taiwan(), "equities": {}}, [], {}, None,
                                      {"date": "2026-10-09"}, {"events": []})
        self.assertIn("上一期沒有記台灣的讀數", body)
        self.assertNotIn("相同", body)
        self.assertFalse(changed)
        same, _ = front_tw.hero({"taiwan": taiwan(), "equities": {}}, [], {}, [],
                                {"date": "2026-10-09"}, {"events": []})
        self.assertIn("與 2026-10-09 相同", same)

    def test_hero_is_stamped_as_fact_and_uses_its_own_anchors(self):
        body, _ = front_tw.hero({"taiwan": taiwan(), "equities": {}}, [], {}, [],
                                {"date": "2026-10-09"}, {"events": []})
        self.assertIn(">實</span>", body)
        self.assertNotIn(">判</span>", body)
        self.assertIn('id="tw-lede"', body)
        self.assertIn('id="tw-lede-h"', body)
        self.assertIn('id="tw-h-since"', body)
        self.assertIn("不下結論句", body)

    def test_fact_margin_without_a_prior_reading_is_a_dash_not_unchanged(self):
        from macro.render.pages import front_blocks as front
        item = {"change": None, "gap": None}
        self.assertIn("未變", front._fact_note(item, "2026-10-09", True))
        self.assertNotIn("未變", front._fact_note(item, "2026-10-09", False))
        self.assertIn("上期未記", front._fact_note(item, "2026-10-09", False))


class RulersAndChart(unittest.TestCase):
    def test_only_the_official_light_has_a_threshold_ruler(self):
        rows = front_tw.figure_rows({"taiwan": taiwan()}, [])
        self.assertEqual([r["name"] for r in rows], ["景氣對策信號", "出口年增", "CPI 年增", "重貼現率"])
        self.assertEqual([r["ruler"]["kind"] for r in rows], ["threshold", "range", "range", "range"])
        self.assertEqual(rows[0]["gap"]["word"], "高出")
        for row in rows[1:]:
            self.assertIsNone(row["gap"])                     # 沒有門檻就沒有「離門檻多遠」
            self.assertIn("沒有寫死的門檻", row["sub"])

    def test_every_row_carries_its_own_data_period(self):
        rows = front_tw.figure_rows({"taiwan": taiwan()}, [])
        self.assertIn("2026-08", rows[0]["sub"])
        self.assertIn("2026-09", rows[1]["sub"])
        self.assertIn("2026-09", rows[2]["sub"])

    def test_missing_cpi_is_marked_missing_and_draws_no_ruler(self):
        data = taiwan(labour={"cpi_yoy": None, "cpi_date": None, "cpi_series": Series.from_pairs("x", [])})
        rows = front_tw.figure_rows({"taiwan": data}, [])
        cpi = rows[2]
        self.assertTrue(cpi["missing"])
        self.assertEqual(cpi["value"], "—")
        section = front_tw.facts({"taiwan": data}, [], {"date": "2026-10-09"})
        cell = section.split("CPI 年增")[1].split("</article>")[0]
        self.assertIn(">缺</span>", cell)
        self.assertNotIn('class="ruler', cell)
        self.assertIn("沒有資料", cell)

    def test_exports_fall_back_to_the_ndc_series_and_say_so(self):
        data = taiwan(external={"customs_yoy": None, "customs_date": None, "exports_yoy": 52.6,
                                "exports_date": date(2026, 8, 1),
                                "exports_yoy_series": scores(30.0, 52.6)})
        row = front_tw.figure_rows({"taiwan": data}, [])[1]
        self.assertEqual(row["value"], "+52.6%")
        self.assertIn("國發會轉載，新台幣計", row["sub"])

    def test_chart_shades_official_zones_and_never_hatches(self):
        """斜線在這一頁專指本站規則判定的區域；國發會的燈號區間只能塗灰底。"""
        figure = front_tw.signal_chart({"taiwan": taiwan()})
        spec = json.loads(html.unescape(re.search(r'data-gate="([^"]*)"', figure).group(1)))
        self.assertEqual(spec["gate"], 38)
        self.assertEqual((spec["gapWord"], spec["gap"]), ("高出", "3"))
        self.assertTrue(spec["zones"])
        self.assertTrue(all(zone["style"] == "tint" for zone in spec["zones"]))
        self.assertIsNone(spec["goal"])
        self.assertIn("不是本站的門檻", figure)
        self.assertTrue(all(spec["lo"] < t["v"] < spec["hi"] for t in spec["thr"]))

    def test_no_chart_without_a_light(self):
        self.assertEqual(front_tw.signal_chart({"taiwan": taiwan(cycle={"score": None, "light": None})}), "")
        self.assertEqual(front_tw.signal_chart({}), "")


class TaiwanVerdict(unittest.TestCase):
    SIGNALS = [
        {"key": "tw_signal_light_extreme", "headline": "台灣景氣對策信號亮紅燈", "why": "w",
         "evidence": "e", "direction": "neutral", "severity": "high", "module": "台灣"},
        {"key": "tw_m1b_below_m2", "headline": "台灣 M1B 年增率低於 M2", "why": "w",
         "evidence": "e", "direction": "neutral", "severity": "low", "module": "台灣"},
    ]

    def test_no_direction_and_no_regime(self):
        body = front_tw.verdict(self.SIGNALS, {})
        self.assertIn('id="tw-verdict"', body)
        self.assertIn("台灣規則訊號 <i>2</i> 條", body)
        for word in ("利升息", "利降息", "中性", "偏升息", "偏降息"):
            self.assertNotIn(word, re.sub(r'data-rule="[^"]*"', "", body))
        self.assertEqual(body.count('class="call"'), 1)       # 只有訊號條數那一格
        self.assertNotIn("call-regime", body)
        self.assertNotIn("gridmap", body)

    def test_new_signal_is_highlighted(self):
        body = front_tw.verdict(self.SIGNALS, {"added": [self.SIGNALS[0]]})
        self.assertIn('class="mn chg"', body)

    def test_nothing_triggered(self):
        body = front_tw.verdict([], {})
        self.assertIn("沒有觸發", body)


class NextAndPrices(unittest.TestCase):
    def test_gates_separate_official_boundary_from_site_threshold(self):
        gates = front_tw.gates({"taiwan": taiwan()})
        self.assertEqual([g["kind"] for g in gates], ["官方分界", "門檻"])
        self.assertEqual(gates[0]["value"], "3")
        self.assertEqual(gates[1]["value"], "0.16")           # 3.27 + 0.3 − 3.41

    def test_unemployment_gate_disappears_once_triggered(self):
        gates = front_tw.gates({"taiwan": taiwan(labour={"unemployment": 3.6})})
        self.assertEqual([g["kind"] for g in gates], ["官方分界"])

    def test_exchange_rate_is_not_coloured_as_a_gain(self):
        rows = front_tw.price_rows({"equities": {"tw": {
            "index": [{"symbol": "^TWII", "price": 49313.44, "change_percent": -0.99}],
            "usdtwd": {"value": 32.01, "as_of": "2026-10-02", "chg_3m": -0.09}}}})
        self.assertEqual([r["name"] for r in rows], ["加權指數", "美元兌新台幣"])
        self.assertTrue(rows[1]["plain"])
        self.assertNotIn("plain", rows[0])


BRIEF = {"date": date(2026, 10, 9), "synthesis": "與本期判斷的交集：通膨黏。", "sections": [
    {"title": "總經數據與事件", "items": [{"headline": "美國 CPI 高於預期"}]},
    {"title": "台灣", "items": [{"headline": "台股收跌"}]},
]}


class Brief(unittest.TestCase):
    def test_each_edition_gets_its_own_news(self):
        tw = overview._curated_brief(BRIEF, "台灣")
        us = overview._curated_brief(BRIEF, "美國")
        self.assertIn("台股收跌", tw)
        self.assertNotIn("美國 CPI", tw)
        self.assertNotIn("與本期判斷的交集", tw)             # 那句講的是九宮格，只跟著美國版
        self.assertIn("美國 CPI", us)
        self.assertNotIn("台股收跌", us)
        self.assertIn("與本期判斷的交集", us)

    def test_no_taiwan_items_is_said_out_loud(self):
        only_us = dict(BRIEF, sections=BRIEF["sections"][:1])
        self.assertIn("沒有台灣的項目", overview._curated_brief(only_us, "台灣"))


SECTION = '<section id="{}"><div class="section-head"><h2>t</h2></div></section>'


class BudgetPerEdition(unittest.TestCase):
    def page(self, us: int, tw: int, shared: int = 1) -> str:
        return ("<header>刊頭</header>"
                + overview.edition("us", "".join(SECTION.format(f"u{i}") for i in range(us)))
                + overview.edition("tw", "".join(SECTION.format(f"tw-u{i}") for i in range(tw)))
                + "".join(SECTION.format(f"s{i}") for i in range(shared)))

    def test_each_edition_is_measured_with_the_shared_parts(self):
        parts = overview.editions(self.page(7, 5))
        self.assertEqual(set(parts), {"us", "tw"})
        self.assertEqual(overview.measure(parts["us"])["sections"], 8)
        self.assertEqual(overview.measure(parts["tw"])["sections"], 6)
        self.assertIn("刊頭", parts["tw"])

    def test_two_full_editions_fit_the_budget(self):
        """兩版各 8 個區塊是 15 個 <section>；預算管的是一版有多長，不是 HTML 有多大。"""
        hard, _soft = overview.budget_report(self.page(7, 7))
        self.assertEqual(hard, [])

    def test_overflow_names_the_edition(self):
        hard, _soft = overview.budget_report(self.page(7, 8))
        self.assertEqual(len(hard), 1)
        self.assertTrue(hard[0].startswith("台灣版sections 9"))

    def test_page_without_edition_markers_is_measured_whole(self):
        self.assertEqual(set(overview.editions(SECTION.format("x"))), {""})


if __name__ == "__main__":
    unittest.main()
