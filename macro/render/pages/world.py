"""全球對照頁。

資料來源比其他頁複雜，每一格都帶自己的 as-of 日期；過期或從缺的會直接標示，
不會拿舊值假裝是現況。
"""
from __future__ import annotations

from ..common import glossary, hbar_chart, line_chart
from ..html import (accordion, callout, delta_span, esc, fmt, kv, pct, section,
                    stat, table, zh_date)


def render(ctx: dict) -> str:
    d = ctx["world"]
    rows = d["countries"]["rows"]
    dollar = d["dollar"]
    body = []

    # ---- 國別對照 ----
    table_rows = []
    for r in rows:
        cpi_cell = pct(r["cpi"], 1)
        if r["cpi"] is None:
            cpi_cell = '<span class="muted">無穩定來源</span>'
        elif r["cpi_stale"]:
            cpi_cell = (f'<span class="muted">{pct(r["cpi"], 1)}'
                        f'<br><small>停更於 {zh_date(r["cpi_date"])}</small></span>')
        table_rows.append([
            esc(r["name"]), cpi_cell,
            pct(r["unemployment"], 1) if r["unemployment"] is not None else '<span class="muted">—</span>',
            pct(r["policy"], 2) if r["policy"] is not None else '<span class="muted">—</span>',
            pct(r["long"], 2) if r["long"] is not None else '<span class="muted">—</span>',
            fmt(r["real_yield"], 2, suffix="%", signed=True) if r["real_yield"] is not None
            else '<span class="muted">—</span>',
        ])

    divergence = d["divergence"]
    note = ""
    if divergence:
        note = callout(
            f'判定：<strong>{esc(divergence["verdict"])}</strong>。'
            f'{divergence["n"]} 個有效讀數中，通膨最高與最低相差 '
            f'{fmt(divergence["cpi_spread"], 1)} 個百分點，平均 '
            f'{pct(divergence["cpi_avg"], 1)}。'
            + (f'長天期公債殖利率最高與最低相差 {fmt(divergence["yield_spread"], 2)} '
               f'個百分點。' if divergence.get("yield_spread") else ""), key=True)

    body.append(section(
        "countries", "主要經濟體對照",
        table(["", "CPI 年增", "失業率", "政策利率", "10 年公債", "實質殖利率"], table_rows)
        + note, note="實質殖利率＝10 年公債殖利率 − CPI 年增率",
        terms=["global_real_yield", "hicp"]))

    # ---- 資料來源說明（誠實交代缺口）----
    gaps = d.get("gaps") or []
    stale = d.get("stale") or []
    if gaps or stale:
        items = []
        if stale:
            items.append("<li>" + "；".join(
                f"{esc(name)} 的 CPI 停更於 {zh_date(when)}" for name, when in stale) + "</li>")
        if gaps:
            items.append(f"<li>{esc('、'.join(gaps))} 沒有穩定的免費 API 來源，本站不填補</li>")
        body.append(section(
            "data-gaps", "資料缺口",
            f'<div class="card"><ul style="color:var(--ink-2);margin:0">{"".join(items)}</ul>'
            f'<p class="muted" style="margin:10px 0 0;font-size:.85rem">'
            f'FRED 上由 OECD 提供的國際 MEI 序列多已凍結，本站各國 CPI 改由 OECD SDMX 直接取得，'
            f'歐元區失業率取自 ECB。仍無來源的項目維持空白，不以舊值或估計值填補。</p></div>'))

    # ---- 通膨對照圖 ----
    fresh = [r for r in rows if r["cpi"] is not None and not r["cpi_stale"]]
    if fresh:
        body.append(section("cpi-compare", "通膨橫向比較", hbar_chart(
            "各國 CPI 年增率",
            [{"name": r["name"], "value": r["cpi"],
              "sub": f'{zh_date(r["cpi_date"])} 資料'} for r in
             sorted(fresh, key=lambda x: x["cpi"], reverse=True)],
            suffix="%", digits=1, label_width=80, sign_color=None,
            sub="只列出仍在更新的來源"),
                        terms=["hicp", "policy_divergence"]))

    # ---- 美元 ----
    tiles = [
        stat("美元指數（廣義）", fmt(dollar["broad"], 1),
             delta=f'近一年 {fmt(dollar["chg_1y"], 1, suffix="%", signed=True)}',
             asof=f'{zh_date(dollar["as_of"], freq="d")}　十年百分位 '
                  f'{fmt(dollar["pct10y"], 0, suffix="%")}',
             spark=[(dt.isoformat(), v) for dt, v in
                    dollar["broad_series"].tail(250).pairs()]),
        stat("近一月", fmt(dollar["chg_1m"], 1, suffix="%", signed=True),
             delta=f'近三月 {fmt(dollar["chg_3m"], 1, suffix="%", signed=True)}'),
        stat("先進國指數", fmt(dollar["advanced"], 1),
             delta="對歐日英加瑞的加權"),
        stat("新興市場指數", fmt(dollar["emerging"], 1),
             delta="對新興市場貨幣的加權"),
    ]
    body.append(section("dollar", "美元",
                        f'<div class="grid grid-4">{"".join(tiles)}</div>'
                        + line_chart("美元指數（廣義）",
                                     [(dollar["broad_series"], "美元指數", "series-1")],
                                     years=20, default_years=5, digits=1, freq="d",
                                     sub="美元走強會透過進口價格壓低美國通膨，同時緊縮全球美元流動性"),
                        terms=["dollar_index"]))

    # ---- 匯率 ----
    fx = d["fx"]
    if fx.get("rows"):
        fx_rows = [[esc(r["name"]), fmt(r["value"], 3),
                    delta_span(r["chg_1m"], 1, suffix="%"),
                    delta_span(r["chg_3m"], 1, suffix="%"),
                    delta_span(r["chg_1y"], 1, suffix="%")]
                   for r in fx["rows"]]
        body.append(section(
            "fx", "主要貨幣",
            table(["貨幣對", "報價", "近一月", "近三月", "近一年"], fx_rows,
                  foot="變動一律以「美元強弱」為方向：正值代表美元對該貨幣升值。")
            + hbar_chart("美元近一年對各貨幣的漲跌",
                         [{"name": r["name"], "value": r["chg_1y"]}
                          for r in fx["rows"] if r["chg_1y"] is not None],
                         suffix="%", digits=1, label_width=120,
                         sign_color=("series-1", "series-8"),
                         sub="正值＝美元升值。顏色只標正負，與升降息方向無關"),
            note=f'{zh_date(fx["as_of"], freq="d")} 資料',
        terms=["dollar_index", "policy_divergence"]))

    body.append(section("glossary", "判讀說明", accordion("資料來源與名詞", glossary([
        ("各國 CPI", "取自 OECD SDMX（OECD.SDD.TPS,DSD_PRICES）。美國取自 FRED，歐元區取自 FRED 的 Eurostat HICP。"),
        ("台灣 CPI", "取自行政院主計總處開放資料「消費者物價基本分類指數」。台灣不在 FRED 也不在 OECD，因此直接接主計總處。"),
        ("歐元區失業率", "取自 ECB Data Portal（LFSI 資料集）。"),
        ("實質殖利率", "10 年公債殖利率減該國 CPI 年增率。跨國比較資金的真實報酬。"),
        ("美元指數", "聯準會編製的貿易加權美元指數，廣義版涵蓋 26 個經濟體。"),
        ("為什麼有些格子是空的", "本站只呈現有穩定免費來源且仍在更新的資料。沒有來源就留白，不以估計值填補。"),
    ]))))

    return "".join(body)
