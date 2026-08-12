"""成長與信用頁。"""
from __future__ import annotations

from ..common import (checks_block, hbar_chart, legend_note,
                      line_chart, signals_block)
from ..html import (accordion, callout, delta_span, esc, fmt, kv, pct, section,
                    stat, table, zh_date)

def render(ctx: dict, signals: list[dict]) -> str:
    d = ctx["growth"]
    activity = d["activity"]
    housing = d["housing"]
    credit = d["credit"]
    gauge = d["gauge"]
    body = []

    body.append(section("signals", "本期關鍵訊號",
                        signals_block(signals, module="成長") + legend_note(),
                        terms=["signal_engine", "hawkish_dovish"]))

    tiles = [
        stat("實質 GDP 年化季增", pct(activity["gdp_qoq"], 1),
             delta=f'年增 {pct(activity["gdp_yoy"], 1)}',
             asof=f'{zh_date(activity["gdp_as_of"], freq="q")} 資料'),
        stat("實質零售銷售年增", pct(activity["retail_yoy"], 1),
             delta=f'實質消費 {pct(activity["consumption_yoy"], 1)}'),
        stat("工業生產年增", pct(activity["indpro"], 1),
             delta=f'產能利用率 {pct(activity["capacity"], 1)}'),
        stat("消費者信心", fmt(activity["sentiment"], 0),
             delta=f'儲蓄率 {pct(activity["savings"], 1)}'),
    ]
    body.append(section("numbers", "活動面",
                        f'<div class="grid grid-4">{"".join(tiles)}</div>',
                        terms=["real_gdp", "retail_sales", "consumer_sentiment"]))

    # ---- 衰退刻度 ----
    if gauge.get("value") is not None:
        rows = [[esc(r["name"]), fmt(r["raw"], 2), fmt(r["z"], 2, signed=True)]
                for r in gauge["rows"]]
        body.append(section(
            "gauge", "衰退風險刻度",
            f'<div class="card">'
            f'<div class="hero-figure">{fmt(gauge["value"], 0)}'
            f'<span style="font-size:.35em;color:var(--ink-muted)"> / 100　'
            f'相對十年常態為「{esc(gauge["level"])}」</span></div>'
            + table(["輸入指標", "目前值", "方向調整後 z 分數"], rows)
            + callout(
                "這是相對十年常態的<strong>定位</strong>，不是衰退機率預測。"
                "每個輸入取 10 年 z 分數、依方向調號後平均，再壓縮到 0–100。"
                "多個領先指標同時偏向風險端時，單一指標的雜訊會被抵消。")
            + (f'<p class="muted">Sahm 法則即時值：{fmt(gauge["sahm"], 2)}</p>'
               if gauge.get("sahm") is not None else "")
            + "</div>",
        terms=["recession_gauge", "sahm_rule", "zscore"]))

    body.append(section("activity-trend", "活動面走勢",
                        f'<div class="grid grid-2">' + "".join([
                            line_chart("實質零售銷售年增",
                                       [(activity["retail_series"], "實質零售年增", "series-1")],
                                       years=20, default_years=5, suffix="%", digits=1,
                                       target=0, include_zero=True,
                                       sub="轉負通常先於衰退"),
                            line_chart("工業生產年增",
                                       [(activity["indpro_series"], "工業生產年增", "series-2")],
                                       years=20, default_years=5, suffix="%", digits=1,
                                       target=0, include_zero=True),
                            line_chart("消費者信心",
                                       [(activity["sentiment_series"], "密大信心指數", "series-1")],
                                       years=20, default_years=10, digits=0,
                                       sub="低於 60 接近衰退期水準"),
                            line_chart("儲蓄率",
                                       [(activity["savings_series"], "儲蓄率", "series-3")],
                                       years=20, default_years=10, suffix="%", digits=1,
                                       sub="緩衝薄時，消費對衝擊更敏感"),
                        ]) + "</div>",
                        terms=["retail_sales", "consumer_sentiment"]))

    # ---- 住宅 ----
    tiles = [
        stat("新屋開工", fmt(housing["starts"], 0, suffix=" 千戶"),
             delta=f'年增 {pct(housing["starts_yoy"], 1)}',
             asof=f'{zh_date(housing["as_of"])} 資料'),
        stat("建築許可", fmt(housing["permits"], 0, suffix=" 千戶"),
             delta=f'年增 {pct(housing["permits_yoy"], 1)}',
             asof="領先開工約一至二個月"),
        stat("30 年房貸利率", pct(housing["mortgage"], 2),
             delta="政策傳導到家戶的實際成本"),
        stat("實質可支配所得年增", pct(activity["income_yoy"], 1),
             delta=f'核心資本財訂單 {pct(activity["capex_orders_yoy"], 1)}'),
    ]
    body.append(section("housing", "住宅與投資",
                        f'<div class="grid grid-4">{"".join(tiles)}</div>'
                        + line_chart("新屋開工與建築許可",
                                     [(housing["starts_series"], "新屋開工", "series-1"),
                                      (housing["permits_series"], "建築許可", "series-2")],
                                     years=25, default_years=10, digits=0, suffix=" 千戶",
                                     sub="住宅對利率最敏感，通常最早反應"),
                        terms=["housing_starts"]))

    # ---- 信用循環 ----
    if credit.get("rows"):
        rows = [[esc(r["name"]), pct(r["value"], 2),
                 delta_span(r["chg_1y"], 2, suffix=" pp", good_is_up=False),
                 fmt(r["pct10y"], 0, suffix="%")]
                for r in credit["rows"]]
        body.append(section(
            "credit", "信用循環",
            f'<div class="card">' + kv([
                ("銀行淨收緊放款標準比例", fmt(credit["standards"], 0, suffix="%", signed=True)),
                ("工商放款年增", pct(credit["loans_yoy"], 1)),
                ("家庭債務負擔比", pct(credit["burden"], 2)),
                ("M2 年增", pct(credit["m2_yoy"], 1)),
            ]) + table(["違約率", "目前", "近一年變動", "十年百分位"], rows)
            + callout("銀行收緊放款標準領先就業惡化約二至四個季度。"
                      "違約率則是落後指標，用來確認循環已經轉向。")
            + "</div>", note=f'{zh_date(credit["as_of"], freq="q")} 資料',
        terms=["sloos", "delinquency"]))

        body.append(section("credit-trend", "放款標準走勢", line_chart(
            "銀行淨收緊工商放款標準的比例",
            [(credit["standards_series"], "淨收緊比例", "series-2")],
            years=30, default_years=10, suffix="%", digits=0, target=0, freq="q",
            sub="正值＝收緊的銀行多於放寬的銀行"),
                        terms=["sloos"]))

    body.append(section("checks", "關鍵指標檢核", checks_block(d["checks"]),
                        terms=["check_lights"]))

    return "".join(body)
