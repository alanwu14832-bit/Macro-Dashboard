"""市場面頁：總經判斷有沒有被市場定價。"""
from __future__ import annotations

from ..common import (checks_block, hbar_chart, legend_note,
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
                        signals_block(signals, module="市場") + legend_note(),
                        terms=["signal_engine", "hawkish_dovish"]))

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
            note=f'{zh_date(equities["as_of"], freq="d")} 資料',
        terms=["drawdown"]))

    # ---- 風險胃納 ----
    risk = d.get("risk") or {}
    if risk.get("parts"):
        rows = [[esc(p["name"]), esc(p["reading"]), fmt(p["score"], 0)]
                for p in risk["parts"]]
        body.append(section(
            "risk", "風險胃納",
            f'<div class="card">'
            f'<div class="hero-figure">{fmt(risk["score"], 0)}'
            f'<span style="font-size:.3em;color:var(--ink-muted)"> /100　{esc(risk["label"])}</span></div>'
            + table(["組成", "讀數", "風險偏好分數"], rows)
            + callout("固定規則的加權平均：VIX 與高收益利差取十年百分位反轉"
                      "（各 30%），美元近三月變化取百分位反轉（20%），"
                      "股債相關性線性映射（20%）。高 = 貪婪、低 = 恐慌，"
                      "同一份資料永遠算出同一個分數，可拿去跟存檔比對。")
            + "</div>",
            note="0–100，收斂四個市場的風險定價"))

    # ---- 聯準會淨流動性 ----
    liq = d.get("liquidity") or {}
    if liq.get("series"):
        body.append(section(
            "liquidity", "聯準會淨流動性",
            line_chart("淨流動性 = 總資產 − 財政部帳戶 − 隔夜逆回購",
                       [(liq["series"], "淨流動性", "series-1")],
                       years=4, default_years=4, suffix="B", freq="w",
                       digits=0)
            + f'<div class="grid grid-4">'
            + stat("目前水位", fmt(liq["latest"] / 1000, 2, suffix=" 兆美元"))
            + stat("近三月變化", fmt(liq["chg_3m"], 0, suffix=" 十億", signed=True),
                   direction=None)
            + stat("近一年變化", fmt(liq["chg_1y"], 0, suffix=" 十億", signed=True),
                   direction=None)
            + stat("組成", f'{fmt(liq["walcl"]/1000, 2)} 兆',
                   delta=f'TGA {fmt(liq["tga"]/1000, 0)}B　RRP {fmt(liq["rrp"], 0)}B',
                   asof="總資產 − 兩個抽水池")
            + "</div>"
            + callout("QT 縮表抽走的錢，可能被財政部帳戶下降或逆回購資金回流"
                      "抵銷——單看縮表會誤判，要看淨額。這個淨額只涵蓋聯準會資產負債表"
                      "這一塊，不是市場上全部的流動性；它跟股市走勢不一致時，"
                      "不能據此判斷漲勢靠的是什麼。"),
            note=f'{zh_date(liq["as_of"], freq="d")} 資料，週頻'))

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
            + callout(f'觀察：<strong>{esc(stock_bond["verdict"])}</strong>。'
                      f'常見的解釋：通膨與利率預期主導行情時兩者同向，成長疑慮主導時反向。'
                      f'相關係數分不出是哪一種——要驗證，看殖利率的變動來自通膨補償還是'
                      f'實質利率（<a href="/fed/#decomposition">長端利率拆解</a>）。', key=True)
            + "</div>",
            note="相關係數只描述兩者一起動的程度，不說明原因",
        terms=["stock_bond_correlation"]))

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
                            + "</div>",
                        terms=["real_rate"]))

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
                       sub="百分位低＝這個市場的隱含波動在自己十年的歷史裡偏低；不等於風險被低估")
            + table(["市場", "目前", "近一年均", "十年百分位"], rows)
            + callout(f'觀察：<strong>{esc(volatility["verdict"])}</strong>。'
                      f'隱含波動低不是賣訊，也不代表風險被低估——那要跟實際波動比，'
                      f'本站沒有這項比較。低波動時期遇到意外，重新定價的幅度通常比較大。'),
        terms=["vix", "percentile_rank"]))

    # ---- 商品 ----
    commodities = d["commodities"]
    if commodities.get("rows"):
        rows = [[esc(r["name"]), fmt(r["value"], 2),
                 delta_span(r["chg_1m"], 1, suffix="%"),
                 delta_span(r["chg_1y"], 1, suffix="%")]
                for r in commodities["rows"]]
        body.append(section("commodities", "商品",
                            table(["商品", "價格", "近一月", "近一年"], rows),
                            note="能源與工業金屬是通膨與全球需求的即時讀數",
                        terms=["commodity_index"]))

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
        sub="長期均值約在 19–20"),
                        terms=["vix"]))

    body.append(section("checks", "關鍵指標檢核", checks_block(d["checks"]),
                        terms=["check_lights"]))

    return "".join(body)
