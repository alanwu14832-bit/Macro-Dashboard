"""台灣央行理監事會：行事曆、決議狀態、政策利率校正。

跟 macro/fomc.py 同一套規矩，只是時區換成台北：
  - 決議的真相是決議新聞稿，不是貼放利率表（那張表只在利率有變時才多一列）
  - 會後一週內，「決議」或「決議遺漏」一定出現在總覽的「今天」區塊
  - 抓不到、讀不出、RSS 停在上一次，全部算遺漏
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

from . import clock
from .series import Series

# 央行每年 12 月公告隔年日期；公告從 RSS 自動讀（sources/cbc.board_schedule），
# 這份寫死的只是 RSS 抓不到時的退路。
MEETINGS_FALLBACK = [
    date(2025, 3, 20), date(2025, 6, 19), date(2025, 9, 18), date(2025, 12, 18),
    date(2026, 3, 19), date(2026, 6, 18), date(2026, 9, 17), date(2026, 12, 17),
]

WINDOW_DAYS = 7
# 會後記者會 16:30，新聞稿通常 16:50 前後上 RSS；過了 17:30 還沒有就算遺漏。
ANNOUNCE_BY = time(17, 30)


def meetings(published: list[date] | None = None) -> list[date]:
    return sorted(set(MEETINGS_FALLBACK) | set(published or []))


def _step_label(step: float) -> str:
    quarters = step / 0.25
    if abs(quarters - 0.5) < 1e-9:
        return "半碼"
    if abs(quarters - round(quarters)) < 1e-9:
        return f"{int(round(quarters))} 碼"
    return f"{step:g} 個百分點"


def is_change(decision: dict) -> bool:
    return (decision["rate"]["action"] != "hold"
            or decision.get("reserve") is not None
            or decision.get("credit") is not None)


def headline(decision: dict) -> str:
    rate = decision["rate"]
    if rate["action"] == "hold":
        parts = [f"利率不變（重貼現率 {rate['to']:g}%）"]
    else:
        word = "升息" if rate["action"] == "raise" else "降息"
        parts = [f"{word} {_step_label(rate['step'])}（重貼現率 {rate['from']:g}% → {rate['to']:g}%）"]
    reserve = decision.get("reserve")
    if reserve:
        parts.append(f"存款準備率調{'升' if reserve['action'] == 'raise' else '降'} "
                     f"{reserve['step']:g} 個百分點")
    if decision.get("credit"):
        parts.append("調整房貸信用管制")
    return "台灣央行" + "；".join(parts)


def details(decision: dict) -> list[str]:
    lines = []
    rate = decision["rate"]
    if rate["action"] != "hold" and rate.get("effective"):
        lines.append(f"新利率 {rate['effective']} 起實施")
    reserve = decision.get("reserve")
    if reserve and reserve.get("effective"):
        lines.append(f"存款準備率 {reserve['effective']} 起實施")
    credit = decision.get("credit")
    if credit:
        lines.extend(credit.get("changes") or [])
        lines.append(f"房貸管制 {credit['effective']} 起實施")
    return lines


def decision_status(decision: dict | None, schedule: list[date],
                    now: datetime | None = None) -> dict | None:
    """announced／pending／missing／None，定義與 fomc.decision_status 相同。"""
    now = now or clock.now()
    today = now.date()
    decision = decision or {}

    announced = None
    if decision.get("status") == "ok" and decision.get("date"):
        announced = date.fromisoformat(decision["date"])

    meeting = next((m for m in reversed(schedule) if m <= today), None)
    if meeting is not None and (today - meeting).days > WINDOW_DAYS:
        meeting = None

    if (announced is not None and (today - announced).days <= WINDOW_DAYS
            and (meeting is None or announced >= meeting)):
        return {"state": "announced", "headline": headline(decision),
                "details": details(decision), "change": is_change(decision),
                **decision}

    if meeting is None:
        return None
    if today == meeting and now.time() < ANNOUNCE_BY:
        return {"state": "pending", "meeting": meeting.isoformat()}
    if announced is not None:
        reason = f"最新取得的決議新聞稿是 {decision['date']}，還不是這次會議的"
    else:
        reason = decision.get("reason") or "沒有取得決議新聞稿"
    return {"state": "missing", "meeting": meeting.isoformat(), "reason": reason}


def reconcile_discount(rate: dict[str, Series], decision: dict | None,
                       *, today: date | None = None) -> tuple[dict[str, Series], dict]:
    """貼放利率表還沒補上這次調整時，用決議新聞稿補上生效日那一點。"""
    from .sources import cbc

    result = {"patched": False, "conflict": False}
    if (decision or {}).get("status") != "ok":
        return rate, result
    move = decision["rate"]
    if move["action"] == "hold" or not move.get("effective"):
        return rate, result
    effective = date.fromisoformat(move["effective"])
    changes = rate["changes"]
    if changes.last_date is not None and changes.last_date >= effective:
        recorded = changes.value_on(effective)
        result["conflict"] = recorded is not None and abs(recorded - move["to"]) > 1e-9
        return rate, result
    ordered = [(d, v) for d, v in changes.pairs() if d < effective] + [(effective, move["to"])]
    meta = {"patched_from": {"statement": decision["date"],
                             "effective": effective.isoformat()}}
    result["patched"] = True
    return cbc.rate_series(ordered, meta=meta, today=today), result
