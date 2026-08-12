"""九宮格情境與部位對照。

九宮格＝就業（強/中/弱）× 通膨（低/中/高）。同一格在不同政策重心下
會導出不同結論，所以重心（通膨優先／就業優先／兩邊並重）是另一個軸，
由通膨與目標的距離、以及通膨預期是否錨定來判定。

門檻全部在此明列，改門檻等於改判斷，不會藏在別處。
"""
from __future__ import annotations

# ---- 判定門檻（可調，改這裡等於改整站判斷） ----------------------------
EMPLOYMENT_BANDS = {
    # 三項輸入各自映射到 -1(弱) ~ +1(強)，加權平均後分級。
    # 用加權分數而非投票，是因為投票制會讓「失業率在低點」這種單一指標
    # 抵銷掉「聘僱遠低於損益兩平」——而失業率下降有可能只是勞動力在萎縮。
    "weak_payroll_ratio": 0.6,      # 三月均非農 ÷ 損益兩平
    "strong_payroll_ratio": 1.6,
    "weak_unrate_gap": 0.4,         # 失業率距一年低點（個百分點）
    "strong_unrate_gap": 0.0,
    "weak_prime_epop": -0.4,        # 黃金年齡就業率 12 個月變動
    "strong_prime_epop": 0.4,
    "weights": {"payrolls": 0.45, "unrate": 0.25, "prime_epop": 0.30},
    "weak_score": -0.33,
    "strong_score": 0.33,
}
INFLATION_BANDS = {
    "low": 2.3,     # 核心 PCE 低於此＝低
    "high": 2.8,    # 核心 PCE 高於此＝高
}
REGIME_RULES = {
    "inflation_first_gap": 0.8,   # 核心 PCE 高於目標超過此值＝通膨優先
    "expectations_threshold": 2.55,
}

EMPLOYMENT_LABELS = {"weak": "弱", "mid": "中", "strong": "強"}
INFLATION_LABELS = {"low": "低", "mid": "中", "high": "高"}

# 九宮格：(就業, 通膨) -> (名稱, 三種重心下的政策傾向)
GRID = {
    ("strong", "low"):  ("金髮女孩", {"inflation_first": "neutral", "employment_first": "neutral", "balanced": "neutral"}),
    ("strong", "mid"):  ("穩健擴張", {"inflation_first": "hawkish", "employment_first": "neutral", "balanced": "neutral"}),
    ("strong", "high"): ("過熱", {"inflation_first": "hawkish", "employment_first": "hawkish", "balanced": "hawkish"}),
    ("mid", "low"):     ("溫和放緩", {"inflation_first": "neutral", "employment_first": "dovish", "balanced": "dovish"}),
    ("mid", "mid"):     ("平衡", {"inflation_first": "neutral", "employment_first": "neutral", "balanced": "neutral"}),
    ("mid", "high"):    ("通膨未解", {"inflation_first": "hawkish", "employment_first": "neutral", "balanced": "hawkish"}),
    ("weak", "low"):    ("需求不足", {"inflation_first": "dovish", "employment_first": "dovish", "balanced": "dovish"}),
    ("weak", "mid"):    ("軟著陸邊緣", {"inflation_first": "neutral", "employment_first": "dovish", "balanced": "dovish"}),
    ("weak", "high"):   ("停滯性通膨", {"inflation_first": "hawkish", "employment_first": "dovish", "balanced": "neutral"}),
}

REGIME_LABELS = {
    "inflation_first": "通膨優先",
    "employment_first": "就業優先",
    "balanced": "兩邊並重",
}
REGIME_EXPLAIN = {
    "inflation_first": "通膨回到目標前，就業轉弱不會單獨換來降息",
    "employment_first": "勞動市場惡化是決定性因素，通膨略高可以容忍",
    "balanced": "哪一邊先出現極端值，哪一邊就主導",
}

# 固定收益部位對照：情境 -> 各部位方向
POSITIONING = {
    "hawkish": [
        ("殖利率曲線", "熊平", "短端被政策推高，長端被壓抑"),
        ("債券存續期間", "縮短", "降息時點延後，長天期承受更多重定價風險"),
        ("抗通膨債券 TIPS", "相對走強", "通膨補償上升時少數受惠的固定收益資產"),
        ("公司債利差", "走闊", "融資成本上升壓縮企業獲利"),
        ("美元", "偏強", "利差擴大吸引資金流入"),
        ("股票存續期間", "偏短", "高估值成長股對貼現率最敏感"),
    ],
    "dovish": [
        ("殖利率曲線", "牛陡", "短端隨政策下行，長端跌幅較小"),
        ("債券存續期間", "拉長", "降息循環中長天期資本利得空間最大"),
        ("抗通膨債券 TIPS", "相對走弱", "通膨補償下降，實質債表現優於 TIPS"),
        ("公司債利差", "先闊後縮", "衰退擔憂先推闊利差，寬鬆到位後收斂"),
        ("美元", "偏弱", "利差收斂，資金流出"),
        ("股票存續期間", "可拉長", "貼現率下行有利長天期現金流"),
    ],
    "neutral": [
        ("殖利率曲線", "區間震盪", "兩個使命拉扯，缺乏單一方向"),
        ("債券存續期間", "中性", "等待數據決定方向，不押邊"),
        ("抗通膨債券 TIPS", "中性", "通膨補償接近合理區間"),
        ("公司債利差", "區間", "基本面未明顯惡化"),
        ("美元", "區間", "各國政策分歧尚未擴大"),
        ("股票存續期間", "中性", "貼現率方向不明"),
    ],
}


# ------------------------------------------------------------- 分類 --------
def _band_score(value: float | None, weak_at: float, strong_at: float) -> float | None:
    """線性映射到 -1(弱) ~ +1(強)，超出端點就夾住。"""
    if value is None:
        return None
    if strong_at == weak_at:
        return 0.0
    score = (value - weak_at) / (strong_at - weak_at) * 2 - 1
    return max(-1.0, min(1.0, score))


def classify_employment(labor: dict) -> tuple[str, list[str], dict]:
    bands = EMPLOYMENT_BANDS
    reasons, parts = [], {}

    avg3 = labor["payrolls"].get("avg3")
    breakeven = labor["breakeven"].get("value")
    ratio = (avg3 / breakeven) if (avg3 is not None and breakeven) else None
    parts["payrolls"] = _band_score(ratio, bands["weak_payroll_ratio"],
                                    bands["strong_payroll_ratio"])
    if ratio is not None:
        reasons.append(f"三月均非農為損益兩平的 {ratio:.2f} 倍")

    gap = labor["unemployment"].get("gap_from_low")
    parts["unrate"] = _band_score(gap, bands["weak_unrate_gap"], bands["strong_unrate_gap"])
    if gap is not None:
        reasons.append(f"失業率距一年低點 {gap:+.1f} 個百分點")

    prime = labor["participation"].get("prime_epop_change")
    parts["prime_epop"] = _band_score(prime, bands["weak_prime_epop"],
                                      bands["strong_prime_epop"])
    if prime is not None:
        reasons.append(f"黃金年齡就業率 12 個月變動 {prime:+.1f} 個百分點")

    weights = bands["weights"]
    total = sum(weights[k] for k, v in parts.items() if v is not None)
    if not total:
        return "mid", reasons + ["輸入資料不足，暫以「中」處理"], parts
    score = sum(v * weights[k] for k, v in parts.items() if v is not None) / total

    if score <= bands["weak_score"]:
        state = "weak"
    elif score >= bands["strong_score"]:
        state = "strong"
    else:
        state = "mid"
    return state, reasons, {"score": score, "parts": parts}


def classify_inflation(inflation: dict) -> tuple[str, list[str]]:
    core_pce = inflation["headline"].get("core_pce")
    reasons = []
    if core_pce is None:
        return "mid", ["核心 PCE 資料缺漏，暫以「中」處理"]
    reasons.append(f"核心 PCE {core_pce:.1f}%")

    momentum = inflation["momentum"].get("core_pce_3m")
    if momentum is not None:
        reasons.append(f"近三月年化 {momentum:.1f}%")

    if core_pce >= INFLATION_BANDS["high"]:
        return "high", reasons
    if core_pce <= INFLATION_BANDS["low"]:
        return "low", reasons
    return "mid", reasons


def classify_regime(inflation: dict) -> tuple[str, list[str]]:
    core_pce = inflation["headline"].get("core_pce")
    target = inflation["target"]
    expectations = inflation["expectations"].get("t5y5y")
    reasons = []

    gap = (core_pce - target) if core_pce is not None else None
    if gap is not None:
        reasons.append(f"核心 PCE 距目標 {gap:+.1f} 個百分點")
    if expectations is not None:
        reasons.append(f"5y5y 通膨預期 {expectations:.2f}%")

    if expectations is not None and expectations > REGIME_RULES["expectations_threshold"]:
        reasons.append("長期預期鬆動，通膨必然優先")
        return "inflation_first", reasons
    if gap is not None and gap > REGIME_RULES["inflation_first_gap"]:
        return "inflation_first", reasons
    if gap is not None and gap < 0.2:
        return "employment_first", reasons
    return "balanced", reasons


# ---------------------------------------------------------- 轉換門檻 -------
def transition_thresholds(labor: dict, inflation: dict, employment_state: str,
                          inflation_state: str, employment_detail: dict) -> list[dict]:
    """要換格，各項還差多少。"""
    out = []
    core_pce = inflation["headline"].get("core_pce")
    if core_pce is not None:
        if inflation_state == "high":
            out.append({
                "name": "通膨由「高」轉「中」",
                "need": f"核心 PCE 需降至 {INFLATION_BANDS['high']:.1f}% 以下",
                "gap": core_pce - INFLATION_BANDS["high"],
                "unit": "個百分點",
            })
            out.append({
                "name": "通膨由「高」轉「低」",
                "need": f"核心 PCE 需降至 {INFLATION_BANDS['low']:.1f}% 以下",
                "gap": core_pce - INFLATION_BANDS["low"],
                "unit": "個百分點",
            })
        elif inflation_state == "mid":
            out.append({
                "name": "通膨由「中」轉「低」",
                "need": f"核心 PCE 需降至 {INFLATION_BANDS['low']:.1f}% 以下",
                "gap": core_pce - INFLATION_BANDS["low"],
                "unit": "個百分點",
            })

    out.extend(_payroll_thresholds(labor, employment_state, employment_detail))
    return out


def _payroll_thresholds(labor: dict, employment_state: str,
                        detail: dict) -> list[dict]:
    """就業要換級，三月均非農需要到哪裡。

    就業分級是三項的加權分數，所以門檻必須反解：固定另外兩項的分數，
    求出讓總分剛好跨過邊界的非農分數，再換算回人數。這樣門檻才和實際
    判定邏輯一致，而不是只看單一指標的近似值。
    """
    bands = EMPLOYMENT_BANDS
    weights = bands["weights"]
    parts = (detail or {}).get("parts") or {}
    avg3 = labor["payrolls"].get("avg3")
    breakeven = labor["breakeven"].get("value")
    if avg3 is None or not breakeven or parts.get("payrolls") is None:
        return []

    total_weight = sum(weights[k] for k, v in parts.items() if v is not None)
    others = sum(v * weights[k] for k, v in parts.items()
                 if v is not None and k != "payrolls")

    targets = []
    if employment_state == "weak":
        targets.append(("就業由「弱」轉「中」", bands["weak_score"] + 1e-9))
    elif employment_state == "mid":
        targets.append(("就業轉「弱」", bands["weak_score"]))
        targets.append(("就業轉「強」", bands["strong_score"]))
    else:
        targets.append(("就業由「強」轉「中」", bands["strong_score"]))

    out = []
    for name, target in targets:
        needed_score = (target * total_weight - others) / weights["payrolls"]
        if needed_score > 1.0 or needed_score < -1.0:
            out.append({
                "name": name,
                "need": "光靠非農無法跨過，另外兩項（失業率、黃金年齡就業率）也要一起動",
                "gap": None, "unit": "",
            })
            continue
        ratio = (bands["weak_payroll_ratio"]
                 + (needed_score + 1) / 2
                 * (bands["strong_payroll_ratio"] - bands["weak_payroll_ratio"]))
        need = ratio * breakeven
        out.append({
            "name": name,
            "need": f"三月均非農需到 {need / 10:.1f} 萬人"
                    f"（其他兩項不變的前提下）",
            "gap": abs(need - avg3) / 10,
            "unit": "萬人",
        })
    return out


# -------------------------------------------------------------- 主入口 -----
def compute(labor: dict, inflation: dict, rates: dict, debt: dict,
            growth: dict, signal_summary: dict) -> dict:
    employment_state, employment_reasons, employment_detail = classify_employment(labor)
    inflation_state, inflation_reasons = classify_inflation(inflation)
    regime, regime_reasons = classify_regime(inflation)

    name, leanings = GRID[(employment_state, inflation_state)]
    lean = leanings[regime]

    alternatives = [
        {"regime": key, "label": REGIME_LABELS[key], "lean": leanings[key],
         "explain": REGIME_EXPLAIN[key], "active": key == regime}
        for key in ("inflation_first", "employment_first", "balanced")
    ]

    grid_cells = []
    for employment in ("strong", "mid", "weak"):
        row = []
        for inf in ("low", "mid", "high"):
            cell_name, cell_leanings = GRID[(employment, inf)]
            row.append({
                "employment": employment, "inflation": inf,
                "name": cell_name, "lean": cell_leanings[regime],
                "active": employment == employment_state and inf == inflation_state,
            })
        grid_cells.append({"employment": employment,
                           "label": EMPLOYMENT_LABELS[employment], "cells": row})

    return {
        "employment_state": employment_state,
        "employment_label": EMPLOYMENT_LABELS[employment_state],
        "employment_reasons": employment_reasons,
        "employment_detail": employment_detail,
        "inflation_state": inflation_state,
        "inflation_label": INFLATION_LABELS[inflation_state],
        "inflation_reasons": inflation_reasons,
        "regime": regime,
        "regime_label": REGIME_LABELS[regime],
        "regime_explain": REGIME_EXPLAIN[regime],
        "regime_reasons": regime_reasons,
        "name": name,
        "lean": lean,
        "alternatives": alternatives,
        "grid": grid_cells,
        "transitions": transition_thresholds(labor, inflation, employment_state,
                                             inflation_state, employment_detail),
        "positioning": POSITIONING[lean],
        "signal_tilt": signal_summary.get("tilt"),
        "market_check": rates["stance"].get("market_implies"),
        "supply_pressure": debt["supply"]["level"],
        "recession_gauge": growth["gauge"].get("level"),
        "bands": {"employment": EMPLOYMENT_BANDS, "inflation": INFLATION_BANDS,
                  "regime": REGIME_RULES},
    }
