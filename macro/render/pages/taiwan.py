"""台灣總經頁。

站上的部位在台股，判斷卻一直來自美國。這一頁補的是台灣自己的循環：
景氣位置、外需、GDP 與內需、勞動與物價、資金與利率。

排序不是照資料來源，是照傳導順序——外銷訂單先動，接著海關出口與工業生產，
再來是勞動與物價，最後才是利率與資金。讀者由上往下讀，讀到的是一條鏈。
"""
from __future__ import annotations

from ..common import glossary, line_chart, signals_block
from ..html import (accordion, callout, delta_span, esc, fmt, kv, section,
                    stat, table, zh_date)


def _n(value, digits=1, suffix="", signed=False):
    """沒有值就畫破折號，不留白也不補前值。"""
    if value is None:
        return '<span class="muted">—</span>'
    return fmt(value, digits, suffix=suffix, signed=signed)


def _hundred(value):
    """百萬美元 -> 億美元。"""
    return None if value is None else value / 100


def _board_callout(state: dict | None) -> str:
    """理監事會決議用中文講在資金與利率最上面。只看貼放利率表的話，利率不變、
    調準備率、調房貸成數這些決議全部看不到。"""
    if not state:
        return ""
    if state.get("state") == "announced":
        lines = "；".join(state.get("details") or [])
        return callout(
            f'<strong>{esc(state["headline"])}</strong>　{esc(state["date"])} 理監事會決議'
            + (f'：{esc(lines)}' if lines else "")
            + f'。<a href="{esc(state["url"])}" target="_blank" rel="noopener noreferrer">決議新聞稿</a>',
            key=True)
    if state.get("state") == "missing":
        return callout(
            f'<strong>{esc(state["meeting"])} 的理監事會決議本站沒有取得</strong>：'
            f'{esc(state["reason"])}。重貼現率可能仍是舊值，請以央行公告為準。', key=True)
    if state.get("state") == "pending":
        return callout(f'今天（{esc(state["meeting"])}）央行理監事會，約 16:30 公布決議。')
    return ""


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
        ["外銷訂單金額　年增", delta_span(ext["orders_amount_yoy"], 1, suffix="%"),
         f'{_n(_hundred(ext["orders_amount"]), 1, suffix=" 億美元")}',
         zh_date(ext["orders_amount_date"])],
        ["海關出口值　年增", delta_span(ext["exports_yoy"], 1, suffix="%"),
         f'{_n(ext["exports"], 0)} 十億元', zh_date(ext["exports_date"])],
        ["積體電路出口　年增", delta_span(ext["ic_yoy"], 1, suffix="%"),
         f'佔總出口 {_n(ext["ic_share"], 1, suffix="%")}', zh_date(ext["ic_date"])],
        ["對美出口佔總出口", _n(ext["us_share"], 1, suffix="%"),
         f'一年前 {_n(ext["us_share_prior"], 1, suffix="%")}',
         zh_date(ext["us_share_date"])],
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
              foot="外銷訂單動向指數以回報家數編製，50 是分界，測的是看增家數的比例；"
                   "外銷訂單金額才是訂單的規模。金額大漲而動向指數低於 50，代表成長"
                   "集中在少數大廠。")
        + line_chart("海關出口值與外銷訂單金額年增率",
                     [(ext["exports_yoy_series"], "海關出口年增", "series-1"),
                      (ext["orders_amount_yoy_series"], "外銷訂單金額年增", "series-3")],
                     years=20, default_years=8, digits=1, freq="m",
                     include_zero=True,
                     sub="訂單領先出口約一到三個月。出口佔台灣 GDP 六成以上，"
                         "這兩條線是台股企業獲利的上游"),
        note="海關出口與積體電路出口取自財政部，外銷訂單金額取自經濟部統計處",
        terms=["tw_export_orders"]))

    # ---- 3. GDP、生產與內需 ----
    out_rows = [
        ["經濟成長率（實質 GDP 年增）", delta_span(out["gdp_growth"], 2, suffix="%"),
         "季頻，約季後一個月公布", zh_date(out["gdp_date"], freq="q")],
        ["實質民間消費　年增", delta_span(out["consumption_yoy"], 1, suffix="%"),
         "內需", zh_date(out["consumption_date"], freq="q")],
        ["實質固定資本形成　年增", delta_span(out["investment_yoy"], 1, suffix="%"),
         "投資循環", zh_date(out["investment_date"], freq="q")],
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
        "output", "GDP、生產與內需",
        table(["指標", "讀數", "說明", "資料日期"], out_rows)
        + line_chart("經濟成長率",
                     [(out["gdp_series"], "實質 GDP 年增", "series-1")],
                     years=25, default_years=10, digits=2, freq="q",
                     include_zero=True,
                     sub="主計總處按季發布。季與季之間的判斷仍靠工業生產與同時指標")
        + line_chart("工業生產與批發零售餐飲營業額",
                     [(out["industrial_series"], "工業生產指數", "series-1"),
                      (out["retail_series"], "批發零售餐飲（十億元）", "series-3")],
                     years=15, default_years=6, digits=1, freq="m",
                     series_axes=[None, "right"], right_suffix=" 十億元",
                     sub="外需帶動生產，生產帶動所得，所得才輪到內需"),
        note="GDP 是季頻、其餘是月頻，用電量與加班工時通常比出口晚一個月，各標各的日期"))

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
        stat("無薪假實施人數", _n(lab["furlough_workers"], 0, suffix=" 人"),
             delta=(f'{_n(lab["furlough_firms"], 0)} 家事業單位'
                    if lab["furlough_firms"] is not None else ""),
             asof=zh_date(lab["furlough_date"])),
    ]
    body.append(section(
        "labour", "勞動與物價",
        f'<div class="grid grid-4">{"".join(tiles)}</div>'
        + table(["指標", "讀數", "說明", "資料日期"], [
            ["單位產出勞動成本　年增",
             _n(lab["unit_labour_cost_yoy"], 1, suffix="%", signed=True),
             "成本傳導到物價的那一段", zh_date(lab["unit_labour_cost_date"])],
            ["工業及服務業受僱員工淨進入率", _n(lab["net_entry"], 2, suffix="%"),
             "進入率減退出率", zh_date(lab["net_entry_date"])],
        ])
        + line_chart("失業率與 CPI 年增率",
                     [(lab["unemployment_series"], "失業率", "series-1"),
                      (lab["cpi_series"], "CPI 年增率", "series-8")],
                     years=20, default_years=8, digits=2, freq="m",
                     sub="台灣失業率的波動遠小於美國，讀它要看離低點多遠，"
                         "不是看絕對水準")
        + line_chart("無薪假實施人數",
                     [(lab["furlough_series"], "實施人數（月底）", "series-1")],
                     years=10, default_years=5, digits=0, freq="m",
                     sub="勞雇雙方協商減少工時的通報。企業先減班才裁員，所以它比失業率"
                         "早轉折；2020 年 3 月以前的口徑不同，不接"),
        note="失業率取自國發會落後指標構成項目，CPI 取自主計總處，無薪假取自勞動部",
        terms=["tw_unemployment", "tw_furlough"]))

    # ---- 5. 資金與利率 ----
    unchanged = money.get("policy_unchanged_months")
    source = money.get("policy_source")
    tiles = [
        stat("央行重貼現率", _n(money["policy"], 3, suffix="%"),
             delta=(f'已 {unchanged} 個月未調整' if unchanged else ""),
             asof=(f'依 {esc(source["statement"])} 理監事會決議，貼放利率表尚未更新'
                   if source else
                   f'最近一次調整 {zh_date(money["policy_date"], freq="d")}'
                   if money["policy_date"] else "")),
        stat("台美政策利差", _n(money["spread_vs_fed"], 2, suffix="pp", signed=True),
             delta=f'聯準會上緣 {_n(money["fed_upper"], 2, suffix="%")}',
             asof="負值＝台灣利率低於美國，利差不利台幣"),
        stat("M1B 減 M2 年增率", _n(money["m1b_m2_spread"], 2, suffix="pp", signed=True),
             delta=(f'M1B {_n(money["m1b_yoy"], 2, suffix="%")}　'
                    f'M2 {_n(money["m2_yoy"], 2, suffix="%")}'),
             asof=zh_date(money["m1b_m2_date"])),
        stat("美元兌新台幣", _n(money["twd"], 3),
             delta=f'近一年 {_n(money["twd_chg_1y"], 1, suffix="%", signed=True)}',
             asof=f'{zh_date(money["twd_date"], freq="d")}　數字變大＝台幣貶值'),
    ]
    reserves_change = money.get("fx_reserves_change")
    money_rows = [
        ["外匯存底", _n(_hundred(money["fx_reserves"]), 1, suffix=" 億美元"),
         (f'較上月 {_n(_hundred(reserves_change), 1, suffix=" 億美元", signed=True)}'
          if reserves_change is not None else "美元計價，央行統計"),
         zh_date(money["fx_reserves_date"])],
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
        _board_callout(ctx.get("cbc"))
        + f'<div class="grid grid-4">{"".join(tiles)}</div>'
        + table(["指標", "讀數", "說明", "資料日期"], money_rows,
                foot="外匯存底取自統計資料庫，比央行每月初的新聞稿慢一期。")
        + line_chart("M1B 與 M2 年增率",
                     [(money["m1b_series"], "M1B 年增率", "series-1"),
                      (money["m2_series"], "M2 年增率", "series-3")],
                     years=25, default_years=10, digits=2, freq="m",
                     sub="M1B 線跌破 M2 線就是台股慣稱的死亡交叉：資金從活存移往定存。"
                         "兩條都是日平均數的年增率")
        + line_chart("央行重貼現率與五大銀行新承做放款利率",
                     [(money["policy_series"], "重貼現率", "series-1"),
                      (money["loan_rate_series"], "五大銀行放款利率", "series-3")],
                     years=25, default_years=10, digits=3, freq="m",
                     sub="政策利率是階梯——兩次決策之間它就是不動，圖上按月展開"
                         "水準，不在決策之間內插"),
        note="M1B、M2 與外匯存底取自主計總處轉載的央行統計，重貼現率解析自央行貼放利率頁",
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
            ("月頻 GDP", "台灣 GDP 只按季發布。季與季之間的判斷靠同時指標與工業生產指數，"
                        "兩者都不是 GDP 的替身。"),
            ("當月的外匯存底", "統計資料庫比央行每月初的新聞稿慢一期，本站不解析新聞稿，"
                          "所以最新一期會晚到。"),
            ("融資維持率", "證交所與櫃買中心不發布整體市場的維持率資料集。可以由個股融資"
                        "餘額 × 收盤價 ÷ 融資金額推估，但口徑與官方的整戶擔保維持率不同，"
                        "本站尚未做。"),
            ("國際收支", "央行只有季頻，本站尚未收。"),
            ("景氣指標的修正", "國發會每月回溯修正歷史值，本站每次建置重抓整包，"
                          "所以圖上的歷史會跟著官方一起變。"),
        ])
        + "</div>"
        + accordion("資料來源與名詞", glossary([
            ("景氣對策信號", "國發會編製的九項指標綜合分數，9–45 分對應藍、黃藍、"
                        "綠、黃紅、紅五個燈號。分界是官方定義，本站原樣使用。"),
            ("領先指標（不含趨勢）", "七項領先性指標的綜合指數，剔除長期趨勢後"
                            "只留循環成分。轉折通常早於同時指標數個月。"),
            ("外銷訂單：動向指數與金額", "動向指數以回報家數編製，50 為分界，測的是看增"
                                "家數多還是看減家數多；金額由經濟部統計處發布，是訂單的規模。"),
            ("M1B 與 M2", "M1B 是通貨加活期存款——可立即動用的錢；M2 再加上定存、"
                         "外匯存款等。台股慣看兩者年增率的交叉。"),
            ("無薪假", "勞動部公布的「勞雇雙方協商減少工時」通報，企業減班休息的家數與人數。"),
            ("重貼現率", "中央銀行對金融機構融通的基準利率，是台灣的政策利率。"
                    "它是階梯函數，一年可能一次都不調整。"),
            ("實質有效匯率", "BIS 編製，對主要貿易對手的加權匯率再扣掉相對物價。"
                      "指數走高代表出口相對變貴。"),
            ("為什麼各格的日期不一樣", "台灣各項統計的公布時程本來就不同："
                          "財政部出口較快，用電量與加班工時較慢，GDP 是季頻。"
                          "本站不對齊到同一個月，各標各的。"),
        ]))))

    return "".join(body)
