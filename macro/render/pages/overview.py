"""總覽頁：一句話結論、關鍵訊號、各模組入口、跟上期比什麼變了。"""
from __future__ import annotations

from ...compute.news import _headline, _is_macro, _same_story, _tokens
from ...compute.scenario import REGIME_LABELS
from ...fomc import next_meeting
from . import mandate_cards as cards
from . import overview_blocks as blocks
from ..common import checks_block, legend_note, signals_block
from ..html import (accordion, callout, delta_span, direction_label,
                    direction_class, esc, fmt, kv, pct, section, stat, table,
                    tag, thousands_to_wan, zh_date)

LEAN_COLOR = {"hawkish": "var(--hawkish)", "dovish": "var(--dovish)",
              "neutral": "var(--neutral)"}
LEAN_WASH = {"hawkish": "var(--hawkish-wash)", "dovish": "var(--dovish-wash)",
             "neutral": "var(--neutral-wash)"}


def narrative(ctx: dict, scenario: dict, summary: dict) -> str:
    """整體情勢的一段話。由數字組出來，不是寫死的文案。"""
    labor = ctx["labor"]
    inflation = ctx["inflation"]
    rates = ctx["rates"]
    debt = ctx["debt"]

    bits = []
    bits.append(f"聯準會目前的重心判定為<strong>{esc(scenario['regime_label'])}</strong>；"
                f"訊號合計{esc(summary['tilt'])}"
                f"（{summary['hawkish']} 條偏升息、{summary['dovish']} 條偏降息）。")

    unrate = labor["unemployment"]["rate"]
    avg3 = labor["payrolls"]["avg3"]
    breakeven = labor["breakeven"].get("value")
    if unrate is not None and avg3 is not None and breakeven:
        verdict = "撐不住現有失業率" if avg3 < breakeven else "足以吸收新增勞動力"
        bits.append(f"失業率 {fmt(unrate, 1, suffix='%')}，"
                    f"但三月均非農 {thousands_to_wan(avg3)}低於損益兩平的 "
                    f"{thousands_to_wan(breakeven, signed=False)}，{verdict}。")

    core_pce = inflation["headline"]["core_pce"]
    ann3 = inflation["momentum"].get("core_pce_3m")
    supercore = inflation["supercore"]
    if core_pce is not None:
        chunk = f"另一頭，核心 PCE {fmt(core_pce, 1, suffix='%')}"
        if ann3 is not None:
            chunk += f"、近三月年化 {fmt(ann3, 1, suffix='%')}"
            chunk += "已在放緩" if ann3 < core_pce else "仍在加速"
        if supercore.get("months_above"):
            chunk += (f"，核心服務除住房連 {supercore['months_above']} 個月高於 2.5%")
        bits.append(chunk + "。")

    nominal = rates["decomposition"].get("nominal")
    real = rates["decomposition"].get("real")
    if nominal is not None:
        chunk = f"長端方面，10 年期 {fmt(nominal, 2, suffix='%')}"
        if real is not None:
            chunk += f"、實質 {fmt(real, 2, suffix='%')}"
        supply = debt["supply"]
        chunk += f"；長端供給壓力判定為「{esc(supply['level'])}」"
        if supply["reasons"]:
            chunk += f"（{esc(supply['reasons'][0])}）"
        bits.append(chunk + "。")

    return "".join(f"<p>{b}</p>" for b in bits)


def glance_board(ctx: dict, scenario: dict) -> str:
    """三欄一眼板：就業、通膨、聯準會，各給判定 + 三個關鍵數字。

    取代原本的散文段落——散文讀者要自己在句子裡找數字，
    這裡直接把「狀況、關鍵讀數、動能方向」排成可掃視的格子。
    """
    labor = ctx["labor"]
    inflation = ctx["inflation"]
    stance = (ctx["rates"] or {}).get("stance") or {}

    avg3 = labor["payrolls"]["avg3"]
    breakeven = labor["breakeven"].get("value")
    unrate = labor["unemployment"]["rate"]
    jobs_gap = (avg3 - breakeven) if (avg3 is not None and breakeven) else None

    core_pce = inflation["headline"]["core_pce"]
    ann3 = inflation["momentum"].get("core_pce_3m")
    core_cpi = inflation["headline"]["core_cpi"]
    inf_trend = ("動能 ↘ 放緩中" if ann3 < core_pce else "動能 ↗ 仍在加速") \
        if (ann3 is not None and core_pce is not None) else ""

    def col(title, judge_dir, judge_text, trend, rows):
        row_html = "".join(
            f'<div class="gl-row"><span>{esc(k)}</span>'
            f'<span class="gl-v">{v}</span></div>' for k, v in rows if v)
        trend_html = f'<div class="gl-trend">{esc(trend)}</div>' if trend else ""
        return (f'<div class="gl-col"><div class="gl-head">{esc(title)}'
                f'{tag(judge_dir, judge_text)}</div>{row_html}{trend_html}</div>')

    jobs_trend = ""
    if jobs_gap is not None:
        jobs_trend = ("增速低於損益兩平 → 失業率有上行壓力" if jobs_gap < 0
                      else "增速高於損益兩平 → 失業率可維持")

    cols = [
        col("就業", "dovish", scenario["employment_label"], jobs_trend, [
            ("三月均非農", thousands_to_wan(avg3)),
            ("損益兩平需", thousands_to_wan(breakeven, signed=False)),
            ("失業率", fmt(unrate, 1, suffix="%")),
        ]),
        col("通膨", "hawkish", scenario["inflation_label"], inf_trend, [
            ("核心 PCE 年增", pct(core_pce, 1)),
            ("近三月年化", pct(ann3, 1)),
            ("核心 CPI 年增", pct(core_cpi, 1)),
        ]),
        col("聯準會", scenario["lean"], scenario["regime_label"], "", [
            ("政策利率上緣", pct(stance.get("policy"), 2)),
            ("實質政策利率", pct(stance.get("real_policy"), 2)),
            ("市場定價", esc((stance.get("market_implies") or "—")
                             .replace("市場定價", ""))),
        ]),
    ]
    return f'<div class="glance">{"".join(cols)}</div>'


def fresh_line(ctx: dict) -> str:
    """剛公布的數據一覽：FRED 在今天或昨天更新過的指標。

    使用者不會背發布行事曆——昨天公布了 PPI，今天打開網站就該一眼看到
    「PPI 是新數據」，而不是自己去對日期。
    """
    fresh = (ctx.get("freshness") or {}).get("fresh") or {}
    if not fresh:
        return ""
    items = "、".join(
        f'{esc(info["name"])}（{esc(info["date"][5:].replace("-", "/"))}）'
        for info in fresh.values())
    return (f'<div class="fresh-line"><span class="new-badge">新</span>'
            f'剛公布：{items}——下方對應讀數也標有「新」。</div>')


def direction_line(scenario: dict, summary: dict, stance: dict) -> str:
    """方向一句話：訊號傾向 → 規則上的閘門 → 市場定價，三段收斂。"""
    bits = [f"訊號 {summary['dovish']} 條偏降息、{summary['hawkish']} 條偏升息"]
    first = next((t for t in (scenario.get("transitions") or [])
                  if t.get("gap") is not None), None)
    if first:
        bits.append(f"但規則上要等{esc(first['name'])}政策重心才會換——"
                    f"還差 {fmt(abs(first['gap']), 2)} {esc(first['unit'])}")
    if stance.get("market_implies"):
        bits.append(esc(stance["market_implies"]))
    return "<strong>方向：</strong>" + "；".join(bits) + "。"


def _when(days: int | None) -> str:
    if days is None:
        return "時程未定"
    return {0: "今天", 1: "明天"}.get(days, f"{days} 天後")


def key_line(scenario: dict) -> str:
    transitions = scenario.get("transitions") or []
    if not transitions:
        return ""
    first = next((t for t in transitions if t.get("gap") is not None), None)
    if not first:
        return ""
    return (f"重點：解鎖條件是{esc(first['name'])}，"
            f"還差 {fmt(abs(first['gap']), 2)} {esc(first['unit'])}。")


def indicator_drawers(ctx: dict) -> str:
    """就業與通膨的全指標下拉。

    目錄裡就有分組與中文名，直接照 catalogue 的分組列出來——不必另外
    維護一份清單，加了新序列自動出現在這裡。
    """
    from ... import catalogue
    from ...data import Bundle

    bundle: Bundle | None = ctx.get("_bundle")
    drawers = []
    for group_key, label in [("labor", "就業"), ("inflation", "通膨")]:
        specs = catalogue.ALL_GROUPS.get(group_key) or {}
        rows = []
        for series_id, (name, unit, freq, _start) in specs.items():
            series = bundle[series_id] if bundle else None
            latest = (fmt(series.last, 2, suffix=f" {unit}" if unit else "")
                      if series is not None and series.last is not None else "—")
            asof = (zh_date(series.last_date, freq=freq)
                    if series is not None and series.last_date else "—")
            rows.append([
                f'<a href="/explore/?id={esc(series_id)}">{esc(name)}</a>',
                f'<code>{esc(series_id)}</code>', latest, asof,
                {"d": "日", "w": "週", "m": "月", "q": "季", "a": "年"}.get(freq, freq),
            ])
        if not rows:
            continue
        drawers.append(accordion(
            f"{label}：全部 {len(rows)} 檔指標",
            table(["指標", "序列代號", "最新值", "資料日期", "頻率"], rows)))

    if not drawers:
        return ""
    return section(
        "indicators", "全部指標",
        "".join(drawers)
        + '<p class="muted" style="margin-top:10px">點指標名稱會到自選比較頁，'
          '可以跟其他序列疊圖。資料直接取自 FRED，本站只做轉換與判定。</p>',
        note="依 FRED 序列代號分組，加新序列會自動出現在這裡")


def module_cards(ctx: dict, signals: list[dict]) -> str:
    labor = ctx["labor"]
    inflation = ctx["inflation"]
    rates = ctx["rates"]
    debt = ctx["debt"]
    growth = ctx["growth"]
    market = ctx["market"]

    def module_direction(name: str) -> str:
        found = [s for s in signals if s.get("module") == name]
        if not found:
            return "neutral"
        score = sum(1 if s["direction"] == "hawkish" else -1 if s["direction"] == "dovish" else 0
                    for s in found)
        return "hawkish" if score > 0 else "dovish" if score < 0 else "neutral"

    # (連結, 模組名, 資料日, 指標名稱, 數值, 方向, 第二行, 導覽)
    # 指標名稱是給讀者的：光看 -2.3 萬人不知道是什麼，要標明是非農月增。
    cards = [
        ("/labor/", "勞動市場", zh_date(labor["as_of"]), "非農就業月增",
         thousands_to_wan(labor["payrolls"]["latest"]), module_direction("就業"),
         f"失業率 {fmt(labor['unemployment']['rate'], 1, suffix='%')}",
         "看損益兩平、修正追蹤、行業拆解與強弱指數"),
        ("/inflation/", "通膨", zh_date(inflation["as_of"]), "核心 CPI 年增率",
         pct(inflation["headline"]["core_cpi"], 1), module_direction("物價"),
         f"核心 PCE {pct(inflation['headline']['core_pce'], 1)}",
         "看分項貢獻、廣度、住房落後與能源傳導"),
        ("/fed/", "聯準會與利率", zh_date(rates["as_of"], freq="d"), "10 年期公債殖利率",
         pct(rates["decomposition"]["nominal"], 2), module_direction("利率"),
         f"實質 {pct(rates['decomposition']['real'], 2)}　·　{esc(rates['shape'].get('label',''))}",
         "看完整曲線、長端拆解與信用利差"),
        ("/debt/", "長端與債務", zh_date(debt["as_of"], freq="q"), "政府債務／GDP",
         fmt(debt["dynamics"]["debt_gdp"], 0, suffix="%"), module_direction("債務"),
         f"供給壓力{esc(debt['supply']['level'])}　·　r−g {fmt(debt['dynamics']['r_minus_g'], 1, signed=True)}",
         "看債務動態、利息負擔與買盤結構"),
        ("/growth/", "成長與信用", zh_date(growth["as_of"]), "衰退風險刻度",
         f"{fmt(growth['gauge']['value'], 0)}<span class='unit'>/100</span>",
         module_direction("成長"),
         f"衰退風險刻度「{esc(growth['gauge'].get('level',''))}」",
         "看消費、住宅、放款標準與違約率"),
        ("/market/", "市場面", zh_date(market["as_of"], freq="d"), "VIX 波動率",
         fmt(market["volatility"]["vix"], 1), module_direction("市場"),
         esc(market["stock_bond"].get("verdict", "")),
         "看股債相關性、波動率定位與實質利率張力"),
    ]

    out = []
    for href, name, when, metric, headline, direction, second, more in cards:
        out.append(
            f'<a class="module-link" href="{href}">'
            f'<div class="m-name">{esc(name)}<span class="date">{esc(when)} 資料</span></div>'
            f'<div class="m-metric">{esc(metric)}</div>'
            f'<div class="m-headline">{headline}{tag(direction)}</div>'
            f'<div class="m-second">{second}</div>'
            f'<div class="m-more">{esc(more)} →</div></a>')
    return f'<div class="grid grid-3">{"".join(out)}</div>'


def changes_block(diff: dict, reading_changes: list[dict]) -> str:
    parts = []
    if diff.get("first_run"):
        parts.append('<p class="muted">這是第一次產生，還沒有可比對的上期。</p>')
    elif diff.get("same") and not reading_changes:
        parts.append('<p class="muted">訊號組成與關鍵讀數都與上期相同。</p>')
    else:
        if diff.get("added"):
            parts.append("<p><strong>新增訊號</strong></p>")
            parts.append('<div class="signal-list">'
                         + "".join(f'<div class="signal">'
                                   f'<div class="sev {s["severity"]}">＋</div>'
                                   f'<div><div class="headline">{esc(s["headline"])}</div>'
                                   f'<div class="evidence">{esc(s.get("evidence",""))}</div></div>'
                                   f'<div class="side">{tag(s["direction"])}</div></div>'
                                   for s in diff["added"]) + "</div>")
        if diff.get("removed"):
            parts.append("<p><strong>不再觸發</strong></p>")
            parts.append('<div class="signal-list">'
                         + "".join(f'<div class="signal">'
                                   f'<div class="sev low">－</div>'
                                   f'<div><div class="headline">{esc(s["headline"])}</div></div>'
                                   f'<div class="side">{tag(s.get("direction","neutral"))}</div></div>'
                                   for s in diff["removed"]) + "</div>")
        if reading_changes:
            rows = [[esc(c["name"]),
                     fmt(c["was"], 2, suffix=c["unit"]),
                     fmt(c["now"], 2, suffix=c["unit"]),
                     delta_span(c["change"], 2, suffix=c["unit"])]
                    for c in reading_changes]
            parts.append(table(["讀數", "上期", "本期", "變動"], rows))
    return "".join(parts)


def render(ctx: dict, signals: list[dict], summary: dict, scenario: dict,
           diff: dict, reading_changes: list[dict], updated: str) -> str:
    lean = scenario["lean"]
    body = []

    # ---- 判斷 ----
    body.append(
        f'<div class="verdict" style="--regime-color:{LEAN_COLOR[lean]}">'
        f'<div class="eyebrow">目前情境</div>'
        f'<div class="hero-figure">{esc(scenario["name"])}：{esc(scenario["regime_label"])}</div>'
        f'<p class="dim" style="margin:0">{esc(scenario["regime_explain"])}</p>'
        f'<div class="chips">'
        f'<span class="chip">就業{esc(scenario["employment_label"])}</span>'
        f'<span class="chip">通膨{esc(scenario["inflation_label"])}</span>'
        f'<span class="chip {direction_class(lean)}"><span class="dot"></span>'
        f'{esc(direction_label(lean))}</span>'
        f'<span class="chip">訊號{esc(summary["tilt"])}</span>'
        f'</div>'
        + fresh_line(ctx)
        + glance_board(ctx, scenario)
        + f'<div class="callout key">'
          f'{direction_line(scenario, summary, (ctx["rates"] or {}).get("stance") or {})}</div>'
        + accordion(f"本期關鍵訊號（{summary['total']} 條）",
                    signals_block(signals, grid=True) + legend_note())
        + accordion("完整敘述", narrative(ctx, scenario, summary))
        + f'<p style="margin:12px 0 0"><a href="/scenario/">'
          f'這個判斷怎麼來的、對應什麼部位　→</a></p>'
        f'</div>')

    # ---- 1 就業、2 通膨（雙目標，同一套視覺語言）----
    body.append(cards.employment(ctx, scenario))
    body.append(cards.inflation(ctx, scenario))

    # ---- 3 聯準會立場與政策 ----
    body.append(blocks.fed_stance(ctx, scenario, next_meeting()))

    # ---- 4 公債利率 ----
    body.append(blocks.rate_structure(ctx))

    # ---- 5 市場定價 ----
    body.append(blocks.market_pricing(ctx))

    # ---- 6 商品與傳導 ----
    body.append(blocks.commodities_block(ctx))

    # ---- 7 對股市的含義 ----
    body.append(blocks.implications(ctx, scenario, summary))

    # ---- 8 今日觀察清單 ----
    body.append(blocks.watchlist(ctx, next_meeting()))

    # ---- 頁尾：模組導覽（精簡）與期間比對 ----
    body.append(module_nav())

    # ---- 變化 ----
    body.append(section("changed", "跟上期比，什麼變了",
                        accordion("展開比對",
                                  changes_block(diff, reading_changes)),
                        note="每天一筆判斷快照，可回看任一天的結論"))

    return "".join(body)


def module_nav() -> str:
    """頁尾的精簡模組導覽。

    詳細數據現在直接在總覽上，所以這裡不需要六張大卡——一行連結
    就夠了，給習慣從首頁進各模組的讀者。
    """
    links = [("/labor/", "勞動市場"), ("/inflation/", "通膨"),
             ("/fed/", "聯準會與利率"), ("/debt/", "長端與債務"),
             ("/growth/", "成長與信用"), ("/market/", "市場面"),
             ("/scenario/", "情境與部位")]
    items = "　·　".join(f'<a href="{h}">{esc(t)}</a>' for h, t in links)
    return section("modules", "看更詳細的模組",
                   f'<p class="mc-foot-note" style="font-size:.88rem">{items}</p>')
