"""LBMA 官方金銀定盤價。

FRED 的黃金序列（GOLDPMGBD228NLBM 等）已於 2023 年停更，Stooq 現在擋
非瀏覽器存取，所以直接接倫敦金銀市場協會自己的公開 JSON。

格式：[{"d": "2026-08-11", "v": [USD, GBP, EUR]}, ...]
"""
from __future__ import annotations

from ..http import get_json
from ..series import Series

ENDPOINTS = {
    "gold": ("https://prices.lbma.org.uk/json/gold_pm.json", "黃金", "美元/盎司"),
    "silver": ("https://prices.lbma.org.uk/json/silver.json", "白銀", "美元/盎司"),
}


def price(metal: str, *, ttl: float = 12 * 3600) -> Series:
    url, label, unit = ENDPOINTS[metal]
    try:
        payload = get_json(url, ttl=ttl, namespace="lbma", timeout=60)
    except Exception:
        return Series(metal.upper(), [], [], label=label, unit=unit, frequency="d")

    pairs = []
    for row in payload or []:
        date = row.get("d")
        values = row.get("v") or []
        if not date or not values:
            continue
        usd = values[0]
        if usd in (None, 0):
            continue
        try:
            pairs.append((date, float(usd)))
        except (TypeError, ValueError):
            continue
    return Series.from_pairs(metal.upper(), pairs, label=label, unit=unit,
                             frequency="d", source="LBMA")


def load() -> dict[str, Series]:
    return {name: price(name) for name in ENDPOINTS}
