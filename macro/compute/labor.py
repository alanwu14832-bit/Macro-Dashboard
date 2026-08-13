"""勞動市場計算。

比參考站多做的：初值修正追蹤（用 FRED vintage 拉出當月初值 vs 現值）、
損益兩平就業增速（由勞動力成長推導，而非寫死）、失業率變動的分子分母拆解、
行業別擴散指數、以及把 8 項指標合成一個加權強弱分數。
"""
from __future__ import annotations

from datetime import date, timedelta

from .. import catalogue
from ..data import Bundle
from ..series import Series
from ..sources import fred


def _safe(value, digits=2):
    return None if value is None else round(value, digits)


# --------------------------------------------------------------- 損益兩平 ---
def breakeven_payrolls(bundle: Bundle) -> dict:
    """維持失業率不變所需的月增就業。

    ΔPopulation × 勞參率 × (1 − 失業率)。

    刻意用「人口」而非「勞動力」推導：勞動力本身會因參與率變動而伸縮，
    參與率下滑時勞動力可能萎縮，用它推導會得到負的損益兩平——那不是
    「不需要新增就業」，而是量錯了東西。人口成長才是外生的分母。
    """
    population = bundle["CNP16OV"]
    participation = bundle["CIVPART"]
    unrate = bundle["UNRATE"]
    if len(population) < 14 or not participation or not unrate:
        return {"value": None}

    rate = (participation.last or 62.0) / 100.0
    employed_share = 1 - (unrate.last or 4.0) / 100.0

    avg_12m = population.diff(1).tail(12).mean() or 0
    avg_36m = population.diff(1).tail(36).mean() or 0

    return {
        "value": avg_12m * rate * employed_share,
        "long_run": avg_36m * rate * employed_share,
        "population_growth": avg_12m,
        "population_growth_36m": avg_36m,
        "participation": participation.last,
        "unrate": unrate.last,
        "labor_force_growth": bundle["CLF16OV"].diff(1).tail(12).mean(),
        "series": population.diff(1).rolling_mean(12).scale(rate * employed_share),
    }


# ----------------------------------------------------------------- 修正 -----
def revision_tracking(bundle: Bundle, months: int = 14) -> dict:
    """初值 vs 現值。

    FRED 的 realtime 參數可以還原「當時公布的數字長什麼樣」。對每個月份，
    取該月首次公布後幾天的 vintage 當作初值，與目前值相減即為累計修正。
    """
    payrolls = bundle["PAYEMS"]
    if len(payrolls) < months + 2:
        return {"rows": [], "avg": None}

    current = payrolls.diff(1)
    rows = []
    for i in range(-months, 0):
        ref = current.date_at(i)
        if ref is None:
            continue
        # 就業報告約在次月第一個週五公布；取次月 15 日的 vintage 保守涵蓋
        release = (ref.replace(day=1) + timedelta(days=45)).replace(day=15)
        if release > date.today():
            continue
        vintage = fred.vintage_series("PAYEMS", release.isoformat(), start="2015-01-01")
        if len(vintage) < 2:
            continue
        first = vintage.diff(1)
        initial = None
        for d, v in first.pairs():
            if d == ref:
                initial = v
                break
        now = current.at(i)
        if initial is None or now is None:
            continue
        rows.append({"month": ref, "initial": initial, "current": now,
                     "revision": now - initial})

    revisions = [r["revision"] for r in rows]
    negatives = sum(1 for r in revisions if r < 0)
    return {
        "rows": rows,
        "avg": sum(revisions) / len(revisions) if revisions else None,
        "negative_share": negatives / len(revisions) if revisions else None,
        "n": len(revisions),
        "last_two": rows[-2:] if len(rows) >= 2 else rows,
    }


# ------------------------------------------------------- 失業率變動拆解 -----
def unemployment_decomposition(bundle: Bundle) -> dict:
    """失業率上升是因為分子（失業人數）還是分母（勞動力）在動？

    Δu ≈ (ΔU - u·ΔL) / L ，把變動拆成「失業人數效果」與「勞動力效果」。
    """
    unemployed = bundle["UNEMPLOY"]
    labor_force = bundle["CLF16OV"]
    rate = bundle["UNRATE"]
    if not (unemployed and labor_force and rate) or len(unemployed) < 4:
        return {}

    out = []
    for lag, name in ((1, "上月"), (3, "三個月"), (12, "一年")):
        u0, u1 = unemployed.at(-1 - lag), unemployed.last
        l0, l1 = labor_force.at(-1 - lag), labor_force.last
        r0, r1 = rate.at(-1 - lag), rate.last
        if None in (u0, u1, l0, l1, r0, r1):
            continue
        numerator_effect = (u1 - u0) / l0 * 100
        denominator_effect = -(r0 / 100) * (l1 - l0) / l0 * 100
        out.append({
            "window": name, "total": r1 - r0,
            "numerator": numerator_effect, "denominator": denominator_effect,
            "residual": (r1 - r0) - numerator_effect - denominator_effect,
        })
    return {"rows": out}


# ------------------------------------------------------------ 行業別貢獻 ----
def sector_contributions(bundle: Bundle) -> dict:
    """各行業對本月非農增減的貢獻，並算擴散指數。"""
    rows = []
    for series_id, name in catalogue.LABOR_SECTORS.items():
        s = bundle[series_id]
        if len(s) < 14:
            continue
        change = s.change_over(1)
        change_3m = (s.change_over(3) or 0) / 3
        change_12m = (s.change_over(12) or 0) / 12
        if change is None:
            continue
        rows.append({
            "id": series_id, "name": name, "value": change,
            "avg3": change_3m, "avg12": change_12m,
            "level": s.last,
            "yoy": s.yoy().last,
        })
    rows.sort(key=lambda r: r["value"], reverse=True)

    expanding = sum(1 for r in rows if r["value"] > 0)
    diffusion = expanding / len(rows) * 100 if rows else None

    # 三個月擴散：更能看出動能是集中在少數行業還是全面性
    expanding_3m = sum(1 for r in rows if r["avg3"] > 0)
    return {
        "rows": rows,
        "diffusion": diffusion,
        "diffusion_3m": expanding_3m / len(rows) * 100 if rows else None,
        "top": rows[:3], "bottom": rows[-3:],
        "n": len(rows),
    }


# --------------------------------------------------------------- 健康檢核 ---
def health_checks(bundle: Bundle, breakeven: dict) -> list[dict]:
    """8 項燈號。門檻寫死在這裡，同一份資料每次判定一致。"""
    checks: list[dict] = []

    def add(name, state, reading, note=""):
        checks.append({"name": name, "state": state, "reading": reading, "note": note})

    payrolls = bundle["PAYEMS"].diff(1)
    be = breakeven.get("value")
    avg3 = payrolls.tail(3).mean() if len(payrolls) >= 3 else None
    if avg3 is not None and be is not None:
        state = "alert" if avg3 < be * 0.5 else "watch" if avg3 < be else "normal"
        add("三月均非農 vs 損益兩平", state, f"{avg3 / 10:+.1f} / {be / 10:.1f} 萬",
            "低於損益兩平即撐不住失業率" if state != "normal" else "足以吸收新增勞動力")

    unrate = bundle["UNRATE"]
    if len(unrate) >= 13:
        low12 = min(unrate.tail(13).values)
        gap = (unrate.last or 0) - low12
        state = "alert" if gap >= 0.5 else "watch" if gap >= 0.3 else "normal"
        add("失業率距一年低點", state, f"+{gap:.1f} 個百分點",
            "Sahm 法則的觸發區間" if gap >= 0.5 else "尚未觸發衰退訊號")

    claims = bundle["IC4WSA"]
    if len(claims) >= 60:
        base = min(claims.last_years(1).values)
        ratio = (claims.last or 0) / base if base else None
        state = "alert" if ratio and ratio > 1.25 else "watch" if ratio and ratio > 1.15 else "normal"
        add("初領失業金四週均", state, f"{(claims.last or 0) / 10000:.1f} 萬人",
            f"距一年低點 {(ratio - 1) * 100:+.0f}%" if ratio else "")

    quits = bundle["JTSQUR"]
    if len(quits) >= 25:
        avg = quits.last_years(2).mean()
        state = "alert" if quits.last and quits.last < 1.9 else "watch" if quits.last and quits.last < avg else "normal"
        add("主動離職率", state, f"{quits.last:.1f}%",
            "勞工不敢換工作＝議價力下降" if state != "normal" else "勞工仍願意換工作")

    openings, unemployed = bundle["JTSJOL"], bundle["UNEMPLOY"]
    if openings and unemployed:
        ratio = (openings.last or 0) / (unemployed.last or 1)
        state = "alert" if ratio < 0.8 else "watch" if ratio < 1.0 else "normal"
        add("職缺對失業人數比", state, f"{ratio:.2f}",
            "低於 1 代表求職者多於職缺" if ratio < 1 else "職缺仍多於求職者")

    wages = bundle["CES0500000003"].yoy()
    if wages:
        state = "alert" if wages.last and wages.last > 4.0 else "watch" if wages.last and wages.last > 3.5 else "normal"
        add("時薪年增", state, f"{wages.last:.1f}%",
            "高於與 2% 通膨相容的區間" if state != "normal" else "與 2% 通膨大致相容")

    parttime = bundle["LNS12032194"]
    if len(parttime) >= 13:
        yoy = parttime.yoy().last
        state = "alert" if yoy and yoy > 10 else "watch" if yoy and yoy > 5 else "normal"
        add("經濟因素兼職人數", state, f"{yoy:+.1f}% 年增" if yoy is not None else "—",
            "被迫兼職上升是隱性弱化" if state != "normal" else "無明顯隱性失業壓力")

    permanent = bundle["LNS13026511"]
    if len(permanent) >= 25:
        avg = permanent.last_years(2).mean()
        state = "alert" if permanent.last and permanent.last > avg + 3 else \
                "watch" if permanent.last and permanent.last > avg else "normal"
        add("永久性失業佔比", state, f"{permanent.last:.1f}%",
            "永久性裁員上升代表結構性走弱" if state != "normal" else "以暫時性失業為主")

    return checks


# ------------------------------------------------------------- 強弱指數 -----
COMPOSITE_WEIGHTS = [
    ("PAYEMS_3M", "三月均非農", 0.22),
    ("UNRATE_CHG", "失業率變動", 0.20),
    ("CLAIMS", "初領失業金", 0.14),
    ("QUITS", "主動離職率", 0.12),
    ("OPENINGS", "職缺對失業比", 0.12),
    ("WAGES", "時薪年增", 0.08),
    ("PARTTIME", "經濟因素兼職", 0.06),
    ("HOURS", "平均週工時", 0.06),
]


def composite_index(bundle: Bundle, breakeven: dict) -> dict:
    """把 8 個分項各自標準化成 -100~+100，再加權平均。

    正值＝勞動市場強於長期常態，負值＝弱於常態。標準化用 10 年 z 分數，
    再以 tanh 型壓縮避免單一極端值主導。
    """
    import math

    def squash(z, invert=False):
        if z is None:
            return None
        z = -z if invert else z
        return max(-100.0, min(100.0, math.tanh(z / 2) * 100))

    parts: dict[str, float | None] = {}

    payrolls3 = bundle["PAYEMS"].diff(1).rolling_mean(3)
    be = breakeven.get("value")
    if payrolls3 and be:
        spread = payrolls3.shift_level(-be)
        parts["PAYEMS_3M"] = squash(spread.zscore(10))

    unrate = bundle["UNRATE"]
    if len(unrate) >= 13:
        parts["UNRATE_CHG"] = squash(unrate.diff_months(12).zscore(10), invert=True)

    claims = bundle["IC4WSA"]
    if claims:
        parts["CLAIMS"] = squash(claims.zscore(10), invert=True)

    quits = bundle["JTSQUR"]
    if quits:
        parts["QUITS"] = squash(quits.zscore(10))

    openings, unemployed = bundle["JTSJOL"], bundle["UNEMPLOY"]
    if openings and unemployed:
        dates, (o, u) = _align_ratio(openings, unemployed)
        if dates:
            ratio = Series("VU", dates, [a / b if b else 0 for a, b in zip(o, u)],
                           frequency="m")
            parts["OPENINGS"] = squash(ratio.zscore(10))

    wages = bundle["CES0500000003"].yoy()
    if wages:
        parts["WAGES"] = squash(wages.zscore(10))

    parttime = bundle["LNS12032194"]
    if len(parttime) >= 13:
        parts["PARTTIME"] = squash(parttime.yoy().zscore(10), invert=True)

    hours = bundle["AWHAETP"]
    if hours:
        parts["HOURS"] = squash(hours.diff_months(12).zscore(10))

    rows, total_weight, total = [], 0.0, 0.0
    for key, name, weight in COMPOSITE_WEIGHTS:
        score = parts.get(key)
        rows.append({"key": key, "name": name, "weight": weight, "score": _safe(score, 1)})
        if score is not None:
            total += score * weight
            total_weight += weight
    value = total / total_weight if total_weight else None
    return {"value": value, "rows": rows, "coverage": total_weight}


def _align_ratio(a: Series, b: Series):
    from ..series import align
    return align(a, b)


# ------------------------------------------------------------------ 主入口 --
def compute(bundle: Bundle) -> dict:
    payrolls = bundle["PAYEMS"]
    monthly = payrolls.diff(1)
    unrate = bundle["UNRATE"]
    wages = bundle["CES0500000003"].yoy()

    be = breakeven_payrolls(bundle)
    revisions = revision_tracking(bundle)
    sectors = sector_contributions(bundle)
    checks = health_checks(bundle, be)
    composite = composite_index(bundle, be)

    latest = monthly.last
    avg3 = monthly.tail(3).mean() if len(monthly) >= 3 else None
    avg6 = monthly.tail(6).mean() if len(monthly) >= 6 else None
    avg12 = monthly.tail(12).mean() if len(monthly) >= 12 else None

    unrate_low12 = min(unrate.tail(13).values) if len(unrate) >= 13 else None
    sahm = bundle["SAHMREALTIME"]

    return {
        "as_of": payrolls.last_date,
        "payrolls": {
            "latest": latest, "avg3": avg3, "avg6": avg6, "avg12": avg12,
            "series": monthly, "level": payrolls.last,
            "ma3": monthly.rolling_mean(3),
        },
        "unemployment": {
            "rate": unrate.last, "prior": unrate.at(-2),
            "low12": unrate_low12,
            "gap_from_low": (unrate.last - unrate_low12) if (unrate.last and unrate_low12) else None,
            "u6": bundle["U6RATE"].last,
            "series": unrate,
            "natural": bundle["NROU"].value_on(unrate.last_date) if unrate.last_date else None,
            "sahm": sahm.last if sahm else None,
        },
        "participation": {
            "rate": bundle["CIVPART"].last,
            "rate_change": bundle["CIVPART"].change_over(12),
            "prime": bundle["LNS11300060"].last,
            "prime_series": bundle["LNS11300060"],
            "prime_epop": bundle["LNS12300060"].last,
            "prime_epop_change": bundle["LNS12300060"].change_over(12),
            "prime_epop_series": bundle["LNS12300060"],
            "emratio": bundle["EMRATIO"].last,
            "population_growth": bundle["CNP16OV"].diff(1).tail(12).mean()
                                 if len(bundle["CNP16OV"]) >= 13 else None,
            "labor_force_growth": bundle["CLF16OV"].diff(1).tail(12).mean()
                                  if len(bundle["CLF16OV"]) >= 13 else None,
        },
        "wages": {
            "yoy": wages.last if wages else None,
            "series": wages,
            "ann3": bundle["CES0500000003"].annualised(3).last,
            "hours": bundle["AWHAETP"].last,
            "hours_series": bundle["AWHAETP"],
        },
        "claims": {
            "initial": bundle["ICSA"].last,
            "initial_4w": bundle["IC4WSA"].last,
            "continued": bundle["CCSA"].last,
            "initial_series": bundle["ICSA"],
            "ma_series": bundle["IC4WSA"],
            "continued_series": bundle["CCSA"],
            "as_of": bundle["ICSA"].last_date,
        },
        "jolts": {
            "openings": bundle["JTSJOL"].last,
            "hires": bundle["JTSHIR"].last,
            "quits": bundle["JTSQUR"].last,
            "layoffs": bundle["JTSLDR"].last,
            "openings_series": bundle["JTSJOL"],
            "quits_series": bundle["JTSQUR"],
            "as_of": bundle["JTSJOL"].last_date,
            "vu_ratio": ((bundle["JTSJOL"].last or 0) / (bundle["UNEMPLOY"].last or 1))
                        if bundle["JTSJOL"] and bundle["UNEMPLOY"] else None,
        },
        "duration": {
            "median": bundle["UEMPMED"].last,
            "mean": bundle["UEMPMEAN"].last,
            "series": bundle["UEMPMED"],
            "permanent_share": bundle["LNS13026511"].last,
        },
        "breakeven": be,
        "revisions": revisions,
        "decomposition": unemployment_decomposition(bundle),
        "sectors": sectors,
        "checks": checks,
        "composite": composite,
    }
