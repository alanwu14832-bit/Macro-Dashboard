"""台灣總經頁。

站上的部位在台股，判斷卻一直來自美國。這一頁補的是台灣自己的循環：
景氣位置、外需、生產與內需、勞動與物價、資金與利率。

排序不是照資料來源，是照傳導順序——外銷訂單先動，接著海關出口與工業生產，
再來是勞動與物價，最後才是利率與資金。讀者由上往下讀，讀到的是一條鏈。
"""
from __future__ import annotations

from ..common import glossary, line_chart, signals_block
from ..html import (accordion, callout, delta_span, esc, fmt, kv, pct, section,
                    stat, table, zh_date)

LIGHT_CLASS = {"紅": "hawkish", "黃紅": "hawkish", "綠": "neutral",
               "黃藍": "dovish", "藍": "dovish"}


def _n(value, digits=1, suffix="", signed=False):
    """沒有值就畫破折號，不留白也不補前值。"""
    if value is None:
        return '<span class="muted">—</span>'
    return fmt(value, digits, suffix=suffix, signed=signed)


def _verdict(cycle: dict) -> str:
    light, score = cycle.get("light"), cycle.get("score")
    if light is None or score is None:
        return callout("國發會景氣指標這一輪沒有取得，本頁的循環判斷留白。", key=True)
    streak = cycle.get("light_streak") or 0
    lead_up, lead_down = cycle.get("leading_up") or 0, cycle.get("leading_down") or 0
    if lead_down >= 3:
        trend = f"領先指標已連續 {lead_down} 個月下滑，轉折訊號成立"
    elif lead_up >= 3:
        trend = f"領先指標連續 {lead_up} 個月走高，擴張仍在延續"
    else:
        trend = "領先指標方向未定，連續同向不足三個月"
    return callout(
        f'台灣景氣目前亮<strong>{esc(light)}燈</strong>'
        f'（{esc(cycle.get("light_meaning") or "")}），綜合分數 '
        f'<strong>{score:.0f}</strong> 分，同一顏色已連續 {streak} 個月。{esc(trend)}。',
        key=True)


def render(ctx: dict, signals: list[dict] | None = None) -> str:
    d = ctx.get("taiwan") or {}
    if not d:
        return section("unavailable", "台灣總經",
                       callout("台灣總經模組這一輪沒有計算成功。", key=True))
    cycle, ext = d["cycle"], d["external"]
    out, lab, money = d["output"], d["labour"], d["money"]
    body = []

    # ---- 1. 景氣循環位置 ----
    tiles = [
        stat("景氣對策信號", _n(cycle["score"], 0, suffix=" 分"),
             delta=(f'{cycle["light"]}燈' if cycle["light"] else ""),
             asof=f'{zh_date(cycle["score_date"])}　同色連續 {cycle["light_streak"]} 個月',
             spark=[(dt.isoformat(), v) for dt, v in
                    cycle["score_series"].tail(60).pairs()]),
        stat("領先指標（不含趨勢）", _n(cycle["leading"], 2),
             delta=(f'連升 {cycle["leading_up"]} 個月' if cycle["leading_up"]
                    else f'連降 {cycle["leading_down"]} 個月'),
             asof=zh_date(cycle["leading_date"])),
        stat("同時指標（不含趨勢）", _n(cycle["coincident"], 2),
             delta="反映當下景氣"),
        stat("落後指標（不含趨勢）", _n(cycle["lagging"], 2),
             delta="失業率與放款成本落在這一組"),
    ]
    body.append(section(
        "cycle", "景氣循環位置",
        f'<div class="grid grid-4">{"".join(tiles)}</div>'
        + _verdict(cycle)
        + line_chart("景氣對策信號綜合分數",
                     [(cycle["score_series"], "綜合分數", "series-1")],
                     years=25, default_years=10, digits=0, freq="m",
                     band=[23, 31],
                     sub="陰影是綠燈區間（23–31 分）＝景氣穩定。往上依序是"
                         "黃紅 32–37、紅 38–45，往下是黃藍 17–22、藍 9–16")
        + line_chart("領先、同時與落後指標（不含趨勢）",
                     [(cycle["leading_series"], "領先", "series-1"),
                      (cycle["coincident_series"], "同時", "series-3"),
                      (cycle["lagging_series"], "落後", "series-8")],
                     years=25, default_years=8, digits=1, freq="m",
                     sub="三條線的先後順序就是景氣傳導的順序"),
        note="分數與燈號的分界由國發會定義，本站不調整",
        terms=["tw_signal_light", "tw_leading_index"]))

    # ---- 2. 外需 ----
    ext_rows = [
        ["外銷訂單動向指數", _n(ext["orders"], 1),
         ("看增家數多於看減" if ext["orders_expanding"] else "看減家數多於看增"),
         zh_date(ext["orders_date"])],
        ["海關出口值　年增", delta_span(ext["exports_yoy"], 1, suffix="%"),
         f'{_n(ext["exports"], 0)} 十億元', zh_date(ext["exports_date"])],
        ["半導體設備進口　年增", delta_span(ext["semi_equip_yoy"], 1, suffix="%"),
         "未來產能，領先出口約一年", zh_date(ext["semi_equip_date"])],
        ["機電設備進口　年增", delta_span(ext["capex_yoy"], 1, suffix="%"),
         "民間資本支出的即時代理", zh_date(ext["capex_date"])],
        ["貿易出超", _n(ext["surplus"], 0, suffix=" 百萬美元"),
         "出口減進口，IMF 統計", zh_date(ext["surplus_date"])],
    ]
    body.append(section(
        "external", "外需",
        table(["指標", "讀數", "說明", "資料日期"], ext_rows,
              foot="外銷訂單動向指數以回報家數編製，50 是擴張與收縮的分界——"
                   "它衡量的是廠商看增或看減的家數比例，不是金額。")
        + line_chart("海關出口值年增率",
                     [(ext["exports_yoy_series"], "海關出口年增", "series-1")],
                     years=20, default_years=8, digits=1, freq="m",
                     include_zero=True,
                     sub="出口佔台灣 GDP 六成以上，這條線是台股企業獲利的上游"),
        note="外銷訂單領先海關出口約一到三個月",
        terms=["tw_export_orders"]))

    # ---- 3. 生產與內需 ----
    out_rows = [
        ["工業生產指數　年增", delta_span(out["industrial_yoy"], 1, suffix="%"),
         f'指數 {_n(out["industrial"], 1)}', zh_date(out["industrial_date"])],
        ["批發、零售及餐飲營業額　年增", delta_span(out["retail_yoy"], 1, suffix="%"),
         "內需消費", zh_date(out["retail_date"])],
        ["製造業銷售量指數", _n(out["mfg_sales"], 1),
         "2021＝100", zh_date(out["mfg_sales_date"])],
        ["製造業存貨價值　年增", delta_span(out["inventory_yoy"], 1, suffix="%"),
         "存貨增加快於銷售＝庫存堆積", zh_date(out["inventory_date"])],
        ["建築物開工樓地板面積　年增", delta_span(out["floor_area_yoy"], 1, suffix="%"),
         "營建循環", zh_date(out["floor_area_date"])],
        ["企業總用電量", _n(out["power"], 2, suffix=" 十億度"),
         "產出的實體對照", zh_date(out["power_date"])],
    ]
    body.append(section(
        "output", "生產與內需",
        table(["指標", "讀數", "說明", "資料日期"], out_rows)
        + line_chart("工業生產與批發零售餐飲營業額",
                     [(out["industrial_series"], "工業生產指數", "series-1"),
                      (out["retail_series"], "批發零售餐飲（十億元）", "series-3")],
                     years=15, default_years=6, digits=1, freq="m",
                     series_axes=[None, "right"], right_suffix=" 十億元",
                     sub="外需帶動生產，生產帶動所得，所得才輪到內需"),
        note="用電量與加班工時通常比出口晚一個月公布，這裡各標各的日期"))

    # ---- 4. 勞動與物價 ----
    tiles = [
        stat("失業率", _n(lab["unemployment"], 2, suffix="%"),
             delta=(f'近 12 個月低點 {lab["unemployment_low_12m"]:.2f}%'
                    if lab["unemployment_low_12m"] is not None else ""),
             asof=zh_date(lab["unemployment_date"]),
             spark=[(dt.isoformat(), v) for dt, v in
                    lab["unemployment_series"].tail(60).pairs()]),
        stat("CPI 年增率", _n(lab["cpi_yoy"], 2, suffix="%"),
             delta="主計總處總指數", asof=zh_date(lab["cpi_date"])),
        stat("加班工時", _n(lab["overtime"], 1, suffix=" 小時"),
             delta="加班先減，才輪到減員", asof=zh_date(lab["overtime_date"])),
        stat("單位產出勞動成本　年增", _n(lab["unit_labour_cost_yoy"], 1,
                                  suffix="%", signed=True),
             delta="成本傳導到物價的那一段",
             asof=zh_date(lab["unit_labour_cost_date"])),
    ]
    body.append(section(
        "labour", "勞動與物價",
        f'<div class="grid grid-4">{"".join(tiles)}</div>'
        + line_chart("失業率與 CPI 年增率",
                     [(lab["unemployment_series"], "失業率", "series-1"),
                      (lab["cpi_series"], "CPI 年增率", "series-8")],
                     years=20, default_years=8, digits=2, freq="m",
                     sub="台灣失業率的波動遠小於美國，讀它要看離低點多遠，"
                         "不是看絕對水準"),
        note="失業率取自國發會落後指標構成項目，CPI 取自主計總處",
        terms=["tw_unemployment"]))

    # ---- 5. 資金與利率 ----
    unchanged = money.get("policy_unchanged_months")
    tiles = [
        stat("央行重貼現率", _n(money["policy"], 3, suffix="%"),
             delta=(f'已 {unchanged} 個月未調整' if unchanged else ""),
             asof=(f'最近一次調整 {zh_date(money["policy_date"], freq="d")}'
                   if money["policy_date"] else "")),
        stat("台美政策利差", _n(money["spread_vs_fed"], 2, suffix="pp", signed=True),
             delta=f'聯準會上緣 {_n(money["fed_upper"], 2, suffix="%")}',
             asof="負值＝台灣利率低於美國，利差不利台幣"),
        stat("M1B 年增率", _n(money["m1b_yoy"], 2, suffix="%", signed=True),
             delta="活存加通貨，台股的可動用資金",
             asof=zh_date(money["m1b_date"]),
             spark=[(dt.isoformat(), v) for dt, v in
                    money["m1b_series"].tail(60).pairs()]),
        stat("美元兌新台幣", _n(money["twd"], 3),
             delta=f'近一年 {_n(money["twd_chg_1y"], 1, suffix="%", signed=True)}',
             asof=f'{zh_date(money["twd_date"], freq="d")}　數字變大＝台幣貶值'),
    ]
    money_rows = [
        ["五大銀行新承做放款平均利率", _n(money["loan_rate"], 3, suffix="%"),
         "企業實際借到的價格", zh_date(money["loan_rate_date"])],
        ["全體金融機構放款與投資　年增", delta_span(money["credit_yoy"], 2, suffix="%"),
         "信用擴張的總量", zh_date(money["credit_date"])],
        ["實質有效匯率指數", _n(money["reer"], 2),
         f'十年百分位 {_n(money["reer_pct10y"], 0, suffix="%")}　BIS 編製，2020＝100',
         zh_date(money["reer_date"])],
    ]
    body.append(section(
        "money", "資金與利率",
        f'<div class="grid grid-4">{"".join(tiles)}</div>'
        + table(["指標", "讀數", "說明", "資料日期"], money_rows)
        + line_chart("央行重貼現率與五大銀行新承做放款利率",
                     [(money["policy_series"], "重貼現率", "series-1"),
                      (money["loan_rate_series"], "五大銀行放款利率", "series-3")],
                     years=25, default_years=10, digits=3, freq="m",
                     sub="政策利率是階梯——兩次決策之間它就是不動，圖上按月展開"
                         "水準，不在決策之間內插")
        + line_chart("M1B 年增率",
                     [(money["m1b_series"], "M1B 年增率", "series-1")],
                     years=25, default_years=10, digits=1, freq="m",
                     include_zero=True,
                     sub="台股慣用的資金面指標。年增率轉負代表資金淨流出活存"),
        note="重貼現率解析自中央銀行「央行貼放利率」頁，M1B 與放款投資取自國發會",
        terms=["tw_m1b", "tw_policy_rate"]))

    # ---- 6. 台灣訊號 ----
    tw_signals = [s for s in (signals or []) if s.get("module") == "台灣"]
    if tw_signals:
        body.append(section(
            "signals", "台灣觸發的規則",
            signals_block(tw_signals)
            + callout("台灣的規則一律不標鷹派或鴿派——那兩個顏色在本站專指"
                      "聯準會的政策方向。台灣的景氣循環不是聯準會決策的理由，"
                      "讓它去推動總覽的判斷會讓結論被無關的資訊帶走。"),
            note="門檻寫死在 macro/compute/signals.py，同一份資料每次執行結果一致"))

    # ---- 7. 缺口與來源 ----
    gaps = d.get("gaps") or []
    gap_html = ""
    if gaps:
        gap_html = ('<ul style="color:var(--ink-2);margin:0 0 12px">'
                    + "".join(f"<li>{esc(g)}</li>" for g in gaps) + "</ul>")
    body.append(section(
        "notes", "拿不到什麼",
        f'<div class="card">{gap_html}'
        + kv([
            ("台灣 GDP", "主計總處只以季頻發布且沒有穩定的免費 API，本站不收。"
                        "月頻的替代是同時指標與工業生產指數。"),
            ("M2 與貨幣總計數全表", "國發會只在領先指標構成項目裡提供 M1B。"
                                "常見的「M1B 與 M2 黃金交叉」因此畫不出來，"
                                "本站改看 M1B 年增率本身。"),
            ("外匯存底", "FRED 上的台灣外匯存底以 SDR 計價，換算成美元會讓讀者"
                       "誤讀，本站不收。"),
            ("融資維持率", "證交所與櫃買中心不公開，本站在台股頁已標明。"),
            ("景氣指標的修正", "國發會每月回溯修正歷史值，本站每次建置重抓整包，"
                          "所以圖上的歷史會跟著官方一起變。"),
        ])
        + "</div>"
        + accordion("資料來源與名詞", glossary([
            ("景氣對策信號", "國發會編製的九項指標綜合分數，9–45 分對應藍、黃藍、"
                        "綠、黃紅、紅五個燈號。分界是官方定義，本站原樣使用。"),
            ("領先指標（不含趨勢）", "七項領先性指標的綜合指數，剔除長期趨勢後"
                            "只留循環成分。轉折通常早於同時指標數個月。"),
            ("外銷訂單動向指數", "以回報家數編製的擴散指數，50 為分界。"
                        "它測的是看增家數多還是看減家數多，不是訂單金額。"),
            ("M1B", "通貨淨額加支票存款、活期存款與活期儲蓄存款——可立即動用的錢。"
                   "台股慣用它衡量市場資金動能。"),
            ("重貼現率", "中央銀行對金融機構融通的基準利率，是台灣的政策利率。"
                    "它是階梯函數，一年可能一次都不調整。"),
            ("實質有效匯率", "BIS 編製，對主要貿易對手的加權匯率再扣掉相對物價。"
                      "指數走高代表出口相對變貴。"),
            ("為什麼各格的日期不一樣", "台灣各項統計的公布時程本來就不同："
                          "海關出口與失業率較快，用電量與加班工時較慢。"
                          "本站不對齊到同一個月，各標各的。"),
        ]))))

    return "".join(body)
