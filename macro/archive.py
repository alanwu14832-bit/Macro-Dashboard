"""每日快照存檔與期間比對。

存的是「判斷」而不是原始資料：訊號清單、九宮格位置、關鍵讀數。
這樣存檔頁可以回看任一天的結論，總覽頁也能算出「跟上期比什麼變了」。
原始資料本來就在 data/cache，不需要重複存。
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime

from . import paths


def _snapshot_path(day: date) -> str:
    return os.path.join(paths.ARCHIVE_DIR, f"{day.isoformat()}.json")


def build_snapshot(ctx: dict, signals: list[dict], summary: dict,
                   scenario_data: dict) -> dict:
    labor = ctx.get("labor") or {}
    inflation = ctx.get("inflation") or {}
    rates = ctx.get("rates") or {}
    growth = ctx.get("growth") or {}

    return {
        "date": date.today().isoformat(),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "signals": [{k: s[k] for k in ("key", "headline", "direction", "severity",
                                       "evidence", "module")} for s in signals],
        "summary": summary,
        "scenario": {
            "name": scenario_data.get("name"),
            "employment": scenario_data.get("employment_label"),
            "inflation": scenario_data.get("inflation_label"),
            "regime": scenario_data.get("regime_label"),
            "lean": scenario_data.get("lean"),
        },
        "readings": {
            "payrolls_latest": labor.get("payrolls", {}).get("latest"),
            "payrolls_3m": labor.get("payrolls", {}).get("avg3"),
            "breakeven": labor.get("breakeven", {}).get("value"),
            "unemployment": labor.get("unemployment", {}).get("rate"),
            "core_cpi": inflation.get("headline", {}).get("core_cpi"),
            "core_pce": inflation.get("headline", {}).get("core_pce"),
            "supercore": inflation.get("supercore", {}).get("yoy"),
            "ten_year": rates.get("decomposition", {}).get("nominal"),
            "real_ten_year": rates.get("decomposition", {}).get("real"),
            "curve_10_2": rates.get("shape", {}).get("slope_10_2"),
            "recession_gauge": growth.get("gauge", {}).get("value"),
            "composite_labor": labor.get("composite", {}).get("value"),
        },
        "as_of": {
            "labor": _iso(labor.get("as_of")),
            "inflation": _iso(inflation.get("as_of")),
            "rates": _iso(rates.get("as_of")),
        },
    }


def _iso(value):
    return value.isoformat() if hasattr(value, "isoformat") else value


def save(snapshot: dict) -> str:
    path = _snapshot_path(date.fromisoformat(snapshot["date"]))
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(snapshot, fh, ensure_ascii=False, indent=1)
    return path


def load_all() -> list[dict]:
    out = []
    for name in sorted(os.listdir(paths.ARCHIVE_DIR)):
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(paths.ARCHIVE_DIR, name), encoding="utf-8") as fh:
                out.append(json.load(fh))
        except Exception:
            continue
    return out


def previous(before: date | None = None) -> dict | None:
    """最近一次「與今天不同」的快照 — 用來做期間比對。"""
    before = before or date.today()
    snapshots = [s for s in load_all() if s.get("date") < before.isoformat()]
    return snapshots[-1] if snapshots else None


def reading_changes(current: dict, prior: dict | None) -> list[dict]:
    """關鍵讀數的變化，供總覽頁的『跟上期比什麼變了』。"""
    if not prior:
        return []
    labels = {
        "payrolls_3m": ("三月均非農", "千人", 10),
        "unemployment": ("失業率", "%", 1),
        "core_pce": ("核心 PCE", "%", 1),
        "core_cpi": ("核心 CPI", "%", 1),
        "supercore": ("核心服務除住房", "%", 1),
        "ten_year": ("10 年期公債", "%", 1),
        "real_ten_year": ("10 年實質利率", "%", 1),
        "recession_gauge": ("衰退風險刻度", "", 1),
    }
    out = []
    for key, (name, unit, divisor) in labels.items():
        now = (current.get("readings") or {}).get(key)
        was = (prior.get("readings") or {}).get(key)
        if now is None or was is None or now == was:
            continue
        out.append({
            "name": name, "unit": unit,
            "now": now / divisor, "was": was / divisor,
            "change": (now - was) / divisor,
        })
    return out
