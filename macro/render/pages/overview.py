"""總覽頁：一句話結論、關鍵訊號、各模組入口、跟上期比什麼變了。"""
from __future__ import annotations

from ...compute.scenario import REGIME_LABELS
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

    cards = [
        ("/labor/", "勞動市場", zh_date(labor["as_of"]),
         thousands_to_wan(labor["payrolls"]["latest"]), module_direction("就業"),
         f"失業率 {fmt(labor['unemployment']['rate'], 1, suffix='%')}",
         "看損益兩平、修正追蹤、行業拆解與強弱指數"),
        ("/inflation/", "通膨", zh_date(inflation["as_of"]),
         pct(inflation["headline"]["core_cpi"], 1), module_direction("物價"),
         f"核心 PCE {pct(inflation['headline']['core_pce'], 1)}",
         "看分項貢獻、廣度、住房落後與能源傳導"),
        ("/fed/", "聯準會與利率", zh_date(rates["as_of"], freq="d"),
         pct(rates["decomposition"]["nominal"], 2), module_direction("利率"),
         f"實質 {pct(rates['decomposition']['real'], 2)}　·　{esc(rates['shape'].get('label',''))}",
         "看完整曲線、長端拆解與信用利差"),
        ("/debt/", "長端與債務", zh_date(debt["as_of"], freq="q"),
         fmt(debt["dynamics"]["debt_gdp"], 0, suffix="%"), module_direction("債務"),
         f"供給壓力{esc(debt['supply']['level'])}　·　r−g {fmt(debt['dynamics']['r_minus_g'], 1, signed=True)}",
         "看債務動態、利息負擔與買盤結構"),
        ("/growth/", "成長與信用", zh_date(growth["as_of"]),
         f"{fmt(growth['gauge']['value'], 0)}<span class='unit'>/100</span>",
         module_direction("成長"),
         f"衰退風險刻度「{esc(growth['gauge'].get('level',''))}」",
         "看消費、住宅、放款標準與違約率"),
        ("/market/", "市場面", zh_date(market["as_of"], freq="d"),
         fmt(market["volatility"]["vix"], 1), module_direction("市場"),
         esc(market["stock_bond"].get("verdict", "")),
         "看股債相關性、波動率定位與實質利率張力"),
    ]

    out = []
    for href, name, when, headline, direction, second, more in cards:
        out.append(
            f'<a class="module-link" href="{href}">'
            f'<div class="m-name">{esc(name)}<span class="date">{esc(when)} 資料</span></div>'
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
        f'<div class="summary">{narrative(ctx, scenario, summary)}</div>'
        + (f'<div class="callout key">{key_line(scenario)}</div>' if key_line(scenario) else "")
        + f'<p style="margin:12px 0 0"><a href="/scenario/">'
          f'這個判斷怎麼來的、對應什麼部位　→</a></p>'
        f'</div>')

    # ---- 模組入口 ----
    body.append(section("modules", "各模組現況", module_cards(ctx, signals),
                        terms=["nine_grid"]))

    # ---- 關鍵訊號 ----
    body.append(section(
        "signals", "本期關鍵訊號",
        signals_block(signals) + legend_note(),
        note=f"共 {summary['total']} 條：{summary['dovish']} 條利降息、"
             f"{summary['hawkish']} 條利升息、{summary['neutral']} 條中性。依嚴重度排序。",
        terms=["signal_engine", "hawkish_dovish"]))

    # ---- 資料新鮮度 ----
    fresh = ctx.get("freshness") or {}
    imminent = fresh.get("imminent") or []
    if imminent:
        chips = "".join(
            f'<span class="chip">{esc(r["name"])}'
            f'<strong style="margin-left:4px">{esc(_when(r["days_away"]))}</strong>'
            f'</span>'
            for r in imminent[:6])
        body.append(section(
            "fresh", "接下來幾天會有新數字",
            f'<div class="chips">{chips}</div>'
            f'<p class="muted" style="margin-top:10px">'
            f'發布後本站的下一次建置就會帶進來，訊號與九宮格判定也可能跟著改變。'
            f'　<a href="/freshness/">看完整發布時程與資料新鮮度 →</a></p>',
            note="資料來源：FRED 官方發布行事曆"))

    # ---- 接下來看什麼 ----
    transitions = scenario.get("transitions") or []
    if transitions:
        rows = [[esc(t["name"]), esc(t["need"]),
                 (f'<span class="num">{fmt(abs(t["gap"]), 2)} {esc(t["unit"])}</span>'
                  if t.get("gap") is not None else '<span class="muted">—</span>')]
                for t in transitions]
        body.append(section("watch", "接下來要盯什麼",
                            table(["情境轉換", "需要什麼", "還差"], rows),
                        terms=["transition_threshold"]))

    # ---- 變化 ----
    body.append(section("changed", "跟上期比，什麼變了",
                        changes_block(diff, reading_changes)))

    return "".join(body)
