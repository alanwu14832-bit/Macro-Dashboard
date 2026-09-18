"""台灣總經。

站上原本只有台股的價格，沒有台灣的總經——部位在台股，判斷卻全部來自美國。
這個模組補的是後者：景氣循環位置、外需動能、生產與內需、勞動與物價、
資金與利率，全部來自台灣官方統計，不是從美國序列外推。

資料線：
  國發會       景氣對策信號、領先／同時／落後指標與其全部構成項目（月）
  主計總處     CPI（月）；總體統計資料庫的經濟成長率與 GDP 支出面（季）、
               轉載央行的 M1B／M2 與美元計價外匯存底（月）
  中央銀行     重貼現率（階梯，一年可能不動）
  財政部       積體電路出口、對美出口（月）
  勞動部       減班休息（無薪假）（月）
  經濟部統計處 外銷訂單金額（月）
外加 FRED 上仍在更新的四檔（BIS 有效匯率、IMF 進出口金額）與 DEXTAUS。

各序列的最新月份不一致是常態——財政部出口與內政部人口通常最快，
加班工時與用電量較慢，GDP 是季頻。每一格都帶自己的資料日期，不對齊到同一個月。
"""
from __future__ import annotations

from .. import cbc_board
from ..data import Bundle
from ..series import EMPTY, Series
from ..sources import cbc, moea, ndc, statdb, taiwan as dgbas

# ---- 本站門檻（國發會燈號分界除外，那是官方定義，寫在 sources/ndc.py）----
LEADING_TURN_MONTHS = 3      # 領先指標不含趨勢連續幾個月同向 = 轉折訊號
EXPORT_ORDERS_MID = 50.0     # 外銷訂單動向指數的擴張／收縮中線（官方定義）
UNEMPLOYMENT_RISE_PP = 0.3   # 失業率高出近 12 個月低點多少 = 勞動市場轉弱
EXPORT_WEAK_MONTHS = 3       # 海關出口年增率連續幾個月為負 = 外需衰退
M1B_STALL_PCT = 3.0          # M1B 年增率低於多少 = 市場資金動能轉弱

# 各部會統計資料庫的取用規格：(部會, 表代號, 欄位位置, 分類0, 分類1, 頻率, 起始年)
# 位置是向 sys=212 表定義查來的。取序列一律用下面 OFFICIAL 裡的標籤——
# 位置錯了標籤就對不上、序列是空的，而不是悄悄變成隔壁那一欄。
TABLES = {
    "money":    ("dgbas", "A090501010", [0], [13, 14], [], "m", 1997),
    "reserves": ("dgbas", "A093102020", [0], [], [], "m", 1997),
    "gdp":      ("dgbas", "A018101010", [2], [], [], "q", 1981),
    "spending": ("dgbas", "A018102060", [1], [0, 3], [], "q", 1981),
    "goods":    ("mof", "i9401", [0], [0], [0, 29], "m", 2001),
    "country":  ("mof", "i9111", [0], [0, 94], [0], "m", 2001),
    "furlough": ("mol", "a06062", [5, 7], [0], [], "m", 2020),
}
_REAL = "連鎖實質值(2021為參考年_新臺幣百萬元)_"
OFFICIAL = {
    "m1b":              ("money", "日平均數_貨幣總計數-M1B"),
    "m2":               ("money", "日平均數_貨幣總計數-M2"),
    "fx_reserves":      ("reserves", "外匯存底(期底數)"),
    "gdp_growth":       ("gdp", "經濟成長率(%)"),
    "real_consumption": ("spending", _REAL + "1.民間消費"),
    "real_investment":  ("spending", _REAL + "3.1固定資本形成"),
    "exports_total":    ("goods", "按美元計算(千美元)_出口_總計"),
    "exports_ic":       ("goods", "按美元計算(千美元)_出口_2611積體電路製造業"),
    "exports_world":    ("country", "按美元計算(千美元)_總計_出口"),
    "exports_us":       ("country", "按美元計算(千美元)_美國_出口"),
    "furlough_firms":   ("furlough", "事業單位家數－月底"),
    "furlough_workers": ("furlough", "實施人數－月底"),
}
TABLE_GAPS = {
    "money": "主計總處總體統計資料庫的貨幣總計數（M1B／M2）",
    "reserves": "主計總處總體統計資料庫的外匯存底",
    "gdp": "主計總處總體統計資料庫的經濟成長率",
    "spending": "主計總處總體統計資料庫的 GDP 支出面",
    "goods": "財政部統計資料庫的貨品別出口",
    "country": "財政部統計資料庫的國別出口",
    "furlough": "勞動部統計資料庫的減班休息（無薪假）",
}


def official() -> dict[str, Series]:
    tables = {key: statdb.table(agency, funid, fields=fields, codes0=codes0,
                                codes1=codes1, freq=freq, start_year=start)
              for key, (agency, funid, fields, codes0, codes1, freq, start)
              in TABLES.items()}
    out = {code: tables[table].get(name, EMPTY)
           for code, (table, name) in OFFICIAL.items()}
    out["orders_usd"] = moea.export_orders()["usd"]
    return out


def _gov(gov: dict | None, key: str) -> Series:
    return (gov or {}).get(key) or EMPTY


def _by_month(series: Series) -> dict[tuple[int, int], float]:
    return {(d.year, d.month): v for d, v in zip(series.dates, series.values)}


def _combine(left: Series, right: Series, fn, series_id: str, **kwargs) -> Series:
    """同一個月的兩個值組成一個新值；任一邊缺那個月就不產生點。"""
    other = _by_month(right)
    pairs = []
    for d, v in zip(left.dates, left.values):
        base = other.get((d.year, d.month))
        if base is None:
            continue
        value = fn(v, base)
        if value is not None:
            pairs.append((d, value))
    if not pairs:
        return EMPTY
    return Series.from_pairs(series_id, pairs, frequency=left.frequency or "m",
                             **kwargs)


def _share(part: float, whole: float) -> float | None:
    return part / whole * 100 if whole else None


def _negative_run(series: Series) -> int:
    count = 0
    for value in reversed(series.values):
        if value >= 0:
            break
        count += 1
    return count


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


def external(ind: dict[str, Series], bundle: Bundle,
             gov: dict | None = None) -> dict:
    """外需：外銷訂單（家數與金額）、海關出口、積體電路與對美出口、資本財進口。"""
    exports = ind["exports"]
    exports_yoy = exports.yoy()
    orders = ind["export_orders"]
    semi, semi_date = _yoy_last(ind["semi_equip"])
    capex, capex_date = _yoy_last(ind["capex_imports"])

    surplus = _combine(bundle["VALEXPTWM052N"], bundle["VALIMPTWM052N"],
                       lambda x, m: x - m, "TW_TRADE_BALANCE",
                       label="台灣貿易出超", unit="百萬美元",
                       source="IMF via FRED")

    amount = _gov(gov, "orders_usd")
    amount_yoy = amount.yoy()
    ic = _gov(gov, "exports_ic")
    ic_yoy = ic.yoy()
    ic_share = _combine(ic, _gov(gov, "exports_total"), _share, "TW_IC_SHARE",
                        label="積體電路佔總出口", unit="%")
    us_share = _combine(_gov(gov, "exports_us"), _gov(gov, "exports_world"),
                        _share, "TW_US_SHARE", label="對美出口佔總出口", unit="%")
    us_prior = None
    if us_share.last_date:
        us_prior = _by_month(us_share).get((us_share.last_date.year - 1,
                                             us_share.last_date.month))

    return {
        "exports": exports.last, "exports_date": exports.last_date,
        "exports_yoy": exports_yoy.last, "exports_yoy_series": exports_yoy,
        "exports_negative_months": _negative_run(exports_yoy),
        "orders": orders.last, "orders_date": orders.last_date,
        "orders_series": orders,
        "orders_expanding": (orders.last is not None
                             and orders.last > EXPORT_ORDERS_MID),
        "orders_amount": amount.last, "orders_amount_date": amount.last_date,
        "orders_amount_yoy": amount_yoy.last,
        "orders_amount_yoy_series": amount_yoy,
        "ic_exports": ic.last, "ic_yoy": ic_yoy.last, "ic_date": ic.last_date,
        "ic_share": ic_share.last, "ic_share_series": ic_share,
        "us_share": us_share.last, "us_share_date": us_share.last_date,
        "us_share_prior": us_prior, "us_share_series": us_share,
        "semi_equip_yoy": semi, "semi_equip_date": semi_date,
        "semi_equip_series": ind["semi_equip"],
        "capex_yoy": capex, "capex_date": capex_date,
        "surplus": surplus.last, "surplus_series": surplus,
        "surplus_date": surplus.last_date,
    }


def output(ind: dict[str, Series], gov: dict | None = None) -> dict:
    """GDP、生產與內需。"""
    industrial_yoy, industrial_date = _yoy_last(ind["industrial"])
    retail_yoy, retail_date = _yoy_last(ind["retail"])
    growth = _gov(gov, "gdp_growth")
    consumption_yoy, consumption_date = _yoy_last(_gov(gov, "real_consumption"))
    investment_yoy, investment_date = _yoy_last(_gov(gov, "real_investment"))
    return {
        "gdp_growth": growth.last, "gdp_date": growth.last_date,
        "gdp_series": growth,
        "consumption_yoy": consumption_yoy, "consumption_date": consumption_date,
        "investment_yoy": investment_yoy, "investment_date": investment_date,
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


def labour_prices(ind: dict[str, Series], cpi: dict[str, Series],
                  gov: dict | None = None) -> dict:
    """勞動與物價。"""
    unemployment = ind["unemployment"]
    recent = unemployment.tail(12)
    low = min(recent.values) if recent else None
    gap = (unemployment.last - low) if (unemployment.last is not None
                                        and low is not None) else None
    workers = _gov(gov, "furlough_workers")
    firms = _gov(gov, "furlough_firms")
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
        "furlough_workers": workers.last, "furlough_firms": firms.last,
        "furlough_date": workers.last_date, "furlough_series": workers,
        "cpi_yoy": cpi["yoy"].last, "cpi_date": cpi["yoy"].last_date,
        "cpi_series": cpi["yoy"],
        "unit_labour_cost_yoy": ind["unit_labour_cost"].yoy().last,
        "unit_labour_cost_date": ind["unit_labour_cost"].last_date,
    }


def money(ind: dict[str, Series], rate: dict[str, Series], bundle: Bundle,
          gov: dict | None = None) -> dict:
    """資金與利率：央行政策利率、放款利率、M1B 與 M2、外匯存底、匯率。"""
    # 主計總處轉載的 M1B 與國發會構成項目裡的是同一個數（日平均數），
    # 前者抓不到時退回後者；M2 只有前者有。
    m1b_yoy = (_gov(gov, "m1b") or ind["m1b"]).yoy()
    m2_yoy = _gov(gov, "m2").yoy()
    spread = _combine(m1b_yoy, m2_yoy, lambda a, b: a - b, "TW_M1B_M2",
                      label="M1B 減 M2 年增率", unit="個百分點")
    credit_yoy = ind["credit"].yoy()
    policy = rate["monthly"]
    fed = bundle["DFEDTARU"]
    twd = bundle["DEXTAUS"]
    reer = bundle["RBTWBIS"]
    reserves = _gov(gov, "fx_reserves")

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
        # 貼放利率表還沒補上時由決議新聞稿校正（cbc_board.reconcile_discount）
        "policy_source": (rate["changes"].meta or {}).get("patched_from"),
        "policy_unchanged_months": (
            _months_between(rate["changes"].last_date, policy.last_date)
            if rate["changes"].last_date and policy.last_date else None),
        "fed_upper": fed.last,
        "fed_source": (fed.meta or {}).get("patched_from"),
        "spread_vs_fed": ((policy.last - fed.last)
                          if (policy.last is not None and fed.last is not None)
                          else None),
        "loan_rate": ind["loan_rate"].last,
        "loan_rate_date": ind["loan_rate"].last_date,
        "loan_rate_series": ind["loan_rate"],
        "m1b_yoy": m1b_yoy.last, "m1b_date": m1b_yoy.last_date,
        "m1b_series": m1b_yoy,
        "m2_yoy": m2_yoy.last, "m2_series": m2_yoy,
        "m1b_m2_spread": spread.last, "m1b_m2_date": spread.last_date,
        "m1b_m2_negative_months": _negative_run(spread),
        "credit_yoy": credit_yoy.last, "credit_date": credit_yoy.last_date,
        "credit_series": credit_yoy,
        "fx_reserves": reserves.last, "fx_reserves_date": reserves.last_date,
        "fx_reserves_change": reserves.change_over(1),
        "fx_reserves_series": reserves,
        "twd": twd.last, "twd_date": twd.last_date, "twd_series": twd,
        "twd_chg_1y": twd_1y,
        "reer": reer.last, "reer_date": reer.last_date, "reer_series": reer,
        "reer_pct10y": reer.percentile_rank(10),
    }


def _months_between(start, end) -> int:
    return (end.year - start.year) * 12 + (end.month - start.month)


def gaps(ind: dict[str, Series], cpi: dict[str, Series],
         rate: dict[str, Series], gov: dict | None = None) -> list[str]:
    """這一輪沒抓到的東西，就地講明。"""
    missing = []
    if not ind.get("signal_score"):
        missing.append("國發會景氣指標整包抓不到（政府資料開放平臺或國發會下載區異常）")
    if not cpi.get("yoy"):
        missing.append("主計總處消費者物價指數抓不到")
    if not rate.get("changes"):
        missing.append("中央銀行貼放利率頁抓不到")
    if gov is not None:
        seen = []
        for code, (table, _name) in OFFICIAL.items():
            if not gov.get(code) and table not in seen:
                seen.append(table)
                missing.append(f"{TABLE_GAPS[table]}這一輪沒有取得"
                               f"（伺服器沒回應，或表格欄位已改版）")
        if not gov.get("orders_usd"):
            missing.append("經濟部統計處的外銷訂單金額這一輪沒有取得")
    return missing


def compute(bundle: Bundle) -> dict:
    ind = ndc.indicators()
    cpi = dgbas.cpi()
    rate = cbc.discount_rate()
    # 央行 RSS 約 3 MB，一次建置只抓一次：決議與會議日程共用
    news = cbc.news_items()
    decision = cbc.latest_board_decision(items=news)
    schedule = cbc.board_schedule(items=news)
    rate, patch = cbc_board.reconcile_discount(rate, decision)
    gov = official()
    return {
        "cbc_decision": decision, "cbc_patch": patch, "cbc_schedule": schedule,
        "cycle": cycle(ind),
        "external": external(ind, bundle, gov),
        "output": output(ind, gov),
        "labour": labour_prices(ind, cpi, gov),
        "money": money(ind, rate, bundle, gov),
        "series": ind,
        "gaps": gaps(ind, cpi, rate, gov),
        # 每一區的資料日期不一樣，頁面各自標。這裡給的是「整頁最新的那一格」。
        "as_of": ind["signal_score"].last_date,
    }
