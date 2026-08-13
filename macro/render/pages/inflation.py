"""通膨頁。"""
from __future__ import annotations

from ..common import (checks_block, hbar_chart, legend_note,
                      line_chart, signals_block)
from ..html import (accordion, callout, delta_span, esc, fmt, kv, pct, section,
                    stat, table, zh_date)

def render(ctx: dict, signals: list[dict]) -> str:
    d = ctx["inflation"]
    headline = d["headline"]
    momentum = d["momentum"]
    supercore = d["supercore"]
    body = []

    body.append(section("signals", "本期關鍵訊號",
                        signals_block(signals, module="物價") + legend_note(),
                        terms=["signal_engine", "hawkish_dovish"]))

    tiles = [
        stat("核心 PCE", pct(headline["core_pce"], 1),
             delta=f'距目標 {fmt(headline["gap_to_target"], 1, suffix=" pp", signed=True)}',
             asof=f'{zh_date(d["pce_as_of"])} 資料　聯準會的政策標的',
             spark=[(dt.isoformat(), v) for dt, v in
                    headline["core_pce_series"].tail(36).pairs()]),
        stat("核心 CPI", pct(headline["core_cpi"], 1),
             delta=f'近三月年化 {pct(momentum["core_cpi_3m"], 1)}',
             asof=f'{zh_date(d["as_of"])} 資料',
             spark=[(dt.isoformat(), v) for dt, v in
                    headline["core_series"].tail(36).pairs()]),
        stat("總體 CPI", pct(headline["cpi"], 1),
             delta=f'總體 PCE {pct(headline["pce"], 1)}',
             asof="含食物與能源　未季調，同 BLS 發布口徑"),
        stat("核心服務除住房", pct(supercore["yoy"], 1),
             delta=f'近三月年化 {pct(supercore["ann3"], 1)}',
             asof=f'連 {supercore["months_above"]} 個月高於 2.5%'),
    ]
    body.append(section("numbers", "關鍵數字",
                        f'<div class="grid grid-4">{"".join(tiles)}</div>',
                        terms=["core_pce", "core_cpi", "cpi", "supercore"]))

    # ---- 動能 ----
    rows = [
        ["核心 CPI", pct(headline["core_cpi"], 2), pct(momentum["core_cpi_6m"], 2),
         pct(momentum["core_cpi_3m"], 2),
         delta_span((momentum["core_cpi_3m"] or 0) - (headline["core_cpi"] or 0), 2,
                    suffix=" pp", good_is_up=False)],
        ["核心 PCE", pct(headline["core_pce"], 2), pct(momentum["core_pce_6m"], 2),
         pct(momentum["core_pce_3m"], 2),
         delta_span((momentum["core_pce_3m"] or 0) - (headline["core_pce"] or 0), 2,
                    suffix=" pp", good_is_up=False)],
        ["核心服務除住房", pct(supercore["yoy"], 2), pct(supercore["ann6"], 2),
         pct(supercore["ann3"], 2),
         delta_span((supercore["ann3"] or 0) - (supercore["yoy"] or 0), 2,
                    suffix=" pp", good_is_up=False)],
    ]
    body.append(section(
        "momentum", "年增率 vs 近月動能",
        table(["指標", "年增率", "近六月年化", "近三月年化", "動能差"], rows)
        + callout("近月年化低於年增率＝通膨在降溫，而且這個訊號會先於年增率出現。"
                  "反過來則是再加速的早期證據。"),
        note="近三月年化把最近三個月的漲幅換算成全年速度",
        terms=["yoy_vs_annualised"]))

    body.append(section("trend", "走勢", f'<div class="grid grid-2">' + "".join([
        line_chart("核心通膨與目標",
                   [(headline["core_series"], "核心 CPI", "series-1"),
                    (headline["core_pce_series"], "核心 PCE", "series-2")],
                   years=15, default_years=5, suffix="%", digits=1, target=2.0,
                   sub="虛線為 2% 目標"),
        line_chart("核心服務除住房",
                   [(supercore["series"], "核心服務除住房", "series-1")],
                   years=15, default_years=5, suffix="%", digits=1, target=2.5,
                   sub="從服務 CPI 剔除住房後重建，最貼近薪資壓力"),
    ]) + "</div>",
                        terms=["core_pce", "supercore"]))

    # ---- 分項貢獻 ----
    contributions = d["contributions"]
    if contributions.get("rows"):
        chart_html = hbar_chart(
            "各分項對 CPI 年增率的貢獻",
            [{"name": r["name"], "value": r["contribution"]} for r in contributions["rows"]],
            suffix=" pp", digits=2, label_width=110,
            sub="貢獻＝分項年增率 × 該項在 CPI 中的權重")
        rows = [[esc(r["name"]), fmt(r["weight"], 1, suffix="%"),
                 pct(r["yoy"], 1), pct(r["ann3"], 1),
                 fmt(r["contribution"], 2, suffix=" pp", signed=True)]
                for r in contributions["rows"]]
        foot = (f'列出的分項合計貢獻 {fmt(contributions["covered"], 2)} 個百分點，'
                f'其餘 {fmt(contributions["other"], 2)} 個百分點來自未列出的項目。')
        body.append(section(
            "contributions", "分項貢獻分解",
            chart_html + accordion("展開分項數字",
                                   table(["分項", "權重", "年增", "近三月年化", "貢獻"],
                                         rows, foot=esc(foot))),
        terms=["contribution"]))

    # ---- 廣度 ----
    breadth = d["breadth"]
    if breadth.get("measures"):
        rows = [[esc(name), pct(value, 1),
                 delta_span((value or 0) - (breadth["core"] or 0), 1,
                            suffix=" pp", good_is_up=False)]
                for name, value in breadth["measures"]]
        body.append(section(
            "breadth", "是全面在漲，還是少數項目？",
            table(["剔除極端值的指標", "年增率", "相對核心 CPI"], rows)
            + callout(f'判定：<strong>{esc(breadth["verdict"])}</strong>。'
                      f'核心 CPI {pct(breadth["core"], 1)}，'
                      f'三個剔除極端值指標的均值 {pct(breadth["average"], 1)}。'
                      f'集中式的漲價比全面性漲價更容易自行消退。', key=True),
            note="中位數與截尾平均剔除當月漲跌最極端的項目",
        terms=["trimmed_median", "sticky_cpi"]))

    # ---- 住房落後 ----
    shelter = d["shelter"]
    if shelter:
        body.append(section("shelter", "住房落後項", f'<div class="card">' + kv([
            ("住房年增", pct(shelter.get("yoy"), 1)),
            ("住房近三月年化", pct(shelter.get("ann3"), 1)),
            ("住房近六月年化", pct(shelter.get("ann6"), 1)),
            ("主要住所租金年增", pct(shelter.get("rent_yoy"), 1)),
            ("業主約當租金年增", pct(shelter.get("oer_yoy"), 1)),
            ("住房佔 CPI 權重", fmt(shelter.get("weight"), 1, suffix="%")),
            ("核心 CPI 剔除住房後", pct(shelter.get("core_ex_shelter"), 1)),
            ("住房收斂對整體 CPI 的影響", fmt(shelter.get("drag"), 2, suffix=" pp", signed=True)),
        ]) + callout(
            "CPI 住房項落後市場租金約 9 至 12 個月。近三月年化低於年增率時，"
            "代表住房還會繼續把整體讀數往下拉；兩者收斂後這股下拉力道就消失了。")
            + "</div>", note="表面讀數與實際通膨的落差來源",
                        terms=["shelter_lag", "oer"]))

    # ---- 能源 ----
    energy = d["energy"]
    if energy:
        lag_rows = [[f'落後 {r["lag"]} 個月', fmt(r["corr"], 2)] for r in energy.get("lags", [])]
        best = energy.get("best_lag")
        body.append(section("energy", "能源價格與傳導", f'<div class="card">' + kv([
            ("WTI 原油", fmt(energy.get("wti"), 1, suffix=" 美元/桶")),
            ("WTI 近一月", fmt(energy.get("wti_1m"), 1, suffix="%", signed=True)),
            ("WTI 近三月", fmt(energy.get("wti_3m"), 1, suffix="%", signed=True)),
            ("零售汽油", fmt(energy.get("gasoline"), 2, suffix=" 美元/加侖")),
            ("汽油年增", pct(energy.get("gasoline_yoy"), 1)),
            ("能源 CPI 年增", pct(energy.get("energy_yoy"), 1)),
            ("能源佔 CPI 權重", fmt(energy.get("weight"), 1, suffix="%")),
            ("能源對總體 CPI 的貢獻", fmt(energy.get("impact"), 2, suffix=" pp", signed=True)),
        ]) + (accordion(
            f'油價領先汽油幾個月？實測相關係數'
            + (f'（最強：落後 {best["lag"]} 個月，r={fmt(best["corr"], 2)}）' if best else ""),
            table(["落後期數", "相關係數"], lag_rows)) if lag_rows else "")
            + "</div>", note="傳導係數由實測相關係數決定，不是套固定值",
                        terms=["energy_passthrough"]))

    # ---- 薪資傳導 ----
    wages = d["wages"]
    if wages:
        body.append(section("wages", "薪資到服務業通膨的傳導",
                            f'<div class="card">' + kv([
                                ("平均時薪年增", pct(wages.get("wages"), 1)),
                                ("僱用成本指數年增", pct(wages.get("eci"), 1)),
                                ("生產力年增", pct(wages.get("productivity"), 1)),
                                ("單位勞動成本年增", pct(wages.get("ulc"), 1)),
                                ("與 2% 通膨相容的薪資增速", pct(wages.get("compatible"), 1)),
                                ("目前的落差", fmt(wages.get("gap"), 1, suffix=" pp", signed=True)),
                                ("核心服務除住房年增", pct(wages.get("supercore"), 1)),
                                ("兩者相關係數（近十年）", fmt(wages.get("corr"), 2)),
                            ]) + callout(
                                "薪資減生產力＝單位勞動成本，那才是服務業通膨的底線。"
                                "薪資漲得比生產力快多少，大致就是企業必須轉嫁的幅度。")
                            + "</div>",
                        terms=["eci", "productivity_ulc"]))

    # ---- 預期 ----
    expectations = d["expectations"]
    tiles = [
        stat("5年後5年通膨預期", pct(expectations["t5y5y"], 2),
             delta="市場定價的長期預期", asof="超過 2.55% 視為開始鬆動"),
        stat("10年通膨補償", pct(expectations["t10yie"], 2),
             delta=f'5 年 {pct(expectations["t5yie"], 2)}'),
        stat("密大 1 年預期", pct(expectations["michigan"], 1),
             delta="家戶的短期預期"),
        stat("克里夫蘭聯準 10 年", pct(expectations["cleveland_10y"], 2),
             delta=f'1 年 {pct(expectations["cleveland_1y"], 2)}'),
    ]
    body.append(section("expectations", "通膨預期",
                        f'<div class="grid grid-4">{"".join(tiles)}</div>'
                        + line_chart("長期通膨預期",
                                     [(expectations["t5y5y_series"], "5y5y 通膨預期", "series-1")],
                                     years=20, default_years=10, suffix="%", digits=2,
                                     target=2.0,
                                     sub="預期一旦脫錨，壓通膨的成本會大幅上升"),
                        terms=["inflation_expectations", "five_y_five_y", "breakeven_inflation"]))

    body.append(section("checks", "關鍵指標檢核", checks_block(d["checks"]),
                        terms=["check_lights"]))

    return "".join(body)
