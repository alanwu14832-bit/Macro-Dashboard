"""聯準會與利率頁：政策立場、完整殖利率曲線、長端拆解、信用。"""
from __future__ import annotations

from ..common import (checks_block, curve_chart, glossary, hbar_chart,
                      legend_note, line_chart, signals_block)
from ..html import (accordion, callout, delta_span, esc, fmt, kv, pct, section,
                    stat, table, zh_date)


def render(ctx: dict, signals: list[dict]) -> str:
    d = ctx["rates"]
    stance = d["stance"]
    shape = d["shape"]
    decomposition = d["decomposition"]
    body = []

    body.append(section("signals", "本期關鍵訊號",
                        signals_block(signals, module="利率") + legend_note()))

    tiles = [
        stat("政策利率上緣", pct(stance["policy"], 2),
             delta=f'有效聯邦資金 {pct(stance["effective"], 2)}',
             asof=f'{zh_date(d["as_of"], freq="d")} 資料'),
        stat("實質政策利率", pct(stance["real_policy"], 2),
             delta="政策利率減核心 PCE", asof="正值代表政策具限制性"),
        stat("10 年期公債", pct(decomposition["nominal"], 2),
             delta=f'近三月 {fmt(decomposition["chg_3m"], 2, suffix=" pp", signed=True)}',
             spark=[(dt.isoformat(), v) for dt, v in
                    decomposition["nominal_series"].tail(180).pairs()]),
        stat("2 年期 vs 政策利率", fmt(stance["market_gap"], 2, suffix=" pp", signed=True),
             delta=esc(stance["market_implies"])),
    ]
    body.append(section("numbers", "政策立場",
                        f'<div class="grid grid-4">{"".join(tiles)}</div>'))

    # ---- 曲線 ----
    curve_rows = d["curve"]["rows"]
    if curve_rows:
        rows = [[esc(r["name"]), pct(r["value"], 2), pct(r["m3"], 2),
                 delta_span(r["chg_1m"], 2, suffix=" pp", good_is_up=False),
                 delta_span(r["chg_3m"], 2, suffix=" pp", good_is_up=False),
                 delta_span(r["chg_1y"], 2, suffix=" pp", good_is_up=False)]
                for r in curve_rows]
        body.append(section(
            "curve", "殖利率曲線",
            curve_chart("現在 vs 三個月前", curve_rows,
                        sub="灰點是三個月前，藍點是現在；線段長度就是這段時間的變動")
            + f'<div style="margin-top:14px">' + kv([
                ("曲線形態", esc(shape.get("label", "—"))),
                ("10 年減 2 年", fmt(shape.get("slope_10_2"), 2, suffix=" pp", signed=True)),
                ("10 年減 3 個月", fmt(shape.get("slope_10_3m"), 2, suffix=" pp", signed=True)),
                ("30 年減 10 年", fmt(shape.get("slope_30_10"), 2, suffix=" pp", signed=True)),
                ("斜率近三月變動", fmt(shape.get("slope_change_3m"), 2, suffix=" pp", signed=True)),
                ("水準近三月變動", fmt(shape.get("level_change_3m"), 2, suffix=" pp", signed=True)),
            ]) + "</div>"
            + accordion("展開 11 個期限的完整數字",
                        table(["期限", "現在", "三個月前", "近一月", "近三月", "近一年"], rows))))

    body.append(section("slope", "曲線斜率走勢", line_chart(
        "10年減2年 與 10年減3個月",
        [(shape.get("slope_series"), "10Y − 2Y", "series-1"),
         (shape.get("slope_3m_series"), "10Y − 3M", "series-2")],
        years=20, default_years=10, suffix="%", digits=2, target=0,
        sub="兩條都跌破零線時，衰退訊號最強")))

    # ---- 長端拆解 ----
    body.append(section("decomposition", "長端利率拆解", f'<div class="card">' + kv([
        ("10 年名目", pct(decomposition["nominal"], 2)),
        ("　實質利率（TIPS）", pct(decomposition["real"], 2)),
        ("　通膨補償", pct(decomposition["inflation_comp"], 2)),
        ("期限溢酬（近似）", fmt(decomposition["term_premium"], 2, suffix="%", signed=True)),
        ("30 年名目", pct(decomposition["nominal_30"], 2)),
        ("30 年實質", pct(decomposition["real_30"], 2)),
        ("實質利率近三月變動", fmt(decomposition["real_chg_3m"], 2, suffix=" pp", signed=True)),
        ("通膨補償近三月變動", fmt(decomposition["be_chg_3m"], 2, suffix=" pp", signed=True)),
    ]) + callout(
        "長端上行如果來自通膨補償，那是通膨預期問題；如果來自實質利率，"
        "那是成長預期或供給問題。兩者對股債的意義完全不同。")
        + '<p class="muted" style="font-size:.82rem">'
          '期限溢酬為近似值：10 年實質利率減去「政策利率減通膨補償」的短期實質利率，'
          '不等同 ACM 或 Kim-Wright 模型的估計。</p></div>'))

    body.append(section("real", "實質利率與通膨補償", line_chart(
        "10 年實質利率 vs 通膨補償",
        [(decomposition["real_series"], "10 年實質利率", "series-1"),
         (decomposition["breakeven_series"], "10 年通膨補償", "series-2")],
        years=20, default_years=10, suffix="%", digits=2,
        sub="兩者相加約等於名目殖利率")))

    # ---- 信用 ----
    credit = d["credit"]
    if credit.get("rows"):
        rows = [[esc(r["name"]), pct(r["value"], 2),
                 delta_span(r["chg_1m"], 2, suffix=" pp", good_is_up=False),
                 delta_span(r["chg_3m"], 2, suffix=" pp", good_is_up=False),
                 fmt(r["pct10y"], 0, suffix="%"),
                 fmt(r["z10y"], 2, signed=True)]
                for r in credit["rows"]]
        body.append(section(
            "credit", "信用利差：壓力已經反映多少",
            hbar_chart("各級距利差的十年百分位",
                       [{"name": r["name"], "value": r["pct10y"]}
                        for r in credit["rows"] if r["pct10y"] is not None],
                       suffix="%", digits=0, label_width=90,
                       sign_color=None,
                       sub="百分位低＝利差在十年低檔＝市場沒有反映壓力")
            + table(["級距", "利差", "近一月", "近三月", "十年百分位", "z 分數"], rows)
            + callout(f'判定：<strong>{esc(credit["verdict"])}</strong>', key=True)))

    body.append(section("credit-trend", "高收益與投資級利差走勢", line_chart(
        "信用利差", [(credit.get("hy_series"), "高收益", "series-2"),
                    (credit.get("ig_series"), "投資級", "series-1")],
        years=20, default_years=10, suffix="%", digits=2,
        sub="利差擴大通常領先違約率與失業率")))

    # ---- 金融情勢與資產負債表 ----
    conditions = d["conditions"]
    tiles = [
        stat("芝加哥聯準金融情勢", fmt(conditions["nfci"], 2, signed=True),
             delta=esc(conditions["verdict"]),
             asof=f'十年百分位 {fmt(conditions["nfci_pct"], 0, suffix="%")}'),
        stat("調整後金融情勢", fmt(conditions["anfci"], 2, signed=True),
             delta="剔除經濟循環後的金融鬆緊"),
        stat("聯準會總資產", fmt((stance["balance_sheet"] or 0) / 1_000_000, 2, suffix=" 兆美元"),
             delta=f'近一年 {fmt((stance["balance_chg_1y"] or 0) / 1_000_000, 2, suffix=" 兆", signed=True)}'),
        stat("30 年房貸利率", pct(d["mortgage"], 2),
             delta="政策傳導到家戶的實際成本"),
    ]
    body.append(section("conditions", "金融情勢",
                        f'<div class="grid grid-4">{"".join(tiles)}</div>'))

    body.append(section("checks", "關鍵指標檢核", checks_block(d["checks"])))

    body.append(section("glossary", "判讀說明", accordion("名詞與門檻", glossary([
        ("實質利率", "名目殖利率減通膨補償，即抗通膨公債（TIPS）的殖利率。真正的緊縮程度看這個。"),
        ("通膨補償", "名目公債與 TIPS 的殖利率差，代表市場定價的平均通膨預期。"),
        ("期限溢酬", "投資人為承擔長天期風險要求的額外補償。本站為近似值，非 ACM 模型估計。"),
        ("曲線倒掛", "短天期殖利率高於長天期。10 年減 3 個月是歷史上最可靠的衰退領先指標之一。"),
        ("信用利差", "公司債與同天期公債的殖利率差。十年百分位低代表市場對風險定價不足。"),
        ("金融情勢指數", "芝加哥聯準綜合貨幣、債務與股權市場的指標。正值＝緊、負值＝鬆。"),
    ]))))

    return "".join(body)
