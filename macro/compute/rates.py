"""利率、殖利率曲線與信用。

比參考站多做的：完整 11 個期限的曲線快照與三個月前對照、長端拆解成
實質利率＋通膨補償＋期限溢酬（期限溢酬用 10 年名目減去預期短率路徑近似）、
曲線形態自動分類（牛陡／熊平…）、以及金融情勢的百分位定位。
"""
from __future__ import annotations

from ..data import Bundle
from ..sources import fomc_text
from ..series import Series

CURVE = [
    ("DGS1MO", "1M", 1 / 12), ("DGS3MO", "3M", 0.25), ("DGS6MO", "6M", 0.5),
    ("DGS1", "1Y", 1), ("DGS2", "2Y", 2), ("DGS3", "3Y", 3), ("DGS5", "5Y", 5),
    ("DGS7", "7Y", 7), ("DGS10", "10Y", 10), ("DGS20", "20Y", 20), ("DGS30", "30Y", 30),
]

SPREADS = [
    ("BAMLC0A1CAAA", "AAA"), ("BAMLC0A0CM", "投資級"),
    ("BAMLC0A4CBBB", "BBB"), ("BAMLH0A0HYM2", "高收益"),
    ("BAMLEMCBPIOAS", "新興市場"),
]


def yield_curve(bundle: Bundle) -> dict:
    """目前曲線、一個月前、三個月前、一年前，以及各點變動。"""
    rows = []
    for series_id, name, tenor in CURVE:
        s = bundle[series_id]
        if not s:
            continue
        now = s.last
        # 交易日序列：用日曆回推再取當日或之前最近一筆
        month_ago = _lookback(s, 21)
        quarter_ago = _lookback(s, 63)
        year_ago = _lookback(s, 252)
        rows.append({
            "id": series_id, "name": name, "tenor": tenor, "value": now,
            "m1": month_ago, "m3": quarter_ago, "y1": year_ago,
            "chg_1m": (now - month_ago) if (now is not None and month_ago is not None) else None,
            "chg_3m": (now - quarter_ago) if (now is not None and quarter_ago is not None) else None,
            "chg_1y": (now - year_ago) if (now is not None and year_ago is not None) else None,
        })
    return {"rows": rows, "as_of": bundle["DGS10"].last_date}


def _lookback(s: Series, periods: int):
    return s.at(-1 - periods)


def curve_shape(bundle: Bundle) -> dict:
    """曲線形態分類：斜率的方向 × 水準的方向。"""
    two, ten, thirty = bundle["DGS2"], bundle["DGS10"], bundle["DGS30"]
    if not (two and ten):
        return {}

    slope = (ten.last or 0) - (two.last or 0)
    slope_3m_ago = ((_lookback(ten, 63) or 0) - (_lookback(two, 63) or 0))
    slope_change = slope - slope_3m_ago
    level_change = (ten.last or 0) - (_lookback(ten, 63) or 0)

    if slope_change > 0.10:
        steepness = "陡化"
    elif slope_change < -0.10:
        steepness = "平坦化"
    else:
        steepness = "形態大致不變"

    if level_change > 0.10:
        direction = "熊"
    elif level_change < -0.10:
        direction = "牛"
    else:
        direction = ""

    label = f"{direction}{steepness}" if direction and steepness != "形態大致不變" else steepness

    return {
        "slope_10_2": slope,
        "slope_10_3m": bundle["T10Y3M"].last,
        "slope_30_10": ((thirty.last or 0) - (ten.last or 0)) if thirty else None,
        "slope_change_3m": slope_change,
        "level_change_3m": level_change,
        "label": label,
        "inverted": slope < 0,
        "slope_series": bundle["T10Y2Y"],
        "slope_3m_series": bundle["T10Y3M"],
    }


def long_end_decomposition(bundle: Bundle) -> dict:
    """長端利率＝實質利率 ＋ 通膨補償；再看期限溢酬佔多少。

    期限溢酬用 10 年名目減 2 年名目的一部分近似不夠嚴謹，這裡改用
    10 年名目 − （政策利率 + 通膨補償調整）的殘差，並標明是近似值。
    """
    ten = bundle["DGS10"]
    real10 = bundle["DFII10"]
    breakeven = bundle["T10YIE"]
    thirty = bundle["DGS30"]
    real30 = bundle["DFII30"]
    policy = bundle["DFEDTARU"]

    nominal = ten.last
    real = real10.last
    inflation_comp = breakeven.last

    # 期限溢酬近似：10 年實質利率 − 短期實質利率（政策利率減通膨補償）
    term_premium = None
    if real is not None and policy and policy.last is not None and inflation_comp is not None:
        short_real = policy.last - inflation_comp
        term_premium = real - short_real

    return {
        "nominal": nominal, "real": real, "inflation_comp": inflation_comp,
        "term_premium": term_premium,
        "nominal_30": thirty.last, "real_30": real30.last,
        "policy": policy.last if policy else None,
        "real_series": real10, "breakeven_series": breakeven,
        "nominal_series": ten,
        "chg_1m": (nominal - _lookback(ten, 21)) if (nominal is not None and _lookback(ten, 21) is not None) else None,
        "chg_3m": (nominal - _lookback(ten, 63)) if (nominal is not None and _lookback(ten, 63) is not None) else None,
        "real_chg_3m": (real - _lookback(real10, 63)) if (real is not None and _lookback(real10, 63) is not None) else None,
        "be_chg_3m": (inflation_comp - _lookback(breakeven, 63))
                     if (inflation_comp is not None and _lookback(breakeven, 63) is not None) else None,
    }


def credit(bundle: Bundle) -> dict:
    """信用利差與其歷史百分位 — 壓力已經反映多少。"""
    rows = []
    for series_id, name in SPREADS:
        s = bundle[series_id]
        if not s:
            continue
        rows.append({
            "id": series_id, "name": name, "value": s.last,
            "chg_1m": (s.last - _lookback(s, 21)) if (s.last is not None and _lookback(s, 21) is not None) else None,
            "chg_3m": (s.last - _lookback(s, 63)) if (s.last is not None and _lookback(s, 63) is not None) else None,
            "pct10y": s.percentile_rank(10),
            "z10y": s.zscore(10),
            "series": s,
        })
    hy = bundle["BAMLH0A0HYM2"]
    return {
        "rows": rows,
        "hy_series": hy,
        "ig_series": bundle["BAMLC0A0CM"],
        "verdict": _credit_verdict(rows),
    }


def _credit_verdict(rows: list[dict]) -> str:
    ranks = [r["pct10y"] for r in rows if r["pct10y"] is not None]
    if not ranks:
        return "資料不足"
    avg = sum(ranks) / len(ranks)
    if avg < 20:
        return "利差處在十年低檔，市場幾乎沒有反映壓力"
    if avg < 40:
        return "利差偏低，壓力反映有限"
    if avg < 60:
        return "利差在十年中位附近"
    if avg < 80:
        return "利差偏高，市場已反映一定壓力"
    return "利差處在十年高檔，壓力反映充分"


def financial_conditions(bundle: Bundle) -> dict:
    nfci = bundle["NFCI"]
    anfci = bundle["ANFCI"]
    stlfsi = bundle["STLFSI4"]
    return {
        "nfci": nfci.last, "anfci": anfci.last, "stlfsi": stlfsi.last,
        "nfci_pct": nfci.percentile_rank(10),
        "nfci_series": nfci,
        "verdict": ("金融情勢偏寬鬆" if nfci.last is not None and nfci.last < 0
                    else "金融情勢偏緊" if nfci.last is not None else "資料不足"),
    }


def policy_stance(bundle: Bundle) -> dict:
    """政策利率相對通膨的實質水準，以及市場定價的方向。"""
    policy = bundle["DFEDTARU"]
    core_pce = bundle["PCEPILFE"].yoy()
    two = bundle["DGS2"]

    real_policy = None
    if policy and policy.last is not None and core_pce and core_pce.last is not None:
        real_policy = policy.last - core_pce.last

    # 2 年期低於政策利率＝市場定價未來降息；高於＝定價升息
    market_gap = None
    if two and two.last is not None and policy and policy.last is not None:
        market_gap = two.last - policy.last

    return {
        "policy": policy.last if policy else None,
        "policy_lower": bundle["DFEDTARL"].last,
        "effective": bundle["DFF"].last,
        "sofr": bundle["SOFR"].last,
        "real_policy": real_policy,
        "market_gap": market_gap,
        "market_implies": ("市場定價未來一至二年降息" if market_gap is not None and market_gap < -0.15
                           else "市場定價未來一至二年升息" if market_gap is not None and market_gap > 0.15
                           else "市場定價政策大致不動"),
        "policy_series": policy,
        "two_series": two,
        "balance_sheet": bundle["WALCL"].last,
        "balance_sheet_series": bundle["WALCL"],
        "balance_chg_1y": bundle["WALCL"].change_over(52) if bundle["WALCL"] else None,
        "rrp": bundle["RRPONTSYD"].last,
        "tga": bundle["WTREGEN"].last,
    }


def health_checks(bundle: Bundle, shape: dict, decomp: dict,
                  credit_data: dict, fci: dict, stance: dict) -> list[dict]:
    checks = []

    def add(name, state, reading, note=""):
        checks.append({"name": name, "state": state, "reading": reading, "note": note})

    if shape.get("slope_10_2") is not None:
        slope = shape["slope_10_2"]
        state = "alert" if slope < 0 else "watch" if slope < 0.3 else "normal"
        add("10年減2年利差", state, f"{slope:+.2f}%",
            "曲線倒掛" if slope < 0 else "曲線正斜率")

    if shape.get("slope_10_3m") is not None:
        slope = shape["slope_10_3m"]
        state = "alert" if slope < 0 else "watch" if slope < 0.5 else "normal"
        add("10年減3個月利差", state, f"{slope:+.2f}%",
            "最可靠的衰退領先指標之一" if slope < 0 else "未發出衰退訊號")

    if decomp.get("real") is not None:
        real = decomp["real"]
        state = "alert" if real > 2.5 else "watch" if real > 1.8 else "normal"
        add("10年實質利率", state, f"{real:.2f}%",
            "實質利率偏高，對估值構成壓力" if real > 1.8 else "實質利率溫和")

    if decomp.get("term_premium") is not None:
        premium = decomp["term_premium"]
        state = "alert" if premium > 1.5 else "watch" if premium > 0.8 else "normal"
        add("期限溢酬（近似）", state, f"{premium:+.2f}%",
            "長端要求更高補償＝供給壓力" if premium > 0.8 else "長端補償要求不高")

    hy = next((r for r in credit_data["rows"] if r["name"] == "高收益"), None)
    if hy and hy["value"] is not None:
        state = "alert" if hy["value"] > 5.0 else "watch" if hy["value"] > 3.5 else "normal"
        add("高收益利差", state, f"{hy['value']:.2f}%",
            f"十年百分位 {hy['pct10y']:.0f}%" if hy["pct10y"] is not None else "")

    if fci.get("nfci") is not None:
        state = "alert" if fci["nfci"] > 0.5 else "watch" if fci["nfci"] > 0 else "normal"
        add("金融情勢指數", state, f"{fci['nfci']:+.2f}", fci["verdict"])

    if stance.get("real_policy") is not None:
        real = stance["real_policy"]
        state = "watch" if real < 0.5 else "normal" if real < 2.5 else "alert"
        add("實質政策利率", state, f"{real:+.2f}%",
            "政策仍具限制性" if real > 1.0 else "政策接近中性或偏寬鬆")

    if stance.get("market_gap") is not None:
        add("2年期 vs 政策利率", "normal", f"{stance['market_gap']:+.2f}%",
            stance["market_implies"])

    return checks


def compute(bundle: Bundle) -> dict:
    curve = yield_curve(bundle)
    shape = curve_shape(bundle)
    decomp = long_end_decomposition(bundle)
    credit_data = credit(bundle)
    fci = financial_conditions(bundle)
    stance = policy_stance(bundle)
    return {
        "as_of": bundle["DGS10"].last_date,
        "curve": curve,
        "shape": shape,
        "decomposition": decomp,
        "credit": credit_data,
        "conditions": fci,
        "stance": stance,
        "statement": fomc_text.compare(),
        "mortgage": bundle["MORTGAGE30US"].last,
        "mortgage_series": bundle["MORTGAGE30US"],
        "checks": health_checks(bundle, shape, decomp, credit_data, fci, stance),
    }
