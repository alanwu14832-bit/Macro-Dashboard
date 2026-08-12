"""大宗商品頁。"""
from __future__ import annotations

from ..common import checks_block, hbar_chart, line_chart
from ..html import (accordion, callout, delta_span, esc, fmt, kv, pct, section,
                    stat, table, zh_date)

def _copper_gold_note(corr) -> str:
    """描述實測到的關係，而不是背誦教科書上的關係。

    銅金比與 10 年殖利率「長期同向」是常見說法，但本站的實測值可能是負的；
    數字就在同一張卡片上，文案不能與它牴觸。
    """
    if corr is None:
        return "資料不足，無法判斷與 10 年殖利率的關係。"
    if corr > 0.3:
        return (f"與 10 年殖利率的相關係數為 {corr:+.2f}，符合兩者同向的典型關係；"
                f"背離時通常是其中一個市場對成長的看法錯了。")
    if corr < -0.1:
        return (f"值得注意的是，近十年兩者的相關係數為 {corr:+.2f}，"
                f"與「銅金比和殖利率同向」的典型說法相反。這段期間殖利率主要由"
                f"通膨與供給推動，而非成長預期——所以殖利率此時不宜當成成長的代理變數。")
    return (f"近十年兩者的相關係數僅 {corr:+.2f}，關係不明顯，"
            f"這段期間殖利率的驅動因素不只成長預期。")

def render(ctx: dict) -> str:
    d = ctx["commodities"]
    precious = d["precious"]
    cg = d["copper_gold"]
    gr = d["gold_real_rate"]
    body = []

    # ---- 貴金屬 ----
    tiles = []
    for r in precious.get("rows", []):
        tiles.append(stat(
            r["name"], fmt(r["value"], 2, prefix="$"),
            delta=f'今年以來 {fmt(r["chg_ytd"], 1, suffix="%", signed=True)}',
            asof=f'{zh_date(r["as_of"], freq="d")}　十年百分位 '
                 f'{fmt(r["pct10y"], 0, suffix="%")}',
            spark=[(dt.isoformat(), v) for dt, v in r["series"].tail(250).pairs()],
            spark_color="series-4"))
    if precious.get("gold_silver_ratio") is not None:
        tiles.append(stat(
            "金銀比", fmt(precious["gold_silver_ratio"], 1),
            delta=f'十年均 {fmt(precious["gold_silver_avg10y"], 1)}',
            asof="偏高代表市場在買純避險，而非買景氣"))
    if cg.get("ratio") is not None:
        tiles.append(stat(
            "銅金比", fmt(cg["ratio"], 4),
            delta=f'十年百分位 {fmt(cg["pct10y"], 0, suffix="%")}',
            asof=esc(cg.get("verdict", ""))))

    body.append(section("precious", "貴金屬與比值",
                        f'<div class="grid grid-4">{"".join(tiles)}</div>',
                        note="金銀價為 LBMA 官方定盤價",
                        terms=["gold_silver_ratio"]))

    if precious.get("rows"):
        rows = [[esc(r["name"]), fmt(r["value"], 2, prefix="$"),
                 delta_span(r["chg_1m"], 1, suffix="%"),
                 delta_span(r["chg_3m"], 1, suffix="%"),
                 delta_span(r["chg_ytd"], 1, suffix="%"),
                 delta_span(r["chg_1y"], 1, suffix="%"),
                 fmt(r["pct10y"], 0, suffix="%")]
                for r in precious["rows"]]
        body.append(section(
            "precious-detail", "",
            table(["金屬", "價格", "近一月", "近三月", "今年以來", "近一年", "十年百分位"], rows)
            + f'<div class="grid grid-2" style="margin-top:14px">' + "".join([
                line_chart("黃金", [(precious["gold"], "黃金 美元/盎司", "series-4")],
                           years=20, default_years=5, digits=0, prefix="$", freq="d"),
                line_chart("金銀比", [(precious["gold_silver"], "金銀比", "series-7")],
                           years=20, default_years=10, digits=1, freq="d",
                           sub="白銀有工業用途，比值拉高代表避險需求主導"),
            ]) + "</div>"))

    # ---- 銅金比 ----
    if cg.get("series"):
        body.append(section(
            "copper-gold", "銅金比：市場定價的成長預期",
            line_chart("銅金比 vs 10 年公債殖利率",
                       [(cg["series"], "銅金比", "series-2")],
                       years=25, default_years=10, digits=4, freq="m",
                       sub="銅反映實體需求、黃金反映避險，比值是最乾淨的成長預期讀數")
            + f'<div class="card" style="margin-top:14px">' + kv([
                ("目前銅金比", fmt(cg["ratio"], 4)),
                ("十年平均", fmt(cg["avg10y"], 4)),
                ("十年百分位", fmt(cg["pct10y"], 0, suffix="%")),
                ("近一年變動", fmt(cg["chg_1y"], 1, suffix="%", signed=True)),
                ("與 10 年殖利率的相關係數（近十年）", fmt(cg["corr_with_10y"], 2, signed=True)),
            ]) + callout(
                f'判定：<strong>{esc(cg.get("verdict", ""))}</strong>。'
                + _copper_gold_note(cg.get("corr_with_10y")), key=True)
            + "</div>",
        terms=["copper_gold_ratio"]))

    # ---- 黃金與實質利率 ----
    if gr.get("corr_yoy_5y") is not None:
        body.append(section(
            "gold-real", "黃金與實質利率",
            f'<div class="card">' + kv([
                ("黃金", fmt(gr["gold"], 2, prefix="$")),
                ("10 年實質利率", pct(gr["real"], 2)),
                ("日報酬相關（近一年）", fmt(gr["corr_daily_1y"], 2, signed=True)),
                ("年增率相關（近五年）", fmt(gr["corr_yoy_5y"], 2, signed=True)),
            ]) + callout(
                f'{esc(gr.get("verdict", ""))}。持有黃金不孳息，機會成本就是實質利率，'
                f'所以兩者長期反向。這個關係鬆脫時，多半代表央行買盤或地緣避險'
                f'蓋過了利率因素。') + "</div>",
        terms=["gold_real_rates", "real_rate"]))

    # ---- 分類明細 ----
    for group in d.get("groups", []):
        rows = [[esc(r["name"]), fmt(r["value"], 2),
                 esc(r["unit"]),
                 delta_span(r["chg_1m"], 1, suffix="%"),
                 delta_span(r["chg_3m"], 1, suffix="%"),
                 delta_span(r["chg_1y"], 1, suffix="%"),
                 fmt(r["pct10y"], 0, suffix="%")]
                for r in group["rows"]]
        anchor = {"能源": "energy", "工業金屬": "metals",
                  "農產": "agri", "指數": "indices"}.get(group["title"], "group")
        group_terms = {
            "能源": ["energy_passthrough", "commodity_index"],
            "工業金屬": ["copper_gold_ratio", "commodity_index"],
            "農產": ["commodity_index"],
            "指數": ["commodity_index", "percentile_rank"],
        }.get(group["title"], [])
        chart_html = hbar_chart(
            f'{group["title"]}：近一年漲跌',
            [{"name": r["name"], "value": r["chg_1y"]}
             for r in group["rows"] if r["chg_1y"] is not None],
            suffix="%", digits=1, label_width=120,
            sub="顏色只標正負")
        body.append(section(
            anchor, group["title"],
            table(["項目", "價格", "單位", "近一月", "近三月", "近一年", "十年百分位"], rows)
            + chart_html, terms=group_terms))

    body.append(section("checks", "關鍵指標檢核", checks_block(d["checks"]),
                        terms=["check_lights"]))

    return "".join(body)
