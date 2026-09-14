"""台灣總經。

站上原本只有台股的價格，沒有台灣的總經——部位在台股，判斷卻全部來自美國。
這個模組補的是後者：景氣循環位置、外需動能、生產與內需、勞動與物價、
資金與利率，全部來自台灣官方統計，不是從美國序列外推。

三條資料線：
  國發會   景氣對策信號、領先／同時／落後指標與其全部構成項目（月頻）
  主計總處 消費者物價指數（月頻）
  中央銀行 重貼現率（階梯，一年可能不動）
外加 FRED 上仍在更新的四檔（BIS 有效匯率、IMF 進出口金額）與 DEXTAUS。

各序列的最新月份不一致是常態——失業率與海關出口通常比加班工時與用電量
快一個月。每一格都帶自己的資料日期，不用鄰近月份對齊。
"""
from __future__ import annotations

from ..data import Bundle
from ..series import EMPTY, Series
from ..sources import cbc, ndc, taiwan as dgbas

# ---- 本站門檻（國發會燈號分界除外，那是官方定義，寫在 sources/ndc.py）----
LEADING_TURN_MONTHS = 3      # 領先指標不含趨勢連續幾個月同向 = 轉折訊號
EXPORT_ORDERS_MID = 50.0     # 外銷訂單動向指數的擴張／收縮中線（官方定義）
UNEMPLOYMENT_RISE_PP = 0.3   # 失業率高出近 12 個月低點多少 = 勞動市場轉弱
EXPORT_WEAK_MONTHS = 3       # 海關出口年增率連續幾個月為負 = 外需衰退
M1B_STALL_PCT = 3.0          # M1B 年增率低於多少 = 市場資金動能轉弱


def _yoy_last(series: Series) -> tuple[float | None, object]:
    growth = series.yoy()
    return growth.last, growth.last_date


def _streak(series: Series, *, rising: bool) -> int:
    """最後一段連續上升（或下降）了幾個月。"""
    count = 0
    for i in range(len(series.values) - 1, 0, -1):
        step = series.values[i] - series.values[i - 1]
        if (step > 0) if rising else (step < 0):
            count += 1
        else:
            break
    return count


def _light_streak(scores: Series) -> tuple[str | None, int]:
    """目前是什麼燈，以及連續幾個月是同一個燈。"""
    lights = [ndc.light_for(v) for v in scores.values]
    if not lights:
        return None, 0
    current = lights[-1]
    count = 0
    for light in reversed(lights):
        if light != current:
            break
        count += 1
    return current, count


def cycle(ind: dict[str, Series]) -> dict:
    """景氣循環位置：對策信號 + 領先指標轉折。"""
    scores = ind["signal_score"]
    light, streak = _light_streak(scores)
    leading = ind["leading"]
    up = _streak(leading, rising=True)
    down = _streak(leading, rising=False)
    return {
        "score": scores.last, "score_date": scores.last_date,
        "score_prev": scores.at(-2),
        "score_series": scores,
        "light": light, "light_meaning": ndc.LIGHT_MEANING.get(light or ""),
        "light_streak": streak,
        "leading": leading.last, "leading_date": leading.last_date,
        "leading_series": leading,
        # 連升與連降要分開講。連降 3 個月是轉折警訊；連升 12 個月不是
        # 「轉折」而是趨勢——把兩者合成一個布林值會讓最強的擴張看起來
        # 跟最早的衰退訊號一樣。
        "leading_up": up, "leading_down": down,
        "leading_falling": down >= LEADING_TURN_MONTHS,
        "leading_extending": up >= LEADING_TURN_MONTHS,
        "coincident": ind["coincident"].last,
        "coincident_series": ind["coincident"],
        "lagging": ind["lagging"].last,
        "lagging_series": ind["lagging"],
    }


def external(ind: dict[str, Series], bundle: Bundle) -> dict:
    """外需：外銷訂單、海關出口、資本財與半導體設備進口。"""
    exports = ind["exports"]
    exports_yoy = exports.yoy()
    negative = 0
    for value in reversed(exports_yoy.values):
        if value < 0:
            negative += 1
        else:
            break
    orders = ind["export_orders"]
    semi, semi_date = _yoy_last(ind["semi_equip"])
    capex, capex_date = _yoy_last(ind["capex_imports"])
    usd_exports = bundle["VALEXPTWM052N"]
    usd_imports = bundle["VALIMPTWM052N"]
    surplus = EMPTY
    if usd_exports and usd_imports:
        by_month = {(d.year, d.month): v
                    for d, v in zip(usd_imports.dates, usd_imports.values)}
        pairs = [(d, v - by_month[(d.year, d.month)])
                 for d, v in zip(usd_exports.dates, usd_exports.values)
                 if (d.year, d.month) in by_month]
        if pairs:
            surplus = Series.from_pairs(
                "TW_TRADE_BALANCE", pairs, label="台灣貿易出超", unit="百萬美元",
                frequency="m", source="IMF via FRED")
    return {
        "exports": exports.last, "exports_date": exports.last_date,
        "exports_yoy": exports_yoy.last, "exports_yoy_series": exports_yoy,
        "exports_negative_months": negative,
        "orders": orders.last, "orders_date": orders.last_date,
        "orders_series": orders,
        "orders_expanding": (orders.last is not None
                             and orders.last > EXPORT_ORDERS_MID),
        "semi_equip_yoy": semi, "semi_equip_date": semi_date,
        "semi_equip_series": ind["semi_equip"],
        "capex_yoy": capex, "capex_date": capex_date,
        "surplus": surplus.last, "surplus_series": surplus,
        "surplus_date": surplus.last_date,
    }


def output(ind: dict[str, Series]) -> dict:
    """生產與內需。"""
    industrial_yoy, industrial_date = _yoy_last(ind["industrial"])
    retail_yoy, retail_date = _yoy_last(ind["retail"])
    return {
        "industrial": ind["industrial"].last,
        "industrial_yoy": industrial_yoy, "industrial_date": industrial_date,
        "industrial_series": ind["industrial"],
        "mfg_sales": ind["mfg_sales"].last,
        "mfg_sales_date": ind["mfg_sales"].last_date,
        "retail_yoy": retail_yoy, "retail_date": retail_date,
        "retail_series": ind["retail"],
        "power": ind["power"].last, "power_date": ind["power"].last_date,
        "inventory_yoy": ind["inventory"].yoy().last,
        "inventory_date": ind["inventory"].last_date,
        "floor_area_yoy": ind["floor_area"].yoy().last,
        "floor_area_date": ind["floor_area"].last_date,
    }


def labour_prices(ind: dict[str, Series], cpi: dict[str, Series]) -> dict:
    """勞動與物價。"""
    unemployment = ind["unemployment"]
    recent = unemployment.tail(12)
    low = min(recent.values) if recent else None
    gap = (unemployment.last - low) if (unemployment.last is not None
                                        and low is not None) else None
    return {
        "unemployment": unemployment.last,
        "unemployment_date": unemployment.last_date,
        "unemployment_series": unemployment,
        "unemployment_low_12m": low, "unemployment_gap": gap,
        "overtime": ind["overtime"].last,
        "overtime_date": ind["overtime"].last_date,
        "overtime_series": ind["overtime"],
        "net_entry": ind["net_entry"].last,
        "net_entry_date": ind["net_entry"].last_date,
        "cpi_yoy": cpi["yoy"].last, "cpi_date": cpi["yoy"].last_date,
        "cpi_series": cpi["yoy"],
        "unit_labour_cost_yoy": ind["unit_labour_cost"].yoy().last,
        "unit_labour_cost_date": ind["unit_labour_cost"].last_date,
    }


def money(ind: dict[str, Series], rate: dict[str, Series],
          bundle: Bundle) -> dict:
    """資金與利率：央行政策利率、放款利率、M1B、放款與投資、匯率。"""
    m1b_yoy = ind["m1b"].yoy()
    credit_yoy = ind["credit"].yoy()
    policy = rate["monthly"]
    fed = bundle["DFEDTARU"]
    twd = bundle["DEXTAUS"]
    reer = bundle["RBTWBIS"]

    twd_1y = None
    if twd and twd.last is not None:
        year_ago = twd.at(-253)
        if year_ago:
            # 報價是「1 美元兌多少台幣」，數字變大＝台幣貶值。
            twd_1y = (twd.last / year_ago - 1) * 100

    return {
        "policy": policy.last, "policy_date": rate["changes"].last_date,
        "policy_series": policy,
        "policy_changes": rate["changes"],
        "policy_unchanged_months": (
            _months_between(rate["changes"].last_date, policy.last_date)
            if rate["changes"].last_date and policy.last_date else None),
        "fed_upper": fed.last,
        "spread_vs_fed": ((policy.last - fed.last)
                          if (policy.last is not None and fed.last is not None)
                          else None),
        "loan_rate": ind["loan_rate"].last,
        "loan_rate_date": ind["loan_rate"].last_date,
        "loan_rate_series": ind["loan_rate"],
        "m1b_yoy": m1b_yoy.last, "m1b_date": m1b_yoy.last_date,
        "m1b_series": m1b_yoy,
        "credit_yoy": credit_yoy.last, "credit_date": credit_yoy.last_date,
        "credit_series": credit_yoy,
        "twd": twd.last, "twd_date": twd.last_date, "twd_series": twd,
        "twd_chg_1y": twd_1y,
        "reer": reer.last, "reer_date": reer.last_date, "reer_series": reer,
        "reer_pct10y": reer.percentile_rank(10),
    }


def _months_between(start, end) -> int:
    return (end.year - start.year) * 12 + (end.month - start.month)


def gaps(ind: dict[str, Series], cpi: dict[str, Series],
         rate: dict[str, Series]) -> list[str]:
    """拿不到或這一輪沒抓到的東西，就地講明。"""
    missing = []
    if not ind.get("signal_score"):
        missing.append("國發會景氣指標整包抓不到（政府資料開放平臺或國發會下載區異常）")
    if not cpi.get("yoy"):
        missing.append("主計總處消費者物價指數抓不到")
    if not rate.get("changes"):
        missing.append("中央銀行貼放利率頁抓不到")
    return missing


def compute(bundle: Bundle) -> dict:
    ind = ndc.indicators()
    cpi = dgbas.cpi()
    rate = cbc.discount_rate()
    return {
        "cycle": cycle(ind),
        "external": external(ind, bundle),
        "output": output(ind),
        "labour": labour_prices(ind, cpi),
        "money": money(ind, rate, bundle),
        "series": ind,
        "gaps": gaps(ind, cpi, rate),
        # 每一區的資料日期不一樣，頁面各自標。這裡給的是「整頁最新的那一格」。
        "as_of": ind["signal_score"].last_date,
    }
