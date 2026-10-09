"""每日快照存檔與期間比對。

存的是「判斷」而不是原始資料：訊號清單、九宮格位置、關鍵讀數。
這樣存檔頁可以回看任一天的結論，總覽頁也能算出「跟上期比什麼變了」。
原始資料本來就在 data/cache，不需要重複存。
"""
from __future__ import annotations

import json
import os
from datetime import date

from . import clock, paths


def _snapshot_path(day: date) -> str:
    return os.path.join(paths.ARCHIVE_DIR, f"{day.isoformat()}.json")


def build_snapshot(ctx: dict, signals: list[dict], summary: dict,
                   scenario_data: dict) -> dict:
    labor = ctx.get("labor") or {}
    inflation = ctx.get("inflation") or {}
    rates = ctx.get("rates") or {}
    growth = ctx.get("growth") or {}

    return {
        "date": clock.today().isoformat(),
        "generated_at": clock.now().isoformat(timespec="seconds"),
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
            # 原本沒有記：2026-09-16 升息之後，「跟昨天比變了什麼」根本不可能比到
            "policy_upper": rates.get("stance", {}).get("policy"),
            "curve_10_2": rates.get("shape", {}).get("slope_10_2"),
            "recession_gauge": growth.get("gauge", {}).get("value"),
            "composite_labor": labor.get("composite", {}).get("value"),
        },
        # 台灣版頭版的「跟上一期比」。2026-10-10 以前的存檔沒有這一段，
        # 所以那之前的存檔不能拿來比台灣——比不了就明講，不當成「沒變」。
        "readings_tw": taiwan_readings(ctx),
        "as_of": {
            "labor": _iso(labor.get("as_of")),
            "inflation": _iso(inflation.get("as_of")),
            "rates": _iso(rates.get("as_of")),
        },
    }


def _iso(value):
    return value.isoformat() if hasattr(value, "isoformat") else value


def _rounded(value, digits: int = 2):
    return None if value is None else round(value, digits)


def taiwan_readings(ctx: dict) -> dict:
    """台灣版頭版盯的讀數。四捨五入後才存：年增率是算出來的，不取位數的話
    同一份資料兩次建置會差在第十幾位小數，被當成「變了」。"""
    tw = ctx.get("taiwan") or {}
    cycle, external = tw.get("cycle") or {}, tw.get("external") or {}
    labour, money, output = tw.get("labour") or {}, tw.get("money") or {}, tw.get("output") or {}
    return {
        "score": _rounded(cycle.get("score"), 0),
        "light": cycle.get("light"),
        "exports_yoy": _rounded(external.get("customs_yoy"), 1),
        "orders_yoy": _rounded(external.get("orders_amount_yoy"), 1),
        "cpi": _rounded(labour.get("cpi_yoy"), 2),
        "unemployment": _rounded(labour.get("unemployment"), 2),
        "policy": _rounded(money.get("policy"), 3),
        "gdp": _rounded(output.get("gdp_growth"), 2),
        "m1b_m2": _rounded(money.get("m1b_m2_spread"), 2),
    }


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
    before = before or clock.today()
    snapshots = [s for s in load_all() if s.get("date") < before.isoformat()]
    return snapshots[-1] if snapshots else None


TAIWAN_LABELS = {
    "score": ("景氣對策信號", "分", 0),
    "exports_yoy": ("出口年增", "%", 1),
    "orders_yoy": ("外銷訂單年增", "%", 1),
    "cpi": ("CPI 年增", "%", 2),
    "unemployment": ("台灣失業率", "%", 2),
    "policy": ("重貼現率", "%", 3),
    "gdp": ("經濟成長率", "%", 2),
    "m1b_m2": ("M1B 減 M2", "pp", 2),
}


def taiwan_changes(readings: dict, prior: dict | None) -> list[dict] | None:
    """台灣讀數跟上一期的差。上一期沒有記台灣讀數時回傳 None——那是「比不了」，
    不是「沒變」，頭版要分開講。"""
    was_all = (prior or {}).get("readings_tw")
    if not was_all:
        return None
    out = []
    if readings.get("light") and was_all.get("light") and readings["light"] != was_all["light"]:
        out.append({"name": "景氣燈號", "text": f'{was_all["light"]}→{readings["light"]}'})
    for key, (name, unit, digits) in TAIWAN_LABELS.items():
        now, was = readings.get(key), was_all.get(key)
        if now is None or was is None or now == was:
            continue
        out.append({"name": name, "unit": unit, "digits": digits,
                    "now": now, "was": was, "change": now - was})
    return out


def reading_changes(current: dict, prior: dict | None) -> list[dict]:
    """關鍵讀數的變化，供總覽頁的『跟上期比什麼變了』。"""
    if not prior:
        return []
    # kind：data＝機構發布、一個月才動一兩次的讀數；market＝每個交易日都在動的價格。
    # 頭版的螢光筆只標 data（見 decision_grade）。2026-08 到 10 月的存檔裡，頁邊有 41/58 天
    # 是黃的，其中 23 天只是殖利率或衰退刻度每天的小波動（10 年期中位數才 0.04 個百分點）
    # ——天天都亮的燈分不出哪一天真的有事。market 仍然留在這份清單裡，存檔頁照列。
    labels = {
        "policy_upper": ("政策利率上緣", "%", 1, "data"),
        "payrolls_3m": ("三月均非農", "千人", 10, "data"),
        "unemployment": ("失業率", "%", 1, "data"),
        "core_pce": ("核心 PCE", "%", 1, "data"),
        "core_cpi": ("核心 CPI", "%", 1, "data"),
        "supercore": ("核心服務除住房", "%", 1, "data"),
        "ten_year": ("10 年期公債", "%", 1, "market"),
        "real_ten_year": ("10 年實質利率", "%", 1, "market"),
        "recession_gauge": ("衰退風險刻度", "", 1, "market"),
    }
    out = []
    for key, (name, unit, divisor, kind) in labels.items():
        now = (current.get("readings") or {}).get(key)
        was = (prior.get("readings") or {}).get(key)
        if now is None or was is None or now == was:
            continue
        out.append({
            "name": name, "unit": unit, "kind": kind,
            "now": now / divisor, "was": was / divisor,
            "change": (now - was) / divisor,
        })
    return out


def decision_grade(changes: list[dict] | None) -> list[dict]:
    """頭版要標出來的讀數變動：機構數據與政策利率。每天都在動的市場價格不算——
    它們在「今日價格」那一段，用綠漲紅跌標，不借螢光筆。"""
    return [c for c in changes or [] if c.get("kind") != "market"]
