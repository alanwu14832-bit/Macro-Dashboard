"""時間來源的迴歸測試。

這兩個錯都不會當場爆炸，只會靜靜產出錯的字串與錯的檔名：
  · 「最後更新」標著台北卻是 UTC（差 8 小時）
  · 台北凌晨 0–8 點的建置被歸到前一天，覆蓋掉前一天的快照

改成每小時建置之後，每天有 8 個小時落在第二種錯的區間，所以這裡釘死。

2026-09-15 又抓到一批繞過 clock 的呼叫：world.country_table 的 CPI 停更天數、
證交所的日期、標著「（台北）」卻是 UTC 的產生時間。所以除了 clock 本身，
這裡也把「UTC runner 在台北凌晨」的瞬間釘住去跑呼叫端，並用 ast 掃一遍，
讓下一個 date.today() 在測試就被擋下來，而不是等某一格的標記悄悄早一天出現。
"""
from __future__ import annotations

import ast
import os
import time
import unittest
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from unittest import mock

from macro import clock, fomc
from macro.compute import world
from macro.data import Bundle
from macro.series import EMPTY, Series

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@contextmanager
def _utc_runner_at(instant: datetime):
    """行程時區設成 UTC，clock 的「現在」釘在 instant——雲端建置在那一刻的樣子。"""

    class Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return instant.astimezone(timezone.utc).replace(tzinfo=None)
            return instant.astimezone(tz)

    original = os.environ.get("TZ")
    os.environ["TZ"] = "UTC"
    if hasattr(time, "tzset"):
        time.tzset()
    try:
        with mock.patch.object(clock, "datetime", Frozen):
            yield
    finally:
        if original is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = original
        if hasattr(time, "tzset"):
            time.tzset()


class TaipeiClock(unittest.TestCase):
    def test_now_is_timezone_aware_at_plus_eight(self):
        now = clock.now()
        self.assertIsNotNone(now.tzinfo)
        self.assertEqual(now.utcoffset(), timedelta(hours=8))

    def test_now_tracks_utc_by_exactly_eight_hours(self):
        utc = datetime.now(timezone.utc)
        delta = clock.now() - utc
        self.assertLess(abs(delta.total_seconds()), 2)  # 同一瞬間，只是不同時區

    def test_independent_of_process_timezone(self):
        """runner 的 TZ 是 UTC 也不能影響結果——這正是雲端建置的情境。"""
        original = os.environ.get("TZ")
        try:
            os.environ["TZ"] = "UTC"
            if hasattr(time, "tzset"):
                time.tzset()
            self.assertEqual(clock.now().utcoffset(), timedelta(hours=8))
            # 台北的日期＝UTC 時間加 8 小時之後的日期
            expected = (datetime.now(timezone.utc) + timedelta(hours=8)).date()
            self.assertEqual(clock.today(), expected)
        finally:
            if original is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = original
            if hasattr(time, "tzset"):
                time.tzset()

    def test_stamp_shape(self):
        text = clock.stamp()
        self.assertTrue(text.startswith("最後更新 "))
        datetime.strptime(text.removeprefix("最後更新 "), "%Y-%m-%d %H:%M")


class UtcRunnerAtTaipeiDawn(unittest.TestCase):
    """上面那組只在「剛好在台北凌晨跑測試」時才碰得到邊界；這組把瞬間釘住。

    UTC 2025-12-31 17:00 ＝ 台北 2026-01-01 01:00：UTC 的日期還在前一年。
    """
    DAWN = datetime(2025, 12, 31, 17, 0, tzinfo=timezone.utc)

    def test_today_is_taipei_date_not_runner_date(self):
        with _utc_runner_at(self.DAWN):
            self.assertEqual(clock.today(), date(2026, 1, 1))
            self.assertEqual(clock.now().utcoffset(), timedelta(hours=8))

    def test_world_cpi_staleness_counts_from_taipei_date(self):
        """停更天數從台北的今天算：剛好跨過門檻的那一天，UTC 會少算一天而不標停更。"""
        last = date(2026, 1, 1) - timedelta(days=world.STALE_DAYS + 1)
        external = {"cpi": {}, "ea_unemployment": EMPTY,
                    "tw_cpi": Series.from_pairs("TW_CPI", [(last.isoformat(), 1.6)],
                                                unit="%", frequency="m")}
        with _utc_runner_at(self.DAWN):
            rows = {r["code"]: r for r in world.country_table(Bundle(), external)["rows"]}
        self.assertEqual(rows["TW"]["cpi_age"], world.STALE_DAYS + 1)
        self.assertTrue(rows["TW"]["cpi_stale"])


class UsEventsUseNewYorkDate(unittest.TestCase):
    """美國事件的日期是美東日期。台北在美東中午就換日——拿台北的今天去比，
    14:00 的 FOMC 決策還沒公布就會被當成「已經過去」而換成下一場。"""

    # UTC 2026-09-16 16:30 ＝ 紐約 12:30（決策前）＝ 台北 9/17 00:30
    BEFORE_DECISION = datetime(2026, 9, 16, 16, 30, tzinfo=timezone.utc)

    def test_us_today_lags_taipei_across_the_boundary(self):
        with _utc_runner_at(self.BEFORE_DECISION):
            self.assertEqual(clock.today(), date(2026, 9, 17))
            self.assertEqual(clock.us_today(), date(2026, 9, 16))

    def test_fomc_countdown_keeps_todays_meeting_until_it_happens(self):
        self.assertIn(date(2026, 9, 16), fomc.MEETINGS)
        with _utc_runner_at(self.BEFORE_DECISION):
            meeting = fomc.next_meeting()
        self.assertEqual(meeting, {"date": date(2026, 9, 16), "days": 0})


# ------------------------------------------------------------ 靜態檢查 -----
PACKAGES = ["macro", "tools"]
EXTRA_FILES = ["build.py"]
CLOCK_FILE = os.path.join(ROOT, "macro", "clock.py")


def _python_files() -> list[str]:
    found = [os.path.join(ROOT, name) for name in EXTRA_FILES]
    for package in PACKAGES:
        for folder, _dirs, files in os.walk(os.path.join(ROOT, package)):
            if "__pycache__" in folder:
                continue
            found += [os.path.join(folder, f) for f in files if f.endswith(".py")]
    return sorted(p for p in found if os.path.exists(p) and p != CLOCK_FILE)


def _naive_call(node: ast.AST) -> str | None:
    """讀到 runner 時區的呼叫。只認沒給時區的寫法——給了時區的就不是這個錯。"""
    if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
        return None
    attr, owner = node.func.attr, node.func.value
    owner_name = (owner.id if isinstance(owner, ast.Name)
                  else owner.attr if isinstance(owner, ast.Attribute) else "")
    bare = not node.args and not node.keywords
    if attr == "today" and owner_name in ("date", "datetime") and bare:
        return f"{owner_name}.today()"
    if attr == "now" and owner_name == "datetime" and bare:
        return "datetime.now()"
    if attr == "utcnow":
        return "datetime.utcnow()"
    if attr == "astimezone" and bare:
        return ".astimezone()（轉到 runner 的時區）"
    if attr == "fromtimestamp" and len(node.args) == 1 and not node.keywords:
        return "fromtimestamp() 沒給 tz"
    return None


class NoNaiveClockCalls(unittest.TestCase):
    def test_only_clock_module_reads_the_runner_clock(self):
        problems = []
        for path in _python_files():
            with open(path, encoding="utf-8") as fh:
                tree = ast.parse(fh.read(), path)
            for node in ast.walk(tree):
                found = _naive_call(node)
                if found:
                    problems.append(f"{os.path.relpath(path, ROOT)}:{node.lineno} {found}")
        self.assertEqual(problems, [],
                         "時間一律從 macro/clock.py 拿（台北用 clock.today/now，"
                         "美國事件日期用 clock.us_today）：\n" + "\n".join(problems))


if __name__ == "__main__":
    unittest.main()
