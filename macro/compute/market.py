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


VIX_LOW, VIX_HIGH = 15.0, 25.0
# 連續幾個交易日在門檻同一側才算換邊。回放 2026-10 以前的 60 個交易日：
# 只看當天翻 14 次、3 天翻 6 次、5 天（一週）翻 0 次；近 250 個交易日是 20／8／2 次。
PERSIST_DAYS = 5


def persistent_side(series, threshold: float, days: int = PERSIST_DAYS) -> str | None:
    """最近一次「連續 days 個交易日都在門檻同一側」是哪一側："below" 或 "above"。

    門檻設在讀數平常就在晃的地方時，只看最新一天會天天翻面：2026 年 8 到 9 月
    VIX 貼著 15 上下 0.7 點，「波動率低檔」這條訊號 58 天裡進出了 10 次，
    佔全部訊號變動的四成——那是門檻在雜訊裡，不是風險定價在變。
    改成要連續 days 天站在同一側才算換邊；中間來回的日子維持上一次的狀態。
    不需要另外存狀態：往回找最近一段連續 days 天同側的就是答案。
    """
    side, run = None, 0
    for value in reversed(series.values):
        now = "below" if value <= threshold else "above"
        if now == side:
            run += 1
        else:
            side, run = now, 1
        if run >= days:
            return side
    return None


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
    low = persistent_side(vix, VIX_LOW) == "below" if vix else False
    high = persistent_side(vix, VIX_HIGH) == "above" if vix else False
    return {
        "rows": rows, "vix": vix.last,
        "vix_series": vix,
        "vix_low": low, "vix_high": high,
        # 只描述隱含波動在哪裡。它便不便宜要跟實際波動比，本站沒有那項比較，
        # 所以不寫「風險定價不足」「市場已在避險」這類替市場下的結論。
        "verdict": (f"VIX 連續 {PERSIST_DAYS} 個交易日在 {VIX_LOW:.0f} 以下，隱含波動處於低檔" if low
                    else f"VIX 連續 {PERSIST_DAYS} 個交易日在 {VIX_HIGH:.0f} 以上，隱含波動偏高" if high
                    else "波動率處於常態區間"),
    }


def stock_bond(bundle: Bundle) -> dict:
    """股債相關性：標普報酬對 10 年殖利率變動。負值＝殖利率升的日子股票多半跌（股債同向）。
    只描述兩者一起動的程度；為什麼同向，相關係數自己答不出來。"""
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
        "verdict": ("股債同向：殖利率上升的日子股票多半下跌，債券對股票的對沖效果較差"
                    if latest is not None and latest < -0.1
                    else "股債反向：殖利率下跌的日子股票多半下跌，債券有對沖效果"
                    if latest is not None and latest > 0.1
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


def net_liquidity(bundle: Bundle) -> dict:
    """聯準會淨流動性 = 總資產 − 財政部帳戶 − 隔夜逆回購。

    三項都是聯準會與財政部的公開數字。邏輯：QT 縮表抽走的錢，可能被
    TGA 下降或逆回購資金回流抵銷——單看縮表會誤判，要看淨額。
    以 WALCL 的週頻日期為準對齊另外兩檔（value_on 取當日或之前最近值）。
    """
    walcl = bundle["WALCL"]          # 百萬美元
    tga = bundle["WTREGEN"]          # 百萬美元（FRED 檔名沿用舊版，實測是百萬）
    rrp = bundle["RRPONTSYD"]        # 十億美元
    if not (walcl and tga and rrp):
        return {}

    # 單位防呆：TGA 頂多兩兆（= 2,000 十億），讀到超過兩萬一定是百萬計。
    # 曾經因為目錄標籤寫錯單位，淨流動性算出 -90 兆——量級檢查比標籤可信。
    def to_billion(v: float) -> float:
        return v / 1000.0 if abs(v) > 20_000 else v

    dates, values = [], []
    for d, v in walcl.last_years(4).pairs():
        t, r = tga.value_on(d), rrp.value_on(d)
        if t is None or r is None:
            continue
        dates.append(d)
        values.append(v / 1000.0 - to_billion(t) - to_billion(r))   # 十億美元
    if not dates:
        return {}

    s = Series("NETLIQ", dates, values, label="淨流動性",
               unit="十億美元", frequency="w")
    prior_3m = s.at(-14)                            # 週頻，約 13 週前
    prior_1y = s.at(-53)
    return {
        "series": s, "latest": s.last, "as_of": s.last_date,
        "chg_3m": (s.last - prior_3m) if prior_3m is not None else None,
        "chg_1y": (s.last - prior_1y) if prior_1y is not None else None,
        "walcl": walcl.last / 1000.0 if walcl.last else None,
        "tga": tga.last, "rrp": rrp.last,
    }


# 風險胃納的組成與權重。全部寫死：同一份資料永遠算出同一個分數。
# 每一項都轉成 0–100 的「風險偏好分數」，高 = 貪婪、低 = 恐慌。
RISK_WEIGHTS = [("vix", 0.30), ("credit", 0.30), ("dollar", 0.20), ("stock_bond", 0.20)]


def risk_appetite(bundle: Bundle, sb: dict) -> dict:
    """把散在各處的風險定價收斂成一個刻度。

    VIX 與高收益利差取十年百分位反轉（利差低 = 市場不擔心違約 = 偏貪婪）；
    美元取近三月變化的十年百分位反轉（美元急升 = 避險資金流 = 偏恐慌）；
    股債相關性直接線性映射（正相關 = 成長主導 = 風險偏好有支撐）。
    """
    parts = []

    vix = bundle["VIXCLS"]
    if vix.last is not None:
        pct = vix.percentile_rank(10)
        if pct is not None:
            parts.append({"key": "vix", "name": "VIX 波動率",
                          "reading": f"{vix.last:.1f}", "score": 100.0 - pct})

    hy = bundle["BAMLH0A0HYM2"]
    if hy.last is not None:
        pct = hy.percentile_rank(10)
        if pct is not None:
            parts.append({"key": "credit", "name": "高收益利差",
                          "reading": f"{hy.last:.2f}%", "score": 100.0 - pct})

    dxy = bundle["DTWEXBGS"]
    if dxy:
        chg = dxy.pct_change(63)                    # 近三月變化的歷史分布
        pct = chg.percentile_rank(10)
        if pct is not None and chg.last is not None:
            parts.append({"key": "dollar", "name": "美元近三月",
                          "reading": f"{chg.last:+.1f}%", "score": 100.0 - pct})

    if sb.get("latest") is not None:
        corr = sb["latest"]
        parts.append({"key": "stock_bond", "name": "股債相關性",
                      "reading": f"{corr:+.2f}",
                      "score": max(0.0, min(100.0, 50.0 + corr * 100.0))})

    weights = dict(RISK_WEIGHTS)
    total_w = sum(weights[p["key"]] for p in parts)
    if not parts or total_w == 0:
        return {}
    score = sum(p["score"] * weights[p["key"]] for p in parts) / total_w

    label = ("恐慌" if score < 25 else "謹慎" if score < 45
             else "中性" if score < 55 else "樂觀" if score < 75 else "貪婪")
    return {"score": score, "label": label, "parts": parts}


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
        "liquidity": net_liquidity(bundle),
        "risk": risk_appetite(bundle, sb),
        "commodities": commodities(bundle),
        "crypto": crypto(bundle),
        "checks": health_checks(bundle, vol, sb, rr),
    }
