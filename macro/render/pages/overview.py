"""總覽頁：一句話結論、關鍵訊號、各模組入口、跟上期比什麼變了。"""
from __future__ import annotations

import re

from ...compute.news import _headline, _is_market, _same_story, _tokens
from ...compute.scenario import REGIME_LABELS
from ...fomc import next_meeting
from . import mandate_cards as cards
from . import overview_blocks as blocks
from ..common import checks_block, legend_note, signals_block
from ..html import (accordion, callout, delta_span, direction_label,
                    direction_class, esc, fmt, kv, new_badge, pct, section,
                    stat, table, tag, thousands_to_wan, zh_date)

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


def keys_strip(ctx: dict, scenario: dict, summary: dict) -> str:
    """關鍵數字帶：六個數字一排，各附判定或補充，取代原本的三欄一眼板。

    讀者要的是「現在在哪、往哪走」——一排大數字加一行小字就夠，
    不需要三個框各塞三列。
    """
    labor = ctx["labor"]
    inflation = ctx["inflation"]
    stance = (ctx["rates"] or {}).get("stance") or {}
    decomp = (ctx["rates"] or {}).get("decomposition") or {}
    futures = ctx.get("fedfunds") or {}

    avg3 = labor["payrolls"]["avg3"]
    breakeven = labor["breakeven"].get("value")
    unrate = labor["unemployment"]["rate"]
    core_pce = inflation["headline"]["core_pce"]
    ann3 = inflation["momentum"].get("core_pce_3m")

    def key(label, value, sub):
        return (f'<div class="key"><div class="key-l">{esc(label)}</div>'
                f'<div class="key-v">{value}</div><div class="key-s">{sub}</div></div>')

    inf_sub = tag("hawkish", f'通膨{scenario["inflation_label"]}')
    if ann3 is not None and core_pce is not None:
        inf_sub += f'　3M 年化 {pct(ann3, 1)}，' + ("放緩中" if ann3 < core_pce else "仍在加速")
    jobs_sub = tag("dovish", f'就業{scenario["employment_label"]}')
    if avg3 is not None:
        jobs_sub += f'　三月均非農 {thousands_to_wan(avg3)}'
        if breakeven:
            jobs_sub += "，低於損益兩平" if avg3 < breakeven else "，高於損益兩平"

    nxt = futures.get("next") if futures.get("available") else None
    if nxt:
        fut_value = (f'{esc(nxt["headline"].split(" ")[0][:2])}'
                     f' {nxt["p_hike"] if nxt["p_hike"] >= nxt["p_cut"] else nxt["p_cut"]:.0%}')
        fut_sub = f'{esc(nxt["label"])} FOMC　{esc(futures["summary"].replace("期貨定價", ""))}'
        fut_label = "期貨隱含機率"
    else:
        fut_value = esc((stance.get("market_implies") or "—").replace("市場定價未來一至二年", ""))
        fut_sub = f'2 年期減政策利率 {fmt(stance.get("market_gap"), 2, suffix=" pp", signed=True)}'
        fut_label = "市場定價"

    items = [
        key("核心 PCE 年增", pct(core_pce, 1), inf_sub),
        key("失業率", pct(unrate, 1), jobs_sub),
        key("政策利率上緣", pct(stance.get("policy"), 2),
            f'實質 {pct(stance.get("real_policy"), 2)}　' +
            ("具限制性" if (stance.get("real_policy") or 0) > 1 else "接近中性")),
        key("10 年期公債", pct(decomp.get("nominal"), 2),
            f'實質 {pct(decomp.get("real"), 2)}　近三月 '
            f'{fmt(decomp.get("chg_3m"), 2, suffix=" pp", signed=True)}'),
        key(fut_label, fut_value, fut_sub),
        key("規則訊號", f'{summary["total"]}<span class="unit"> 條</span>',
            f'{summary["dovish"]} 條偏降息、{summary["hawkish"]} 條偏升息　'
            f'{tag(scenario["lean"], summary["tilt"])}'),
    ]
    return f'<div class="keys">{"".join(items)}</div>'


def _digits(value) -> int:
    """千以上的數（非農總數、貨幣供給）不需要小數。"""
    try:
        return 0 if abs(float(value)) >= 1000 else 2
    except (TypeError, ValueError):
        return 2


def _series_update(series, series_id: str) -> dict:
    before = series.at(-2)
    return {"id": series_id, "name": series.label or series_id, "unit": series.unit,
            "frequency": series.frequency, "date": series.last_date,
            "value": series.last, "prev": before,
            "change": (series.last - before) if before is not None else None}


def today_updates_block(ctx: dict) -> str:
    """今天到的數據，直接列在總覽最上面。

    兩個來源合併：資料日期比上一輪建置推進的序列（涵蓋全站 199 檔，不用
    多打 API），加上 FRED 兩天內更新過的主要發布（那組有「新」徽章）。
    使用者不會背發布行事曆——昨天公布了 PPI，今天打開網站就該一眼看到。
    """
    freshness = ctx.get("freshness") or {}
    today = freshness.get("today") or {}
    fresh = freshness.get("fresh") or {}
    bundle = ctx.get("_bundle")

    periodic = list(today.get("periodic") or [])
    have = {u["id"] for u in periodic}
    for series_id in fresh:
        series = bundle[series_id] if bundle is not None else None
        if series_id in have or not series:
            continue
        periodic.append(_series_update(series, series_id))
    periodic.sort(key=lambda u: u["name"])
    daily = today.get("daily") or []

    parts = []
    if periodic:
        rows = [[esc(u["name"]) + new_badge(fresh, u["id"]),
                 zh_date(u["date"], freq=u["frequency"]),
                 fmt(u["value"], _digits(u["value"]), suffix=f' {u["unit"]}' if u["unit"] else ""),
                 delta_span(u["change"], 2) if u["change"] is not None else "—",
                 f'<a href="/explore/?id={esc(u["id"])}">疊圖</a>']
                for u in periodic]
        parts.append(table(["指標", "資料期間", "最新值", "較前值", ""], rows))
    if daily:
        shown = daily[:12]
        bits = [f'{esc(u["name"])} {fmt(u["value"], _digits(u["value"]))}'
                + (f' {delta_span(u["change"], 2)}' if u["change"] is not None else "")
                for u in shown]
        more = f"…等 {len(daily)} 檔" if len(daily) > len(shown) else ""
        parts.append(f'<p class="muted" style="font-size:.86rem;margin-top:10px">'
                     f'日頻更新 {len(daily)} 檔：' + "、".join(bits) + more + "</p>")
    if not parts:
        nxt = next((r for r in (freshness.get("rows") or [])
                    if r.get("days_away") is not None), None)
        hint = (f'下一個：{esc(nxt["name"])}，{_when(nxt["days_away"])}'
                f'（{esc(str(nxt["next_release"]))}）。' if nxt else "")
        parts.append(f'<p class="muted">今天還沒有新公布的總經數據。{hint}</p>')

    return "".join(parts)


def _commodity_row(ctx: dict, name: str) -> dict | None:
    commodities = ctx.get("commodities") or {}
    for group in commodities.get("groups") or []:
        for row in group.get("rows") or []:
            if row.get("name") == name:
                return row
    for row in (commodities.get("precious") or {}).get("rows") or []:
        if row.get("name") == name:
            return row
    return None


def _related_reading(headline: str, ctx: dict) -> str:
    """新聞講到什麼，就把本站對應的讀數放在旁邊。最多兩項，不硬湊。"""
    text = headline.lower()
    out: list[str] = []

    def has(pattern: str) -> bool:
        return re.search(pattern, text) is not None

    if has(r"\b(oil|crude|opec|brent|gasoline|gas prices|energy)\b"):
        row = _commodity_row(ctx, "WTI 原油")
        if row and row.get("value") is not None:
            out.append(f'WTI {fmt(row["value"], 2)} 美元/桶，近一月 '
                       f'{fmt(row.get("chg_1m"), 1, suffix="%", signed=True)}')
    if has(r"\bgold\b"):
        row = _commodity_row(ctx, "黃金")
        if row and row.get("value") is not None:
            out.append(f'黃金 {fmt(row["value"], 0)} 美元/盎司，近一月 '
                       f'{fmt(row.get("chg_1m"), 1, suffix="%", signed=True)}')
    if has(r"\b(fed|fomc|powell|rate cuts?|rate hikes?|interest rates?|"
           r"treasur(ies|ys)|treasury yields?|yields?|bonds?)\b"):
        bits = []
        nominal = ((ctx.get("rates") or {}).get("decomposition") or {}).get("nominal")
        if nominal is not None:
            bits.append(f"10 年期 {pct(nominal, 2)}")
        nxt = (ctx.get("fedfunds") or {}).get("next")
        if nxt:
            bits.append(f'期貨定價 {esc(nxt["label"])} {esc(nxt["headline"])}')
        if bits:
            out.append("，".join(bits))
    if has(r"\b(dollar|yen|yuan|euro|rupee|currenc(y|ies)|forex|fx)\b"):
        world = ctx.get("world") or {}
        dollar = world.get("dollar") or {}
        bits = []
        if dollar.get("broad") is not None:
            bits.append(f'美元廣義指數 {fmt(dollar["broad"], 1)}，近一月 '
                        f'{fmt(dollar.get("chg_1m"), 1, suffix="%", signed=True)}')
        if has(r"\byen\b"):
            jpy = next((r for r in (world.get("fx") or {}).get("rows") or []
                        if r.get("name") == "美元/日圓"), None)
            if jpy and jpy.get("value") is not None:
                bits.append(f'美元/日圓 {fmt(jpy["value"], 2)}')
        if bits:
            out.append("，".join(bits))
    if has(r"\b(stocks?|shares|wall street|s&p|nasdaq|dow|equit(y|ies)|rally|"
           r"sell-?off|investors|futures)\b"):
        us = ((ctx.get("equities") or {}).get("us") or {}).get("indices") or []
        if us and us[0].get("price") is not None:
            out.append(f'{esc(us[0]["name"])} {fmt(us[0]["price"], 2)}'
                       f'（{fmt(us[0].get("change_percent"), 2, suffix="%", signed=True)}）')
    if has(r"\b(bitcoin|crypto|ethereum)\b"):
        rows = ((ctx.get("market") or {}).get("crypto") or {}).get("rows") or []
        if rows and rows[0].get("value") is not None:
            out.append(f'{esc(rows[0]["name"])} {fmt(rows[0]["value"], 0)} 美元，近一月 '
                       f'{fmt(rows[0].get("chg_1m"), 1, suffix="%", signed=True)}')
    if has(r"\b(inflation|cpi|pce|prices)\b"):
        head = (ctx.get("inflation") or {}).get("headline") or {}
        if head.get("core_pce") is not None:
            out.append(f'核心 PCE {pct(head["core_pce"], 1)}、核心 CPI {pct(head.get("core_cpi"), 1)}')
    if has(r"\b(jobs?|payrolls?|unemployment|labor market|jobless)\b"):
        labor = ctx.get("labor") or {}
        rate = (labor.get("unemployment") or {}).get("rate")
        if rate is not None:
            out.append(f'失業率 {pct(rate, 1)}、三月均非農 '
                       f'{thousands_to_wan((labor.get("payrolls") or {}).get("avg3"))}')
    if has(r"\b(recession|gdp)\b"):
        gauge = (ctx.get("growth") or {}).get("gauge") or {}
        if gauge.get("value") is not None:
            out.append(f'衰退風險刻度 {fmt(gauge["value"], 0)}/100（{esc(gauge.get("level", ""))}）')
    if has(r"\b(taiwan|tsmc|chips?|semiconductors?|nvidia)\b"):
        twii = next((r for r in ((ctx.get("equities") or {}).get("tw") or {}).get("index") or []
                     if str(r.get("symbol")) == "^TWII"), None)
        if twii and twii.get("price") is not None:
            out.append(f'台股加權 {fmt(twii["price"], 0)}'
                       f'（{fmt(twii.get("change_percent"), 2, suffix="%", signed=True)}）')
    return "；".join(out[:2])


def _curated_brief(brief: dict) -> str:
    """整理過的要聞：四類、中文 headline、一行說明與來源。"""
    groups = []
    for sec in brief["sections"]:
        if not sec["items"]:
            continue
        items = []
        for it in sec["items"]:
            head = esc(it["headline"])
            if it["link"]:
                head = (f'<a href="{esc(it["link"])}" target="_blank" '
                        f'rel="noopener noreferrer">{head}</a>')
            meta = "　".join(x for x in (esc(it["detail"]), esc(it["source"])) if x)
            items.append(f'<li><span class="bf-h">{head}</span>'
                         + (f'<span class="bf-m">{meta}</span>' if meta else "") + '</li>')
        groups.append(f'<div class="bf-group"><div class="bf-k">{esc(sec["title"])}</div>'
                      f'<ul class="bf-list">{"".join(items)}</ul></div>')
    synthesis = (f'<p class="bf-syn"><strong>與本期判斷的交集</strong>　{esc(brief["synthesis"])}</p>'
                 if brief.get("synthesis") else "")
    stamp = brief["date"].isoformat()
    return ("".join(groups) + synthesis
            + f'<p class="mc-foot-note">整理於 {esc(stamp)}，由排程任務讀完 64 個來源後寫成；'
              f'<a href="/news/">看原始的今日焦點與分類 →</a></p>')


def market_brief(ctx: dict, *, limit: int = 6) -> str:
    """今日資本市場要聞。

    有整理過的 data/brief.json 就用它（中文 headline、四類）；沒有或過期時
    退回關鍵字挑出的原始標題，並在頁面上明講這是未整理的版本。
    """
    from ... import brief as brief_module
    curated = brief_module.load()
    if curated:
        return _curated_brief(curated)

    news = ctx.get("news") or {}
    if not news.get("available"):
        return ('<p class="muted">新聞來源這一輪抓不到，'
                '<a href="/news/">看國際新聞頁的說明</a>。</p>')

    picked: list[tuple[str, int, str]] = []
    seen: list[set[str]] = []

    def take(headline: str, count: int, link: str) -> None:
        tokens = _tokens(_headline(headline))
        if any(_same_story(tokens, t) for t in seen):
            return
        seen.append(tokens)
        picked.append((headline, count, link or ""))

    for group in sorted(news.get("clusters") or [], key=lambda c: -c["count"]):
        if len(picked) >= limit:
            break
        if _is_market(group["headline"]):
            take(group["headline"], group["count"], group.get("link", ""))
    for item in news.get("macro") or []:
        if len(picked) >= limit:
            break
        if _is_market(item["title"]):
            take(item["title"], 1, item.get("link", ""))

    if not picked:
        return '<p class="muted">36 小時內沒有命中資本市場關鍵字的報導。</p>'

    items = []
    for headline, count, link in picked:
        title = esc(_headline(headline))
        if link.lower().startswith(("http://", "https://")):
            title = (f'<a href="{esc(link)}" target="_blank" rel="noopener noreferrer">'
                     f'{title}</a>')
        reading = _related_reading(headline, ctx)
        items.append(f'<div class="digest-item"><span class="digest-n">{count} 家</span>'
                     f'<span class="digest-text">{title}'
                     + (f'<span class="digest-data">{reading}</span>' if reading else "")
                     + '</span></div>')
    return ('<p class="muted" style="font-size:.82rem;margin-bottom:8px">'
            '尚未整理：以下是關鍵字挑出的原始標題，整理版由排程任務每天寫入。</p>'
            f'<div class="digest">{"".join(items)}</div>'
            '<p class="mc-foot-note"><a href="/news/">看今日焦點全表與分類 →</a></p>')


def direction_line(scenario: dict, summary: dict, stance: dict,
                   futures: dict | None = None) -> str:
    """方向一句話：訊號傾向 → 規則上的閘門 → 市場定價，三段收斂。"""
    bits = [f"訊號 {summary['dovish']} 條偏降息、{summary['hawkish']} 條偏升息"]
    first = next((t for t in (scenario.get("transitions") or [])
                  if t.get("gap") is not None), None)
    if first:
        bits.append(f"但規則上要等{esc(first['name'])}政策重心才會換——"
                    f"還差 {fmt(abs(first['gap']), 2)} {esc(first['unit'])}")
    if stance.get("market_implies"):
        bits.append(esc(stance["market_implies"]))
    nxt = (futures or {}).get("next")
    if nxt:
        bits.append(f'期貨定價 {esc(nxt["label"])} {esc(nxt["headline"])}')
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
        + keys_strip(ctx, scenario, summary)
        + f'<div class="callout key">'
          f'{direction_line(scenario, summary, (ctx["rates"] or {}).get("stance") or {}, ctx.get("fedfunds"))}</div>'
        + accordion(f"本期關鍵訊號（{summary['total']} 條）",
                    signals_block(signals, grid=True) + legend_note())
        + accordion("完整敘述", narrative(ctx, scenario, summary))
        + f'<p style="margin:12px 0 0"><a href="/scenario/">'
          f'這個判斷怎麼來的、對應什麼部位　→</a></p>'
        f'</div>')

    # ---- 今天到了什麼：新數據、資本市場要聞（並排一個區塊） ----
    body.append(section(
        "today", "今日更新與要聞",
        f'<div class="today-grid"><div><h3>今日更新的數據</h3>{today_updates_block(ctx)}</div>'
        f'<div><h3>今日資本市場要聞</h3>{market_brief(ctx)}</div></div>',
        note="新數據以台北時間為準；要聞由排程任務每日讀完全部來源後整理成四類"))

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
             ("/scenario/", "情境與部位"), ("/deep-dive/", "深度專題")]
    items = "　·　".join(f'<a href="{h}">{esc(t)}</a>' for h, t in links)
    return section("modules", "看更詳細的模組",
                   f'<p class="mc-foot-note" style="font-size:.88rem">{items}</p>')
