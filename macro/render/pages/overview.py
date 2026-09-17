"""總覽頁：一句話結論、關鍵訊號、各模組入口、跟上期比什麼變了。"""
from __future__ import annotations

import re

from ...compute.news import _headline, _is_market, _same_story, _tokens
from ...compute.scenario import REGIME_LABELS
from ...fomc import next_meeting
from . import mandate_cards as cards
from . import overview_blocks as blocks
from ..common import checks_block, legend_note, signals_block
from ..html import (SEV_GLYPH, SEV_TEXT, accordion, callout, delta_span,
                    direction_label, direction_class, esc, fmt, kv, new_badge,
                    pct, section, stat, table, tag, thousands_to_wan, zh_date)

LEAN_COLOR = {"hawkish": "var(--hawkish)", "dovish": "var(--dovish)",
              "neutral": "var(--neutral)"}
LEAN_WASH = {"hawkish": "var(--hawkish-wash)", "dovish": "var(--dovish-wash)",
             "neutral": "var(--neutral-wash)"}


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

    # 事實與判定分開：上面四格是機構發布的數字，下面兩格是本站規則的輸出。
    # 混在同一排會讓「規則說的」看起來跟「BLS 說的」一樣硬。
    facts = [
        key("核心 PCE 年增", pct(core_pce, 1), inf_sub),
        key("失業率", pct(unrate, 1), jobs_sub),
        key("政策利率上緣", pct(stance.get("policy"), 2),
            f'實質 {pct(stance.get("real_policy"), 2)}　' +
            ("具限制性" if (stance.get("real_policy") or 0) > 1 else "接近中性") +
            ("　依聯準會聲明" if stance.get("policy_source") else "")),
        key("10 年期公債", pct(decomp.get("nominal"), 2),
            f'實質 {pct(decomp.get("real"), 2)}　近三月 '
            f'{fmt(decomp.get("chg_3m"), 2, suffix=" pp", signed=True)}'),
    ]
    calls = [
        key("規則訊號", f'{summary["total"]}<span class="unit"> 條</span>',
            f'{summary["dovish"]} 條偏降息、{summary["hawkish"]} 條偏升息'),
        key("情境傾向", esc(scenario["regime_label"]),
            f'{tag(scenario["lean"], summary["tilt"])}　'
            f'就業{esc(scenario["employment_label"])}'
            f'、通膨{esc(scenario["inflation_label"])}'),
    ]
    return (f'<div class="keys keys-fact">{"".join(facts)}</div>'
            f'<div class="keys-split"><span>以上為機構發布的數字</span>'
            f'<span>以下為本站規則的判定</span></div>'
            f'<div class="keys keys-call">{"".join(calls)}</div>')


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


def _curated_brief(brief: dict) -> str:
    """整理過的要聞：四類，預設只出標題。

    內文收在標題底下，點標題才展開。理由是掃視與閱讀是兩件事：早上那一眼要
    的是「今天有哪幾件事」，不是十二段各 90 字的說明；真的想看某一則再點開。
    這也讓這個區塊從全頁最長（2,219 字）縮回一份可以一眼掃完的清單。

    標題本身是展開鈕而不是外連——點標題會跳走的話，就沒有「先看一眼再決定」
    這個動作了。原文連結放在展開後的內文裡。
    """
    groups = []
    for sec in brief["sections"]:
        if not sec["items"]:
            continue
        items = []
        for it in sec["items"]:
            body = []
            if it.get("detail"):
                body.append(f'<p class="bf-detail">{esc(it["detail"])}</p>')
            meta = []
            if it.get("source"):
                meta.append(esc(it["source"]))
            if it.get("link"):
                meta.append(f'<a href="{esc(it["link"])}" target="_blank" '
                            f'rel="noopener noreferrer">看原文 →</a>')
            if meta:
                body.append(f'<p class="bf-m">{"　".join(meta)}</p>')
            if body:
                items.append(
                    f'<li class="bf-item"><details class="bf-d">'
                    f'<summary class="bf-h">{esc(it["headline"])}</summary>'
                    f'<div class="bf-body">{"".join(body)}</div>'
                    f'</details></li>')
            else:
                # 沒有內文可展開就不要做成假的可點元素
                items.append(f'<li class="bf-item"><span class="bf-h bf-flat">'
                             f'{esc(it["headline"])}</span></li>')
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
        items.append(f'<div class="digest-item"><span class="digest-n">{count} 家</span>'
                     f'<span class="digest-text">{title}</span></div>')
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
                latest, asof,
                {"d": "日", "w": "週", "m": "月", "q": "季", "a": "年"}.get(freq, freq),
            ])
        if not rows:
            continue
        drawers.append(accordion(
            f"{label}：全部 {len(rows)} 檔指標",
            table(["指標", "最新值", "資料日期", "頻率"], rows)))

    if not drawers:
        return ""
    return section(
        "indicators", "全部指標",
        "".join(drawers)
        + '<p class="muted" style="margin-top:10px">點指標名稱可以到自選比較頁，'
          '跟其他指標疊在同一張圖上看。</p>',
        note="點指標名稱可疊圖比較")


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


def _fomc_items(state: dict | None) -> list[dict]:
    """FOMC 決議置頂，排在換格之上。

    2026-09-16 升息，總覽兩天都沒有顯示：政策利率讀的是還沒更新的 FRED，
    行事曆在會後默默翻到下一次。所以會後一週內，「決議」或「決議遺漏」
    兩者之一一定出現在這裡（macro/fomc.py decision_status），而且不依賴
    跟昨天的比對——決議不是「讀數變動」，是事件。
    """
    from datetime import date as _date

    if not state or state.get("state") not in ("announced", "missing"):
        return []
    if state["state"] == "announced":
        effective = _date.fromisoformat(state["effective"])
        vote = f'，表決 {state["vote"]}' if state.get("vote") else ""
        return [{
            "rank": -1, "sev": "high", "tag": "FOMC 決議",
            "title": state["headline"],
            "detail": (f'{state["date"]} 聯準會聲明{vote}；'
                       f'新利率 {effective.month}/{effective.day} 生效。'),
            "href": "/fed/#statement",
        }]
    meeting = _date.fromisoformat(state["meeting"])
    return [{
        "rank": -1, "sev": "high", "tag": "FOMC 決議遺漏",
        "title": f"{meeting.month}/{meeting.day} FOMC 決議本站沒有取得",
        "detail": f'{state["reason"]}。政策利率可能仍是舊值，請以聯準會官網為準。',
        "href": "https://www.federalreserve.gov/newsevents/pressreleases.htm",
    }]


def _change_items(diff: dict, reading_changes: list[dict],
                  scenario: dict, prior: dict | None,
                  fomc: dict | None = None) -> list[dict]:
    """把「跟上次建置相比變了什麼」收成一份排好序的清單。

    排序是判斷的輕重，不是時間：換格（九宮格位置變了）永遠排第一，因為它
    代表整套判斷的前提改變；其次是新觸發的嚴重訊號、再其次是跨過門檻的讀數。
    「不再觸發」排最後——訊號消失通常不是新資訊，是舊資訊退場。
    """
    items: list[dict] = _fomc_items(fomc)

    was = (prior or {}).get("scenario") or {}
    for key, cur_key, label in (("employment", "employment_label", "就業"),
                                ("inflation", "inflation_label", "通膨"),
                                ("regime", "regime_label", "政策重心")):
        old, new = was.get(key), scenario.get(cur_key)
        if old and new and old != new:
            items.append({
                "rank": 0, "sev": "high", "tag": "換格",
                "title": f"{label}　{old} → {new}",
                "detail": "九宮格位置改變，底下的訊號與部位對照都跟著重算。",
            })

    for signal in diff.get("added") or []:
        sev = signal.get("severity") or "low"
        items.append({
            "rank": 1 if sev == "high" else 2, "sev": sev, "tag": "新增訊號",
            "title": signal.get("headline") or "",
            "detail": signal.get("evidence") or signal.get("why") or "",
        })

    for change in reading_changes:
        unit = change.get("unit") or ""
        items.append({
            "rank": 3, "sev": "medium", "tag": "讀數變動",
            "title": (f'{change["name"]}　{fmt(change["was"], 2)}'
                      f' → {fmt(change["now"], 2)}{unit}'),
            "detail": "",
            "delta": delta_span(change.get("change"), 2, suffix=unit),
        })

    for signal in diff.get("removed") or []:
        items.append({
            "rank": 4, "sev": "low", "tag": "不再觸發",
            "title": signal.get("headline") or "", "detail": "",
        })

    items.sort(key=lambda i: (i["rank"], {"high": 0, "medium": 1}.get(i["sev"], 2)))
    return items


CHANGE_SCOPE = ("偵測範圍：FOMC 決議、九宮格的三個位置、規則訊號的增減、9 項關鍵讀數。"
                "曲線形狀、市場廣度、法人連續性不在偵測範圍內。")


def changes_top(ctx: dict, diff: dict, reading_changes: list[dict],
                scenario: dict, prior: dict | None, *, shown: int = 8) -> str:
    """總覽最上面的變動卡堆。

    放在判斷之上是刻意的：每天打開來，九成的像素跟昨天一樣，唯一有價值的
    問題是「這一眼跟上一眼之間變了什麼」。看不到答案的話，這一頁就只是
    昨天的頁面再看一次。

    來源是伺服器端算好、直接烘進 HTML 的建置比對——service worker 的快取
    騙不了它，離線打開也仍然為真。
    """
    base = (prior or {}).get("date")
    title = f"自 {base} 以來" if base else "自上次以來"

    fomc_state = ctx.get("fomc")
    if diff.get("first_run"):
        # 沒有上一期可比，但決議不是比對出來的——照樣置頂
        items = _fomc_items(fomc_state)
        if not items:
            return section("changes", title,
                           '<p class="muted">這是第一次建置，還沒有可以比對的上一期。</p>')
    else:
        items = _change_items(diff, reading_changes, scenario, prior, fomc=fomc_state)
    if not items:
        nxt = ((ctx.get("freshness") or {}).get("imminent") or [None])[0]
        tail = ""
        if nxt:
            tail = (f'　下一筆公布：{esc(nxt["name"])}'
                    f'（{_when(nxt.get("days_away"))}）')
        return section(
            "changes", title,
            f'<div class="chg-none">判斷與關鍵讀數與 {esc(str(base or "上次"))} 相同。{tail}</div>'
            f'<p class="chg-scope">{esc(CHANGE_SCOPE)}</p>')

    rows = []
    for item in items[:shown]:
        sev = item["sev"]
        detail = item.get("detail") or ""
        extra = item.get("delta") or ""
        rows.append(
            f'<a class="chg-row" href="{esc(item.get("href") or "/archive/#today")}">'
            f'<span class="chg-sev sev-{esc(sev)}" title="{esc(SEV_TEXT.get(sev, ""))}">'
            f'{SEV_GLYPH.get(sev, "●")}'
            f'<span class="sr-only">{esc(SEV_TEXT.get(sev, ""))}</span></span>'
            f'<span class="chg-body">'
            f'<span class="chg-tag">{esc(item["tag"])}</span>'
            f'<span class="chg-title">{esc(item["title"])}{(" " + extra) if extra else ""}</span>'
            + (f'<span class="chg-detail">{esc(detail)}</span>' if detail else "")
            + f'</span><span class="chg-go" aria-hidden="true">›</span></a>')

    more = ""
    if len(items) > shown:
        more = (f'<a class="chg-more" href="/archive/#today">'
                f'看全部 {len(items)} 項變動　›</a>')

    return section(
        "changes", title,
        f'<div class="chg-stack">{"".join(rows)}</div>{more}'
        f'<p class="chg-scope">{esc(CHANGE_SCOPE)}</p>',
        note=f"共 {len(items)} 項")


def render(ctx: dict, signals: list[dict], summary: dict, scenario: dict,
           diff: dict, reading_changes: list[dict], updated: str,
           prior: dict | None = None) -> str:
    lean = scenario["lean"]
    body = []

    # ---- 1 目前情境（真的 section：側欄目錄與尋找的索引才抓得到它）----
    body.append(verdict_section(ctx, scenario, summary, signals, lean))

    # ---- 2 自上次以來 ----
    body.append(changes_top(ctx, diff, reading_changes, scenario, prior))

    # ---- 3 今天到了什麼（機構發了什麼；與「別人怎麼說」分開容器）----
    body.append(section(
        "today", "今天到了什麼", today_updates_block(ctx),
        note="以台北時間為準；這裡只放機構正式發布的數字"))

    # ---- 4 接下來盯什麼（含換檔門檻：來了會不會改判定）----
    body.append(blocks.watchlist(ctx, next_meeting(), scenario=scenario))

    # ---- 5 今日價格（全頁唯一的即時內容）----
    body.append(blocks.price_band(ctx))

    # ---- 6 雙目標（平日四格，公布日升格成完整卡）----
    body.append(cards.dual_mandate(ctx, scenario))

    # ---- 7 別人怎麼說 ----
    body.append(section(
        "voices", "別人怎麼說",
        '<p class="chg-scope">以下每一句的錯誤責任在報導者。本站沒有為它們設'
        '任何門檻，也不會因為它們改變上面的判定。</p>'
        + market_brief(ctx)))

    # ---- 8 看更詳細的模組 ----
    body.append(module_nav(ctx))

    return "".join(body)


def verdict_section(ctx: dict, scenario: dict, summary: dict,
                    signals: list[dict], lean: str) -> str:
    """目前情境。

    原本是一個 <div class="verdict">，所以 layout 的區塊抽取正則抓不到它——
    側欄的跨頁目錄底下沒有「判定」這一項，尋找頁的全站索引也索引不到全站
    最重要的那一句話。改成真的 section 只花三行，換回錨點、目錄與索引。

    嚴重度高的訊號直接列在版面上，其餘收起來：把全部訊號都摺起來，等於把
    「可反駁」這個性質也一起摺起來，而那是這個產品的全部主張。
    """
    high = [s for s in signals if s.get("severity") == "high"]
    rest = [s for s in signals if s.get("severity") != "high"]
    stance = (ctx["rates"] or {}).get("stance") or {}

    parts = [
        f'<div class="hero-figure">{esc(scenario["name"])}：'
        f'{esc(scenario["regime_label"])}</div>',
        f'<p class="dim" style="margin:0 0 4px">{esc(scenario["regime_explain"])}</p>',
        keys_strip(ctx, scenario, summary),
        f'<div class="callout key">'
        f'{direction_line(scenario, summary, stance, ctx.get("fedfunds"))}</div>',
    ]
    if high:
        parts.append(f'<h3 class="fd-h">最重的 {len(high)} 條規則訊號</h3>')
        parts.append(signals_block(high, grid=True))
    if rest:
        parts.append(accordion(f"其餘 {len(rest)} 條訊號",
                               signals_block(rest, grid=True) + legend_note()))
    parts.append('<p style="margin:12px 0 0"><a href="/scenario/">'
                 '這個判斷怎麼來的、對應什麼部位　→</a></p>')

    return section(
        "verdict", "目前情境",
        f'<div class="verdict verdict-flat" style="--regime-color:{LEAN_COLOR[lean]}">'
        + "".join(parts) + '</div>',
        note="判定由寫死的門檻產生；同一份資料每次執行結果一致")


def module_nav(ctx: dict | None = None) -> str:
    """看更詳細的模組。

    漸進揭露的成敗全在這一行——前面每刪一個區塊，它就多欠一份責任。沒有
    日期的連結列是裝飾；標上「近 7 天有幾檔更新」之後它回答一個真問題：
    這一頁這週沒動，今晚不用點。有更新的排前面。
    """
    links = [("/labor/", "勞動市場", "勞動市場"), ("/inflation/", "通膨", "通膨"),
             ("/fed/", "聯準會與利率", "利率"), ("/debt/", "長端與債務", "債務"),
             ("/growth/", "成長與信用", "成長"), ("/market/", "市場面", "市場"),
             # 台灣的序列不走 FRED，不在新鮮度追蹤清單裡，所以沒有更新徽章。
             # 沒有徽章就沒有——不拿別的模組的計數來假裝它有。
             ("/taiwan/", "台灣總經", None),
             ("/scenario/", "情境與部位", None), ("/deep-dive/", "深度專題", None)]

    counts: dict[str, int] = {}
    for row in ((ctx or {}).get("freshness") or {}).get("rows") or []:
        age = row.get("updated_days")
        if age is not None and age <= 7:
            counts[row.get("module", "")] = counts.get(row.get("module", ""), 0) + 1

    items = []
    for href, label, module in links:
        n = counts.get(module or "", 0)
        badge = (f'<span class="nav-fresh">近 7 天 {n} 檔更新</span>' if n else "")
        items.append((n, f'<a class="mod-link" href="{href}">{esc(label)}{badge}</a>'))
    items.sort(key=lambda x: -x[0])

    return section("modules", "看更詳細的模組",
                   f'<div class="mod-row">{"".join(i[1] for i in items)}</div>')

# --------------------------------------------------------------- 版面預算 --

# 總覽在四個月內被抱怨過兩次「東西太多」。前一次的修法是把表收進摺疊——
# 那是把「決定不了」變成「先收起來」，所以復發了。這一次改成預算加驅逐律：
# 要加第 9 個區塊，必須指名擠掉現有八個裡的哪一個。
#
# 結構類的預算（區塊、表、摺疊、讀數格）只有改程式才會動，所以超標就讓建置
# 失敗。字數不同：它會隨訊號條數與當天新聞長度自然浮動，用硬失敗擋它的代價
# 是「網站因為版面預算而停止更新資料」——那比版面變長嚴重得多，所以只警告。
BUDGET = {
    "sections": 8,
    "tables": 3,
    "accordions": 3,      # 不含要聞的行內展開（見 NEWS_DISCLOSURES）
    "cells": 22,
}
NEWS_DISCLOSURES = 12     # 要聞四類各 3 則，每則一個行內展開；具名例外
VISIBLE_CHARS_SOFT = 2600  # 重構當下實測 2,537，留 2.5% 餘裕


def measure(body: str) -> dict:
    """量總覽的版面用量。輸入是渲染完的 body HTML。"""
    import re
    visible = re.sub(r'<div class="acc-body">.*?</div></details>', "</details>",
                     body, flags=re.S)
    visible = re.sub(r'<div class="bf-body">.*?</div></details>', "</details>",
                     visible, flags=re.S)
    text = re.sub(r"\s+", "", re.sub(r"<[^>]+>", "", visible))
    return {
        "sections": body.count("<section id="),
        "tables": body.count("<table"),
        "accordions": max(0, body.count("<details") - NEWS_DISCLOSURES),
        "cells": (body.count('class="stat') + body.count('class="key"')
                  + body.count('class="mc-cell')),
        "visible_chars": len(text),
    }


def budget_report(body: str) -> tuple[list[str], list[str]]:
    """回傳 (硬性超標, 軟性警告)。硬性超標要讓建置失敗。"""
    used = measure(body)
    hard = [f'{k} {used[k]} 超過上限 {v}——要加東西必須指名擠掉哪一個'
            for k, v in BUDGET.items() if used[k] > v]
    soft = ([f'可見字元 {used["visible_chars"]} 超過 {VISIBLE_CHARS_SOFT}']
            if used["visible_chars"] > VISIBLE_CHARS_SOFT else [])
    return hard, soft
