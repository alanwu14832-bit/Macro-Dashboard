"""FOMC 會議行事曆。

日期是聯準會每年提前整年公布的，寫死在這裡就好，不需要 API。
每年年底聯準會公布隔年時程時，把新的一年加進 MEETINGS——
建置時若行事曆已走完，總覽的倒數 chip 會自動消失而不是報錯，
所以忘了更新也只是少一個 chip。

日期取決策日（兩天會期的第二天，聲明與記者會在這天）。
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

from . import clock
from .series import Series

# 決議公布後在總覽置頂幾天。一週是「上週的決議」還算新聞的極限。
WINDOW_DAYS = 7
# 聲明美東 14:00 發布；過了 14:30 還沒有就算遺漏，不是「還沒到」。
ANNOUNCE_BY = time(14, 30)

MEETINGS = [
    # 2026 年（聯準會 2025-06 公布）
    date(2026, 1, 28), date(2026, 3, 18), date(2026, 4, 29),
    date(2026, 6, 17), date(2026, 7, 29), date(2026, 9, 16),
    date(2026, 10, 28), date(2026, 12, 9),
    # 2027 年（聯準會 2026-06 公布）
    date(2027, 1, 27), date(2027, 3, 17), date(2027, 4, 28),
    date(2027, 6, 9), date(2027, 7, 28), date(2027, 9, 15),
    date(2027, 10, 27), date(2027, 12, 8),
]


def next_meeting(today: date | None = None) -> dict | None:
    """下一次 FOMC 決策日與倒數天數。行事曆走完回 None。"""
    today = today or clock.us_today()
    for when in MEETINGS:
        if when >= today:
            return {"date": when, "days": (when - today).days}
    return None


# ------------------------------------------------------------------ 決議 ----
# 2026-09-16 聯準會升息 1 碼，網站兩天都沒顯示：政策利率只讀 FRED 的
# DFEDTARU，它要隔天以後才補上生效日的新值；聲明雖然有抓，只拿來做英文逐句
# 比對，從來沒被讀成「升息了」；行事曆則在會後默默翻到下一次會議。
# 所以決議的真相改由聯準會聲明決定，而且會後一週內「決議」或「決議遺漏」
# 兩者之一一定出現在總覽最上面——不准兩個都沒有。

def range_label(lower: float, upper: float) -> str:
    return f"{lower:.2f}%–{upper:.2f}%"


def action_label(decision: dict) -> str:
    if decision["action"] == "hold":
        return "利率維持不變"
    step = decision.get("step")
    if step is None and decision.get("prev_upper") is not None:
        step = abs(decision["upper"] - decision["prev_upper"])
    word = "升息" if decision["action"] == "raise" else "降息"
    if not step:
        return word
    bp = round(step * 100)
    return f"{word} {bp // 25} 碼" if bp % 25 == 0 else f"{word} {bp} 個基點"


def headline(decision: dict) -> str:
    new = range_label(decision["lower"], decision["upper"])
    if decision["action"] == "hold":
        return f"聯準會利率維持不變　{new}"
    if decision.get("prev_upper") is not None:
        old = range_label(decision["prev_lower"], decision["prev_upper"])
        return f"聯準會{action_label(decision)}　{old} → {new}"
    return f"聯準會{action_label(decision)}至 {new}"


def reconcile_policy(bundle, decision: dict | None) -> dict:
    """聲明比 FRED 新的時候，用聲明補上政策利率的生效日那一點。

    利率決議在聲明隔天生效，FRED 的 DFEDTARU／DFEDTARL 又要再晚一兩天才補上。
    這段時間裡，所有讀政策利率的地方（實質政策利率、台美利差、全球對照）
    都會拿舊值算。補上的點在序列 meta 裡標明來源；FRED 一旦補上就以 FRED 為準，
    兩者不一致時保留 FRED 並回報衝突，不偷偷覆蓋。
    """
    result = {"patched": False, "conflict": [], "effective": None}
    if (decision or {}).get("status") != "ok":
        return result
    effective = date.fromisoformat(decision["date"]) + timedelta(days=1)
    result["effective"] = effective.isoformat()
    for series_id, value in (("DFEDTARU", decision["upper"]),
                             ("DFEDTARL", decision["lower"])):
        series = bundle[series_id]
        if series.last_date is not None and series.last_date >= effective:
            recorded = series.value_on(effective)
            if recorded is not None and abs(recorded - value) > 1e-9:
                result["conflict"].append(series_id)
            continue
        pairs = [(d, v) for d, v in series.pairs() if d < effective]
        meta = dict(series.meta)
        meta["patched_from"] = {"statement": decision["date"],
                                "effective": effective.isoformat()}
        bundle.add(series_id, Series.from_pairs(
            series_id, pairs + [(effective, value)], label=series.label,
            unit=series.unit, frequency=series.frequency or "d",
            source=series.source, meta=meta))
        result["patched"] = True
    return result


def decision_status(decision: dict | None, now: datetime | None = None) -> dict | None:
    """會後一週內，總覽該顯示什麼。

      announced  讀到這次（或臨時會議）的決議
      pending    今天是會議日、美東 14:30 以前，聲明本來就還沒出
      missing    會議已經開完，卻沒有對應的決議——抓不到、讀不出、或 RSS 還停在上一次
      None       最近一週沒有會議也沒有決議
    """
    now = now or clock.us_now()
    today = now.date()
    decision = decision or {}

    announced = None
    if decision.get("status") == "ok" and decision.get("date"):
        announced = date.fromisoformat(decision["date"])

    meeting = next((m for m in reversed(MEETINGS) if m <= today), None)
    if meeting is not None and (today - meeting).days > WINDOW_DAYS:
        meeting = None

    if (announced is not None and (today - announced).days <= WINDOW_DAYS
            and (meeting is None or announced >= meeting)):
        return {"state": "announced", "headline": headline(decision),
                "effective": (announced + timedelta(days=1)).isoformat(),
                **decision}

    if meeting is None:
        return None
    if today == meeting and now.time() < ANNOUNCE_BY:
        return {"state": "pending", "meeting": meeting.isoformat()}

    if announced is not None:
        reason = f"最新取得的聲明是 {decision['date']}，還不是這次會議的"
    else:
        reason = decision.get("reason") or "沒有取得聲明"
    return {"state": "missing", "meeting": meeting.isoformat(), "reason": reason}
