"""時間來源的迴歸測試。

這兩個錯都不會當場爆炸，只會靜靜產出錯的字串與錯的檔名：
  · 「最後更新」標著台北卻是 UTC（差 8 小時）
  · 台北凌晨 0–8 點的建置被歸到前一天，覆蓋掉前一天的快照

改成每小時建置之後，每天有 8 個小時落在第二種錯的區間，所以這裡釘死。
"""
from __future__ import annotations

import os
import time
import unittest
from datetime import datetime, timedelta, timezone

from macro import clock


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


if __name__ == "__main__":
    unittest.main()
