"""總覽頁的分析區塊。

這裡的每一段都回答一個問題，而不是列一堆數字：

  利率結構   殖利率動了，是成長預期還是通膨預期在動？
  數據解讀   這個數字對政策路徑意味著什麼（二階），不是「好／壞」（一階）
  隔夜回顧   板塊怎麼輪動，反映哪一種宏觀敘事
  商品傳導   油銅金的變動會打到台股哪些族群
  含義       規則產生的情境對照——不是投資建議

所有判定都由固定門檻產生，同一份資料每次執行結果一致。
"""
from __future__ import annotations

from ..html import (accordion, callout, delta_span, esc, fmt, pct, section,
                    stat, table, zh_date)


# --------------------------------------------------------------- 1 利率結構 --

def rate_structure(ctx: dict) -> str:
    """殖利率曲線的三個期限、形態含義，以及「為什麼動」的拆解。"""
    rates = ctx.get("rates") or {}
    curve = {r["name"]: r for r in (rates.get("curve") or {}).get("rows") or []}
    shape = rates.get("shape") or {}
    decomp = rates.get("decomposition") or {}
    credit = {c["name"]: c for c in (rates.get("credit") or {}).get("rows") or []}
    if not curve:
        return ""

    tiles = []
    for key, label in [("2Y", "2 年期"), ("10Y", "10 年期"), ("30Y", "30 年期")]:
        row = curve.get(key)
        if not row:
            continue
        tiles.append(stat(
            label, pct(row["value"], 2),
            delta=(f'近一月 {fmt(row["chg_1m"], 2, suffix=" pp", signed=True)}　'
                   f'近三月 {fmt(row["chg_3m"], 2, suffix=" pp", signed=True)}'),
            direction=None,
            asof="2 年期最貼近政策預期" if key == "2Y"
                 else "30 年期最反映供給與期限貼水" if key == "30Y"
                 else "估值的分母"))

    slope = shape.get("slope_10_2")
    slope_chg = shape.get("slope_change_3m")
    level_chg = shape.get("level_change_3m")
    tiles.append(stat(
        "10 年減 2 年", fmt(slope, 2, suffix=" pp", signed=True),
        delta=f'近三月 {fmt(slope_chg, 2, suffix=" pp", signed=True)}',
        direction=None,
        asof=esc(shape.get("label", ""))))

    # 曲線的動法：陡化／平坦化 × 是短端還是長端在帶動
    move = _curve_move(shape, curve)

    # 名目 = 實質 + 通膨補償。哪一邊在帶動，故事完全不同。
    real_chg = decomp.get("real_chg_3m")
    be_chg = decomp.get("be_chg_3m")
    driver = _yield_driver(decomp.get("chg_3m"), real_chg, be_chg)

    decomp_rows = [
        ["10 年名目", pct(decomp.get("nominal"), 2),
         delta_span(decomp.get("chg_3m"), 2, suffix=" pp", good_is_up=False)],
        ["　實質（TIPS）", pct(decomp.get("real"), 2),
         delta_span(real_chg, 2, suffix=" pp", good_is_up=False)],
        ["　通膨補償（breakeven）", pct(decomp.get("inflation_comp"), 2),
         delta_span(be_chg, 2, suffix=" pp", good_is_up=False)],
        ["期限貼水", pct(decomp.get("term_premium"), 2), "—"],
    ]

    credit_rows = [
        [esc(name), pct(c["value"], 2),
         delta_span(c["chg_3m"], 2, suffix=" pp", good_is_up=False),
         fmt(c["pct10y"], 0, suffix="%")]
        for name, c in credit.items() if name in ("投資級", "高收益", "新興市場")
    ]
    hy = credit.get("高收益") or {}
    credit_verdict = _credit_verdict(hy.get("pct10y"), hy.get("chg_3m"))

    return section(
        "rates", "公債利率",
        f'<div class="grid grid-4">{"".join(tiles)}</div>'
        + callout(f'<strong>曲線</strong>：{move}<br><strong>驅動</strong>：{driver}')
        + '<h3 class="fd-h">殖利率上升是成長還是通膨？</h3>'
        + table(["拆解（近三月）", "現值", "變動"], decomp_rows)
        + '<h3 class="fd-h">信用利差（風險胃納的價格）</h3>'
        + table(["類別", "利差", "近三月", "十年百分位"], credit_rows)
        + callout(credit_verdict),
        note="殖利率、利差皆為每日更新；百分位取十年分布",
        terms=["yield_curve", "real_rate"])


def _curve_move(shape: dict, curve: dict) -> str:
    slope_chg = shape.get("slope_change_3m")
    level_chg = shape.get("level_change_3m")
    two = (curve.get("2Y") or {}).get("chg_3m")
    ten = (curve.get("10Y") or {}).get("chg_3m")
    if slope_chg is None or two is None or ten is None:
        return esc(shape.get("label", "資料不足"))

    if abs(slope_chg) < 0.1:
        kind = "形態大致不變（平行移動）"
    elif slope_chg > 0:
        kind = ("<strong>熊市陡化</strong>（長端漲得比短端多）"
                if ten > 0 and ten > two else
                "<strong>牛市陡化</strong>（短端跌得比長端多）")
    else:
        kind = ("<strong>熊市平坦化</strong>（短端漲得比長端多）"
                if two > 0 and two > ten else
                "<strong>牛市平坦化</strong>（長端跌得比短端多）")

    meaning = {
        "熊市陡化": "市場在定價更高的長期通膨或更大的公債供給——對長天期資產與高估值股票最不利。",
        "牛市陡化": "市場在定價降息——通常出現在政策轉向或衰退預期升溫時。",
        "熊市平坦化": "市場在定價聯準會更久的緊縮，短端被政策預期推高。",
        "牛市平坦化": "資金湧入長端避險，或長期成長預期下修。",
    }
    for k, v in meaning.items():
        if k in kind:
            return f"{kind}。{v}"
    return f"{kind}。近三月整體水準 {fmt(level_chg, 2, suffix=' pp', signed=True)}。"


def _yield_driver(nominal_chg, real_chg, be_chg) -> str:
    if nominal_chg is None or real_chg is None or be_chg is None:
        return "拆解資料不足。"
    if abs(nominal_chg) < 0.1:
        return "名目殖利率近三月大致持平，實質與通膨補償的變動互相抵銷。"
    who = "實質利率" if abs(real_chg) > abs(be_chg) else "通膨補償"
    if who == "實質利率":
        story = ("成長預期或期限貼水在推升殖利率，不是通膨——這對估值的壓力"
                 "更直接，因為實質利率就是折現率的分母。"
                 if real_chg > 0 else
                 "實質利率在下行，對高估值資產是支撐。")
    else:
        story = ("市場在上修通膨預期——聯準會的降息空間會被壓縮。"
                 if be_chg > 0 else
                 "通膨預期在降溫，這是聯準會轉向的必要條件。")
    return (f"名目 {fmt(nominal_chg, 2, suffix=' pp', signed=True)} 主要由"
            f"<strong>{who}</strong>帶動"
            f"（實質 {fmt(real_chg, 2, signed=True)}、"
            f"通膨補償 {fmt(be_chg, 2, signed=True)}）。{story}")


def _credit_verdict(pct10y, chg_3m) -> str:
    if pct10y is None:
        return "信用利差資料不足。"
    if pct10y < 20:
        base = ("高收益利差位在十年分布的低檔，信用市場幾乎沒有在定價違約風險"
                "——這種時候壞消息的殺傷力最大，因為沒有緩衝。")
    elif pct10y > 70:
        base = "高收益利差已在十年高檔，信用市場在定價明顯的違約風險。"
    else:
        base = "高收益利差位在十年分布的中段，信用市場定價中性。"
    if chg_3m is not None and abs(chg_3m) >= 0.2:
        base += ("　近三月利差<strong>擴大</strong>，風險胃納在收縮。"
                 if chg_3m > 0 else
                 "　近三月利差<strong>收斂</strong>，風險胃納在擴張。")
    return base


# ------------------------------------------------------ 2 數據與二階解讀 --

def data_reads(ctx: dict) -> str:
    """近期公布的數據：實際 vs 前值 vs 近期趨勢，以及二階解讀。

    刻意不列「市場共識預期」——那是付費資料，本站拿不到。用「近三月
    均值」當基準是誠實的替代：它回答「這次比近期趨勢強還是弱」，
    但不是真正的 surprise。頁面上明講這件事，不假裝有。
    """
    labor = ctx.get("labor") or {}
    inflation = ctx.get("inflation") or {}
    growth = ctx.get("growth") or {}

    rows = []

    payrolls = labor.get("payrolls") or {}
    latest, avg3 = payrolls.get("latest"), payrolls.get("avg3")
    breakeven = (labor.get("breakeven") or {}).get("value")
    if latest is not None and avg3 is not None:
        rows.append({
            "name": "非農就業月增",
            "actual": f'{latest / 10:+.1f} 萬人',
            "prior": f'{(payrolls.get("avg3") or 0) / 10:+.1f} 萬人（三月均）',
            "trend": f'{(payrolls.get("avg12") or 0) / 10:+.1f} 萬人（十二月均）',
            "read": _payroll_read(latest, avg3, breakeven),
        })

    unrate = (labor.get("unemployment") or {}).get("rate")
    if unrate is not None:
        rows.append({
            "name": "失業率",
            "actual": pct(unrate, 1),
            "prior": "—",
            "trend": "—",
            "read": ("失業率每上行 0.1 個百分點，市場對降息的定價就多一分——"
                     "但聯準會在通膨未回到目標前不會單獨對就業轉弱反應。"),
        })

    head = inflation.get("headline") or {}
    mom = inflation.get("momentum") or {}
    core_pce, ann3 = head.get("core_pce"), mom.get("core_pce_3m")
    if core_pce is not None:
        rows.append({
            "name": "核心 PCE 年增率",
            "actual": pct(core_pce, 1),
            "prior": pct(mom.get("core_pce_6m"), 1) + "（近六月年化）",
            "trend": pct(ann3, 1) + "（近三月年化）",
            "read": _inflation_read(core_pce, ann3),
        })

    core_cpi = head.get("core_cpi")
    if core_cpi is not None:
        rows.append({
            "name": "核心 CPI 年增率",
            "actual": pct(core_cpi, 1),
            "prior": "—",
            "trend": pct(mom.get("core_cpi_3m"), 1) + "（近三月年化）",
            "read": ("CPI 早於 PCE 公布，是市場當天交易的標的；但聯準會的"
                     "目標是 PCE，兩者的權重不同（住房在 CPI 裡權重高得多）。"),
        })

    gauge = growth.get("gauge") or {}
    if gauge.get("value") is not None:
        rows.append({
            "name": "衰退風險刻度",
            "actual": f'{gauge["value"]:.0f}/100',
            "prior": "—",
            "trend": esc(gauge.get("level", "")),
            "read": ("這是本站規則引擎的合成刻度，不是外部指標——組成與門檻"
                     "見成長與信用頁。"),
        })

    if not rows:
        return ""

    table_rows = [
        [esc(r["name"]), r["actual"], r["prior"], r["trend"]] for r in rows
    ]
    reads = "".join(
        f'<div class="read-item"><span class="read-name">{esc(r["name"])}</span>'
        f'<span class="read-text">{r["read"]}</span></div>' for r in rows)

    return section(
        "data", "數據與二階解讀",
        table(["指標", "最新值", "前值／基準", "近期趨勢"], table_rows)
        + callout("<strong>這裡沒有「市場共識預期」</strong>：共識資料只有付費"
                  "供應商有（Bloomberg、Refinitiv 等），本站拿不到，所以不假裝"
                  "有。中間兩欄用前值與近期均值當基準——能回答「這次比近期趨勢"
                  "強還是弱」，但不是真正的 surprise。")
        + '<h3 class="fd-h">二階解讀：這個數字對政策路徑意味著什麼</h3>'
        + f'<div class="read-list">{reads}</div>',
        note="一階是「數字好不好」，二階是「政策與估值會怎麼反應」")


def _payroll_read(latest, avg3, breakeven) -> str:
    if breakeven and avg3 is not None:
        if avg3 < breakeven:
            return ("三月均低於損益兩平，勞動市場正在鬆動。一階想法是「就業差"
                    "＝股市差」，二階是：這正是聯準會轉向的必要條件之一，"
                    "但在通膨回到目標前不足以單獨換來降息。")
        return ("三月均高於損益兩平，就業仍在吸收新增勞動力。一階想法是"
                "「就業好＝股市好」，二階是：強勁就業會讓降息預期後移，"
                "折現率維持高檔，高估值資產承壓。")
    return "資料不足以判定與損益兩平的關係。"


def _inflation_read(core_pce, ann3) -> str:
    if ann3 is None or core_pce is None:
        return "動能資料不足。"
    if ann3 < core_pce:
        return ("近三月年化低於年增率，代表最近的漲價速度比過去一年慢——"
                "這是聯準會要看到的方向。但年增率仍高於 2% 目標，"
                "降息的門檻還沒過。")
    return ("近三月年化高於年增率，通膨動能在重新加速——這比年增率本身"
            "更早反映轉折，也是降息預期最容易被推翻的地方。")


# ------------------------------------------- 5 市場定價（精簡＋導向專頁） --

def market_pricing(ctx: dict) -> str:
    """市場怎麼定價這個總經環境。這裡只給結論，細節在各專頁。"""
    eq = ctx.get("equities") or {}
    market = ctx.get("market") or {}
    tw = eq.get("tw") or {}
    us = eq.get("us") or {}
    vol = market.get("volatility") or {}
    risk = market.get("risk") or {}
    liq = market.get("liquidity") or {}

    tiles = []
    for row in (us.get("indices") or [])[:2]:
        tiles.append(stat(row["name"], fmt(row["price"], 2),
                          delta=fmt(row["change_percent"], 2, suffix="%", signed=True),
                          asof=f'昨收 {fmt(row["previous_close"], 2)}'))
    twii = next((r for r in (tw.get("index") or [])
                 if str(r.get("symbol")) == "^TWII"), None)
    if twii:
        tiles.append(stat("台股加權", fmt(twii["price"], 2),
                          delta=fmt(twii["change_percent"], 2, suffix="%", signed=True),
                          asof="證交所即時"))
    if vol.get("vix") is not None:
        tiles.append(stat("VIX", fmt(vol["vix"], 1),
                          delta=esc(vol.get("verdict", "")), direction=None,
                          asof="波動率定價"))

    parts = [f'<div class="grid grid-4">{"".join(tiles)}</div>'] if tiles else []

    rotation = _rotation(us.get("sectors") or [])
    lines = []
    if rotation.get("verdict"):
        lines.append(f'<strong>板塊輪動</strong>：{rotation["verdict"]}')
    if risk.get("score") is not None:
        lines.append(f'<strong>風險胃納</strong>：{risk["score"]:.0f}/100'
                     f'（{esc(risk.get("label", ""))}）')
    if liq.get("latest") is not None:
        lines.append(f'<strong>聯準會淨流動性</strong>：'
                     f'{fmt(liq["latest"] / 1000, 2, suffix=" 兆美元")}，'
                     f'近三月 {fmt(liq.get("chg_3m"), 0, suffix=" 十億", signed=True)}')
    inst = tw.get("institutional") or {}
    if inst.get("foreign") is not None:
        lines.append(f'<strong>台股外資</strong>：'
                     f'{fmt(inst["foreign"], 1, suffix=" 億", signed=True)}'
                     f'（{esc(inst.get("date", ""))}）')
    if lines:
        parts.append(callout("<br>".join(lines)))

    events = _events(ctx)
    if events:
        parts.append('<h3 class="fd-h">當日重大事件</h3>')
        parts.append(f'<div class="digest">{events}</div>')

    parts.append('<p class="mc-foot-note">'
                 '<a href="/equities/">看完整美股與國際 →</a>　'
                 '<a href="/tw/">看完整台股 →</a>　'
                 '<a href="/market/">看股債相關性與實質利率張力 →</a></p>')

    if not parts:
        return ""
    return section("market", "市場定價", "".join(parts),
                   note="指數為建置快照，台股為即時；板塊輪動判定由固定規則產生")


# 類股 ETF 的宏觀屬性。判定 risk-on/off 與循環／防禦要靠這個分類。
CYCLICAL = {"XLK", "XLY", "XLF", "XLI", "XLB", "XLE"}
DEFENSIVE = {"XLP", "XLU", "XLV", "XLRE"}
GROWTH_PROXY = {"XLK", "XLY"}
VALUE_PROXY = {"XLF", "XLE", "XLI", "XLB"}


def _rotation(sectors: list[dict]) -> dict:
    rows = [s for s in sectors if s.get("change_percent") is not None]
    if len(rows) < 4:
        return {}
    ranked = sorted(rows, key=lambda s: s["change_percent"], reverse=True)

    def avg(symbols):
        picked = [s["change_percent"] for s in rows
                  if str(s.get("symbol", "")).upper() in symbols]
        return sum(picked) / len(picked) if picked else None

    cyc, dfn = avg(CYCLICAL), avg(DEFENSIVE)
    gro, val = avg(GROWTH_PROXY), avg(VALUE_PROXY)

    bits = []
    if cyc is not None and dfn is not None:
        gap = cyc - dfn
        if gap > 0.3:
            bits.append(f"risk-on，循環類股領先防禦 {fmt(gap, 2, suffix=' 個百分點')}")
        elif gap < -0.3:
            bits.append(f"risk-off，防禦類股領先循環 {fmt(abs(gap), 2, suffix=' 個百分點')}")
        else:
            bits.append("循環與防禦差距不到 0.3 個百分點，沒有明顯方向")
    if gro is not None and val is not None and abs(gro - val) > 0.3:
        bits.append("成長股領先價值股" if gro > val else "價值股領先成長股")
    if ranked:
        bits.append(f'領漲 {esc(ranked[0]["name"])}、領跌 {esc(ranked[-1]["name"])}')
    return {"ranked": ranked, "verdict": "；".join(bits) + "。" if bits else ""}


def _events(ctx: dict) -> str:
    """當日重大事件：多家媒體同報的財金新聞。"""
    from ...compute.news import _headline, _is_macro
    news = ctx.get("news") or {}
    if not news.get("available"):
        return ""
    items = []
    for c in (news.get("clusters") or [])[:14]:
        if not _is_macro(c["headline"]):
            continue
        items.append(f'<div class="digest-item">'
                     f'<span class="digest-n">{c["count"]} 家</span>'
                     f'<span class="digest-text">{esc(_headline(c["headline"]))}</span>'
                     f'</div>')
        if len(items) >= 4:
            break
    return "".join(items)


# --------------------------------------------- 6 對股市的含義（機械對照） --

def implications(ctx: dict, scenario: dict, summary: dict) -> str:
    """情境 → 方向的機械對照。

    這一段刻意不寫成「建議加碼／減碼」。本站所有判斷都由固定規則產生、
    可回溯也可反駁；一旦寫成建議就失去這個性質，而且那需要知道讀者的
    風險承受度、稅務與既有部位——本站什麼都不知道。
    """
    positions = scenario.get("positions") or []
    regime = scenario.get("regime_label", "")
    rows = [[esc(p.get("asset", "")), esc(p.get("stance", "")),
             esc(p.get("why", ""))] for p in positions]

    sector_rows = _sector_pressure(scenario)

    parts = [callout(
        f'目前情境是<strong>{esc(scenario.get("name", ""))}</strong>，'
        f'政策重心<strong>{esc(regime)}</strong>，訊號合計{esc(summary.get("tilt", ""))}。'
        f'以下是規則把這個情境對照到方向的結果——'
        f'<strong>不是投資建議</strong>，未考慮任何個人的風險承受度、'
        f'稅務與既有部位。', key=True)]

    if rows:
        parts.append(table(["資產", "情境對照的方向", "機制"], rows))
    if sector_rows:
        parts.append('<h3 class="fd-h">類股的傳導方向</h3>')
        parts.append(table(["類股", "在這個情境下", "機制"], sector_rows))
    parts.append(f'<p style="margin-top:12px"><a href="/scenario/">'
                 f'看完整的九宮格定位、轉換門檻與部位對照　→</a></p>')

    return section("implications", "對股市的含義", "".join(parts),
                   note="規則產生的情境對照，不構成投資建議")


# 情境 → 類股方向。依據是折現率與景氣循環的機制，不是歷史回測。
SECTOR_MAP = {
    "通膨優先": [
        ("能源、原物料", "相對受惠", "通膨環境下的定價能力與存貨利益"),
        ("金融", "中性偏多", "利率維持高檔有利淨利差，但信用成本要盯"),
        ("高本益比科技", "承壓", "折現率維持高檔，估值倍數被壓縮"),
        ("公用事業、REITs", "承壓", "債券替代品，實質利率上行時最直接受害"),
    ],
    "就業優先": [
        ("高本益比科技", "相對受惠", "降息預期推升估值倍數"),
        ("公用事業、REITs", "相對受惠", "利率下行讓債券替代品重獲吸引力"),
        ("金融", "承壓", "淨利差收窄"),
        ("循環消費", "看衰退深度", "降息若是因為衰退，需求端會先受傷"),
    ],
    "雙率平衡": [
        ("整體", "中性", "政策沒有明確偏向，個股與獲利面的重要性上升"),
    ],
}


def _sector_pressure(scenario: dict) -> list[list[str]]:
    regime = (scenario or {}).get("regime_label") or ""
    for key, rows in SECTOR_MAP.items():
        if key in regime:
            return [[esc(a), esc(b), esc(c)] for a, b, c in rows]
    return []


# ------------------------------------------------------- 7 今日觀察清單 --

def watchlist(ctx: dict, fomc: dict | None) -> str:
    """今日與未來數日要盯的事件：數據、財報、央行、標售、期權到期。"""
    from ...sources import treasury

    rows = []

    if fomc:
        rows.append({
            "days": fomc["days"], "kind": "央行",
            "what": f'FOMC 利率決策（{fomc["date"].month}/{fomc["date"].day}）',
            "why": "決策日的聲明措辭與點陣圖比升降息本身更常主導行情",
        })

    fresh = ctx.get("freshness") or {}
    for item in (fresh.get("imminent") or [])[:8]:
        rows.append({
            "days": item.get("days_away"), "kind": "數據",
            "what": esc(item["name"]),
            "why": "本站沒有市場共識預期（付費資料），只能對照前值與近期趨勢",
        })

    for auction in treasury.upcoming():
        rows.append({
            "days": auction["days"], "kind": "標售",
            "what": f'{auction["term"]}{auction["type"]}標售',
            "why": "需求疲弱的長天期標售會當天推升整條曲線的長端",
        })

    eq = ctx.get("equities") or {}
    for e in ((eq.get("us") or {}).get("earnings") or [])[:6]:
        rows.append({
            "days": None, "kind": "財報",
            "what": f'{esc(e["symbol"])} 財報（{esc(e["date"][5:].replace("-", "/"))}'
                    + (f'　{esc(e["hour"])}' if e.get("hour") else "") + "）",
            "why": "權值股財報會透過指數權重影響大盤，也影響同族群評價",
        })

    expiry = _next_opex()
    if expiry:
        rows.append({
            "days": expiry["days"], "kind": "期權",
            "what": f'月選擇權到期日（{expiry["date"].month}/{expiry["date"].day}）',
            "why": "到期前後的避險部位調整會放大波動，尤其是季末的四巫日",
        })

    if not rows:
        return ""

    rows.sort(key=lambda r: (r["days"] if r["days"] is not None else 99))
    table_rows = [
        [esc(r["kind"]), r["what"],
         (_when_label(r["days"]) if r["days"] is not None else "—"),
         esc(r["why"])]
        for r in rows
    ]
    return section(
        "watchlist", "今日觀察清單",
        table(["類型", "事件", "時間", "為什麼要盯"], table_rows)
        + callout("<strong>沒有市場共識預期欄位</strong>：consensus 只有付費"
                  "供應商提供。市場交易的是意外（surprise），沒有共識就算不出"
                  "意外——這是本站目前最大的資料缺口，與其塞一個假的數字，"
                  "不如把缺口標明。"),
        note="數據取自 FRED 發布行事曆、標售取自 TreasuryDirect、財報取自 Finnhub")


def _when_label(days: int) -> str:
    return {0: "今天", 1: "明天"}.get(days, f"{days} 天後")


def _next_opex() -> dict | None:
    """下一個月選擇權到期日（每月第三個星期五）。"""
    from datetime import date, timedelta
    today = date.today()
    for offset in (0, 1):
        year = today.year + (today.month + offset - 1) // 12
        month = (today.month + offset - 1) % 12 + 1
        first = date(year, month, 1)
        # 第一個星期五往後推兩週
        friday = first + timedelta(days=(4 - first.weekday()) % 7)
        third = friday + timedelta(days=14)
        if third >= today:
            return {"date": third, "days": (third - today).days}
    return None


# ------------------------------------------ 3 聯準會立場與政策（三處合一） --

def fed_stance(ctx: dict, scenario: dict, fomc: dict | None) -> str:
    """政策現況、上次聲明改了什麼、換檔門檻——三件事合成一段。

    合併的理由：它們回答的是同一個問題「聯準會現在站在哪、什麼會讓它動」。
    原本散在三個區塊，讀者要自己把它們接起來。
    """
    rates = ctx.get("rates") or {}
    stance = rates.get("stance") or {}
    statement = rates.get("statement") or {}

    tiles = []
    if stance.get("policy") is not None:
        tiles.append(stat("政策利率上緣", pct(stance["policy"], 2),
                          delta=f'有效聯邦資金 {pct(stance.get("effective"), 2)}',
                          direction=None, asof="目標區間上緣"))
    if stance.get("real_policy") is not None:
        tiles.append(stat("實質政策利率", pct(stance["real_policy"], 2),
                          delta="政策利率減核心 PCE", direction=None,
                          asof="正值代表政策具限制性"))
    if stance.get("market_implies"):
        tiles.append(stat("市場定價", esc(stance["market_implies"].replace("市場定價", "")),
                          delta=f'2 年期減政策利率 {fmt(stance.get("market_gap"), 2, suffix=" pp", signed=True)}',
                          direction=None, asof="短端公債隱含，非 CME FedWatch"))
    if fomc:
        tiles.append(stat("下次 FOMC",
                          f'{fomc["date"].month}/{fomc["date"].day}',
                          delta=f'還有 {fomc["days"]} 天', direction="hawkish",
                          asof="決策日（聲明與記者會）"))

    parts = [f'<div class="grid grid-4">{"".join(tiles)}</div>'] if tiles else []

    # 上次聲明：只放結論，逐句 diff 在聯準會頁
    if statement:
        vote_changed = statement.get("vote") and statement["vote"] != statement.get("vote_prev")
        bits = [f'{esc(statement["date"])} 的聲明與前一次相比，'
                f'改寫 {len(statement.get("changed") or [])} 句、'
                f'新增 {len(statement.get("added") or [])} 句、'
                f'刪除 {len(statement.get("removed") or [])} 句']
        if statement.get("vote"):
            bits.append(f'表決 {esc(statement["vote"])}'
                        + (f'（前次 {esc(statement["vote_prev"])}）' if vote_changed else ""))
        parts.append(callout(
            "<strong>上次會議聲明</strong>：" + "；".join(bits) + "。"
            + ("　<strong>異議票增加</strong>代表委員會內部對下一步的看法不再一致。"
               if vote_changed else "")
            + f'　<a href="/fed/#statement">看逐句比對與措辭變化 →</a>',
            key=vote_changed))

    # 換檔門檻：規則寫死的閘門
    transitions = [t for t in (scenario.get("transitions") or [])
                   if t.get("gap") is not None]
    if transitions:
        rows = [[esc(t["name"]), esc(t["need"]),
                 f'{fmt(abs(t["gap"]), 2)} {esc(t["unit"])}']
                for t in transitions]
        parts.append('<h3 class="fd-h">什麼會讓判定換檔</h3>')
        parts.append(table(["情境轉換", "需要什麼", "還差"], rows))

    if not parts:
        return ""
    return section("fed", "聯準會立場與政策", "".join(parts),
                   note="政策利率為每日更新；聲明比對取自聯準會官網",
                   terms=["fed_funds", "real_policy_rate"])


# ------------------------------------ 6 商品與傳導（精簡＋導向專頁） --------

TRANSMISSION = [
    ("WTI 原油", "塑化", "cost",
     "原油是乙烯的原料，油價漲推升進料成本"),
    ("WTI 原油", "航運", "cost", "燃油是航運最大的變動成本"),
    ("銅", "重電與電力設備", "revenue", "銅價是全球電網與資本支出的景氣代理"),
    ("黃金", "金融", "macro", "金價反映實質利率與避險需求"),
]


def commodities_block(ctx: dict) -> str:
    comm = ctx.get("commodities") or {}
    rows = []
    for group in (comm.get("groups") or []):
        rows.extend(group.get("rows") or [])
    rows.extend((comm.get("precious") or {}).get("rows") or [])
    by_name = {r["name"]: r for r in rows}

    tiles = []
    for name, note in [("WTI 原油", "供需與地緣"),
                       ("黃金", "實質利率與避險"),
                       ("銅", "全球製造業景氣")]:
        row = by_name.get(name)
        if not row:
            continue
        tiles.append(stat(name, fmt(row.get("value"), 2),
                          delta=f'近一月 {fmt(row.get("chg_1m"), 1, suffix="%", signed=True)}',
                          direction=None, asof=note))
    if not tiles:
        return ""

    eq = ctx.get("equities") or {}
    group_avgs = {g["name"]: g["value"]
                  for g in ((eq.get("tw") or {}).get("group_avgs") or [])}
    trans_rows = []
    for commodity, group, kind, why in TRANSMISSION:
        src = by_name.get(commodity)
        if not src or src.get("chg_1m") is None:
            continue
        move = src["chg_1m"]
        if kind == "cost":
            effect = "成本壓力↑" if move > 3 else "成本壓力↓" if move < -3 else "影響有限"
        elif kind == "revenue":
            effect = "報價／庫存利益↑" if move > 3 else "報價壓力↓" if move < -3 else "影響有限"
        else:
            effect = "避險需求↑" if move > 3 else "避險需求↓" if move < -3 else "影響有限"
        today = group_avgs.get(group)
        trans_rows.append([esc(commodity), fmt(move, 1, suffix="%", signed=True),
                           esc(group), esc(effect),
                           delta_span(today, 2, suffix="%") if today is not None else "—",
                           esc(why)])

    body = f'<div class="grid grid-3">{"".join(tiles)}</div>'
    if trans_rows:
        body += ('<h3 class="fd-h">對台股族群的傳導</h3>'
                 + table(["商品", "近一月", "族群", "方向", "族群今日", "機制"],
                         trans_rows)
                 + callout("傳導方向是規則，不是預測。「族群今日」是即時報價的"
                           "平均，不是傳導的結果——當天股價還受無數其他因素影響。"))
    body += ('<p class="mc-foot-note">'
             '<a href="/commodities/">看貴金屬、能源、工業金屬與農產全表 →</a>　'
             '<a href="/tw/#tw-heat">看台股族群熱力圖 →</a></p>')
    return section("commodities", "商品與傳導", body,
                   note="商品為建置快照；族群漲跌幅取自台股熱力圖")
