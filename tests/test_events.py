"""總覽「今天」：一眼回答今天有沒有重大數據或政策轉向。

會靜默給錯答案的地方：
  - 時區。FOMC 美東 14:00 的聲明是台北隔天凌晨；美東 8:30 的數據是台北當晚，
    冬令時是 21:30。FRED 的更新時間常比實際發布晚半天，不能當公布時間。
  - 看板只給「MM/DD」，12 月底看到 1 月的項目時年份要進位；年修正不是新數據；
    國發會同一次發布在看板上是兩項。
  - 「轉向」跟「調整」混用會讓利率不變的決議看起來像升降息。
  - 行事曆抓不到時，第一句不能說「今天沒有重大數據」。
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
FOMC_HOLD = {**FOMC_HIKE, "action": "hold", "headline": "聯準會利率維持不變　3.75%–4.00%"}
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

    def test_unknown_previous_is_not_called_a_turn(self):
        """上一份聲明被擠出 RSS 時，不知道是不是轉向，只能說有變動。"""
        self.assertEqual(events._policy_kind("raise", None, True), "變動")
        self.assertEqual(events._policy_kind("hold", None, False), "不變")


class Policy(unittest.TestCase):
    def test_overnight_fomc_counts_as_today_in_taipei(self):
        today = events.policy_events(FOMC_HIKE, None, tpe(2026, 9, 17, 8))
        self.assertTrue(today[0]["today"])
        self.assertEqual(today[0]["tag"], "FOMC　政策轉向")
        self.assertIn("台北 9/17 02:00", today[0]["detail"])
        tomorrow = events.policy_events(FOMC_HIKE, None, tpe(2026, 9, 18, 8))
        self.assertFalse(tomorrow[0]["today"])

    def test_emergency_decision_uses_its_real_announcement_time(self):
        """臨時會議美東 10:00 公布＝台北當晚 22:00，不是隔天凌晨。"""
        emergency = {**FOMC_HIKE, "date": "2026-10-08", "at": "2026-10-08T10:00:00-04:00"}
        ev = events.policy_events(emergency, None, tpe(2026, 10, 8, 23, 30))[0]
        self.assertTrue(ev["today"])
        self.assertIn("台北 10/8 22:00", ev["detail"])

    def test_hold_does_not_say_a_new_rate_takes_effect(self):
        ev = events.policy_events(FOMC_HOLD, None, tpe(2026, 9, 17, 8))[0]
        self.assertNotIn("新利率", ev["detail"])

    def test_rate_unchanged_with_credit_controls_is_an_adjustment_not_a_turn(self):
        ev = events.policy_events(None, CBC_CREDIT, tpe(2026, 9, 17, 18))[0]
        self.assertEqual(ev["tag"], "台灣央行　政策調整")
        self.assertIn("6 成 → 7 成", ev["detail"])

    def test_overdue_pending_is_loud_and_promises_nothing(self):
        overdue = {"state": "pending", "meeting": "2026-10-28", "overdue": True,
                   "at": "2026-10-28T14:00:00-04:00"}
        ev = events.policy_events(overdue, None, tpe(2026, 10, 29, 2, 20))[0]
        self.assertEqual((ev["tag"], ev["sev"]), ("FOMC　公布時間已過", "high"))
        pending = {**overdue, "overdue": False}
        ev = events.policy_events(pending, None, tpe(2026, 10, 28, 21))[0]
        self.assertNotIn("一小時", ev["detail"])
        self.assertIn("本頁建置於台北 21:00", ev["detail"])


class UsData(unittest.TestCase):
    def test_release_time_comes_from_the_schedule_not_fred_update_time(self):
        """PPI 美東 8:30 發布、FRED 中午才更新：台北是 9/10 20:30，不是 9/11 凌晨。"""
        fred_updated = datetime(2026, 9, 10, 11, 53, tzinfo=NEW_YORK)
        rows = [{"id": "PPIFIS", "name": "PPI", "frequency": "m", "updated": fred_updated,
                 "next_release": None}]
        ev = events.us_data_events({"rows": rows}, tpe(2026, 9, 10, 23))[0]
        self.assertEqual((ev["tag"], ev["today"]), ("美國數據　已公布", True))
        self.assertIn("台北 9/10 20:30", ev["detail"])

    def test_scheduled_then_overdue_and_daily_series_skipped(self):
        rows = [{"id": "RSAFS", "name": "零售銷售", "frequency": "m", "updated": None,
                 "next_release": date(2026, 9, 17)},
                {"id": "DGS10", "name": "公債殖利率", "frequency": "d", "updated": None,
                 "next_release": date(2026, 9, 17)}]
        before = events.us_data_events({"rows": rows}, tpe(2026, 9, 17, 18))
        after = events.us_data_events({"rows": rows}, tpe(2026, 9, 17, 22))
        self.assertEqual([e["tag"] for e in before], ["美國數據　今晚公布"])
        self.assertEqual([e["tag"] for e in after], ["美國數據　公布時間已過"])

    def test_winter_time_is_one_hour_later(self):
        rows = [{"id": "CPIAUCSL", "name": "CPI", "frequency": "m", "updated": None,
                 "next_release": date(2026, 12, 10)}]
        ev = events.us_data_events({"rows": rows}, tpe(2026, 12, 10, 18))[0]
        self.assertIn("21:30", ev["detail"])

    def test_jolts_at_ten_eastern(self):
        rows = [{"id": "JTSJOL", "name": "JOLTS 職缺", "frequency": "m", "updated": None,
                 "next_release": date(2026, 9, 29)}]
        ev = events.us_data_events({"rows": rows}, tpe(2026, 9, 29, 18))[0]
        self.assertIn("22:00", ev["detail"])


class TaiwanData(unittest.TestCase):
    def _item(self, dept, name, label, day, hh, period):
        return {"dept": dept, "name": name, "label": label, "date": day,
                "time": time(hh, 0), "period": period}

    def test_major_only_and_release_time(self):
        items = [self._item("經濟部", "外銷訂單統計", "外銷訂單", date(2026, 9, 22), 16, "11508"),
                 self._item("交通部", "觀光旅館住用率", None, date(2026, 9, 22), 16, "11507")]
        before = events.taiwan_data_events(items, tpe(2026, 9, 22, 10))
        after = events.taiwan_data_events(items, tpe(2026, 9, 22, 17))
        self.assertEqual([e["tag"] for e in before], ["台灣數據　16:00 公布"])
        self.assertEqual([e["tag"] for e in after], ["台灣數據　已公布"])

    def test_same_release_listed_twice_counts_once(self):
        items = [self._item("國家發展委員會", "景氣指標－景氣對策信號", "景氣對策信號",
                            date(2026, 9, 29), 16, "11508")] * 2
        self.assertEqual(len(events.taiwan_data_events(items, tpe(2026, 9, 29, 17))), 1)


class Calendar(unittest.TestCase):
    PAGE = ('<script>var VueData = {"list":[{"DeptName":"經濟部","name":"外銷訂單統計",'
            '"timedatas":{"date":"01/05","time":"16:00","notice":"(11511)"},'
            '"note":"含 {大括號} 的字串"},'
            '{"DeptName":"財政部","name":"海關進出口貿易初步統計",'
            '"timedatas":{"date":"01/06","time":"16:00","notice":"(114年第2次年修正)"}}],'
            '"showtype":1};</script>')

    def test_braces_inside_strings_and_year_rollover(self):
        items = twcal.parse(self.PAGE, date(2026, 12, 28))
        self.assertEqual(items[0]["date"], date(2027, 1, 5))
        self.assertEqual((items[0]["label"], items[0]["period"]), ("外銷訂單", "11511"))

    def test_annual_revision_is_not_a_new_release(self):
        items = twcal.parse(self.PAGE, date(2026, 12, 28))
        self.assertIsNone(items[1]["label"])

    def test_major_list(self):
        self.assertEqual(twcal.major_label("行政院主計總處", "消費者物價指數"), "消費者物價（CPI）")
        self.assertIsNone(twcal.major_label("行政院主計總處", "躉售物價指數"))
        self.assertIsNone(twcal.major_label("國家發展委員會", "景氣指標－景氣動向指標"))
        self.assertIsNone(twcal.major_label("衛生福利部", "國民年金保險統計-給付"))


class Verdict(unittest.TestCase):
    def test_quiet_day_says_so(self):
        ev = events.build(None, None, {}, [], tpe(2026, 9, 1), tw_ok=True)
        self.assertEqual(ev["verdict"], "今天沒有重大數據或政策決議。")

    def test_failed_calendar_is_not_reported_as_a_quiet_day(self):
        ev = events.build(None, None, {"calendar_failed": ["CPI"]}, [], tpe(2026, 9, 1))
        self.assertTrue(ev["verdict"].startswith("今天沒有偵測到重大數據或政策決議"))
        self.assertIn("美國發布行事曆與台灣統計發布看板這一輪沒有取得", ev["verdict"])
        html = today_section({"events": ev})
        self.assertIn("美國發布行事曆這一輪沒有取得（CPI）", html)

    def test_busy_day_counts_and_orders(self):
        rows = [{"id": "ICSA", "name": "初領失業金", "frequency": "w", "updated": None,
                 "next_release": date(2026, 9, 17)}]
        ev = events.build(FOMC_HIKE, CBC_CREDIT, {"rows": rows}, [], tpe(2026, 9, 17, 18), tw_ok=True)
        self.assertEqual(ev["verdict"], "今天有政策轉向 1 項、政策調整 1 項、重大數據 1 項。")
        self.assertEqual([e["tag"] for e in ev["events"]],
                         ["FOMC　政策轉向", "台灣央行　政策調整", "美國數據　今晚公布"])

    def test_earlier_this_week_is_listed_but_not_counted(self):
        ev = events.build(FOMC_HIKE, None, {}, [], tpe(2026, 9, 20), tw_ok=True)
        self.assertEqual(ev["verdict"], "今天沒有重大數據或政策決議。")
        html = today_section({"events": ev})
        self.assertIn("本週稍早", html)
        self.assertIn("聯準會升息 1 碼", html)

    def test_overview_first_sentence_is_the_answer(self):
        ev = events.build(FOMC_HIKE, CBC_CREDIT, {}, [], tpe(2026, 9, 17, 18), tw_ok=True)
        html = today_section({"events": ev})
        self.assertLess(html.find("今天有政策轉向"), html.find('class="chg-row"'))


if __name__ == "__main__":
    unittest.main()
