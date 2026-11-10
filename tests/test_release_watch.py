"""公布時間到了、資料跟上了沒——建置的繞過快取（compute/due.py）與發布守候
（tools/release_watch.py）。全部不連網。

會靜默給錯答案的地方：
  - 公布時間已過卻讀了公布前的快取：頁面看起來正常，只是停在上個月（2026-11-10 的 CPI）。
  - 還沒到公布時間就繞過快取：每一輪都重抓，等於把快取關掉。
  - 夏令冬令：美東 8:30 夏天是 UTC 12:30、冬天是 13:30，寫死 UTC 會早一小時或晚一小時。
  - 守候對同一次公布觸發兩次、或站上已經跟上了還觸發。
  - 只重抓追蹤的那一檔：總指數是新的，同一份發布的分項還是舊的。
"""
from __future__ import annotations

import os
import sys
import unittest
from datetime import date, datetime, timedelta, timezone
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import release_watch as watch  # noqa: E402
from macro import catalogue, data  # noqa: E402
from macro.clock import NEW_YORK, TAIPEI  # noqa: E402
from macro.compute import due, freshness  # noqa: E402
from macro.series import Series  # noqa: E402

UTC = timezone.utc
CPI_DAY = date(2026, 11, 10)                      # 冬令：美東 8:30 = UTC 13:30 = 台北 21:30
CPI_AT = datetime(2026, 11, 10, 13, 30, tzinfo=UTC)
CAL = {10: [CPI_DAY, date(2026, 12, 10)]}
# 上一輪建置記下的：9 月的資料，10/14 第一次看到
OLD = {"date": "2026-09-01", "seen": "2026-10-14"}
NEW = {"date": "2026-10-01", "seen": "2026-11-10"}


def utc(day, hh, mm=0):
    return datetime(2026, 11, day, hh, mm, tzinfo=UTC)


def stale_state():
    return {sid: dict(OLD) for sid in catalogue.RELEASE_FAMILY[10]}


class TestReleaseInstant(unittest.TestCase):
    def test_winter_and_summer(self):
        winter = due.release_at("CPIAUCSL", date(2026, 11, 10))
        summer = due.release_at("CPIAUCSL", date(2026, 7, 14))
        self.assertEqual(winter.astimezone(UTC).hour, 13)      # EST
        self.assertEqual(summer.astimezone(UTC).hour, 12)      # EDT
        self.assertEqual(winter.astimezone(TAIPEI).strftime("%m-%d %H:%M"), "11-10 21:30")
        self.assertEqual(summer.astimezone(TAIPEI).strftime("%m-%d %H:%M"), "07-14 20:30")

    def test_non_default_times(self):
        self.assertEqual(due.release_at("JTSJOL", CPI_DAY).strftime("%H:%M"), "10:00")
        self.assertEqual(due.release_at("INDPRO", CPI_DAY).strftime("%H:%M"), "09:15")
        # SLOOS 美東 14:00 是台北隔天凌晨
        sloos = due.release_at("DRTSCILM", CPI_DAY).astimezone(TAIPEI)
        self.assertEqual(sloos.strftime("%m-%d %H:%M"), "11-11 03:00")

    def test_daily_series_are_not_tracked(self):
        ids = [sid for sid, _label, _rid in due.tracked()]
        self.assertNotIn("DGS10", ids)
        self.assertIn("CPIAUCSL", ids)


class TestLanded(unittest.TestCase):
    def test_seen_before_release_is_not_landed(self):
        self.assertFalse(due.landed(OLD, CPI_AT))

    def test_seen_on_or_after_release_day_in_taipei(self):
        self.assertTrue(due.landed({"date": "2026-10-01", "seen": "2026-11-10"}, CPI_AT))
        # 台北過了午夜才建置到：一樣算
        self.assertTrue(due.landed({"date": "2026-10-01", "seen": "2026-11-11"}, CPI_AT))

    def test_unknown_is_not_landed(self):
        for entry in (None, {}, {"date": "2026-09-01", "seen": None}, {"seen": "不是日期"}):
            self.assertFalse(due.landed(entry, CPI_AT))

    def test_taipei_date_not_us_date(self):
        # SLOOS 11/10 美東 14:00 公布＝台北 11/11 03:00。台北 11/10 看到的資料是公布前的。
        at = due.release_at("DRTSCILM", CPI_DAY)
        self.assertFalse(due.landed({"date": "2026-07-01", "seen": "2026-11-10"}, at))
        self.assertTrue(due.landed({"date": "2026-10-01", "seen": "2026-11-11"}, at))


class TestRefresh(unittest.TestCase):
    def test_before_release_time_nothing_bypasses(self):
        now = utc(10, 13, 29)
        self.assertEqual(due.waiting(now, CAL, stale_state()), {})
        self.assertEqual(due.refresh_ids(now, CAL, stale_state()), set())

    def test_after_release_time_the_whole_release_bypasses(self):
        now = utc(10, 13, 31)
        self.assertEqual(list(due.waiting(now, CAL, stale_state())), ["CPIAUCSL"])
        ids = due.refresh_ids(now, CAL, stale_state())
        self.assertEqual(ids, set(catalogue.RELEASE_FAMILY[10]))
        self.assertIn("CPILFESL", ids)                 # 核心 CPI 跟著重抓
        self.assertNotIn("PAYEMS", ids)                # 別的發布不動
        self.assertLess(len(ids), 30)                  # 不是把全站的快取打掉

    def test_once_landed_it_stops(self):
        state = {sid: dict(NEW) for sid in catalogue.RELEASE_FAMILY[10]}
        now = utc(10, 15)
        self.assertEqual(due.waiting(now, CAL, state), {})
        self.assertEqual(due.refresh_ids(now, CAL, state), set())

    def test_stragglers_keep_bypassing_after_the_headline_landed(self):
        # 建置落在 FRED 分批登出的中間：總指數到了，核心 CPI 還沒
        state = {sid: dict(NEW) for sid in catalogue.RELEASE_FAMILY[10]}
        state["CPILFESL"] = dict(OLD)
        now = utc(10, 15)
        self.assertEqual(due.waiting(now, CAL, state), {})
        self.assertEqual(due.refresh_ids(now, CAL, state), {"CPILFESL"})

    def test_window_closes_after_three_days(self):
        # 行事曆上有日期、實際沒發布（政府關門）：不能永遠每輪重抓
        self.assertTrue(due.refresh_ids(utc(13, 13), CAL, stale_state()))
        self.assertEqual(due.refresh_ids(utc(13, 14), CAL, stale_state()), set())

    def test_unknown_calendar_does_not_guess(self):
        self.assertEqual(due.refresh_ids(utc(10, 15), {10: None}, stale_state()), set())
        self.assertEqual(due.refresh_ids(utc(10, 15), {}, stale_state()), set())

    def test_summer_release_uses_eastern_time(self):
        cal = {10: [date(2026, 7, 14)]}
        before = datetime(2026, 7, 14, 12, 29, tzinfo=UTC)
        after = datetime(2026, 7, 14, 12, 31, tzinfo=UTC)
        state = {sid: {"date": "2026-05-01", "seen": "2026-06-10"}
                 for sid in catalogue.RELEASE_FAMILY[10]}
        self.assertEqual(due.refresh_ids(before, cal, state), set())
        self.assertTrue(due.refresh_ids(after, cal, state))


class TestFamilyTable(unittest.TestCase):
    def test_every_member_is_in_the_catalogue_and_not_daily(self):
        specs = {}
        for group in catalogue.ALL_GROUPS.values():
            specs.update(group)
        specs.update(catalogue.sector_specs())
        for release_id, members in catalogue.RELEASE_FAMILY.items():
            for sid in members:
                self.assertIn(sid, specs, f"{sid}（發布 {release_id}）不在目錄裡")
                self.assertNotEqual(specs[sid][2], "d", sid)

    def test_no_series_in_two_releases(self):
        seen = [sid for members in catalogue.RELEASE_FAMILY.values() for sid in members]
        self.assertEqual(len(seen), len(set(seen)))

    def test_every_tracked_release_has_its_family(self):
        for sid, _label, release_id in due.tracked():
            self.assertIn(sid, catalogue.RELEASE_FAMILY.get(release_id, ()),
                          f"{sid} 不在發布 {release_id} 的清單裡")


class TestLoadBypassesCacheOnlyForThose(unittest.TestCase):
    def test_ttl_zero_only_for_refresh_ids(self):
        calls = {}

        def fake_series(series_id, **kwargs):
            calls[series_id] = kwargs["ttl"]
            return Series.from_pairs(series_id, [("2026-09-01", "1.0")], frequency="m")

        with mock.patch.object(data.fred, "series", fake_series):
            data.load(["inflation"], verbose=False, ttl=3000,
                      refresh={"CPIAUCSL", "CPILFESL"})
        self.assertEqual(calls["CPIAUCSL"], 0)
        self.assertEqual(calls["CPILFESL"], 0)
        others = {ttl for sid, ttl in calls.items() if sid not in ("CPIAUCSL", "CPILFESL")}
        self.assertEqual(others, {3000})

    def test_freshness_metadata_follows(self):
        # 頭版「今天」靠 last_updated 寫「已公布」，推播靠它判斷這一輪才公布
        bundle = data.Bundle()
        for sid in ("CPIAUCSL", "PAYEMS"):
            bundle.add(sid, Series.from_pairs(sid, [("2026-09-01", "1.0"), ("2026-10-01", "2.0")],
                                              frequency="m"))
        ttls = {}

        def fake_metadata(series_id, ttl=None):
            ttls[series_id] = ttl
            return {"last_updated": "2026-11-10 08:12:46-06"}

        with mock.patch.object(freshness.fred, "metadata", fake_metadata), \
                mock.patch.object(freshness, "_release_dates", lambda release_id: []), \
                mock.patch.object(freshness, "load_state", lambda: {}), \
                mock.patch.object(freshness, "REFRESH", {"CPIAUCSL"}):
            freshness.compute(bundle)
        self.assertEqual(ttls["CPIAUCSL"], 0)
        self.assertEqual(ttls["PAYEMS"], 3000)


# ---------------------------------------------------------------- 發布守候 ----

class FakeIO:
    """假的時鐘、FRED 與 GitHub。sleep 只把時鐘往前撥。

    fred_at：{序列: FRED 幾點登出新的一期}；觸發建置之後 build_minutes 分鐘，
    站上的 series_dates.json 跟上當時 FRED 已經有的那幾檔。
    """

    def __init__(self, start, calendar, *, fred_at=None, state=None, build_minutes=6,
                 dispatch_fails=0, others_land_at=None, bls_at=None, bls_fails=0):
        self.clock = start
        self._calendar = calendar
        self.fred_at = fred_at or {}
        self._state = state if state is not None else {
            sid: dict(OLD) for members in catalogue.RELEASE_FAMILY.values() for sid in members}
        self.build_minutes = build_minutes
        self.dispatch_fails = dispatch_fails
        self.others_land_at = others_land_at or {}     # {序列: 別的建置幾點帶上站}
        self.dispatched: list[datetime] = []
        self.pending_builds: list[datetime] = []
        self.lines: list[str] = []
        self.bls_at = bls_at or {}                     # {序列: BLS API 幾點有新的一期}
        self.bls_fails = bls_fails                     # 前幾次查詢失敗
        self.bls_asked: list[tuple[datetime, list[str]]] = []

    def now(self):
        return self.clock

    def sleep(self, seconds):
        self.clock += timedelta(seconds=seconds)

    def log(self, message):
        self.lines.append(message)

    def calendar(self):
        return self._calendar

    def fred_date(self, series_id):
        posted = self.fred_at.get(series_id)
        return "2026-10-01" if posted and self.clock >= posted else "2026-09-01"

    def bls_dates(self, series_ids):
        self.bls_asked.append((self.clock, list(series_ids)))
        if self.bls_fails:
            self.bls_fails -= 1
            raise RuntimeError("REQUEST_NOT_PROCESSED：daily threshold reached")
        return {sid: "2026-10-01" if sid in self.bls_at and self.clock >= self.bls_at[sid]
                else "2026-09-01" for sid in series_ids}

    def _land(self, series_id, when):
        self._state[series_id] = {"date": "2026-10-01",
                                  "seen": when.astimezone(TAIPEI).date().isoformat()}

    def state(self):
        for series_id, when in self.others_land_at.items():
            if self.clock >= when and self._state[series_id]["date"] != "2026-10-01":
                self._land(series_id, when)
        for started in list(self.pending_builds):
            if self.clock >= started + timedelta(minutes=self.build_minutes):
                self.pending_builds.remove(started)
                for series_id, posted in self.fred_at.items():
                    if posted <= started:
                        self._land(series_id, self.clock)
        return self._state

    def dispatch_build(self):
        if self.dispatch_fails:
            self.dispatch_fails -= 1
            raise RuntimeError("HTTP 403")
        self.dispatched.append(self.clock)
        self.pending_builds.append(self.clock)

    def said(self, text):
        return any(text in line for line in self.lines)


class TestPlan(unittest.TestCase):
    def test_nothing_within_eight_hours(self):
        # 公布前 9 小時：還太早
        self.assertEqual(watch.plan(utc(10, 4, 29), CAL, stale_state()), [])
        io = FakeIO(utc(10, 4, 29), CAL)
        self.assertEqual(watch.run(io), "idle")
        self.assertEqual(io.dispatched, [])

    def test_upcoming_release_is_planned(self):
        items = watch.plan(utc(10, 6), CAL, stale_state())
        self.assertEqual([i["at"] for i in items], [CPI_AT])
        self.assertEqual(items[0]["series"], [("CPIAUCSL", "CPI")])

    def test_summer_time(self):
        cal = {10: [date(2026, 7, 14)]}
        items = watch.plan(datetime(2026, 7, 14, 6, 0, tzinfo=UTC), cal, {})
        self.assertEqual(items[0]["at"].astimezone(UTC).strftime("%H:%M"), "12:30")
        # 冬令的 13:30 在夏天就是晚了一小時：UTC 04:29 起算 8 小時到 12:29，還看不到
        self.assertEqual(watch.plan(datetime(2026, 7, 14, 4, 29, tzinfo=UTC), cal, {}), [])
        self.assertEqual(len(watch.plan(datetime(2026, 7, 14, 4, 31, tzinfo=UTC), cal, {})), 1)

    def test_same_instant_is_one_item_and_same_day_sorted(self):
        cal = {50: [date(2026, 12, 4)], 192: [date(2026, 12, 4)]}
        items = watch.plan(datetime(2026, 12, 4, 9, 0, tzinfo=UTC), cal, {})
        self.assertEqual([[sid for sid, _ in i["series"]] for i in items],
                         [["PAYEMS", "UNRATE"], ["JTSJOL"]])
        self.assertLess(items[0]["at"], items[1]["at"])

    def test_already_landed_release_is_not_planned(self):
        state = {"CPIAUCSL": dict(NEW)}
        self.assertEqual(watch.plan(utc(10, 16), CAL, state), [])

    def test_yesterdays_unlanded_release_is_still_planned(self):
        self.assertEqual(len(watch.plan(utc(11, 9), CAL, stale_state())), 1)
        self.assertEqual(watch.plan(utc(11, 14), CAL, stale_state()), [])   # 超過 24 小時


class TestVerdict(unittest.TestCase):
    ITEM = {"at": CPI_AT, "series": [("CPIAUCSL", "CPI")]}

    def test_each_state(self):
        old, new = {"CPIAUCSL": "2026-09-01"}, {"CPIAUCSL": "2026-10-01"}
        state = stale_state()
        self.assertEqual(watch.verdict(self.ITEM, utc(10, 13, 29), old, state, set())[0], "wait")
        self.assertEqual(watch.verdict(self.ITEM, utc(10, 13, 40), old, state, set())[0], "poll")
        self.assertEqual(watch.verdict(self.ITEM, utc(10, 14, 13), new, state, set()),
                         ("trigger", ["CPIAUCSL"]))
        self.assertEqual(watch.verdict(self.ITEM, utc(10, 16, 31), old, state, set())[0], "timeout")
        self.assertEqual(watch.verdict(self.ITEM, utc(10, 14, 30), new, state, {"CPIAUCSL"})[0], "done")
        self.assertEqual(watch.verdict(self.ITEM, utc(10, 14, 30), new,
                                       {"CPIAUCSL": dict(NEW)}, set())[0], "done")

    def test_late_but_fred_has_it_still_triggers(self):
        # 守候晚了 4 小時才啟動：超過等 FRED 的時限，但 FRED 明明有新的——要觸發，不是放棄
        new = {"CPIAUCSL": "2026-10-01"}
        self.assertEqual(watch.verdict(self.ITEM, utc(10, 17, 30), new, stale_state(), set())[0],
                         "trigger")

    def test_unknown_dates_never_trigger(self):
        self.assertFalse(watch.is_ahead(None, OLD))
        self.assertFalse(watch.is_ahead("2026-10-01", None))
        self.assertFalse(watch.is_ahead("2026-10-01", {"seen": "2026-10-14"}))
        self.assertFalse(watch.is_ahead("2026-09-01", OLD))
        self.assertTrue(watch.is_ahead("2026-10-01", OLD))


class TestRun(unittest.TestCase):
    def test_waits_polls_triggers_once_and_sees_it_land(self):
        # 2026-11-10 的實況：13:30 公布，FRED 14:12:46 登出
        posted = datetime(2026, 11, 10, 14, 12, 46, tzinfo=UTC)
        io = FakeIO(utc(10, 10), CAL, fred_at={"CPIAUCSL": posted})
        self.assertEqual(watch.run(io), "done")
        self.assertEqual(len(io.dispatched), 1)
        fired = io.dispatched[0]
        self.assertGreaterEqual(fired, posted + timedelta(seconds=watch.SETTLE))
        self.assertLess(fired, posted + timedelta(seconds=watch.SETTLE + 2 * watch.POLL))
        self.assertTrue(io.said("上站了"))
        self.assertTrue(due.landed(io.state()["CPIAUCSL"], CPI_AT))

    def test_does_not_poll_before_release_time(self):
        io = FakeIO(utc(10, 10), CAL, fred_at={"CPIAUCSL": utc(10, 14, 12)})
        asked = []
        real = io.fred_date
        io.fred_date = lambda sid: (asked.append(io.clock), real(sid))[1]
        watch.run(io)
        self.assertGreaterEqual(min(asked), CPI_AT)

    def test_timeout_without_trigger(self):
        io = FakeIO(utc(10, 12), CAL)                  # FRED 始終沒有新的一期
        self.assertEqual(watch.run(io), "done")
        self.assertEqual(io.dispatched, [])
        self.assertTrue(io.said("沒等到"))
        self.assertGreater(io.clock, CPI_AT + watch.FRED_TIMEOUT)
        self.assertLess(io.clock, CPI_AT + watch.FRED_TIMEOUT + timedelta(minutes=3))

    def test_started_after_release_checks_and_triggers_immediately(self):
        # 守候被 GitHub 延後到公布之後 3 小時才啟動，FRED 早就有了
        io = FakeIO(utc(10, 16, 40), CAL, fred_at={"CPIAUCSL": utc(10, 14, 12)})
        self.assertEqual(watch.run(io), "done")
        self.assertEqual(len(io.dispatched), 1)
        self.assertLess(io.dispatched[0], utc(10, 16, 40) + timedelta(seconds=watch.SETTLE + 5))

    def test_no_trigger_when_another_build_already_carried_it(self):
        posted = utc(10, 14, 12)
        io = FakeIO(utc(10, 13), CAL, fred_at={"CPIAUCSL": posted},
                    others_land_at={"CPIAUCSL": posted + timedelta(minutes=2)})
        self.assertEqual(watch.run(io), "done")
        self.assertEqual(io.dispatched, [])
        self.assertTrue(io.said("不另外觸發"))

    def test_two_releases_same_day_one_trigger_each(self):
        # 12/4：非農與失業率 8:30、JOLTS 10:00（美東）
        day = date(2026, 12, 4)
        cal = {50: [day], 192: [day]}
        jobs_posted = datetime(2026, 12, 4, 15, 43, tzinfo=UTC)       # 公布後 133 分鐘
        jolts_posted = datetime(2026, 12, 4, 15, 10, tzinfo=UTC)
        io = FakeIO(datetime(2026, 12, 4, 8, 0, tzinfo=UTC), cal,
                    fred_at={"PAYEMS": jobs_posted, "UNRATE": jobs_posted, "JTSJOL": jolts_posted})
        self.assertEqual(watch.run(io, budget=timedelta(hours=12)), "done")
        self.assertEqual(len(io.dispatched), 2)        # 非農＋失業率一次、JOLTS 一次
        state = io.state()
        for sid in ("PAYEMS", "UNRATE", "JTSJOL"):
            self.assertEqual(state[sid]["date"], "2026-10-01", sid)

    def test_build_that_never_lands_is_not_retriggered(self):
        io = FakeIO(utc(10, 13), CAL, fred_at={"CPIAUCSL": utc(10, 14, 12)}, build_minutes=10_000)
        self.assertEqual(watch.run(io), "done")
        self.assertEqual(len(io.dispatched), 1)
        self.assertTrue(io.said("不重複觸發"))

    def test_dispatch_failure_is_retried_then_given_up(self):
        io = FakeIO(utc(10, 13), CAL, fred_at={"CPIAUCSL": utc(10, 14, 12)}, dispatch_fails=1)
        self.assertEqual(watch.run(io), "done")
        self.assertEqual(len(io.dispatched), 1)        # 第一次失敗，第二次成功
        io = FakeIO(utc(10, 13), CAL, fred_at={"CPIAUCSL": utc(10, 14, 12)}, dispatch_fails=99)
        self.assertEqual(watch.run(io), "done")
        self.assertEqual(io.dispatched, [])
        self.assertTrue(io.said("不再試"))

    def test_unknown_calendar_is_not_reported_as_nothing_to_watch(self):
        io = FakeIO(utc(10, 10), {10: None, 50: None})
        self.assertEqual(watch.run(io), "blind")
        self.assertTrue(io.said("::error"))
        self.assertFalse(io.said("沒有追蹤的發布"))
        # 只缺一份：照常守候看得到的，缺的那一份講明
        io = FakeIO(utc(10, 10), {**CAL, 50: None}, fred_at={"CPIAUCSL": utc(10, 14, 12)})
        self.assertEqual(watch.run(io), "done")
        self.assertEqual(len(io.dispatched), 1)
        self.assertTrue(io.said("::warning"))

    def test_hands_off_when_out_of_budget(self):
        io = FakeIO(utc(10, 6), CAL, fred_at={"CPIAUCSL": utc(10, 14, 12)})
        self.assertEqual(watch.run(io, budget=timedelta(hours=5)), "handoff")
        self.assertEqual(io.dispatched, [])
        self.assertLess(io.clock, utc(10, 11, 10))
        # 下一支接著等，照樣只觸發一次
        self.assertEqual(watch.run(io), "done")
        self.assertEqual(len(io.dispatched), 1)


class TestBlsProbe(unittest.TestCase):
    """只記錄的探針：公布後問 BLS API 幾次，記下它幾點有、FRED 幾點有。

    會靜默出錯的地方：把額度用完的回應當成「還沒有新的一期」；問太多次把一天 25 次的
    額度用光；探針自己出錯拖垮守候；或者探針影響了觸發（它不該改變網站的任何行為）。
    """

    POSTED = datetime(2026, 11, 10, 14, 12, 46, tzinfo=UTC)      # FRED 登出 CPI 的時間

    def notices(self, io):
        return [line for line in io.lines if line.startswith("::notice title=BLS 探針::")]

    def test_parses_the_real_response_shape(self):
        payload = {"status": "REQUEST_SUCCEEDED", "message": [], "Results": {"series": [
            {"seriesID": "CUSR0000SA0", "data": [
                {"year": "2026", "period": "M10", "value": "337.476"},
                {"year": "2026", "period": "M09", "value": "336.298"},
                {"year": "2025", "period": "M13", "value": "330.0"},        # 年平均，不是月份
                {"year": "2025", "period": "M12", "value": "331.0"}]},
            {"seriesID": "WPSFD4", "data": []}]}}
        self.assertEqual(watch.bls_latest(payload), {"CUSR0000SA0": "2026-10-01"})

    def test_refused_request_is_not_an_empty_answer(self):
        with self.assertRaises(RuntimeError) as caught:
            watch.bls_latest({"status": "REQUEST_NOT_PROCESSED",
                              "message": ["daily threshold reached"], "Results": {}})
        self.assertIn("daily threshold", str(caught.exception))

    def test_schedule_fits_the_daily_quota(self):
        self.assertLessEqual(len(watch.BLS_ASK_AT), 12)             # 一天 25 次，兩場公布也夠
        self.assertEqual(watch.bls_next_ask(0), 2)
        self.assertEqual(watch.bls_next_ask(41.5), 45)              # 啟動得晚：跳過已經過去的
        self.assertIsNone(watch.bls_next_ask(90))

    def test_every_probed_series_is_tracked_and_from_bls(self):
        tracked = {series_id: release_id for series_id, _label, release_id in due.tracked()}
        for series_id in watch.BLS_IDS:
            self.assertIn(tracked.get(series_id), (10, 46, 50, 192), series_id)

    def test_records_when_bls_and_fred_each_had_it(self):
        # BLS 公布後 1 分鐘有、FRED 42 分鐘：0 分鐘問不到、2 分鐘問到，之後不再問
        io = FakeIO(utc(10, 10), CAL, fred_at={"CPIAUCSL": self.POSTED},
                    bls_at={"CPIAUCSL": CPI_AT + timedelta(minutes=1)})
        self.assertEqual(watch.run(io), "done")
        self.assertEqual([when for when, _ids in io.bls_asked],
                         [CPI_AT, CPI_AT + timedelta(minutes=2)])
        self.assertEqual(io.bls_asked[0][1], ["CPIAUCSL"])
        found, compared = self.notices(io)
        self.assertIn("公布後 2 分鐘問到", found)
        self.assertIn("上一次問是公布後 0 分鐘", found)
        self.assertIn("FRED 公布後 43 分鐘", compared)
        self.assertIn("可以早約 41 分鐘", compared)
        # 探針不改變觸發：仍然只在 FRED 登出之後觸發一次
        self.assertEqual(len(io.dispatched), 1)
        self.assertGreaterEqual(io.dispatched[0], self.POSTED)

    def test_stops_asking_when_bls_never_updates(self):
        io = FakeIO(utc(10, 12), CAL)                  # BLS 與 FRED 都沒有新的一期
        self.assertEqual(watch.run(io), "done")
        self.assertEqual(len(io.bls_asked), len(watch.BLS_ASK_AT))
        self.assertEqual(io.bls_asked[-1][0], CPI_AT + timedelta(minutes=90))
        self.assertIn("仍沒有新的一期", self.notices(io)[-1])
        self.assertEqual(io.dispatched, [])

    def test_fred_first_is_reported_as_no_gain(self):
        io = FakeIO(utc(10, 10), CAL, fred_at={"CPIAUCSL": self.POSTED})
        watch.run(io)
        self.assertIn("直讀沒有比較快", self.notices(io)[-1])
        self.assertLess(max(when for when, _ids in io.bls_asked), self.POSTED + timedelta(minutes=1))
        self.assertEqual(len(io.dispatched), 1)

    def test_blocked_api_stops_after_three_and_never_breaks_the_watch(self):
        io = FakeIO(utc(10, 10), CAL, fred_at={"CPIAUCSL": self.POSTED}, bls_fails=99)
        self.assertEqual(watch.run(io), "done")
        self.assertEqual(len(io.bls_asked), watch.BLS_MAX_FAILURES)
        self.assertIn("從這裡用不了", self.notices(io)[0])
        self.assertIn("daily threshold", self.notices(io)[0])
        self.assertEqual(len(io.dispatched), 1)
        self.assertTrue(io.said("上站了"))

    def test_a_probe_that_blows_up_is_contained(self):
        io = FakeIO(utc(10, 10), CAL, fred_at={"CPIAUCSL": self.POSTED})
        with mock.patch.object(watch, "bls_next_ask", side_effect=ValueError("boom")):
            self.assertEqual(watch.run(io), "done")
        self.assertTrue(io.said("BLS 探針出錯"))
        self.assertEqual(len(io.dispatched), 1)
        self.assertTrue(io.said("上站了"))

    def test_late_start_only_claims_an_upper_bound(self):
        # 守候被延後到公布後 50 分鐘才啟動：BLS 與 FRED 都已經有了
        io = FakeIO(utc(10, 14, 20), CAL, fred_at={"CPIAUCSL": self.POSTED},
                    bls_at={"CPIAUCSL": CPI_AT})
        watch.run(io)
        found, compared = self.notices(io)
        self.assertIn("只知道不晚於這個時間", found)
        self.assertIn("量不出差距", compared)
        self.assertEqual(len(io.bls_asked), 1)

    def test_releases_not_from_bls_are_never_asked(self):
        claims = {180: [date(2026, 11, 12)]}
        state = {sid: {"date": "2026-10-31", "seen": "2026-11-05"}
                 for sid in catalogue.RELEASE_FAMILY[180]}
        io = FakeIO(utc(12, 10), claims, state=state)
        watch.run(io)
        self.assertEqual(io.bls_asked, [])
        self.assertEqual(self.notices(io), [])

    def test_same_instant_series_share_one_query(self):
        jobs = {50: [date(2026, 11, 6)]}
        state = {sid: dict(OLD) for sid in catalogue.RELEASE_FAMILY[50]}
        at = utc(6, 13, 30)
        io = FakeIO(utc(6, 12), jobs, state=state,
                    bls_at={"PAYEMS": at, "UNRATE": at + timedelta(minutes=3)})
        watch.run(io)
        self.assertEqual(io.bls_asked[0], (at, ["PAYEMS", "UNRATE"]))
        self.assertEqual(io.bls_asked[1][1], ["UNRATE"])           # 到了的那一檔不再問
        self.assertIn("公布後 4 分鐘問到", self.notices(io)[0])


class TestYield(unittest.TestCase):
    def test_older_run_wins(self):
        runs = [{"id": 5, "status": "in_progress", "display_title": "發布守候"},
                {"id": 9, "status": "in_progress", "display_title": "發布守候"}]
        self.assertTrue(watch.should_yield(runs, 9, False))
        self.assertFalse(watch.should_yield(runs, 5, False))

    def test_completed_runs_do_not_count(self):
        runs = [{"id": 5, "status": "completed", "display_title": "發布守候"},
                {"id": 9, "status": "queued", "display_title": "發布守候"}]
        self.assertFalse(watch.should_yield(runs, 9, False))

    def test_successor_never_yields_and_everyone_yields_to_it(self):
        runs = [{"id": 5, "status": "in_progress", "display_title": "發布守候"},
                {"id": 7, "status": "in_progress", "display_title": "發布守候"},
                {"id": 9, "status": "queued", "display_title": "發布守候（接力）"}]
        self.assertFalse(watch.should_yield(runs, 9, True))
        self.assertTrue(watch.should_yield([runs[1], runs[2]], 7, False))

    def test_local_run_without_run_id(self):
        self.assertFalse(watch.should_yield([{"id": 1, "status": "in_progress"}], None, False))

    def test_workflow_marks_the_successor_in_its_run_name(self):
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            ".github", "workflows", watch.WORKFLOW)
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        run_name = next(line for line in text.splitlines() if line.startswith("run-name:"))
        self.assertIn(watch.HANDOFF_MARK, run_name)
        self.assertIn("actions: write", text)
        self.assertIn("workflow_dispatch", text)


if __name__ == "__main__":
    unittest.main()
