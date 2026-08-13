"""把序列資料另外輸出成 JSON，讓前端能自行取用。

這是「動態化」的基礎：頁面不再是資料的唯一出口，瀏覽器可以按需要抓
任一檔序列，做自己的比較與轉換，不必等下一次建置。

只輸出中繼資料，不輸出序列本身：

  /api/catalogue.json   全部序列的中繼資料（約 40 KB，給選單用）
  /api/state.json       目前的判斷與輸入值（機器可讀）

序列資料改由 netlify/functions/series.mjs 即時向 FRED 取。原本試過把
196 檔序列烤成靜態 JSON，共 9.1 MB——問題不在絕對大小，而在每天兩次
建置會讓四十幾檔日資料重寫，一年下來 repo 會膨脹到 GB 等級。而且烤成
靜態檔本質上還是快照，跟「動態」的目的相違。
"""
from __future__ import annotations

import json
import os

from .. import catalogue, paths
from ..data import Bundle

API_DIR = os.path.join(paths.SITE_DIR, "api")
SERIES_DIR = os.path.join(API_DIR, "series")

# 序列所屬的分組，決定前端選單的分類
GROUP_LABELS = {
    "labor": "勞動市場", "inflation": "通膨", "rates": "利率與信用",
    "debt": "債務與財政", "growth": "成長與消費", "global": "全球與匯率",
    "market": "市場", "commodities": "大宗商品", "sectors": "行業別就業",
}


def _group_of(series_id: str) -> str:
    for name, group in catalogue.ALL_GROUPS.items():
        if series_id in group:
            return name
    if series_id in catalogue.LABOR_SECTORS:
        return "sectors"
    return "other"


def _write(path: str, payload) -> int:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return len(text.encode("utf-8"))


def _round(value: float) -> float:
    """四捨五入到 6 位有效數字左右，砍掉浮點雜訊帶來的檔案體積。"""
    if value == 0:
        return 0.0
    rounded = round(value, 6)
    return int(rounded) if rounded == int(rounded) and abs(rounded) < 1e15 else rounded


def write_series(bundle: Bundle) -> dict:
    """序列目錄。實際資料由 /api/series function 即時提供。"""
    entries, total_bytes = [], 0

    for series_id, series in sorted(bundle.series.items()):
        if not series:
            continue
        group = _group_of(series_id)
        entries.append({
            "id": series_id,
            "name": series.label,
            "unit": series.unit,
            "freq": series.frequency,
            "group": group,
            "group_label": GROUP_LABELS.get(group, "其他"),
            "n": len(series),
            "start": series.first_date.isoformat() if series.first_date else None,
            "last": series.last_date.isoformat() if series.last_date else None,
            "value": _round(series.last) if series.last is not None else None,
            # 建置當下的值，讓選單不必等 function 就能顯示概況
            "prev": _round(series.at(-2)) if series.at(-2) is not None else None,
        })

    total_bytes += _write(os.path.join(API_DIR, "catalogue.json"), {
        "count": len(entries),
        "groups": [{"key": k, "label": v} for k, v in GROUP_LABELS.items()],
        "series": entries,
    })
    return {"count": len(entries), "bytes": total_bytes}


def write_readings(ctx: dict, signals: list[dict], summary: dict,
                   scenario_data: dict) -> int:
    """目前判斷的機器可讀版本。

    給前端（以及任何想接這個站的人）一個不必解析 HTML 就能拿到結論的出口。
    """
    labor = ctx.get("labor") or {}
    inflation = ctx.get("inflation") or {}
    rates = ctx.get("rates") or {}

    return _write(os.path.join(API_DIR, "state.json"), {
        "scenario": {
            "name": scenario_data.get("name"),
            "employment": scenario_data.get("employment_label"),
            "inflation": scenario_data.get("inflation_label"),
            "regime": scenario_data.get("regime_label"),
            "lean": scenario_data.get("lean"),
            "score": (scenario_data.get("employment_detail") or {}).get("score"),
        },
        "bands": scenario_data.get("bands"),
        "signals": [{k: s.get(k) for k in
                     ("key", "headline", "why", "evidence", "direction",
                      "severity", "module")} for s in signals],
        "summary": summary,
        "inputs": {
            "payrolls_3m": (labor.get("payrolls") or {}).get("avg3"),
            "breakeven": (labor.get("breakeven") or {}).get("value"),
            "unrate_gap": (labor.get("unemployment") or {}).get("gap_from_low"),
            "prime_epop_change": (labor.get("participation") or {}).get("prime_epop_change"),
            "core_pce": (inflation.get("headline") or {}).get("core_pce"),
            "core_pce_3m": (inflation.get("momentum") or {}).get("core_pce_3m"),
            "expectations_5y5y": (inflation.get("expectations") or {}).get("t5y5y"),
            "ten_year": (rates.get("decomposition") or {}).get("nominal"),
            "real_ten_year": (rates.get("decomposition") or {}).get("real"),
        },
        "transitions": [{k: t.get(k) for k in ("name", "need", "gap", "unit")}
                        for t in (scenario_data.get("transitions") or [])],
    })
