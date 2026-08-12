"""市場面頁：總經判斷有沒有被市場定價。"""
from __future__ import annotations

from ..common import (checks_block, glossary, hbar_chart, legend_note,
                      line_chart, signals_block)
from ..html import (accordion, callout, delta_span, esc, fmt, kv, pct, section,
                    stat, table, zh_date)


def render(ctx: dict, signals: list[dict]) -> str:
    d = ctx["market"]
    equities = d["equities"]
    volatility = d["volatility"]
    stock_bond = d["stock_bond"]
    real_rate = d["real_rate"]
    body = []

    body.append(section("signals", "本期關鍵訊號",
                        signals_block(signals, module="市場") + legend_note()))

    # ---- 股市 ----
    if equities.get("rows"):
        rows = [[esc(r["name"]), fmt(r["value"], 0),
                 delta_span(r["chg_1m"], 1, suffix="%"),
                 delta_span(r["chg_3m"], 1, suffix="%"),
                 delta_span(r["chg_ytd"], 1, suffix="%"),
                 delta_span(r["chg_1y"], 1, suffix="%"),
                 delta_span(r["from_high"], 1, suffix="%")]
                for r in equities["rows"]]
        body.append(section(
            "equities", "股市",
            table(["指數", "點數", "近一月", "近三月", "今年以來", "近一年", "距一年高點"], rows),
            note=f'{zh_date(equities["as_of"], freq="d")} 資料'))

    # ---- 股債相關性 ----
    if stock_bond.get("windows"):
        rows = [[esc(w["label"]), fmt(w["corr"], 2, signed=True)]
                for w in stock_bond["windows"]]
        body.append(section(
            "stock-bond", "股債相關性",
            f'<div class="card">'
            f'<div class="hero-figure">{fmt(stock_bond["latest"], 2, signed=True)}'
            f'<span style="font-size:.3em;color:var(--ink-muted)"> 近一年</span></div>'
            + table(["期間", "標普報酬 vs 10 年殖利率變動的相關係數"], rows)
            + callout(f'判定：<strong>{esc(stock_bond["verdict"])}</strong>。'
                      f'殖利率上升時股票同步下跌（負相關）＝通膨主導，'
                      f'債券無法對沖股票，傳統 60/40 的分散效果下降。', key=True)
            + "</div>",
            note="這是總經體制最直接的市場證據"))

    # ---- 實質利率張力 ----
    if real_rate.get("tension"):
        body.append(section("real-rate", "實質利率與估值",
                            f'<div class="card">' + kv([
                                ("10 年實質利率", pct(real_rate["real"], 2)),
                                ("實質利率近三月變動", fmt(real_rate["real_chg_3m"], 2,
                                                  suffix=" pp", signed=True)),
                                ("標普近三月", fmt(real_rate["equity_chg_3m"], 1,
                                              suffix="%", signed=True)),
                            ]) + callout(f'{esc(real_rate["tension"])}。實質利率是估值的分母，'
                                         f'上行而股價不跌，代表估值倍數被壓縮或市場在定價更高的獲利成長。')
                            + "</div>"))

    # ---- 波動率 ----
    if volatility.get("rows"):
        rows = [[esc(r["name"]), fmt(r["value"], 1),
                 fmt(r["avg1y"], 1), fmt(r["pct10y"], 0, suffix="%")]
                for r in volatility["rows"]]
        body.append(section(
            "volatility", "波動率定位",
            hbar_chart("各市場波動率的十年百分位",
                       [{"name": r["name"], "value": r["pct10y"]}
                        for r in volatility["rows"] if r["pct10y"] is not None],
                       suffix="%", digits=0, label_width=100, sign_color=None,
                       sub="百分位低＝市場對該資產的風險定價不足")
            + table(["市場", "目前", "近一年均", "十年百分位"], rows)
            + callout(f'判定：<strong>{esc(volatility["verdict"])}</strong>。'
                      f'低波動本身不是賣訊，但代表壞消息來時的重定價幅度會較大。')))

    # ---- 商品 ----
    commodities = d["commodities"]
    if commodities.get("rows"):
        rows = [[esc(r["name"]), fmt(r["value"], 2),
                 delta_span(r["chg_1m"], 1, suffix="%"),
                 delta_span(r["chg_1y"], 1, suffix="%")]
                for r in commodities["rows"]]
        body.append(section("commodities", "商品",
                            table(["商品", "價格", "近一月", "近一年"], rows),
                            note="能源與工業金屬是通膨與全球需求的即時讀數"))

    crypto = d["crypto"]
    if crypto.get("rows"):
        rows = [[esc(r["name"]), fmt(r["value"], 0),
                 delta_span(r["chg_1m"], 1, suffix="%"),
                 delta_span(r["chg_1y"], 1, suffix="%")]
                for r in crypto["rows"]]
        body.append(section("crypto", "加密資產",
                            table(["資產", "價格（美元）", "近一月", "近一年"], rows),
                            note="風險偏好與流動性的高 beta 讀數"))

    body.append(section("vix-trend", "VIX 走勢", line_chart(
        "VIX", [(volatility.get("vix_series"), "VIX", "series-2")],
        years=20, default_years=5, digits=1, freq="d",
        sub="長期均值約在 19–20")))

    body.append(section("checks", "關鍵指標檢核", checks_block(d["checks"])))

    body.append(section("glossary", "判讀說明", accordion("名詞與門檻", glossary([
        ("股債相關性", "標普日報酬與 10 年殖利率日變動的相關係數。負值代表殖利率上升時股票下跌，也就是通膨主導的體制。"),
        ("十年百分位", "目前讀數在過去十年分布中的位置。低百分位代表市場對該風險定價不足。"),
        ("實質利率張力", "實質利率上行而股市仍漲時，估值倍數承受壓縮壓力。"),
        ("為什麼看市場面", "總經判斷若已被市場完全定價，就沒有交易價值；本頁的目的是找出判斷與定價之間的落差。"),
    ]))))

    return "".join(body)
