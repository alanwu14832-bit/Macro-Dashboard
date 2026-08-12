"""成長、消費、住宅與信用循環。

參考站沒有這一塊。放進來的理由：九宮格只看就業與通膨，會漏掉「成長正在
從哪裡漏氣」；信用違約率與放款標準是勞動市場惡化的上游。
"""
from __future__ import annotations

from ..data import Bundle
from ..series import Series

RECESSION_INPUTS = [
    ("T10Y3M", "殖利率曲線 10Y-3M", -1),   # 負值＝倒掛＝風險高
    ("SAHMREALTIME", "Sahm 法則", 1),
    ("IC4WSA", "初領失業金", 1),
    ("NFCI", "金融情勢", 1),
    ("PERMIT", "建築許可", -1),
]


def activity(bundle: Bundle) -> dict:
    gdp = bundle["GDPC1"]
    return {
        "gdp_qoq": bundle["A191RL1Q225SBEA"].last,
        "gdp_yoy": gdp.yoy().last if gdp else None,
        "gdp_series": gdp.yoy() if gdp else Series("", [], []),
        "gdp_as_of": gdp.last_date,
        "indpro": bundle["INDPRO"].yoy().last,
        "indpro_series": bundle["INDPRO"].yoy(),
        "capacity": bundle["TCU"].last,
        "retail_yoy": bundle["RRSFS"].yoy().last,
        "retail_series": bundle["RRSFS"].yoy(),
        "consumption_yoy": bundle["PCEC96"].yoy().last,
        "income_yoy": bundle["DSPIC96"].yoy().last,
        "savings": bundle["PSAVERT"].last,
        "savings_series": bundle["PSAVERT"],
        "sentiment": bundle["UMCSENT"].last,
        "sentiment_series": bundle["UMCSENT"],
        "capex_orders_yoy": bundle["NEWORDER"].yoy().last,
        "investment_yoy": bundle["GPDIC1"].yoy().last,
    }


def housing(bundle: Bundle) -> dict:
    starts = bundle["HOUST"]
    permits = bundle["PERMIT"]
    return {
        "starts": starts.last, "starts_yoy": starts.yoy().last,
        "permits": permits.last, "permits_yoy": permits.yoy().last,
        "starts_series": starts, "permits_series": permits,
        "mortgage": bundle["MORTGAGE30US"].last,
        "as_of": starts.last_date,
    }


def credit_cycle(bundle: Bundle) -> dict:
    """違約率與放款標準 — 信用循環的位置。"""
    rows = []
    for series_id, name in [("DRCCLACBS", "信用卡"), ("DRSFRMACBS", "住宅房貸"),
                            ("DRBLACBS", "商業放款")]:
        s = bundle[series_id]
        if not s:
            continue
        rows.append({
            "name": name, "value": s.last,
            "chg_1y": s.change_over(4),
            "pct10y": s.percentile_rank(10),
            "series": s,
        })
    standards = bundle["DRTSCILM"]
    return {
        "rows": rows,
        "standards": standards.last,
        "standards_series": standards,
        "loans_yoy": bundle["BUSLOANS"].yoy().last,
        "burden": bundle["TDSP"].last,
        "m2_yoy": bundle["M2SL"].yoy().last,
        "m2_series": bundle["M2SL"].yoy(),
        "as_of": standards.last_date,
    }


def recession_gauge(bundle: Bundle) -> dict:
    """把幾個領先指標合成一個 0-100 的風險刻度。

    每個輸入取 10 年 z 分數，依方向調號，平均後映射到 0-100。
    這是相對定位，不是機率預測 — 標籤上會寫清楚。
    """
    import math
    parts = []
    for series_id, name, sign in RECESSION_INPUTS:
        s = bundle[series_id]
        if not s:
            continue
        z = s.zscore(10)
        if z is None:
            continue
        parts.append({"name": name, "z": z * sign, "raw": s.last})

    if not parts:
        return {"value": None, "rows": []}

    avg = sum(p["z"] for p in parts) / len(parts)
    value = max(0.0, min(100.0, 50 + math.tanh(avg / 1.5) * 50))
    level = ("低" if value < 35 else "中性" if value < 55 else
             "偏高" if value < 75 else "高")
    return {"value": value, "level": level, "rows": parts,
            "sahm": bundle["SAHMREALTIME"].last}


def health_checks(bundle: Bundle, act: dict, credit: dict, gauge: dict) -> list[dict]:
    checks = []

    def add(name, state, reading, note=""):
        checks.append({"name": name, "state": state, "reading": reading, "note": note})

    if act.get("gdp_qoq") is not None:
        value = act["gdp_qoq"]
        state = "alert" if value < 0 else "watch" if value < 1.5 else "normal"
        add("實質 GDP 年化季增", state, f"{value:+.1f}%",
            "低於潛在成長" if value < 1.8 else "高於潛在成長")

    if act.get("retail_yoy") is not None:
        value = act["retail_yoy"]
        state = "alert" if value < -1 else "watch" if value < 1 else "normal"
        add("實質零售銷售年增", state, f"{value:+.1f}%",
            "實質消費在萎縮" if value < 0 else "實質消費仍在成長")

    if act.get("savings") is not None:
        value = act["savings"]
        state = "watch" if value < 4 else "normal"
        add("儲蓄率", state, f"{value:.1f}%",
            "緩衝薄，消費對衝擊敏感" if value < 4 else "仍有緩衝")

    if act.get("sentiment") is not None:
        value = act["sentiment"]
        state = "alert" if value < 60 else "watch" if value < 75 else "normal"
        add("消費者信心", state, f"{value:.0f}", "接近衰退期水準" if value < 60 else "")

    if credit.get("standards") is not None:
        value = credit["standards"]
        state = "alert" if value > 30 else "watch" if value > 10 else "normal"
        add("銀行收緊放款標準比例", state, f"{value:+.0f}%",
            "信用供給在收縮" if value > 10 else "信用供給未收縮")

    for row in credit.get("rows", []):
        if row["value"] is None or row["pct10y"] is None:
            continue
        state = "alert" if row["pct10y"] > 85 else "watch" if row["pct10y"] > 65 else "normal"
        add(f"{row['name']}違約率", state, f"{row['value']:.2f}%",
            f"十年百分位 {row['pct10y']:.0f}%")

    if gauge.get("value") is not None:
        state = "alert" if gauge["value"] > 70 else "watch" if gauge["value"] > 55 else "normal"
        add("衰退風險刻度", state, f"{gauge['value']:.0f}/100",
            f"相對十年常態為「{gauge['level']}」")

    return checks


def compute(bundle: Bundle) -> dict:
    act = activity(bundle)
    house = housing(bundle)
    credit = credit_cycle(bundle)
    gauge = recession_gauge(bundle)
    return {
        "as_of": bundle["INDPRO"].last_date,
        "activity": act,
        "housing": house,
        "credit": credit,
        "gauge": gauge,
        "checks": health_checks(bundle, act, credit, gauge),
    }
