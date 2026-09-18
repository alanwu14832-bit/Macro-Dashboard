"""FOMC 會議行事曆與決議狀態。

日期是聯準會每年提前整年公布的，寫死在這裡就好，不需要 API。
每年年底聯準會公布隔年時程時，把新的一年加進 MEETINGS——行事曆剩不到
120 天時建置會印警告，因為行事曆走完之後「例會開完卻沒有決議」就偵測不到了。

日期取決策日（兩天會期的第二天，聲明與記者會在這天）。
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

from . import clock
from .clock import NEW_YORK
from .series import Series

# 決議公布後在總覽留幾天。一週是「上週的決議」還算新聞的極限。
WINDOW_DAYS = 7
# 例會聲明美東 14:00 發布；過了 14:30 還沒有就算遺漏，不是「還沒到」。
ANNOUNCE_AT = time(14, 0)
ANNOUNCE_BY = time(14, 30)
# 公布前多久開始顯示「待公布」。36 小時讓台北會議日當天整天看得到。
PENDING_HOURS = 36

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
# 2026-09-16 聯準會升息 1 碼，網站兩天都沒有顯示：政策利率只讀 FRED 的
# DFEDTARU，它要隔天以後才補上生效日的新值；聲明雖然有抓，只拿來做英文逐句
# 比對，從來沒被讀成「升息了」；行事曆則在會後默默翻到下一次會議。
# 所以決議的真相改由聯準會聲明決定，而且會後一週內「決議」或「決議遺漏」
# 至少一個出現在總覽的「今天」——不准兩個都沒有。

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


def announced_at(decision: dict) -> datetime:
    """聲明的公布時間（美東）。臨時會議不在 14:00——2020-03-03 是 10:00、
    2020-03-15 是週日 17:00——所以優先用 RSS 的發布時間。"""
    if decision.get("published"):
        try:
            return datetime.fromisoformat(decision["published"]).astimezone(NEW_YORK)
        except ValueError:
            pass
    return datetime.combine(date.fromisoformat(decision["date"]), ANNOUNCE_AT, tzinfo=NEW_YORK)


def _ok_decisions(decision: dict) -> list[dict]:
    """這次（若讀得出）與上一次讀得出的決議，新到舊。"""
    out = []
    if decision.get("status") == "ok" and decision.get("date"):
        out.append(decision)
    previous = decision.get("previous")
    if previous and previous.get("status", "ok") == "ok" and previous.get("date"):
        out.append(previous)
        if decision.get("status") != "ok" and previous.get("previous"):
            out.append(previous["previous"])
    return out


def reconcile_policy(bundle, decision: dict | None) -> dict:
    """聲明比 FRED 新的時候，用聲明補上政策利率的生效日那一點。

    利率決議在聲明隔天生效，FRED 的 DFEDTARU／DFEDTARL 又要再晚一兩天才補上。
    這段時間裡，所有讀政策利率的地方（實質政策利率、台美利差、全球對照）
    都會拿舊值算。補上的點在序列 meta 裡標明來源；FRED 一旦補上就以 FRED 為準，
    兩者不一致時保留 FRED 並回報衝突，不偷偷覆蓋。最新聲明讀不出時，用上一次
    讀得出的決議補——那一次的生效日 FRED 也可能還沒補上。
    """
    result = {"patched": False, "conflict": [], "effective": None}
    candidates = _ok_decisions(decision or {})
    if not candidates:
        return result
    latest = candidates[0]
    try:
        effective = date.fromisoformat(latest["date"]) + timedelta(days=1)
    except (TypeError, ValueError):
        return result
    result["effective"] = effective.isoformat()
    for series_id, value in (("DFEDTARU", latest["upper"]),
                             ("DFEDTARL", latest["lower"])):
        series = bundle[series_id]
        if series.last_date is not None and series.last_date >= effective:
            recorded = series.value_on(effective)
            if recorded is not None and abs(recorded - value) > 1e-9:
                result["conflict"].append(series_id)
            continue
        pairs = [(d, v) for d, v in series.pairs() if d < effective]
        meta = dict(series.meta)
        meta["patched_from"] = {"statement": latest["date"],
                                "effective": effective.isoformat()}
        bundle.add(series_id, Series.from_pairs(
            series_id, pairs + [(effective, value)], label=series.label,
            unit=series.unit, frequency=series.frequency or "d",
            source=series.source, meta=meta))
        result["patched"] = True
    return result


def decision_states(decision: dict | None, now: datetime | None = None) -> list[dict]:
    """會後一週內，總覽該顯示的每一列。遺漏在前、待公布其次、已公布最後。

      announced  讀到的決議（這次與上一次，只要在一週內都列——臨時會議之後緊接
                 例會時，兩次都要看得到）
      pending    例會聲明快出來了（公布前 36 小時起）；過了 14:00 仍沒取得標 overdue
      missing    例會開完卻沒有對應決議；或最新聲明像決議卻讀不出／抓不到
                 （臨時會議不在行事曆上，也照樣算）
    """
    now = (now or clock.us_now()).astimezone(NEW_YORK)
    today = now.date()
    decision = decision or {}
    oks = _ok_decisions(decision)
    latest_ok = max((date.fromisoformat(d["date"]) for d in oks), default=None)

    unreadable = None
    if decision.get("status") in ("unparsed", "unavailable") and decision.get("date"):
        unreadable = date.fromisoformat(decision["date"])

    states: list[dict] = []
    if (unreadable is not None and 0 <= (today - unreadable).days <= WINDOW_DAYS
            and (latest_ok is None or unreadable > latest_ok)):
        states.append({"state": "missing", "meeting": unreadable.isoformat(),
                       "reason": decision.get("reason") or "沒有取得聲明"})

    past = next((m for m in reversed(MEETINGS)
                 if datetime.combine(m, ANNOUNCE_BY, tzinfo=NEW_YORK) <= now), None)
    if past is not None and (today - past).days > WINDOW_DAYS:
        past = None
    covered = (latest_ok is not None and latest_ok >= past) if past else True
    if past is not None and not covered and not (unreadable is not None and unreadable >= past):
        if latest_ok is not None:
            reason = f"最新取得的聲明是 {latest_ok.isoformat()}，還不是這次會議的"
            if (past - latest_ok).days <= WINDOW_DAYS:
                reason += f"（若例會已由 {latest_ok.isoformat()} 的臨時會議取代則屬正常）"
        else:
            reason = decision.get("reason") or "沒有取得聲明"
        states.append({"state": "missing", "meeting": past.isoformat(), "reason": reason})

    for meeting in MEETINGS:
        at = datetime.combine(meeting, ANNOUNCE_AT, tzinfo=NEW_YORK)
        by = datetime.combine(meeting, ANNOUNCE_BY, tzinfo=NEW_YORK)
        if at - timedelta(hours=PENDING_HOURS) <= now < by:
            if latest_ok is None or latest_ok < meeting:
                states.append({"state": "pending", "meeting": meeting.isoformat(),
                               "at": at.isoformat(), "overdue": now >= at})
            break

    for d in oks:
        day = date.fromisoformat(d["date"])
        if 0 <= (today - day).days <= WINDOW_DAYS:
            states.append({**d, "state": "announced", "headline": headline(d),
                           "effective": (day + timedelta(days=1)).isoformat(),
                           "at": announced_at(d).isoformat()})
    return states


def decision_status(decision: dict | None, now: datetime | None = None) -> dict | None:
    """最需要注意的那一列（遺漏 > 待公布 > 已公布），沒有就回 None。"""
    states = decision_states(decision, now)
    return states[0] if states else None
