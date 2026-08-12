"""市場面對照。

目的不是看盤，而是回答「總經判斷有沒有被市場定價」。所以重點放在
股債相關性、實質利率與股市的關係、波動率的相對位置，而不是報價本身。
"""
from __future__ import annotations

from ..data import Bundle
from ..series import Series, correlation


def _change(s: Series, periods: int):
    prior = s.at(-1 - periods)
    if s.last is None or not prior:
        return None
    return (s.last / prior - 1) * 100


def equities(bundle: Bundle) -> dict:
    rows = []
    for series_id, name in [("SP500", "標普 500"), ("NASDAQCOM", "那斯達克"),
                            ("DJIA", "道瓊工業")]:
        s = bundle[series_id]
        if not s:
            continue
        high = max(s.last_years(1).values) if len(s) > 10 else None
        rows.append({
            "name": name, "value": s.last,
            "chg_1m": _change(s, 21), "chg_3m": _change(s, 63),
            "chg_1y": _change(s, 252), "chg_ytd": _ytd(s),
            "from_high": ((s.last / high - 1) * 100) if (high and s.last) else None,
            "series": s,
        })
    return {"rows": rows, "as_of": bundle["SP500"].last_date}


def _ytd(s: Series):
    if not s.last_date:
        return None
    start = s.value_on(f"{s.last_date.year}-01-02")
    return ((s.last / start - 1) * 100) if start else None


def volatility(bundle: Bundle) -> dict:
    rows = []
    for series_id, name in [("VIXCLS", "VIX 股市"), ("VXNCLS", "那斯達克"),
                            ("OVXCLS", "原油"), ("GVZCLS", "黃金")]:
        s = bundle[series_id]
        if not s:
            continue
        rows.append({
            "name": name, "value": s.last,
            "pct10y": s.percentile_rank(10),
            "avg1y": s.last_years(1).mean(),
            "series": s,
        })
    vix = bundle["VIXCLS"]
    return {
        "rows": rows, "vix": vix.last,
        "vix_series": vix,
        "verdict": ("市場對風險幾乎沒有定價" if vix.last is not None and vix.last < 15
                    else "波動率偏高，市場已在避險" if vix.last is not None and vix.last > 25
                    else "波動率處於常態區間"),
    }


def stock_bond(bundle: Bundle) -> dict:
    """股債相關性。轉正代表通膨主導，債券不再是股票的避險工具。"""
    sp500 = bundle["SP500"]
    ten = bundle["DGS10"]
    if not (sp500 and ten):
        return {}

    sp_returns = sp500.pct_change(1)
    yield_changes = ten.diff(1)

    windows = []
    for years, label in [(1, "近一年"), (3, "近三年"), (10, "近十年")]:
        c = correlation(sp_returns.last_years(years), yield_changes.last_years(years))
        if c is not None:
            windows.append({"label": label, "corr": c})

    latest = windows[0]["corr"] if windows else None
    return {
        "windows": windows,
        "latest": latest,
        "verdict": ("股債同向：通膨主導，債券無法對沖股票" if latest is not None and latest < -0.1
                    else "股債反向：成長主導，債券仍具避險功能" if latest is not None and latest > 0.1
                    else "股債相關性接近零"),
    }


def real_rate_pressure(bundle: Bundle) -> dict:
    """實質利率是估值的分母。實質利率上行而股市不跌，代表估值在承壓。"""
    real10 = bundle["DFII10"]
    sp500 = bundle["SP500"]
    if not (real10 and sp500):
        return {}

    real_chg = None
    if real10.last is not None and real10.at(-64) is not None:
        real_chg = real10.last - real10.at(-64)
    equity_chg = _change(sp500, 63)

    tension = None
    if real_chg is not None and equity_chg is not None:
        if real_chg > 0.25 and equity_chg > 3:
            tension = "實質利率上行但股市仍漲，估值承壓"
        elif real_chg < -0.25 and equity_chg > 3:
            tension = "實質利率下行推升估值，漲勢有支撐"
        elif real_chg > 0.25 and equity_chg < -3:
            tension = "實質利率上行、股市回檔，兩者一致"
        else:
            tension = "實質利率與股市無明顯張力"

    return {
        "real": real10.last, "real_chg_3m": real_chg,
        "equity_chg_3m": equity_chg, "tension": tension,
        "real_series": real10,
    }


def commodities(bundle: Bundle) -> dict:
    rows = []
    for series_id, name, freq in [("DCOILWTICO", "WTI 原油", 21),
                                  ("DCOILBRENTEU", "布蘭特原油", 21),
                                  ("DHHNGSP", "天然氣", 21),
                                  ("PCOPPUSDM", "銅", 1),
                                  ("PALLFNFINDEXM", "全球商品指數", 1)]:
        s = bundle[series_id]
        if not s:
            continue
        rows.append({
            "name": name, "value": s.last,
            "chg_1m": _change(s, freq),
            "chg_1y": _change(s, freq * 12 if freq > 1 else 12),
            "series": s,
        })
    return {"rows": rows}


def crypto(bundle: Bundle) -> dict:
    rows = []
    for series_id, name in [("CBBTCUSD", "比特幣"), ("CBETHUSD", "以太幣")]:
        s = bundle[series_id]
        if not s:
            continue
        rows.append({
            "name": name, "value": s.last,
            "chg_1m": _change(s, 21), "chg_1y": _change(s, 252),
            "series": s,
        })
    return {"rows": rows}


def health_checks(bundle: Bundle, vol: dict, sb: dict, rr: dict) -> list[dict]:
    checks = []

    def add(name, state, reading, note=""):
        checks.append({"name": name, "state": state, "reading": reading, "note": note})

    vix = bundle["VIXCLS"]
    if vix.last is not None:
        pct = vix.percentile_rank(10)
        state = "watch" if pct is not None and pct < 15 else "alert" if vix.last > 28 else "normal"
        add("VIX", state, f"{vix.last:.1f}",
            f"十年百分位 {pct:.0f}%" if pct is not None else "")

    if sb.get("latest") is not None:
        value = sb["latest"]
        state = "alert" if value < -0.2 else "watch" if value < 0 else "normal"
        add("股債相關性（近一年）", state, f"{value:+.2f}", sb["verdict"])

    if rr.get("real_chg_3m") is not None:
        value = rr["real_chg_3m"]
        state = "watch" if value > 0.3 else "normal"
        add("10年實質利率近三月變動", state, f"{value:+.2f}%", rr.get("tension", ""))

    sp500 = bundle["SP500"]
    if sp500.last is not None:
        high = max(sp500.last_years(1).values)
        drawdown = (sp500.last / high - 1) * 100
        state = "alert" if drawdown < -15 else "watch" if drawdown < -7 else "normal"
        add("標普距一年高點", state, f"{drawdown:+.1f}%",
            "已進入修正區間" if drawdown < -10 else "")

    hy = bundle["BAMLH0A0HYM2"]
    if hy.last is not None and vix.last is not None:
        pct_hy = hy.percentile_rank(10)
        pct_vix = vix.percentile_rank(10)
        if pct_hy is not None and pct_vix is not None:
            gap = pct_hy - pct_vix
            state = "watch" if abs(gap) > 30 else "normal"
            add("信用 vs 股市風險定價", state, f"差 {gap:+.0f} 個百分位",
                "信用市場比股市更緊張" if gap > 30
                else "股市比信用市場更緊張" if gap < -30
                else "兩個市場定價一致")

    return checks


def compute(bundle: Bundle) -> dict:
    vol = volatility(bundle)
    sb = stock_bond(bundle)
    rr = real_rate_pressure(bundle)
    return {
        "as_of": bundle["SP500"].last_date,
        "equities": equities(bundle),
        "volatility": vol,
        "stock_bond": sb,
        "real_rate": rr,
        "commodities": commodities(bundle),
        "crypto": crypto(bundle),
        "checks": health_checks(bundle, vol, sb, rr),
    }
