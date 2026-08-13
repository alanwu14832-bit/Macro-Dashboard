"""公債標售行事曆（TreasuryDirect 官方 API，免金鑰）。

長天期標售的結果會直接反映在殖利率上——需求疲弱的 30 年期標售能在
當天推升整條曲線的長端。所以標售日是總經行事曆上真正的事件，不是
行政瑣事。

只取未來的標售，並且只留 2 年期以上：短天期國庫券每週都標，列出來
只會淹沒真正重要的那幾場。
"""
from __future__ import annotations

from datetime import date, datetime

from ..http import get_json

UPCOMING = "https://www.treasurydirect.gov/TA_WS/securities/upcoming?format=json"

# 天期 → 中文名。只列這些，其餘（13-Week 之類的例行國庫券）不顯示。
TERMS = {
    "2-Year": "2 年期", "3-Year": "3 年期", "5-Year": "5 年期",
    "7-Year": "7 年期", "10-Year": "10 年期", "20-Year": "20 年期",
    "30-Year": "30 年期",
}


def _parse(raw: str) -> date | None:
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "")).date()
    except (ValueError, TypeError):
        return None


def upcoming(*, days: int = 21, ttl: float = 6 * 3600) -> list[dict]:
    """未來 N 天內的中長天期標售。"""
    try:
        rows = get_json(UPCOMING, ttl=ttl, namespace="treasury",
                        timeout=30, retries=2)
    except Exception:
        return []

    today = date.today()
    out = {}
    for row in rows or []:
        term = str(row.get("securityTerm", ""))
        label = next((v for k, v in TERMS.items() if term.startswith(k)), None)
        if not label:
            continue
        when = _parse(row.get("auctionDate") or row.get("issueDate"))
        if not when or not (0 <= (when - today).days <= days):
            continue
        kind = str(row.get("securityType", ""))
        key = (when, label, kind)
        if key in out:
            continue
        out[key] = {
            "date": when, "days": (when - today).days,
            "term": label, "type": {"Note": "中期公債", "Bond": "長期公債",
                                    "TIPS": "抗通膨債", "FRN": "浮動利率"}.get(kind, kind),
        }
    return sorted(out.values(), key=lambda r: (r["date"], r["term"]))
