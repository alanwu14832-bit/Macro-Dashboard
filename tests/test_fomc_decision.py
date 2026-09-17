"""FOMC 決議不准遺漏。

2026-09-16 聯準會升息 1 碼，網站兩天都沒有顯示，三層都壞：
  1. 政策利率只讀 FRED 的 DFEDTARU，它隔天以後才補上生效日的新值
  2. 聲明有抓，但只拿來做英文逐句比對，沒有被讀成「升息了」
  3. 行事曆在會後默默翻到下一次會議；每日存檔連政策利率都沒記

這裡釘住的性質是：**任何一次會議之後一週內，總覽最上面一定有「FOMC 決議」
或「FOMC 決議遺漏」，不准兩個都沒有。**
"""
from __future__ import annotations

import unittest
from datetime import date, datetime, time, timedelta
from unittest import mock

from macro import fomc
from macro.clock import NEW_YORK, TAIPEI
from macro.compute import events
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
    def _run(self, newest, previous):
        pages = {"u1": newest, "u2": previous}
        with mock.patch.object(fomc_text, "_statement_links",
                               return_value=[("2026-09-16", "u1"), ("2026-07-29", "u2")]), \
                mock.patch.object(fomc_text, "get", side_effect=lambda url, **_: pages[url]), \
                mock.patch.object(fomc_text, "_clean", side_effect=lambda body: body):
            return fomc_text.latest_decision()

    def test_consistent_hike_carries_the_previous_range(self):
        out = self._run(HIKE, HOLD)
        self.assertEqual(out["status"], "ok")
        self.assertEqual((out["prev_lower"], out["prev_upper"]), (3.5, 3.75))

    def test_verb_that_contradicts_the_numbers_is_rejected(self):
        """讀錯動詞比讀不到更危險：會在總覽上印出相反的決議。"""
        contradiction = HIKE.replace("3-3/4 to 4 percent", "3-1/4 to 3-1/2 percent")
        self.assertEqual(self._run(contradiction, HOLD)["status"], "unparsed")

    def test_statement_without_a_decision_sentence_is_unparsed(self):
        self.assertEqual(self._run("Minutes of the meeting.", HOLD)["status"], "unparsed")

    def test_no_feed_is_unavailable(self):
        with mock.patch.object(fomc_text, "_statement_links", return_value=[]):
            self.assertEqual(fomc_text.latest_decision()["status"], "unavailable")


class Labels(unittest.TestCase):
    def test_headline_with_previous_range(self):
        d = ok("2026-09-16", prev_lower=3.5, prev_upper=3.75)
        self.assertEqual(fomc.headline(d), "聯準會升息 1 碼　3.50%–3.75% → 3.75%–4.00%")

    def test_half_point_is_two_quarters(self):
        self.assertEqual(fomc.action_label(ok("x", "lower", 4.75, 5.0, 0.5)), "降息 2 碼")

    def test_hold(self):
        self.assertEqual(fomc.headline(ok("x", "hold", 3.5, 3.75, None)),
                         "聯準會利率維持不變　3.50%–3.75%")


def _fred(values):
    return Series.from_pairs("DFEDTARU", values, label="政策利率上緣", unit="%",
                             frequency="d", source="FRED")


class Reconcile(unittest.TestCase):
    def _bundle(self, upper_pairs, lower_pairs):
        bundle = Bundle()
        bundle.add("DFEDTARU", _fred(upper_pairs))
        bundle.add("DFEDTARL", _fred(lower_pairs))
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

    def test_unparsed_decision_changes_nothing(self):
        bundle = self._bundle([("2026-09-16", 3.75)], [("2026-09-16", 3.5)])
        fomc.reconcile_policy(bundle, {"status": "unparsed", "date": "2026-09-16"})
        self.assertEqual(bundle["DFEDTARU"].last, 3.75)


class Status(unittest.TestCase):
    def test_announced_the_day_after(self):
        state = fomc.decision_status(ok("2026-09-16"), ny(2026, 9, 17))
        self.assertEqual(state["state"], "announced")
        self.assertEqual(state["effective"], "2026-09-17")

    def test_stale_feed_after_a_meeting_is_missing(self):
        """RSS 還停在上一次會議的聲明——這正是 12 小時快取造成的樣子。"""
        state = fomc.decision_status(ok("2026-07-29", "hold", 3.5, 3.75, None),
                                     ny(2026, 9, 17))
        self.assertEqual(state["state"], "missing")
        self.assertEqual(state["meeting"], "2026-09-16")
        self.assertIn("2026-07-29", state["reason"])

    def test_meeting_morning_is_pending_not_missing(self):
        old = ok("2026-07-29", "hold", 3.5, 3.75, None)
        self.assertEqual(fomc.decision_status(old, ny(2026, 9, 16, 13, 0))["state"], "pending")
        self.assertEqual(fomc.decision_status(old, ny(2026, 9, 16, 15, 0))["state"], "missing")

    def test_unparsed_statement_is_missing_with_its_reason(self):
        state = fomc.decision_status({"status": "unparsed", "date": "2026-09-16",
                                      "reason": "讀不出決議"}, ny(2026, 9, 17))
        self.assertEqual((state["state"], state["reason"]), ("missing", "讀不出決議"))

    def test_unscheduled_meeting_is_still_announced(self):
        state = fomc.decision_status(ok("2026-08-20", "lower", 3.25, 3.5, 0.25),
                                     ny(2026, 8, 21))
        self.assertEqual(state["state"], "announced")

    def test_quiet_week_shows_nothing(self):
        self.assertIsNone(fomc.decision_status(ok("2026-07-29", "hold", 3.5, 3.75, None),
                                               ny(2026, 9, 1)))


class OverviewNeverOmits(unittest.TestCase):
    def test_every_meeting_surfaces_a_decision_or_a_gap(self):
        """行事曆上每一次會議，會後一到七天，不論聲明抓到、抓不到、讀不出，
        總覽最上面的「今天」都要有 FOMC 那一列。"""
        for meeting in fomc.MEETINGS:
            for days_after in (1, 3, 7):
                now = datetime.combine(meeting + timedelta(days=days_after),
                                       time(9, 0), tzinfo=NEW_YORK)
                for decision in (ok(meeting.isoformat()),
                                 {"status": "unavailable", "reason": "抓不到"},
                                 {"status": "unparsed", "date": meeting.isoformat(),
                                  "reason": "讀不出"},
                                 ok((meeting - timedelta(days=42)).isoformat())):
                    state = fomc.decision_status(decision, now)
                    ev = events.build(state, None, {}, [], now.astimezone(TAIPEI))
                    html = today_section({"events": ev})
                    self.assertIn('class="chg-tag">FOMC', html,
                                  f"{meeting} +{days_after}d {decision.get('status')}")

    def test_missing_decision_is_first(self):
        state = fomc.decision_status({"status": "unavailable", "reason": "抓不到"},
                                     ny(2026, 9, 17))
        freshness = {"rows": [{"name": "CPI", "frequency": "m", "updated": None,
                               "next_release": date(2026, 9, 17)}]}
        ev = events.build(state, None, freshness, [], ny(2026, 9, 17).astimezone(TAIPEI))
        self.assertEqual(ev["events"][0]["tag"], "FOMC　決議遺漏")
        self.assertIn("決議遺漏 1 項", ev["verdict"])

    def test_changes_stack_no_longer_repeats_the_decision(self):
        """決議只在「今天」出現一次，「自上次以來」只放本站判定的比對。"""
        html = changes_top({"fomc": {"state": "announced"}}, {"same": True}, [],
                           {"employment_label": "放緩", "inflation_label": "偏高",
                            "regime_label": "通膨優先"}, {"date": "x", "scenario": {}})
        self.assertNotIn("FOMC", html)


if __name__ == "__main__":
    unittest.main()
