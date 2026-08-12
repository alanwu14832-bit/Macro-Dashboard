"""大宗商品。

不只列價格。放進總經儀表板的理由是這三條關係：
  銅金比   — 銅反映實體需求、黃金反映避險，比值是最乾淨的成長預期讀數
  金銀比   — 白銀有工業用途，比值拉高代表市場在買純避險而非買景氣
  黃金 vs 實質利率 — 持有黃金的機會成本就是實質利率，兩者長期反向

金銀價走 LBMA 官方定盤價，其餘走 FRED 上的 IMF Primary Commodity Prices。
"""
from __future__ import annotations

from .. import catalogue
from ..data import Bundle
from ..series import Series, align, correlation
from ..sources import lbma


def _change(s: Series, periods: int):
    prior = s.at(-1 - periods)
    if s.last is None or not prior:
        return None
    return (s.last / prior - 1) * 100


def _ytd(s: Series):
    if not s.last_date:
        return None
    start = s.value_on(f"{s.last_date.year}-01-02")
    return ((s.last / start - 1) * 100) if start else None


def _ratio(a: Series, b: Series, series_id: str, label: str) -> Series:
    dates, (x, y) = align(a, b)
    if not dates:
        return Series(series_id, [], [], frequency="d")
    values = [p / q for p, q in zip(x, y) if q]
    keep = [d for d, q in zip(dates, y) if q]
    return Series(series_id, keep, values, label=label, unit="倍",
                  frequency=a.frequency or "d", source="計算值")


def precious_metals(bundle: Bundle, metals: dict[str, Series]) -> dict:
    gold, silver = metals.get("gold"), metals.get("silver")
    rows = []
    for s, name, periods in ((gold, "黃金", 21), (silver, "白銀", 21)):
        if not s:
            continue
        rows.append({
            "name": name, "value": s.last, "unit": s.unit,
            "chg_1m": _change(s, periods), "chg_3m": _change(s, periods * 3),
            "chg_1y": _change(s, 252), "chg_ytd": _ytd(s),
            "pct10y": s.percentile_rank(10), "series": s,
            "as_of": s.last_date,
        })

    gold_silver = _ratio(gold, silver, "GOLD_SILVER", "金銀比") if (gold and silver) else Series("", [], [])
    return {
        "rows": rows,
        "gold": gold, "silver": silver,
        "gold_silver": gold_silver,
        "gold_silver_ratio": gold_silver.last,
        "gold_silver_avg10y": gold_silver.last_years(10).mean() if gold_silver else None,
    }


def copper_gold(bundle: Bundle, gold: Series) -> dict:
    """銅金比：成長預期的經典讀數，與 10 年殖利率長期同向。"""
    copper = bundle["PCOPPUSDM"]
    if not (copper and gold):
        return {}

    gold_monthly = gold.to_monthly()
    ratio = _ratio(copper, gold_monthly, "COPPER_GOLD", "銅金比")
    if not ratio:
        return {}
    ratio = ratio.relabel(frequency="m")

    ten = bundle["DGS10"].to_monthly().relabel(frequency="m")
    corr = correlation(ratio.last_years(10), ten.last_years(10))

    return {
        "ratio": ratio.last,
        "series": ratio,
        "avg10y": ratio.last_years(10).mean(),
        "pct10y": ratio.percentile_rank(10),
        "chg_1y": _change(ratio, 12),
        "corr_with_10y": corr,
        "ten_series": ten,
        "verdict": ("銅金比偏低，市場在定價成長放緩"
                    if ratio.percentile_rank(10) is not None and ratio.percentile_rank(10) < 35
                    else "銅金比偏高，市場在定價成長加速"
                    if ratio.percentile_rank(10) is not None and ratio.percentile_rank(10) > 65
                    else "銅金比接近十年中位"),
    }


def gold_real_rate(bundle: Bundle, gold: Series) -> dict:
    """黃金 vs 10 年實質利率：持有黃金的機會成本。"""
    real = bundle["DFII10"]
    if not (gold and real):
        return {}
    corr_1y = correlation(gold.pct_change(1).last_years(1), real.diff(1).last_years(1))
    corr_5y = correlation(gold.to_monthly().relabel(frequency="m").yoy().last_years(5),
                          real.to_monthly().relabel(frequency="m").last_years(5))
    return {
        "gold": gold.last, "real": real.last,
        "corr_daily_1y": corr_1y, "corr_yoy_5y": corr_5y,
        "real_series": real,
        "verdict": ("黃金與實質利率維持典型的反向關係" if corr_5y is not None and corr_5y < -0.3
                    else "黃金與實質利率的反向關係鬆脫，多半是避險或央行買盤主導"
                    if corr_5y is not None else "資料不足"),
    }


def groups(bundle: Bundle) -> list[dict]:
    out = []
    for title, ids in catalogue.COMMODITY_GROUPS:
        rows = []
        for series_id in ids:
            s = bundle[series_id]
            if not s:
                continue
            label = catalogue.COMMODITIES.get(series_id, (series_id,))[0]
            step = 21 if s.frequency == "d" else 4 if s.frequency == "w" else 1
            rows.append({
                "id": series_id, "name": label, "value": s.last, "unit": s.unit,
                "chg_1m": _change(s, step),
                "chg_3m": _change(s, step * 3),
                "chg_1y": _change(s, step * 12),
                "pct10y": s.percentile_rank(10),
                "as_of": s.last_date, "series": s,
            })
        if rows:
            out.append({"title": title, "rows": rows})
    return out


def health_checks(precious: dict, cg: dict, gr: dict, bundle: Bundle) -> list[dict]:
    checks = []

    def add(name, state, reading, note=""):
        checks.append({"name": name, "state": state, "reading": reading, "note": note})

    ratio = precious.get("gold_silver_ratio")
    average = precious.get("gold_silver_avg10y")
    if ratio is not None and average:
        state = "alert" if ratio > average * 1.25 else "watch" if ratio > average * 1.1 else "normal"
        add("金銀比", state, f"{ratio:.1f}",
            f"十年均 {average:.1f}；偏高代表市場在買純避險而非景氣" if state != "normal"
            else f"十年均 {average:.1f}")

    if cg.get("pct10y") is not None:
        pct = cg["pct10y"]
        state = "alert" if pct < 20 else "watch" if pct < 40 else "normal"
        add("銅金比", state, f"{cg['ratio']:.4f}",
            f"十年百分位 {pct:.0f}%　{cg.get('verdict', '')}")

    energy = bundle["PNRGINDEXM"]
    if energy and energy.last is not None:
        yoy = energy.yoy().last
        if yoy is not None:
            state = "alert" if yoy > 25 else "watch" if yoy > 10 else "normal"
            add("能源指數年增", state, f"{yoy:+.1f}%",
                "會直接推升總體 CPI" if yoy > 10 else "對總體 CPI 無明顯上行壓力")

    food = bundle["PFOODINDEXM"]
    if food:
        yoy = food.yoy().last
        if yoy is not None:
            state = "alert" if yoy > 15 else "watch" if yoy > 6 else "normal"
            add("食品指數年增", state, f"{yoy:+.1f}%",
                "食品佔 CPI 約 13%，傳導期約 3 至 6 個月")

    metals = bundle["PMETAINDEXM"]
    if metals:
        yoy = metals.yoy().last
        if yoy is not None:
            state = "watch" if yoy is not None and yoy < -10 else "normal"
            add("金屬指數年增", state, f"{yoy:+.1f}%",
                "工業金屬走弱通常先於製造業轉弱" if yoy < -10 else "")

    if gr.get("corr_yoy_5y") is not None:
        value = gr["corr_yoy_5y"]
        state = "watch" if value > -0.1 else "normal"
        add("黃金 vs 實質利率相關", state, f"{value:+.2f}", gr.get("verdict", ""))

    return checks


def compute(bundle: Bundle) -> dict:
    metals = lbma.load()
    gold = metals.get("gold") or Series("", [], [])
    precious = precious_metals(bundle, metals)
    cg = copper_gold(bundle, gold)
    gr = gold_real_rate(bundle, gold)
    return {
        "as_of": gold.last_date or bundle["DCOILWTICO"].last_date,
        "precious": precious,
        "copper_gold": cg,
        "gold_real_rate": gr,
        "groups": groups(bundle),
        "checks": health_checks(precious, cg, gr, bundle),
    }
