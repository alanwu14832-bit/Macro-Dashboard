"""總覽「今天」：一眼回答今天有沒有重大數據或政策轉向。

會靜默給錯答案的地方：
  - 時區。FOMC 美東 14:00 的聲明是台北隔天凌晨；美東 8:30 的數據是台北當晚。
    用錯時區，凌晨的升息會被當成「昨天」，今晚的 CPI 會被當成「明天」。
  - 看板只給「MM/DD」，12 月底看到 1 月的項目時年份要進位。
  - 「轉向」跟「調整」混用會讓利率不變的決議看起來像升降息。
"""
from __future__ import annotations

import unittest
from datetime import date, datetime, time

from macro.clock import NEW_YORK, TAIPEI
from macro.compute import events
from macro.render.pages.overview import today_section
from macro.sources import twcal


def tpe(y, m, d, hh=9, mm=0):
    return datetime.combine(date(y, m, d), time(hh, mm), tzinfo=TAIPEI)


FOMC_HIKE = {"state": "announced", "date": "2026-09-16", "action": "raise", "prev_action": "hold",
             "headline": "聯準會升息 1 碼　3.50%–3.75% → 3.75%–4.00%", "vote": "12–0",
             "effective": "2026-09-17"}
CBC_CREDIT = {"state": "announced", "date": "2026-09-17", "rate": {"action": "hold"},
              "prev_action": "hold", "change": True, "url": "u",
              "headline": "台灣央行利率不變（重貼現率 2%）；調整房貸信用管制",
              "details": ["第 2 戶購屋貸款成數上限 6 成 → 7 成"]}


class PolicyKind(unittest.TestCase):
    def test_kinds(self):
        self.assertEqual(events._policy_kind("raise", "hold", True), "轉向")
        self.assertEqual(events._policy_kind("hold", "raise", False), "轉向")
        self.assertEqual(events._policy_kind("raise", "raise", True), "調整")
        self.assertEqual(events._policy_kind("hold", "hold", True), "調整")
        self.assertEqual(events._policy_kind("hold", "hold", False), "不變")


class Policy(unittest.TestCase):
    def test_overnight_fomc_counts_as_today_in_taipei(self):
        today = events.policy_events(FOMC_HIKE, None, tpe(2026, 9, 17, 8))
        self.assertTrue(today[0]["today"])
        self.assertEqual(today[0]["tag"], "FOMC　政策轉向")
        self.assertIn("台北 9/17 02:00", today[0]["detail"])
        tomorrow = events.policy_events(FOMC_HIKE, None, tpe(2026, 9, 18, 8))
        self.assertFalse(tomorrow[0]["today"])

    def test_rate_unchanged_with_credit_controls_is_an_adjustment_not_a_turn(self):
        ev = events.policy_events(None, CBC_CREDIT, tpe(2026, 9, 17, 18))[0]
        self.assertEqual(ev["tag"], "台灣央行　政策調整")
        self.assertIn("6 成 → 7 成", ev["detail"])


class Data(unittest.TestCase):
    def test_us_release_converted_to_taipei(self):
        released = datetime(2026, 9, 17, 8, 31, tzinfo=NEW_YORK)
        rows = [{"name": "CPI", "frequency": "m", "updated": released, "next_release": None},
                {"name": "零售銷售", "frequency": "m", "updated": None,
                 "next_release": date(2026, 9, 17)},
                {"name": "公債殖利率", "frequency": "d", "updated": released,
                 "next_release": date(2026, 9, 17)}]
        out = events.us_data_events({"rows": rows}, tpe(2026, 9, 17, 22))
        self.assertEqual([(e["title"], e["tag"]) for e in out],
                         [("CPI", "美國數據　已公布"), ("零售銷售", "美國數據　今晚公布")])
        self.assertIn("台北 9/17 20:31", out[0]["detail"])

    def test_taiwan_major_only_and_release_time(self):
        items = [{"dept": "經濟部", "name": "外銷訂單統計", "label": "外銷訂單",
                  "date": date(2026, 9, 22), "time": time(16, 0), "period": "11508"},
                 {"dept": "交通部", "name": "觀光旅館住用率", "label": None,
                  "date": date(2026, 9, 22), "time": time(16, 20), "period": "11507"}]
        before = events.taiwan_data_events(items, tpe(2026, 9, 22, 10))
        after = events.taiwan_data_events(items, tpe(2026, 9, 22, 17))
        self.assertEqual([e["tag"] for e in before], ["台灣數據　16:00 公布"])
        self.assertEqual([e["tag"] for e in after], ["台灣數據　已公布"])


class Calendar(unittest.TestCase):
    PAGE = ('<script>var VueData = {"list":[{"DeptName":"經濟部","name":"外銷訂單統計",'
            '"timedatas":{"date":"01/05","time":"16:00","notice":"(11511)"},'
            '"note":"含 {大括號} 的字串"}],"showtype":1};</script>')

    def test_braces_inside_strings_and_year_rollover(self):
        items = twcal.parse(self.PAGE, date(2026, 12, 28))
        self.assertEqual(items[0]["date"], date(2027, 1, 5))
        self.assertEqual((items[0]["label"], items[0]["period"]), ("外銷訂單", "11511"))

    def test_major_list(self):
        self.assertEqual(twcal.major_label("行政院主計總處", "消費者物價指數"), "消費者物價（CPI）")
        self.assertIsNone(twcal.major_label("行政院主計總處", "躉售物價指數"))
        self.assertIsNone(twcal.major_label("衛生福利部", "國民年金保險統計-給付"))


class Verdict(unittest.TestCase):
    def test_quiet_day_says_so(self):
        ev = events.build(None, None, {}, [], tpe(2026, 9, 1))
        self.assertEqual(ev["verdict"], "今天沒有重大數據或政策決議。")

    def test_busy_day_counts_and_orders(self):
        rows = [{"name": "初領失業金", "frequency": "w", "updated": None,
                 "next_release": date(2026, 9, 17)}]
        ev = events.build(FOMC_HIKE, CBC_CREDIT, {"rows": rows}, [], tpe(2026, 9, 17, 18))
        self.assertEqual(ev["verdict"], "今天有政策轉向 1 項、政策調整 1 項、重大數據 1 項。")
        self.assertEqual([e["tag"] for e in ev["events"]],
                         ["FOMC　政策轉向", "台灣央行　政策調整", "美國數據　今晚公布"])

    def test_earlier_this_week_is_listed_but_not_counted(self):
        ev = events.build(FOMC_HIKE, None, {}, [], tpe(2026, 9, 20))
        self.assertEqual(ev["verdict"], "今天沒有重大數據或政策決議。")
        html = today_section({"events": ev})
        self.assertIn("本週稍早", html)
        self.assertIn("聯準會升息 1 碼", html)

    def test_overview_first_sentence_is_the_answer(self):
        ev = events.build(FOMC_HIKE, CBC_CREDIT, {}, [], tpe(2026, 9, 17, 18))
        html = today_section({"events": ev})
        self.assertLess(html.find("今天有政策轉向"), html.find('class="chg-row"'))


if __name__ == "__main__":
    unittest.main()
