"""FOMC 決議不准遺漏。

2026-09-16 聯準會升息 1 碼，網站兩天都沒有顯示，三層都壞：
  1. 政策利率只讀 FRED 的 DFEDTARU，它隔天以後才補上生效日的新值
  2. 聲明有抓，但只拿來做英文逐句比對，沒有被讀成「升息了」
  3. 行事曆在會後默默翻到下一次會議；每日存檔連政策利率都沒記

之後的對抗性審查又找到臨時會議整列消失、非決議聲明頂掉決議、例會被臨時會議
取代時誤報遺漏、期貨把剛宣布的一碼重複計價等問題，都釘在這裡。

釘住的性質是：**任何一次會議（含臨時會議）之後一週內，總覽的「今天」一定有
FOMC 決議或決議遺漏，不准兩個都沒有。**
"""
from __future__ import annotations

import unittest
from datetime import date, datetime, time, timedelta
from unittest import mock

from macro import fomc
from macro.clock import NEW_YORK, TAIPEI
from macro.compute import events, fedfunds
from macro.data import Bundle
from macro.render.pages.overview import changes_top, today_section
from macro.series import Series
from macro.sources import fomc_text

HIKE = ("The Federal Open Market Committee approved the following statement for "
        "release by a 12 – 0 vote: Economic activity is expanding at a solid pace. "
        "The Committee decided to raise the target range for the federal funds rate "
        "by 1/4 percentage point to 3-3/4 to 4 percent, in support of the Federal "
        "Reserve's dual mandate.")
HOLD = ("The Committee decided to maintain the target range for the federal funds "
        "rate at 3-1/2 to 3-3/4 percent. Voting against the monetary policy action "
        "were Beth M. Hammack and Neel Kashkari, who preferred to raise the target "
        "range by 1/4 percentage point at this meeting.")
# 2020-03-03 臨時降息的真實寫法：decided 後面多了 today，point 後面多了逗號
EMERGENCY_2020 = ("In light of these risks and in support of achieving its maximum employment "
                  "and price stability goals, the Federal Open Market Committee decided today to "
                  "lower the target range for the federal funds rate by 1/2 percentage point, "
                  "to 1 to 1-1/4 percent.")
# 2020-03-23 的「FOMC statement」沒有利率決議
NOTATION_VOTE = ("The Federal Reserve is committed to using its full range of tools to support "
                 "households and businesses. The Committee will continue to purchase Treasury "
                 "securities in the amounts needed to support smooth market functioning.")


def ny(y, m, d, hh=10, mm=0):
    return datetime.combine(date(y, m, d), time(hh, mm), tzinfo=NEW_YORK)


def ok(day, action="raise", lower=3.75, upper=4.0, step=0.25, **extra):
    return {"status": "ok", "date": day, "url": "https://example/x", "action": action,
            "lower": lower, "upper": upper, "step": step, "vote": "12–0", **extra}


class ParseDecision(unittest.TestCase):
    def test_hike(self):
        self.assertEqual(fomc_text.parse_decision(HIKE),
                         {"action": "raise", "lower": 3.75, "upper": 4.0, "step": 0.25})

    def test_hold_is_not_confused_by_a_dissent_preferring_a_hike(self):
        """異議委員那句也有 'raise the target range by 1/4'，但決議是維持。"""
        self.assertEqual(fomc_text.parse_decision(HOLD),
                         {"action": "hold", "lower": 3.5, "upper": 3.75, "step": None})

    def test_half_point_cut(self):
        text = ("The Committee decided to lower the target range for the federal "
                "funds rate by 1/2 percentage point to 4-3/4 to 5 percent.")
        self.assertEqual(fomc_text.parse_decision(text),
                         {"action": "lower", "lower": 4.75, "upper": 5.0, "step": 0.5})

    def test_emergency_cut_wording_of_2020_03_03(self):
        self.assertEqual(fomc_text.parse_decision(EMERGENCY_2020),
                         {"action": "lower", "lower": 1.0, "upper": 1.25, "step": 0.5})

    def test_emergency_cut_to_zero_without_a_step(self):
        text = ("The Committee decided to lower the target range for the federal "
                "funds rate to 0 to 1/4 percent.")
        self.assertEqual(fomc_text.parse_decision(text),
                         {"action": "lower", "lower": 0.0, "upper": 0.25, "step": None})

    def test_non_breaking_hyphen(self):
        text = HIKE.replace("3-3/4", "3‑3/4")
        self.assertEqual(fomc_text.parse_decision(text)["lower"], 3.75)

    def test_unrecognised_wording_is_none_not_a_guess(self):
        self.assertIsNone(fomc_text.parse_decision("The Committee will continue to assess."))


class LatestDecision(unittest.TestCase):
    def _run(self, *pages):
        """pages：(日期, 內文)，新到舊。"""
        links = [(day, f"u{i}", f"{day}T14:00:00-04:00") for i, (day, _body) in enumerate(pages)]
        bodies = {f"u{i}": body for i, (_day, body) in enumerate(pages)}
        with mock.patch.object(fomc_text, "_statement_links", return_value=links), \
                mock.patch.object(fomc_text, "get", side_effect=lambda url, **_: bodies[url]), \
                mock.patch.object(fomc_text, "_clean", side_effect=lambda body: body):
            return fomc_text.latest_decision()

    def test_consistent_hike_carries_the_previous_decision(self):
        out = self._run(("2026-09-16", HIKE), ("2026-07-29", HOLD))
        self.assertEqual(out["status"], "ok")
        self.assertEqual((out["prev_lower"], out["prev_upper"], out["prev_action"]),
                         (3.5, 3.75, "hold"))
        self.assertEqual(out["previous"]["date"], "2026-07-29")
        self.assertEqual(out["published"], "2026-09-16T14:00:00-04:00")

    def test_verb_that_contradicts_the_numbers_is_rejected(self):
        """讀錯動詞比讀不到更危險：會在總覽上印出相反的決議。"""
        contradiction = HIKE.replace("3-3/4 to 4 percent", "3-1/4 to 3-1/2 percent")
        self.assertEqual(self._run(("2026-09-16", contradiction), ("2026-07-29", HOLD))["status"],
                         "unparsed")

    def test_statement_without_a_rate_decision_does_not_hide_the_decision(self):
        """2020-03-23 那種沒有利率句的聲明，不能頂掉一週前剛公布的決議。"""
        out = self._run(("2026-09-20", NOTATION_VOTE), ("2026-09-16", HIKE), ("2026-07-29", HOLD))
        self.assertEqual((out["status"], out["date"]), ("ok", "2026-09-16"))

    def test_decision_like_statement_that_cannot_be_read_is_unparsed_with_the_previous_kept(self):
        garbled = "The Committee decided to adjust the target range for the federal funds rate."
        out = self._run(("2026-10-08", garbled), ("2026-09-16", HIKE), ("2026-07-29", HOLD))
        self.assertEqual((out["status"], out["date"]), ("unparsed", "2026-10-08"))
        self.assertEqual(out["previous"]["date"], "2026-09-16")

    def test_no_feed_is_unavailable(self):
        with mock.patch.object(fomc_text, "_statement_links", return_value=[]):
            self.assertEqual(fomc_text.latest_decision()["status"], "unavailable")

    def test_only_exact_statement_titles_count(self):
        feed = ("<rss><item><title>Federal Reserve issues FOMC statement on policy normalization "
                "principles and plans</title><link>https://x/monetary20260916c.htm</link>"
                "<pubDate>Wed, 16 Sep 2026 18:00:00 GMT</pubDate></item>"
                "<item><title>Federal Reserve issues FOMC statement</title>"
                "<link>https://x/monetary20260916a.htm</link>"
                "<pubDate>Wed, 16 Sep 2026 18:00:00 GMT</pubDate></item></rss>")
        with mock.patch.object(fomc_text, "get", return_value=feed):
            links = fomc_text._statement_links(0)
        self.assertEqual([href for _d, href, _p in links], ["https://x/monetary20260916a.htm"])
        self.assertEqual(links[0][2], "2026-09-16T14:00:00-04:00")


class Labels(unittest.TestCase):
    def test_headline_with_previous_range(self):
        d = ok("2026-09-16", prev_lower=3.5, prev_upper=3.75)
        self.assertEqual(fomc.headline(d), "聯準會升息 1 碼　3.50%–3.75% → 3.75%–4.00%")

    def test_half_point_is_two_quarters(self):
        self.assertEqual(fomc.action_label(ok("x", "lower", 4.75, 5.0, 0.5)), "降息 2 碼")

    def test_hold(self):
        self.assertEqual(fomc.headline(ok("x", "hold", 3.5, 3.75, None)),
                         "聯準會利率維持不變　3.50%–3.75%")

    def test_announcement_time_prefers_the_feed(self):
        emergency = ok("2020-03-03", published="2020-03-03T10:00:00-05:00")
        self.assertEqual(fomc.announced_at(emergency).hour, 10)
        self.assertEqual(fomc.announced_at(ok("2026-09-16")).hour, 14)


def _fred(values, sid="DFEDTARU"):
    return Series.from_pairs(sid, values, label="政策利率", unit="%", frequency="d", source="FRED")


class Reconcile(unittest.TestCase):
    def _bundle(self, upper_pairs, lower_pairs):
        bundle = Bundle()
        bundle.add("DFEDTARU", _fred(upper_pairs))
        bundle.add("DFEDTARL", _fred(lower_pairs, "DFEDTARL"))
        return bundle

    def test_lagging_fred_is_patched_from_the_statement(self):
        bundle = self._bundle([("2026-09-16", 3.75)], [("2026-09-16", 3.5)])
        result = fomc.reconcile_policy(bundle, ok("2026-09-16"))
        self.assertTrue(result["patched"])
        upper = bundle["DFEDTARU"]
        self.assertEqual((upper.last_date, upper.last), (date(2026, 9, 17), 4.0))
        self.assertEqual(upper.meta["patched_from"]["statement"], "2026-09-16")
        self.assertEqual(bundle["DFEDTARL"].last, 3.75)

    def test_caught_up_fred_is_left_alone(self):
        bundle = self._bundle([("2026-09-17", 4.0)], [("2026-09-17", 3.75)])
        result = fomc.reconcile_policy(bundle, ok("2026-09-16"))
        self.assertEqual((result["patched"], result["conflict"]), (False, []))
        self.assertNotIn("patched_from", bundle["DFEDTARU"].meta)

    def test_disagreement_keeps_fred_and_reports_it(self):
        bundle = self._bundle([("2026-09-17", 3.75)], [("2026-09-17", 3.75)])
        result = fomc.reconcile_policy(bundle, ok("2026-09-16"))
        self.assertEqual(result["conflict"], ["DFEDTARU"])
        self.assertEqual(bundle["DFEDTARU"].last, 3.75)

    def test_unreadable_latest_still_patches_from_the_previous_decision(self):
        bundle = self._bundle([("2026-09-16", 3.75)], [("2026-09-16", 3.5)])
        decision = {"status": "unparsed", "date": "2026-09-18", "previous": ok("2026-09-16")}
        self.assertTrue(fomc.reconcile_policy(bundle, decision)["patched"])
        self.assertEqual(bundle["DFEDTARU"].last, 4.0)

    def test_missing_date_does_not_crash_the_build(self):
        bundle = self._bundle([("2026-09-16", 3.75)], [("2026-09-16", 3.5)])
        self.assertFalse(fomc.reconcile_policy(bundle, ok(""))["patched"])

    def test_futures_start_is_shifted_by_the_new_range(self):
        """EFFR 還停在升息前，直接用會把剛宣布的一碼算成「下次還會升息」。"""
        bundle = self._bundle([("2026-09-17", 4.0)], [("2026-09-15", 3.5), ("2026-09-17", 3.75)])
        bundle.add("DFF", _fred([("2026-09-15", 3.63)], "DFF"))
        effr, note = fedfunds.start_rate(bundle)
        self.assertAlmostEqual(effr, 3.88)
        self.assertIn("尚未反映最新決議", note)


class Status(unittest.TestCase):
    def test_announced_the_day_after(self):
        state = fomc.decision_status(ok("2026-09-16"), ny(2026, 9, 17))
        self.assertEqual(state["state"], "announced")
        self.assertEqual(state["effective"], "2026-09-17")

    def test_stale_feed_after_a_meeting_is_missing(self):
        """RSS 還停在上一次會議的聲明——這正是 12 小時快取造成的樣子。"""
        state = fomc.decision_status(ok("2026-07-29", "hold", 3.5, 3.75, None), ny(2026, 9, 17))
        self.assertEqual(state["state"], "missing")
        self.assertEqual(state["meeting"], "2026-09-16")
        self.assertIn("2026-07-29", state["reason"])

    def test_meeting_day_is_pending_then_overdue_then_missing(self):
        old = ok("2026-07-29", "hold", 3.5, 3.75, None)
        morning = fomc.decision_status(old, ny(2026, 9, 16, 13, 0))
        self.assertEqual((morning["state"], morning["overdue"]), ("pending", False))
        self.assertTrue(fomc.decision_status(old, ny(2026, 9, 16, 14, 10))["overdue"])
        self.assertEqual(fomc.decision_status(old, ny(2026, 9, 16, 15, 0))["state"], "missing")

    def test_pending_shows_the_evening_before_in_new_york(self):
        """台北會議日上午，美東還是前一天。"""
        old = ok("2026-07-29", "hold", 3.5, 3.75, None)
        self.assertEqual(fomc.decision_status(old, ny(2026, 9, 15, 21, 0))["state"], "pending")

    def test_unparsed_statement_is_missing_with_its_reason(self):
        state = fomc.decision_status({"status": "unparsed", "date": "2026-09-16",
                                      "reason": "讀不出決議"}, ny(2026, 9, 17))
        self.assertEqual((state["state"], state["reason"]), ("missing", "讀不出決議"))

    def test_unreadable_unscheduled_meeting_is_missing(self):
        """臨時會議不在行事曆上；讀不出來時原本整列消失。"""
        decision = {"status": "unparsed", "date": "2026-10-08", "reason": "讀不出",
                    "previous": ok("2026-09-16")}
        state = fomc.decision_status(decision, ny(2026, 10, 9))
        self.assertEqual((state["state"], state["meeting"]), ("missing", "2026-10-08"))

    def test_unscheduled_meeting_is_still_announced(self):
        state = fomc.decision_status(ok("2026-08-20", "lower", 3.25, 3.5, 0.25), ny(2026, 8, 21))
        self.assertEqual(state["state"], "announced")

    def test_emergency_decision_survives_the_next_meeting_becoming_pending(self):
        emergency = ok("2026-10-23", "lower", 3.25, 3.5, 0.5)
        states = fomc.decision_states(emergency, ny(2026, 10, 28, 9))
        self.assertEqual([s["state"] for s in states], ["pending", "announced"])

    def test_meeting_replaced_by_an_emergency_one_says_so(self):
        """2020-03-15 臨時會議取代了 3/17-18 例會。"""
        emergency = ok("2026-10-25", "lower", 3.25, 3.5, 0.5)
        states = fomc.decision_states(emergency, ny(2026, 10, 29))
        self.assertEqual([s["state"] for s in states], ["missing", "announced"])
        self.assertIn("臨時會議取代", states[0]["reason"])

    def test_quiet_week_shows_nothing(self):
        self.assertIsNone(fomc.decision_status(ok("2026-07-29", "hold", 3.5, 3.75, None),
                                               ny(2026, 9, 1)))


class OverviewNeverOmits(unittest.TestCase):
    def test_every_meeting_surfaces_a_decision_or_a_gap(self):
        """行事曆上每一次會議，會後一到七天，不論聲明抓到、抓不到、讀不出，
        總覽最上面的「今天」都要有 FOMC 那一列。"""
        for meeting in fomc.MEETINGS:
            for days_after in (1, 3, 7):
                now = datetime.combine(meeting + timedelta(days=days_after), time(9, 0),
                                       tzinfo=NEW_YORK)
                for decision in (ok(meeting.isoformat()),
                                 {"status": "unavailable", "reason": "抓不到"},
                                 {"status": "unparsed", "date": meeting.isoformat(),
                                  "reason": "讀不出"},
                                 ok((meeting - timedelta(days=42)).isoformat())):
                    states = fomc.decision_states(decision, now)
                    ev = events.build(states, None, {}, [], now.astimezone(TAIPEI), tw_ok=True)
                    html = today_section({"events": ev})
                    self.assertIn('class="chg-tag">FOMC', html,
                                  f"{meeting} +{days_after}d {decision.get('status')}")

    def test_unscheduled_meeting_surfaces_too(self):
        for decision in ({"status": "unparsed", "date": "2026-10-08", "reason": "讀不出"},
                         {"status": "unavailable", "date": "2026-10-08", "reason": "抓不到"},
                         ok("2026-10-08", "lower", 3.5, 3.75, 0.25)):
            now = ny(2026, 10, 9, 21)
            ev = events.build(fomc.decision_states(decision, now), None, {}, [],
                              now.astimezone(TAIPEI), tw_ok=True)
            self.assertIn('class="chg-tag">FOMC', today_section({"events": ev}))

    def test_missing_decision_is_first(self):
        states = fomc.decision_states({"status": "unavailable", "reason": "抓不到"}, ny(2026, 9, 17))
        freshness = {"rows": [{"name": "CPI", "frequency": "m", "updated": None,
                               "next_release": date(2026, 9, 17)}]}
        ev = events.build(states, None, freshness, [], ny(2026, 9, 17).astimezone(TAIPEI), tw_ok=True)
        self.assertEqual(ev["events"][0]["tag"], "FOMC　決議遺漏")
        self.assertIn("決議遺漏 1 項", ev["verdict"])

    def test_changes_stack_no_longer_repeats_the_decision(self):
        """決議只在「今天」出現一次，「自上次以來」只放本站判定的比對。"""
        html = changes_top({"fomc": [{"state": "announced"}]}, {"same": True}, [],
                           {"employment_label": "放緩", "inflation_label": "偏高",
                            "regime_label": "通膨優先"}, {"date": "x", "scenario": {}})
        self.assertNotIn("FOMC", html)


class Catalogue(unittest.TestCase):
    def test_patched_points_are_labelled_in_the_api_catalogue(self):
        from macro.render import api
        bundle = Bundle()
        bundle.add("DFEDTARU", _fred([("2026-09-16", 3.75)]))
        bundle.add("DFEDTARL", _fred([("2026-09-16", 3.5)], "DFEDTARL"))
        fomc.reconcile_policy(bundle, ok("2026-09-16"))
        written = {}
        with mock.patch.object(api, "_write", side_effect=lambda path, payload: written.update(payload) or 0):
            api.write_series(bundle)
        entry = next(e for e in written["series"] if e["id"] == "DFEDTARU")
        self.assertEqual(entry["patched_from"]["statement"], "2026-09-16")


if __name__ == "__main__":
    unittest.main()
