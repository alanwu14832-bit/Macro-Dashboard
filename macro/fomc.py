"""FOMC 會議行事曆。

日期是聯準會每年提前整年公布的，寫死在這裡就好，不需要 API。
每年年底聯準會公布隔年時程時，把新的一年加進 MEETINGS——
建置時若行事曆已走完，總覽的倒數 chip 會自動消失而不是報錯，
所以忘了更新也只是少一個 chip。

日期取決策日（兩天會期的第二天，聲明與記者會在這天）。
"""
from __future__ import annotations

from datetime import date

MEETINGS = [
    # 2026 年（聯準會 2025-06 公布）
    date(2026, 1, 28), date(2026, 3, 18), date(2026, 4, 29),
    date(2026, 6, 17), date(2026, 7, 29), date(2026, 9, 16),
    date(2026, 10, 28), date(2026, 12, 9),
]


def next_meeting(today: date | None = None) -> dict | None:
    """下一次 FOMC 決策日與倒數天數。行事曆走完回 None。"""
    today = today or date.today()
    for when in MEETINGS:
        if when >= today:
            return {"date": when, "days": (when - today).days}
    return None
