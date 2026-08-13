"""通膨計算。

比參考站多做的：核心服務除住房自行從 CPI 分項重建（FRED 沒有直接序列）、
分項貢獻用 BLS 相對權重加權、住房落後以租金領先指標估算、
能源傳導用油價對汽油與 CPI 的實測領先相關係數而非固定係數。
"""
from __future__ import annotations

from .. import catalogue
from ..data import Bundle
from ..series import Series, align, correlation

TARGET = 2.0  # 聯準會目標（以 PCE 計）


def _yoy_last(s: Series):
    y = s.yoy()
    return y.last if y else None


# ------------------------------------------------------- 核心服務除住房 -----
def core_services_ex_housing(bundle: Bundle) -> Series:
    """從服務 CPI 剔除住房，重建俗稱 supercore 的序列。

    服務指數與住房指數的權重來自 BLS 相對重要性，做加權相減後重新指數化。
    這是聯準會口中「最能反映薪資壓力」的那一段。
    """
    services = bundle["CUSR0000SAS"]
    housing = bundle["CUSR0000SAH1"]
    if not (services and housing):
        return Series("SUPERCORE", [], [], frequency="m")

    w_services, w_housing = 61.5, 35.2      # 佔 CPI 比重
    w_rest = w_services - w_housing
    if w_rest <= 0:
        return Series("SUPERCORE", [], [], frequency="m")

    dates, (svc, hou) = align(services, housing)
    if not dates:
        return Series("SUPERCORE", [], [], frequency="m")

    values = [(s * w_services - h * w_housing) / w_rest for s, h in zip(svc, hou)]
    return Series("SUPERCORE", dates, values, label="核心服務除住房",
                  unit="指數", frequency="m", source="計算值")


# ---------------------------------------------------------- 分項貢獻 -------
def contributions(bundle: Bundle) -> dict:
    """各分項對 CPI 年增率的貢獻＝分項年增 × 權重。"""
    rows = []
    for series_id, (name, weight) in catalogue.CPI_WEIGHTS.items():
        s = bundle[series_id]
        if len(s) < 14:
            continue
        yoy = _yoy_last(s)
        mom3 = s.annualised(3).last
        if yoy is None:
            continue
        rows.append({
            "id": series_id, "name": name, "weight": weight,
            "yoy": yoy, "ann3": mom3,
            "contribution": yoy * weight / 100.0,
            "contribution_3m": (mom3 * weight / 100.0) if mom3 is not None else None,
        })
    rows.sort(key=lambda r: r["contribution"], reverse=True)

    headline = _yoy_last(bundle["CPIAUCSL"])
    covered = sum(r["contribution"] for r in rows)
    return {
        "rows": rows,
        "headline": headline,
        "covered": covered,
        "other": (headline - covered) if headline is not None else None,
    }


# ----------------------------------------------------------- 廣度 ----------
def breadth(bundle: Bundle) -> dict:
    """是全面在漲，還是少數項目？

    三個剔除極端值的指標若明顯低於核心，代表漲勢集中；若貼近核心，
    代表通膨是廣泛的。
    """
    core = _yoy_last(bundle["CPILFESL"])
    median = bundle["MEDCPIM158SFRBCLE"].last
    trimmed = bundle["TRMMEANCPIM158SFRBCLE"].last
    sticky = bundle["CORESTICKM159SFRBATL"].last

    measures = [("中位數 CPI", median), ("截尾平均 CPI", trimmed), ("黏性核心 CPI", sticky)]
    valid = [v for _, v in measures if v is not None]
    spread = (core - sum(valid) / len(valid)) if (core is not None and valid) else None

    return {
        "core": core, "measures": measures,
        "average": sum(valid) / len(valid) if valid else None,
        "spread": spread,
        "verdict": ("集中在少數項目" if spread is not None and spread > 0.3
                    else "全面性" if spread is not None and spread < -0.3
                    else "介於兩者之間"),
        "median_series": bundle["MEDCPIM158SFRBCLE"],
        "trimmed_series": bundle["TRMMEANCPIM158SFRBCLE"],
        "sticky_series": bundle["CORESTICKM159SFRBATL"],
    }


# -------------------------------------------------------- 住房落後 ---------
def shelter_lag(bundle: Bundle) -> dict:
    """住房項落後市場租金約 9-12 個月。

    用 CPI 住房自身的近三月年化與年增率的差，估計「若住房照近期速度走，
    整體通膨還會被拉低多少」。
    """
    shelter = bundle["CUSR0000SAH1"]
    rent = bundle["CUSR0000SEHA"]
    oer = bundle["CUSR0000SEHC"]
    if not shelter:
        return {}

    yoy = _yoy_last(shelter)
    ann3 = shelter.annualised(3).last
    ann6 = shelter.annualised(6).last
    weight = catalogue.CPI_WEIGHTS["CUSR0000SAH1"][1]

    drag = None
    if yoy is not None and ann3 is not None:
        # 住房年增率若收斂到近三月年化，對整體 CPI 的影響
        drag = (ann3 - yoy) * weight / 100.0

    core = _yoy_last(bundle["CPILFESL"])
    core_ex_shelter = None
    if core is not None and yoy is not None:
        # 核心中住房權重約 43%（核心 CPI 不含食物能源，住房佔比更高）
        w_core = 43.0
        core_ex_shelter = (core - yoy * w_core / 100.0) / (1 - w_core / 100.0)

    return {
        "yoy": yoy, "ann3": ann3, "ann6": ann6, "weight": weight,
        "rent_yoy": _yoy_last(rent), "oer_yoy": _yoy_last(oer),
        "drag": drag,
        "core_ex_shelter": core_ex_shelter,
        "core": core,
        "series": shelter.yoy(),
        "ann3_series": shelter.annualised(3),
    }


# ------------------------------------------------------- 能源傳導 ----------
def energy_passthrough(bundle: Bundle) -> dict:
    """油價 → 汽油 → 總體 CPI。

    傳導係數用實測領先相關係數挑出最強的落後期數，而不是套固定值。
    """
    wti = bundle["DCOILWTICO"].to_monthly()
    gasoline = bundle["GASREGW"].to_monthly()
    energy_cpi = bundle["CPIENGSL"]
    if not (wti and gasoline):
        return {}

    wti_yoy = wti.relabel(frequency="m").yoy()
    gas_yoy = gasoline.relabel(frequency="m").yoy()

    lags = []
    for lag in range(0, 5):
        c = correlation(wti_yoy.last_years(10), gas_yoy.last_years(10), lag)
        if c is not None:
            lags.append({"lag": lag, "corr": c})
    best = max(lags, key=lambda r: r["corr"]) if lags else None

    wti_1m = wti.pct_change(1).last
    wti_3m = wti.pct_change(3).last
    energy_weight = catalogue.CPI_WEIGHTS["CPIENGSL"][1]

    # 能源 CPI 對總體 CPI 的估計影響
    energy_yoy = _yoy_last(energy_cpi)
    impact = (energy_yoy * energy_weight / 100.0) if energy_yoy is not None else None

    return {
        "wti": wti.last, "wti_1m": wti_1m, "wti_3m": wti_3m,
        "gasoline": gasoline.last,
        "gasoline_yoy": gas_yoy.last if gas_yoy else None,
        "energy_yoy": energy_yoy,
        "weight": energy_weight,
        "impact": impact,
        "lags": lags, "best_lag": best,
        "wti_series": wti.relabel(frequency="m"),
        "gas_series": gasoline.relabel(frequency="m"),
    }


# ------------------------------------------------------- 薪資傳導 ----------
def wage_passthrough(bundle: Bundle) -> dict:
    """薪資 → 服務業通膨。生產力決定多少薪資漲幅會變成通膨。"""
    wages = bundle["CES0500000003"].yoy()
    eci = bundle["ECIALLCIV"].yoy()
    supercore = core_services_ex_housing(bundle)
    supercore_yoy = supercore.yoy() if supercore else None
    productivity = bundle["OPHNFB"].yoy()
    ulc = bundle["ULCNFB"].yoy()

    # 與 2% 通膨相容的薪資增速 ≈ 2% + 生產力成長
    compatible = None
    if productivity and productivity.last is not None:
        compatible = TARGET + productivity.last

    corr = None
    if wages and supercore_yoy:
        corr = correlation(wages.last_years(10), supercore_yoy.last_years(10), 0)

    return {
        "wages": wages.last if wages else None,
        "eci": eci.last if eci else None,
        "supercore": supercore_yoy.last if supercore_yoy else None,
        "productivity": productivity.last if productivity else None,
        "ulc": ulc.last if ulc else None,
        "compatible": compatible,
        "gap": (wages.last - compatible) if (wages and wages.last is not None and compatible) else None,
        "corr": corr,
        "wages_series": wages,
        "supercore_series": supercore_yoy,
    }


# ---------------------------------------------------------- 檢核 -----------
def health_checks(bundle: Bundle, supercore: Series, shelter: dict,
                  energy: dict, wage: dict) -> list[dict]:
    checks = []

    def add(name, state, reading, note=""):
        checks.append({"name": name, "state": state, "reading": reading, "note": note})

    core_pce = _yoy_last(bundle["PCEPILFE"])
    if core_pce is not None:
        gap = core_pce - TARGET
        state = "alert" if gap > 1.0 else "watch" if gap > 0.3 else "normal"
        add("核心 PCE 距目標", state, f"{core_pce:.1f}%", f"高於 2% 目標 {gap:+.1f} 個百分點")

    core_cpi = bundle["CPILFESL"]
    if core_cpi:
        yoy, ann3 = _yoy_last(core_cpi), core_cpi.annualised(3).last
        if yoy is not None and ann3 is not None:
            diff = ann3 - yoy
            state = "normal" if diff < -0.4 else "watch" if diff < 0.4 else "alert"
            add("核心 CPI 近三月年化 vs 年增", state, f"{ann3:.1f}% / {yoy:.1f}%",
                "近期動能明顯低於年增＝降溫" if diff < -0.4 else
                "近期動能高於年增＝再加速" if diff > 0.4 else "與年增相當")

    if supercore:
        yoy = _yoy_last(supercore)
        ann3 = supercore.annualised(3).last
        if yoy is not None:
            state = "alert" if yoy > 3.5 else "watch" if yoy > 2.5 else "normal"
            months = _months_above(supercore.yoy(), 2.5)
            add("核心服務除住房", state, f"{yoy:.1f}%",
                f"連 {months} 個月高於 2.5%" if months else "已回到目標相容區間")

    expect = bundle["T5YIFR"]
    if expect and expect.last is not None:
        state = "alert" if expect.last > 2.6 else "watch" if expect.last > 2.4 else "normal"
        add("長期通膨預期 5y5y", state, f"{expect.last:.2f}%",
            "預期仍錨定" if state == "normal" else "預期開始鬆動")

    short_expect = bundle["MICH"]
    if short_expect and short_expect.last is not None:
        state = "alert" if short_expect.last > 4.0 else "watch" if short_expect.last > 3.2 else "normal"
        add("密大 1 年通膨預期", state, f"{short_expect.last:.1f}%",
            "短期預期偏高" if state != "normal" else "短期預期溫和")

    if shelter.get("drag") is not None:
        drag = shelter["drag"]
        state = "normal" if drag < -0.2 else "watch" if drag < 0.1 else "alert"
        add("住房落後項", state, f"{drag:+.2f} 個百分點",
            "住房仍會把通膨往下拉" if drag < 0 else "住房不再提供下拉力道")

    if energy.get("wti_1m") is not None:
        wti_1m = energy["wti_1m"]
        state = "alert" if wti_1m > 12 else "watch" if wti_1m > 5 else "normal"
        add("油價近一月變動", state, f"{wti_1m:+.1f}%",
            "未來一至兩月推升總體 CPI" if wti_1m > 5 else "對 CPI 無明顯上行壓力")

    if wage.get("gap") is not None:
        gap = wage["gap"]
        state = "alert" if gap > 1.0 else "watch" if gap > 0.3 else "normal"
        add("薪資 vs 與 2% 相容水準", state, f"{gap:+.1f} 個百分點",
            "薪資仍高於生產力容許的空間" if gap > 0.3 else "薪資與 2% 通膨大致相容")

    return checks


def _months_above(series: Series, threshold: float) -> int:
    count = 0
    for value in reversed(series.values):
        if value > threshold:
            count += 1
        else:
            break
    return count


# ------------------------------------------------------------- 主入口 ------
def compute(bundle: Bundle) -> dict:
    cpi = bundle["CPIAUCSL"]
    core_cpi = bundle["CPILFESL"]
    # 標題年增率用未季調指數，跟 BLS 新聞稿同口徑（季調版的年增率會差
    # 約 0.1 個百分點，讀者對報導核對時會以為網站算錯）。月增動能與
    # 分項貢獻仍用季調版——比較相鄰月份時才需要去季節性。
    cpi_nsa = bundle["CPIAUCNS"] or cpi
    core_nsa = bundle["CPILFENS"] or core_cpi
    pce = bundle["PCEPI"]
    core_pce = bundle["PCEPILFE"]
    supercore = core_services_ex_housing(bundle)

    shelter = shelter_lag(bundle)
    energy = energy_passthrough(bundle)
    wage = wage_passthrough(bundle)
    breadth_data = breadth(bundle)
    contrib = contributions(bundle)
    checks = health_checks(bundle, supercore, shelter, energy, wage)

    return {
        "as_of": core_cpi.last_date,
        "pce_as_of": core_pce.last_date,
        "headline": {
            "cpi": _yoy_last(cpi_nsa), "core_cpi": _yoy_last(core_nsa),
            "pce": _yoy_last(pce), "core_pce": _yoy_last(core_pce),
            "cpi_series": cpi_nsa.yoy(), "core_series": core_nsa.yoy(),
            "core_pce_series": core_pce.yoy(),
            "gap_to_target": (_yoy_last(core_pce) - TARGET) if _yoy_last(core_pce) is not None else None,
        },
        "momentum": {
            "core_cpi_3m": core_cpi.annualised(3).last,
            "core_cpi_6m": core_cpi.annualised(6).last,
            "core_pce_3m": core_pce.annualised(3).last,
            "core_pce_6m": core_pce.annualised(6).last,
            "core_3m_series": core_cpi.annualised(3),
        },
        "supercore": {
            "yoy": _yoy_last(supercore),
            "ann3": supercore.annualised(3).last if supercore else None,
            "ann6": supercore.annualised(6).last if supercore else None,
            "series": supercore.yoy() if supercore else Series("", [], []),
            "months_above": _months_above(supercore.yoy(), 2.5) if supercore else 0,
        },
        "expectations": {
            "t5y5y": bundle["T5YIFR"].last,
            "t10yie": bundle["T10YIE"].last,
            "t5yie": bundle["T5YIE"].last,
            "michigan": bundle["MICH"].last,
            "cleveland_1y": bundle["EXPINF1YR"].last,
            "cleveland_10y": bundle["EXPINF10YR"].last,
            "t5y5y_series": bundle["T5YIFR"],
            "michigan_series": bundle["MICH"],
        },
        "contributions": contrib,
        "breadth": breadth_data,
        "shelter": shelter,
        "energy": energy,
        "wages": wage,
        "checks": checks,
        "target": TARGET,
    }
