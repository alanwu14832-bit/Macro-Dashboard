"""勞動市場頁。"""
from __future__ import annotations

from ..common import (bar_chart, checks_block, glossary, hbar_chart, legend_note,
                      line_chart, signals_block)
from ..html import (accordion, callout, delta_span, esc, fmt, kv, pct, section,
                    stat, table, thousands_to_wan, zh_date)


def render(ctx: dict, signals: list[dict]) -> str:
    d = ctx["labor"]
    payrolls = d["payrolls"]
    unemployment = d["unemployment"]
    breakeven = d["breakeven"]
    body = []

    body.append(section("signals", "本期關鍵訊號",
                        signals_block(signals, module="就業") + legend_note()))

    # ---- 關鍵數字 ----
    tiles = [
        stat("本月非農", thousands_to_wan(payrolls["latest"]),
             delta=f'三月均 {thousands_to_wan(payrolls["avg3"])}',
             asof=f'{zh_date(d["as_of"])} 資料',
             spark=[(dt.isoformat(), v) for dt, v in payrolls["series"].tail(24).pairs()]),
        stat("失業率", pct(unemployment["rate"], 1),
             delta=f'U6 {pct(unemployment["u6"], 1)}',
             asof=f'距一年低點 {fmt(unemployment["gap_from_low"], 1, signed=True)} 個百分點',
             spark=[(dt.isoformat(), v) for dt, v in unemployment["series"].tail(36).pairs()]),
        stat("平均時薪年增", pct(d["wages"]["yoy"], 1),
             delta=f'近三月年化 {pct(d["wages"]["ann3"], 1)}',
             asof=f'週工時 {fmt(d["wages"]["hours"], 1)} 小時'),
        stat("初領失業金四週均", fmt((d["claims"]["initial_4w"] or 0) / 10000, 1, suffix=" 萬人"),
             delta=f'續領 {fmt((d["claims"]["continued"] or 0) / 10000, 1, suffix=" 萬人")}',
             asof=f'{zh_date(d["claims"]["as_of"], freq="d")} 週'),
    ]
    body.append(section("numbers", "關鍵數字",
                        f'<div class="grid grid-4">{"".join(tiles)}</div>'))

    # ---- 損益兩平 ----
    be_body = kv([
        ("損益兩平就業增速（近 12 月人口）", thousands_to_wan(breakeven.get("value"), signed=False)),
        ("以近 36 月人口計", thousands_to_wan(breakeven.get("long_run"), signed=False)),
        ("民間非機構人口月增", thousands_to_wan(breakeven.get("population_growth"))),
        ("勞動力月增", thousands_to_wan(breakeven.get("labor_force_growth"))),
        ("勞參率", pct(breakeven.get("participation"), 1)),
        ("三月均非農", thousands_to_wan(payrolls["avg3"])),
        ("六月均非農", thousands_to_wan(payrolls["avg6"])),
        ("十二月均非農", thousands_to_wan(payrolls["avg12"])),
    ])
    gap = None
    if payrolls["avg3"] is not None and breakeven.get("value"):
        gap = payrolls["avg3"] - breakeven["value"]
    note = ""
    if gap is not None:
        note = callout(
            f'三月均非農{"低於" if gap < 0 else "高於"}損益兩平 '
            f'{fmt(abs(gap) / 10, 1)} 萬人。'
            + ("低於時失業率會自己往上飄，不需要出現裁員潮。"
               if gap < 0 else "高於時足以吸收新增勞動力。"), key=True)

    lf_growth = breakeven.get("labor_force_growth")
    pop_growth = breakeven.get("population_growth")
    caveat = ""
    if lf_growth is not None and pop_growth is not None and lf_growth < 0 < pop_growth:
        caveat = callout(
            f"注意：人口每月增加 {fmt(pop_growth / 10, 1)} 萬，勞動力卻每月減少 "
            f"{fmt(abs(lf_growth) / 10, 1)} 萬。失業率的分母正在萎縮，"
            f"這會讓失業率看起來比實際更好。")

    body.append(section(
        "breakeven", "損益兩平就業增速",
        f'<div class="card">{be_body}{note}{caveat}'
        f'<p class="muted" style="font-size:.83rem;margin-top:10px">'
        f'算法：民間非機構人口月增 × 勞參率 × (1 − 失業率)。'
        f'刻意用人口而非勞動力推導——參與率下滑時勞動力可能萎縮，'
        f'用勞動力會算出負的損益兩平，那是量錯了東西。</p></div>',
        note="維持失業率不變所需的月增就業"))

    # ---- 走勢圖 ----
    # 每張圖只放同一單位的序列 — 不同單位就分開畫，不共用一條 Y 軸。
    charts = [
        bar_chart("非農就業月增", payrolls["series"], years=10, default_years=3,
                  suffix=" 千人", digits=0, name="月增",
                  sign_color=("series-1", "series-8"),
                  sub="顏色只標正負，與升降息方向無關；懸停可看單月數字"),
        line_chart("失業率",
                   [(unemployment["series"], "失業率", "series-1"),
                    (d["participation"]["prime_epop_series"], "黃金年齡就業率 25-54", "series-3")],
                   years=15, default_years=5, suffix="%", digits=1,
                   sub="兩者皆為百分比。黃金年齡就業率排除人口老化，是最乾淨的強弱讀數"),
        line_chart("平均時薪年增",
                   [(d["wages"]["series"], "時薪年增", "series-1")],
                   years=15, default_years=5, suffix="%", digits=1,
                   sub="與 2% 通膨相容的區間約在 3.0–3.5%"),
        line_chart("失業期間中位數",
                   [(d["duration"]["series"], "失業期間中位數", "series-2")],
                   years=15, default_years=5, suffix=" 週", digits=1,
                   sub="拉長代表再就業變難，是勞動市場惡化的確認指標"),
        line_chart("初領失業金（四週均）",
                   [(d["claims"]["ma_series"], "初領四週均", "series-1")],
                   years=10, default_years=3, suffix=" 人", digits=0,
                   sub="最即時的裁員訊號，領先失業率數月"),
        line_chart("續領失業金",
                   [(d["claims"]["continued_series"], "續領", "series-2")],
                   years=10, default_years=3, suffix=" 人", digits=0,
                   sub="與初領量級差近 10 倍，分開畫才看得出各自的轉折"),
    ]
    body.append(section("charts", "走勢",
                        f'<div class="grid grid-2">{"".join(c for c in charts if c)}</div>'))

    # ---- 修正追蹤 ----
    revisions = d["revisions"]
    if revisions.get("rows"):
        rows = [[zh_date(r["month"]),
                 thousands_to_wan(r["initial"]),
                 thousands_to_wan(r["current"]),
                 delta_span(r["revision"] / 10, 1, suffix=" 萬人")]
                for r in reversed(revisions["rows"])]
        foot = (f'近 {revisions["n"]} 個月平均修正 '
                f'{fmt((revisions["avg"] or 0) / 10, 1, signed=True)} 萬人，'
                f'其中 {fmt((revisions["negative_share"] or 0) * 100, 0)}% 遭下修。'
                f'初值取該月次月 15 日的 FRED vintage。')
        body.append(section("revisions", "初值 vs 現值：修正追蹤",
                            table(["月份", "初值", "目前值", "累計修正"], rows) if rows else "",
                            note="系統性下修代表當月公布的數字應該打折看待"))
        body.append(f'<p class="muted" style="font-size:.83rem;margin-top:-24px">{esc(foot)}</p>')

    # ---- 失業率拆解 ----
    decomposition = d["decomposition"].get("rows") or []
    if decomposition:
        rows = [[esc(r["window"]),
                 delta_span(r["total"], 2, suffix=" pp", good_is_up=False),
                 fmt(r["numerator"], 2, suffix=" pp", signed=True),
                 fmt(r["denominator"], 2, suffix=" pp", signed=True)]
                for r in decomposition]
        body.append(section(
            "decomposition", "失業率變動分解",
            table(["期間", "失業率變動", "失業人數效果", "勞動力效果"], rows)
            + callout("失業人數效果為正＝真的有人失業；勞動力效果為負＝有人退出勞動力"
                      "把失業率壓下去。後者不是好消息。"),
            note="Δu ≈ (ΔU − u·ΔL) / L"))

    # ---- 行業別 ----
    sectors = d["sectors"]
    if sectors.get("rows"):
        chart_html = hbar_chart(
            "行業別對本月非農的貢獻",
            [{"name": r["name"], "value": r["value"]} for r in sectors["rows"]],
            suffix=" 千人", digits=0, label_width=120,
            sub=f'擴散指數 {fmt(sectors["diffusion"], 0)}%'
                f'（{sectors["n"]} 個行業中增加就業的比例）')
        rows = [[esc(r["name"]),
                 thousands_to_wan(r["value"]),
                 thousands_to_wan(r["avg3"]),
                 thousands_to_wan(r["avg12"]),
                 pct(r["yoy"], 1)]
                for r in sectors["rows"]]
        body.append(section(
            "sectors", "行業別貢獻分解",
            chart_html + accordion("展開 17 個行業的完整數字",
                                   table(["行業", "本月", "三月均", "十二月均", "年增"], rows)),
            note=f'三月擴散指數 {fmt(sectors["diffusion_3m"], 0)}%'))

    # ---- JOLTS ----
    jolts = d["jolts"]
    tiles = [
        stat("職缺數", fmt((jolts["openings"] or 0) / 100, 1, suffix=" 萬個"),
             asof=f'{zh_date(jolts["as_of"])} 資料'),
        stat("職缺對失業人數比", fmt(jolts["vu_ratio"], 2),
             delta="低於 1 代表求職者多於職缺"),
        stat("主動離職率", pct(jolts["quits"], 1),
             delta="薪資增速的領先指標"),
        stat("裁員率", pct(jolts["layoffs"], 1),
             delta=f'招聘 {fmt((jolts["hires"] or 0) / 100, 1, suffix=" 萬人")}'),
    ]
    body.append(section("jolts", "JOLTS 職缺與人力流動",
                        f'<div class="grid grid-4">{"".join(tiles)}</div>'))

    # ---- 強弱指數 ----
    composite = d["composite"]
    if composite.get("value") is not None:
        rows = [[esc(r["name"]), fmt(r["weight"] * 100, 0, suffix="%"),
                 fmt(r["score"], 1) if r["score"] is not None else "—",
                 fmt((r["score"] or 0) * r["weight"], 1) if r["score"] is not None else "—"]
                for r in composite["rows"]]
        body.append(section(
            "composite", "勞動市場綜合強弱指數",
            f'<div class="card"><div class="hero-figure">{fmt(composite["value"], 1)}'
            f'<span style="font-size:.4em;color:var(--ink-muted)"> / ±100</span></div>'
            f'<p class="dim">正值＝強於十年常態，負值＝弱於常態。'
            f'各分項取 10 年 z 分數後以 tanh 壓縮，避免單一極端值主導。</p>'
            + table(["分項", "權重", "分數", "加權貢獻"], rows) + "</div>"))

    # ---- 檢核 ----
    body.append(section("checks", "關鍵指標檢核", checks_block(d["checks"])))

    # ---- 名詞 ----
    body.append(section("glossary", "判讀說明", accordion("名詞與門檻", glossary([
        ("損益兩平就業增速", "維持失業率不變所需的月增就業。算法：民間非機構人口月增 × 勞參率 × (1−失業率)。"),
        ("擴散指數", "增加就業的行業佔全部行業的比例。低於 50% 代表多數行業在縮減。"),
        ("Sahm 法則", "三月均失業率高出前一年低點 0.5 個百分點時，歷史上多半已進入衰退。"),
        ("職缺對失業人數比", "JOLTS 職缺數 ÷ 失業人數。低於 1 代表求職者多於職缺。"),
        ("黃金年齡就業率", "25–54 歲的就業人口比。排除人口老化與升學影響，是最乾淨的勞動市場強弱讀數。"),
        ("初值 vs 現值", "非農就業每月會被修正兩次。初值取該月次月 15 日的 FRED vintage。"),
    ])), note="門檻寫死在程式碼中，同一份資料每次判定一致"))

    return "".join(body)
