"""就業與通膨的雙目標卡。

兩張卡刻意用**完全相同的結構**：判定標題 → 四格讀數 → 傳導鏈 → 全指標
下拉。相同的視覺語言讓讀者第二次就不必重新學怎麼讀，也讓「這兩件事
在聯準會眼裡是對等的」這個事實在版面上成立。

四格裡有一格帶綠邊，標示的是**九宮格判定實際採用的那一個口徑**——
其餘三格是脈絡，不是判定依據。這一點在通膨特別重要：媒體報 CPI，
但聯準會的目標是核心 PCE，兩者常常給出不同的印象。
"""
from __future__ import annotations

from .overview_blocks import _inflation_read, _payroll_read
from ..html import (accordion, callout, esc, fmt, new_badge, pct, section,
                    table, zh_date)


def _cell(label, sub, value, foot, *, key=False, badge="") -> str:
    """四格讀數的一格。key=True 會加左側綠邊，標示判定採用的口徑。"""
    return (f'<div class="mc-cell{" mc-key" if key else ""}">'
            f'<div class="mc-label">{esc(label)}{badge}'
            + (f'<span class="mc-sub">｜{esc(sub)}</span>' if sub else "")
            + f'</div><div class="mc-value">{value}</div>'
            f'<div class="mc-foot">{esc(foot)}</div></div>')


def _chain(steps: list[tuple]) -> str:
    """傳導鏈：三張卡以箭頭相連。每張是 (標題, 副標, 讀數, 說明[, 徽章])。"""
    cards = []
    for i, step in enumerate(steps):
        title, sub, reading, note = step[:4]
        badge = step[4] if len(step) > 4 else ""
        if i:
            cards.append('<div class="mc-arrow" aria-hidden="true">→</div>')
        cards.append(
            f'<div class="mc-step"><div class="mc-step-head">{esc(title)}{badge}'
            f'<span class="mc-sub">｜{esc(sub)}</span></div>'
            f'<div class="mc-step-read">{esc(reading)}</div>'
            f'<div class="mc-step-note">{esc(note)}</div></div>')
    return f'<div class="mc-chain">{"".join(cards)}</div>'


def _drawer(bundle, group_key: str, label: str) -> str:
    from ... import catalogue
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
            {"d": "日", "w": "週", "m": "月", "q": "季", "a": "年"}.get(freq, freq)])
    if not rows:
        return ""
    return accordion(f"{label}：全部 {len(rows)} 檔指標",
                     table(["指標", "序列代號", "最新值", "資料日期", "頻率"], rows))


# ------------------------------------------------------------------ 就業 --

def employment(ctx: dict, scenario: dict) -> str:
    labor = ctx.get("labor") or {}
    payrolls = labor.get("payrolls") or {}
    unemployment = labor.get("unemployment") or {}
    jolts = labor.get("jolts") or {}
    claims = labor.get("claims") or {}
    breakeven = (labor.get("breakeven") or {}).get("value")
    if not payrolls:
        return ""

    latest, prev = payrolls.get("latest"), payrolls.get("prev")
    avg3 = payrolls.get("avg3")
    unrate = unemployment.get("rate")

    headline = _employment_headline(latest, avg3, breakeven, unrate,
                                    unemployment.get("prior"))
    fresh = (ctx.get("freshness") or {}).get("fresh") or {}

    cells = "".join([
        _cell("非農就業", "月增", _wan(latest),
              f'上期 {_wan(prev)}' if prev is not None else "—",
              badge=new_badge(fresh, "PAYEMS")),
        _cell("三月均", "降噪後的趨勢", _wan(avg3),
              f'十二月均 {_wan(payrolls.get("avg12"))}'),
        _cell("損益兩平", "撐住失業率所需", _wan(breakeven, signed=False),
              _gap_note(avg3, breakeven)),
        _cell("失業率", "九宮格水準", pct(unrate, 1),
              f'判定 {esc(scenario.get("employment_label", ""))}', key=True,
              badge=new_badge(fresh, "UNRATE")),
    ])

    chain = _chain([
        ("職缺", "需求端",
         f'{fmt(jolts.get("openings"), 0)} 千個'
         + (f'　V/U {fmt(jolts.get("vu_ratio"), 2)}' if jolts.get("vu_ratio") else ""),
         "企業想僱多少人；最早鬆動的一環",
         new_badge(fresh, "JTSJOL")),
        ("流量", "僱用與離職",
         f'招聘 {fmt(jolts.get("hires"), 1)}%　主動離職 {fmt(jolts.get("quits"), 1)}%'
         + (f'　初領 {fmt(claims.get("initial_4w", 0) / 10000, 1)} 萬'
            if claims.get("initial_4w") else ""),
         "主動離職率跌代表勞工不敢換工作，是信心的溫度計",
         new_badge(fresh, "ICSA")),
        ("失業率", "結果",
         f'{fmt(unrate, 1)}%　自然率附近',
         "落後指標；等它動的時候，前兩環早就轉向了"),
    ])

    return section(
        "employment", "就業",
        f'<div class="mc-eyebrow">EMPLOYMENT NOW</div>'
        f'<h3 class="mc-title">{esc(headline)}</h3>'
        f'<p class="mc-lede">先看失業率的格位，再用非農看流量、用職缺與離職'
        f'看需求端；月增波動大，趨勢看三月均。</p>'
        f'<div class="mc-cells">{cells}</div>'
        f'<details class="mc-chain-wrap"><summary class="mc-chain-toggle">'
        f'查看 職缺、流量、失業率 傳導</summary>{chain}</details>'
        + callout("<strong>二階解讀</strong>：" + _payroll_read(latest, avg3, breakeven))
        + _drawer(ctx.get("_bundle"), "labor", "就業")
        + f'<p class="mc-foot-note">非農 {zh_date(labor.get("as_of"))}　'
          f'口徑：月增（千人）；趨勢：近 3 個月平均</p>',
        terms=["breakeven_payrolls"])


def _wan(value, *, signed: bool = True) -> str:
    if value is None:
        return "—"
    return f'{value / 10:+.1f} 萬人' if signed else f'{value / 10:.1f} 萬人'


def _gap_note(avg3, breakeven) -> str:
    if avg3 is None or not breakeven:
        return "—"
    return "三月均低於門檻" if avg3 < breakeven else "三月均高於門檻"


def _employment_headline(latest, avg3, breakeven, unrate, unrate_prior) -> str:
    bits = []
    if latest is not None and avg3 is not None:
        bits.append("非農轉負" if latest < 0 else
                    "非農放緩" if avg3 is not None and latest < avg3 else "非農回升")
    if unrate is not None and unrate_prior is not None:
        diff = unrate - unrate_prior
        bits.append("失業率上行" if diff > 0.05 else
                    "失業率下行" if diff < -0.05 else "失業率持穩")
    return "，".join(bits) if bits else "就業現況"


# ------------------------------------------------------------------ 通膨 --

def inflation(ctx: dict, scenario: dict) -> str:
    infl = ctx.get("inflation") or {}
    head = infl.get("headline") or {}
    mom = infl.get("momentum") or {}
    ppi = infl.get("ppi") or {}
    if not head:
        return ""

    core_pce, core_pce_3m = head.get("core_pce"), mom.get("core_pce_3m")
    trend = ("降溫" if core_pce_3m is not None and core_pce is not None
             and core_pce_3m < core_pce else "升溫")
    ppi_trend = ""
    if ppi.get("core") is not None and ppi.get("core_3m") is not None:
        ppi_trend = "降溫" if ppi["core_3m"] < ppi["core"] else "升溫"

    headline = f'核心 PCE {trend}'
    if ppi_trend:
        headline += f'，PPI 壓力{ppi_trend}'

    fresh = (ctx.get("freshness") or {}).get("fresh") or {}
    cells = "".join([
        _cell("總體 CPI", "民眾體感", pct(head.get("cpi"), 1), "含食物與能源",
              badge=new_badge(fresh, "CPIAUCSL")),
        _cell("核心 CPI", "消費端趨勢", pct(head.get("core_cpi"), 1),
              f'3M 年化 {fmt(mom.get("core_cpi_3m"), 1, suffix="%")}',
              badge=new_badge(fresh, "CPIAUCSL")),
        _cell("總體 PCE", "Fed 2% 目標", pct(head.get("pce"), 1),
              f'3M 年化 {fmt(mom.get("pce_3m"), 1, suffix="%")}',
              badge=new_badge(fresh, "PCEPILFE")),
        _cell("核心 PCE", "九宮格水準", pct(core_pce, 1),
              f'動能 {trend}', key=True,
              badge=new_badge(fresh, "PCEPILFE")),
    ])

    chain = _chain([
        ("PPI", "企業上游",
         f'總體 {fmt(ppi.get("headline"), 1, suffix="%")}'
         f' · 核心 {fmt(ppi.get("core"), 1, suffix="%")}'
         f' · 3M {fmt(ppi.get("core_3m"), 1, suffix="%")}',
         "只判斷成本壓力，不直接移動九宮格",
         new_badge(fresh, "PPIFIS")),
        ("CPI", "消費者價格",
         f'總體 {fmt(head.get("cpi"), 1, suffix="%")}'
         f' · 核心 {fmt(head.get("core_cpi"), 1, suffix="%")}'
         f' · 3M {fmt(mom.get("core_cpi_3m"), 1, suffix="%")}',
         "最早確認消費端轉折與分項來源",
         new_badge(fresh, "CPIAUCSL")),
        ("PCE", "政策口徑",
         f'總體 {fmt(head.get("pce"), 1, suffix="%")}'
         f' · 核心 {fmt(core_pce, 1, suffix="%")}'
         f' · 3M {fmt(core_pce_3m, 1, suffix="%")}',
         "核心年增決定格位；三個月年化只決定方向",
         new_badge(fresh, "PCEPILFE")),
    ])

    dates = []
    if head.get("cpi") is not None:
        dates.append(f'CPI {zh_date(infl.get("as_of"))}')
    if ppi.get("as_of"):
        dates.append(f'PPI {zh_date(ppi["as_of"])}')
    pce_date = infl.get("pce_as_of") or infl.get("as_of")
    if pce_date:
        dates.append(f'PCE {zh_date(pce_date)}')

    return section(
        "inflation", "通膨",
        f'<div class="mc-eyebrow">INFLATION NOW</div>'
        f'<h3 class="mc-title">{esc(headline)}</h3>'
        f'<p class="mc-lede">先看核心 PCE 的格位與方向，再用 CPI 拆消費端、'
        f'PPI 看上游風險；三者不混成單一分數。</p>'
        f'<div class="mc-cells">{cells}</div>'
        f'<details class="mc-chain-wrap"><summary class="mc-chain-toggle">'
        f'查看 PPI、CPI、PCE 傳導</summary>{chain}</details>'
        + callout("<strong>二階解讀</strong>：" + _inflation_read(core_pce, core_pce_3m))
        + _drawer(ctx.get("_bundle"), "inflation", "通膨")
        + f'<p class="mc-foot-note">{esc("　".join(dates))}　'
          f'口徑：年增率；動能：近 3 個月年化</p>',
        terms=["core_inflation", "supercore"])
