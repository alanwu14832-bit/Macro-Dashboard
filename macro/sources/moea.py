"""台灣：經濟部統計處。

外銷訂單**金額**。國發會景氣指標裡的「外銷訂單動向指數」是廠商家數的擴散
指數（看增家數多還是看減家數多），兩者是不同的東西：少數大廠的巨額訂單會
推高金額，卻不會推高動向指數。台股法人看的是金額。

單位寫在每一列裡。單位欄對不上預期（例如從百萬美元改成千美元）時丟掉那一
列，不照數字硬收——差一千倍的數字畫在同一條線上不會報錯。
"""
from __future__ import annotations

import csv
import io
import re

from ..http import get
from ..series import Series
from . import datagov

DATASET_EXPORT_ORDERS = 6845
EXPORT_ORDERS_CSV = "https://service.moea.gov.tw/EE520/opendata/b.csv"

_PERIOD = re.compile(r"^(\d{3})(\d{2})$")


def _iso(raw: str) -> str | None:
    """民國年月 '11507' -> '2026-07-01'。"""
    m = _PERIOD.match(raw.strip())
    if not m:
        return None
    month = int(m.group(2))
    if not 1 <= month <= 12:
        return None
    return f"{int(m.group(1)) + 1911:04d}-{month:02d}-01"


def _empty() -> dict[str, Series]:
    return {"usd": Series("TW_EXPORT_ORDERS_USD", [], [], frequency="m"),
            "twd": Series("TW_EXPORT_ORDERS_TWD", [], [], frequency="m")}


def _parse_export_orders(text: str) -> dict[str, Series]:
    usd, twd = [], []
    for row in csv.DictReader(io.StringIO(text.lstrip("﻿"))):
        if (row.get("統計項目") or "").strip() != "外銷訂單金額":
            continue
        when = _iso(row.get("資料期(民國年)") or "")
        if not when:
            continue
        for bucket, value_key, unit_key, unit in (
                (usd, "統計值(美元)", "計量單位(美元)", "百萬美元"),
                (twd, "統計值(新台幣)", "計量單位(新台幣)", "新臺幣億元")):
            if (row.get(unit_key) or "").strip() != unit:
                continue
            try:
                bucket.append((when, float((row.get(value_key) or "").replace(",", ""))))
            except ValueError:
                continue

    out = _empty()
    if usd:
        out["usd"] = Series.from_pairs("TW_EXPORT_ORDERS_USD", usd,
                                       label="外銷訂單金額", unit="百萬美元",
                                       frequency="m", source="經濟部統計處")
    if twd:
        out["twd"] = Series.from_pairs("TW_EXPORT_ORDERS_TWD", twd,
                                       label="外銷訂單金額", unit="新臺幣億元",
                                       frequency="m", source="經濟部統計處")
    return out


def export_orders(*, ttl: float = 24 * 3600) -> dict[str, Series]:
    try:
        target = datagov.download_url(DATASET_EXPORT_ORDERS, ext=".csv",
                                      fallback=EXPORT_ORDERS_CSV, ttl=ttl)
        return _parse_export_orders(get(target, ttl=ttl, namespace="moea",
                                        timeout=60))
    except Exception:
        return _empty()
