"""頭版的排版。

刊名 At the Margin 在這一頁有具體的形狀：版面左側有一條真的頁邊，中間一條直線
從頭畫到尾。正文（直線右邊）講現況，頁邊（直線左邊）只寫變化——跟上一期比動了
多少、離門檻還差多少、離公布還有幾天。沿著直線掃一遍，就是今天。

三條不能破的規矩：

  螢光筆只標「跟上一期不一樣」。頁邊上有黃底的就是變了，沒有的就是沒變。
            離門檻多遠、幾天後公布也寫在頁邊，但不上色——它們不是變化。
  誰說的    每一段開頭有一枚印：實＝機構發布的數字、判＝本站固定規則的判定、
            市＝市場價格、聞＝別人的報導。四種責任不並排、不混色。
            頭條底下的「今日導讀」是第五種：摘＝排程任務（語言模型）寫的摘要，
            只轉述前四種、不另下判斷，而且永遠帶著寫的時間。
  尺        有寫死門檻的畫門檻尺（實線、有刻度）；沒有門檻的只能畫區間尺
            （虛線），不能讓一個區間的端點看起來像一條規則。

每一列都是 .row：.b 是正文、.m 是頁邊。這裡只產生 HTML；樣式在 static/margin.css，
圖與互動在 static/front.js。

頭版有兩個版：美國版（這個檔）與台灣版（front_tw.py），同一個網址，刊頭底下切換。
兩版的段落一一對應，所以切換時讀者停在同一段；台灣版的錨點都以 tw- 開頭。
"""
from __future__ import annotations

import math
import re

from ... import clock
from ...compute.scenario import EMPLOYMENT_BANDS, INFLATION_BANDS
from ..html import (SEV_TEXT, accordion, attr_json, esc, fmt, new_badge, pct,
                    thousands_to_wan, zh_date)
from . import frontpage

WEEKDAYS = "一二三四五六日"
INFLATION_TARGET = 2.0
RESTRICTIVE_REAL_RATE = 1.0     # 本站的分類門檻：實質政策利率高於此，尺上標成「限制性」
# 離門檻不到這個距離就不判定落在哪一邊。核心 PCE 年增率只到小數一兩位、每月還會修正，
# 0.99 與 1.01 的差別在資料誤差裡；讓標籤跟著它翻面，等於把雜訊當成判定。
NEAR_THRESHOLD = 0.10
MINUS = "−"                # 頁邊的數字用真的負號，不用連字號

DIR_CLASS = {"hawkish": "hk", "dovish": "dv"}
DIR_TEXT = {"hawkish": "利升息", "dovish": "利降息", "neutral": "中性"}
SEV_CLASS = {"high": "sv-1", "medium": "sv-2", "low": "sv-3"}


# ------------------------------------------------------------------ 零件 ----

def _signed(value: float, digits: int = 2) -> str:
    return fmt(value, digits, signed=True).replace("-", MINUS)


def _delta_digits(value: float) -> int:
    """變動量的小數位跟著量級走：兩千人的變動不需要「.00」。"""
    size = abs(value)
    return 0 if size >= 100 else (1 if size >= 10 else 2)


def row(body: str, margin: str = "", *, cls: str = "", tag: str = "div", attrs: str = "") -> str:
    """一列：正文＋頁邊。頁邊沒東西就不輸出——空的頁邊就是「沒變」。"""
    side = f'<div class="m">{margin}</div>' if margin else ""
    classes = f"row {cls}".strip()
    return f'<{tag} class="{classes}"{attrs}><div class="b">{body}</div>{side}</{tag}>'


def note(key: str, small: str = "", *, kind: str = "") -> str:
    """頁邊批註。kind：chg＝跟上一期不同（螢光筆）、up／dn＝價格漲跌、na＝沒有資料、
    空字串＝不是變化的註記（離門檻多遠、幾天後）。"""
    tail = f"<small>{small}</small>" if small else ""
    classes = f"mn {kind}".strip()
    return f'<span class="{classes}"><span class="k">{key}</span>{tail}</span>'


def seal(kind: str) -> str:
    """責任印。實＝機構事實、判＝本站規則、市＝市場價格、聞＝別人的報導、缺＝本站沒拿到、
    摘＝排程任務寫的摘要。"""
    cls = {"實": "s-fact", "聞": "s-said", "缺": "s-gap", "市": "s-mkt", "摘": "s-sum"}.get(kind, "")
    return f'<span class="seal {cls}" aria-hidden="true">{kind}</span>'


def sec_open(anchor: str, title: str, *, kind: str = "", sub: str = "", cls: str = "",
             nav: str = "") -> str:
    """段落開頭。data-title 給側欄目錄與站內搜尋用（layout.extract_sections）；
    nav 是那裡要顯示的名字，沒給就用標題。"""
    classes = f"sec {cls}".strip()
    mark = seal(kind) if kind else ""
    lede = f"<p>{sub}</p>" if sub else ""
    return (f'<section id="{esc(anchor)}" class="{classes}" data-title="{esc(nav or title)}">'
            + row(f'<h2>{mark}{esc(title)}</h2>{lede}', cls="sh rv", tag="header"))


def _phrases(parts: list[str], cls: str) -> str:
    return "".join(f'<span class="{cls} {cls}{i + 1}">{esc(part)}</span>'
                   for i, part in enumerate(parts) if part)


def _by_comma(text: str) -> list[str]:
    """依逗號切句。中文沒有空格，瀏覽器會在任何兩個字之間換行；
    「聯準會／的重心仍在物價」這種斷法只能靠自己擋。"""
    return [p for p in re.split(r"(?<=[，；：])", text) if p]


# ------------------------------------------------------------------ 刊頭 ----

def masthead(trust_row: str) -> str:
    """刊頭全站共用，定義在 layout。"""
    from ..layout import masthead as shared
    return shared(trust_row)


def edition_row() -> str:
    """刊頭底下的版別：美國版｜台灣版。哪一版亮著由 <html data-ed> 決定（BOOT 在
    第一次繪製前設好），所以這裡不標預設——標了，記住台灣版的人會先看到美國版閃一下。"""
    from ..layout import edition_tabs
    return row(edition_tabs(), '<span class="edsw-k" aria-hidden="true">版別</span>', cls="edrow")


# -------------------------------------------------- 頁邊：自上一期以來 ----

def since_items(diff: dict, reading_changes: list[dict], scenario: dict,
                prior: dict | None) -> list[dict]:
    """跟上一期比，變了什麼。順序是輕重不是時間：換格 > 新訊號 > 讀數 > 訊號退場。"""
    items: list[dict] = []
    was = (prior or {}).get("scenario") or {}
    for key, cur_key, label in (("employment", "employment_label", "就業"),
                                ("inflation", "inflation_label", "通膨"),
                                ("regime", "regime_label", "政策重心")):
        old, new = was.get(key), scenario.get(cur_key)
        if old and new and old != new:
            items.append({"big": f"{old}→{new}", "text": True, "name": f"{label}換格",
                          "ft": "九宮格位置改變"})
    added = diff.get("added") or []
    if added:
        more = f"等 {len(added)} 條" if len(added) > 1 else ""
        items.append({"big": f"+{len(added)}", "name": "新增訊號", "long": True,
                      "ft": esc(added[0].get("headline") or "") + more})
    for change in reading_changes or []:
        unit = change.get("unit") or ""
        items.append({
            "big": _signed(change["change"], _delta_digits(change["change"])),
            "name": change["name"],
            "ft": f'{fmt(change["was"], 2)} → <em>{fmt(change["now"], 2)}{esc(unit)}</em>'})
    removed = diff.get("removed") or []
    if removed:
        more = f"等 {len(removed)} 條" if len(removed) > 1 else ""
        items.append({"big": f"{MINUS}{len(removed)}", "name": "不再觸發", "long": True,
                      "ft": esc(removed[0].get("headline") or "") + more})
    items.extend(retired_items(diff))
    return items


def retired_items(diff: dict) -> list[dict]:
    """本站停用的規則。它跟「不再觸發」分開列：這是規則變了，不是數據變了。"""
    retired = diff.get("retired") or []
    if not retired:
        return []
    more = f"等 {len(retired)} 條" if len(retired) > 1 else ""
    return [{"big": f"{MINUS}{len(retired)}", "name": "本站停用規則", "long": True,
             "ft": esc(retired[0].get("headline") or "") + more + "（規則改了，不是數據變了）"}]


def since_block(items: list[dict], prior: dict | None, first_run: bool, *, shown: int = 4,
                prefix: str = "", none_text: str = "") -> str:
    """頭條旁邊那一欄頁邊。有變動才有黃底；沒變動時這一欄是空白的紙。

    none_text：沒有項目時要說的話。預設是「跟上一期相同」；台灣版在上一期沒有記錄
    台灣讀數時要換一句——那是比不了，不是沒變。
    """
    from ..layout import TAGLINE
    base = (prior or {}).get("date")
    head = (f'自 <time datetime="{esc(base)}">{esc(base)}</time> 以來' if base else "自上一期以來")
    if first_run:
        body = '<p class="since-none">這是第一期，還沒有可以比對的上一期。</p>'
    elif not items:
        same = none_text or f'判斷與關鍵讀數與 {base or "上一期"} 相同。'
        body = ('<p class="since-none">'
                + "".join(f"<span>{esc(part)}</span>" for part in _by_comma(same)) + "</p>")
    else:
        rows = []
        for item in items[:shown]:
            big_cls = "d"
            if item.get("text"):
                # 「黃紅→紅」比「高→中」長，同一個字級會在頁邊折成兩行
                big_cls = "d d-t d-long" if len(item["big"]) > 3 else "d d-t"
            ft_cls = "ft ft-t" if item.get("long") else "ft"
            rows.append(f'<li><span class="{big_cls}">{esc(item["big"])}</span>'
                        f'<span class="w"><b>{esc(item["name"])}</b>'
                        f'<span class="{ft_cls}">{item["ft"]}</span></span></li>')
        more = (f'<a class="since-more" href="/archive/#today">看全部 {len(items)} 項 →</a>'
                if len(items) > shown else "")
        body = f'<ol>{"".join(rows)}</ol>{more}'
    return (
        '<div class="hero-m">'
        f'<p class="tagline">{esc(TAGLINE)}</p>'
        f'<section class="since" aria-labelledby="{prefix}h-since">'
        f'<h2 id="{prefix}h-since">{head}</h2>{body}</section>'
        '<button class="scan" type="button" aria-pressed="false" '
        'title="把正文調淡，只沿著頁邊讀今天的變化（快捷鍵 M）">只看頁邊<kbd>M</kbd></button>'
        '</div>')


# ------------------------------------------------------------------ 頭條 ----

DECIDED = {"轉向", "變動", "調整", "不變", "遺漏"}


def story_block(story: dict | None, events: dict | None = None) -> str:
    """頭條底下的今日導讀：兩段，排程任務寫的。

    它是全頁唯一不是由程式從資料算出來的文字，所以三件事不能省：
      - 印「摘」，不借「實」「判」的印——它不是機構的數字，也不是本站規則的判定
      - 寫的時間永遠在標題列上（不是今天寫的就連日期一起寫）
      - 寫完之後才公布的決議或數據，文章不可能提到：點名講出來，
        不讓讀者以為文章已經把它算進去了
    story 是 brief.story() 的結果；None 就整塊不出現，不放佔位的字。
    """
    if not story:
        return ""
    written = story["written"].astimezone(clock.TAIPEI)
    stamp = f"{written:%H:%M}"
    if written.date() != clock.today():
        stamp = f"{written.month}/{written.day} {stamp}"
    later = [e for e in (events or {}).get("events") or []
             if e.get("today") and e.get("at") is not None and e["at"] > written
             and ("已公布" in (e.get("tag") or "") or e.get("policy") in DECIDED)]
    note = "語言模型讀完本站數據與新聞後寫的摘要：只轉述，不另下判斷。"
    if later:
        names = "、".join(dict.fromkeys(e["title"].split("　")[0] for e in later[:3]))
        note += f'<strong>寫在「{esc(names)}」公布之前，沒有提到它。</strong>'
    body = "".join(f"<p>{esc(paragraph)}</p>" for paragraph in story["paragraphs"])
    return ('<article class="story">'
            f'<h2 class="story-k">{seal("摘")}今日導讀'
            f'<time datetime="{esc(written.isoformat(timespec="minutes"))}">寫於 {esc(stamp)}</time></h2>'
            f'{body}<p class="story-n">{note}</p></article>')


def lead_note(gists: str, story: str = "") -> str:
    """頭條底下那一區。有導讀時導讀佔主欄，原本那幾句短的（本站規則、市場）排到旁邊。"""
    if story:
        return f'<div class="lead-note has-story">{story}<div class="gists">{gists}</div></div>'
    return f'<div class="lead-note">{gists}</div>'


def gist_blocks(scenario: dict, summary: dict, stance: dict, futures: dict | None,
                standing: dict | None, story: str = "") -> str:
    """頭條底下的兩三句：本站規則怎麼說、市場怎麼定價。兩者責任不同，所以分兩欄。"""
    rule = f"訊號 {summary['dovish']} 條偏降息、{summary['hawkish']} 條偏升息"
    first = next((t for t in (scenario.get("transitions") or []) if t.get("gap") is not None), None)
    if first:
        rule += (f'；依本站規則要等{esc(first["name"])}，分類才會換'
                 f'<span class="dash">——</span><strong>還差 {fmt(abs(first["gap"]), 2)} '
                 f'{esc(first["unit"])}</strong>')
    blocks = []
    if standing:
        blocks.append(f'<div class="gist"><h2>目前情境</h2><p><a href="/scenario/">'
                      f'{esc(standing["headline"])}</a></p></div>')
    blocks.append(f'<div class="gist"><h2>本站規則</h2><p>{rule}。</p></div>')
    market = []
    if stance.get("market_implies"):
        market.append(esc(stance["market_implies"]))
    nxt = (futures or {}).get("next")
    if nxt:
        market.append(f'期貨定價 {esc(nxt["label"])} {esc(nxt["headline"])}')
    if market:
        blocks.append(f'<div class="gist"><h2>市場</h2><p>{"；".join(market)}。</p></div>')
    return lead_note("".join(blocks), story)


def hero_shell(lede: dict, since_html: str, gist_html: str, *, prefix: str = "",
               nav: str = "頭條") -> str:
    """頭條的外殼：兩個版共用。印哪一枚印看頭條的來源——本站的判定印「判」、
    本站沒拿到印「缺」，其餘（決議、數據、國發會的燈號）都是機構事實。"""
    kind = lede["kind"]
    mark = {"verdict": "判", "gap": "缺"}.get(kind, "實")
    quiet = f'<span>{esc(lede["quiet"])}</span>' if lede.get("quiet") else ""
    phrases = lede.get("phrases") or _by_comma(lede["headline"])
    figure = f'<p class="lede-fig">{esc(lede["figure"])}</p>' if lede.get("figure") else ""
    deck = (f'<p class="sub">{_phrases(_by_comma(lede["deck"]), "cl")}</p>'
            if lede.get("deck") else "")
    # 兩個版各有一個 h1，但同一時間只有一個版在畫面與無障礙樹裡（另一版 display:none）。
    head = (
        f'<div class="lead-head lede-{esc(kind)}">'
        f'<p class="eyebrow"><b>{seal(mark)}{esc(lede["eyebrow"])}</b>{quiet}</p>'
        f'<h1 id="{prefix}lede-h"><a href="{esc(lede["href"])}">{_phrases(phrases, "l")}</a></h1>'
        f'{figure}{deck}</div>')
    return (f'<section id="{prefix}lede" class="hero" data-title="{esc(nav)}" '
            f'aria-labelledby="{prefix}lede-h">' + head + since_html + gist_html + '</section>')


def hero(ctx: dict, scenario: dict, summary: dict, diff: dict,
         reading_changes: list[dict], prior: dict | None, *,
         events: dict | None = None, story: dict | None = None) -> tuple[str, bool]:
    """頭條＋頁邊的變動欄。回傳 (HTML, 有沒有變動)。

    events：這一版要看的事件（美國版傳 events.for_region(…, "美國")）。沒給就用全部。
    story：這一版的今日導讀（brief.story 的結果），沒有就不出現。
    """
    events = ctx.get("events") if events is None else events
    lede = frontpage.lede(events, scenario, ctx.get("_bundle"))
    items = since_items(diff, reading_changes, scenario, prior)
    stance = (ctx.get("rates") or {}).get("stance") or {}
    standing = frontpage.verdict_lede(scenario) if lede["kind"] != "verdict" else None
    body = hero_shell(lede, since_block(items, prior, bool(diff.get("first_run"))),
                      gist_blocks(scenario, summary, stance, ctx.get("fedfunds"), standing,
                                  story_block(story, events)))
    return body, bool(items)


# ---------------------------------------------------- 圖：直線就是 Y 軸 ----

def gate_chart(ctx: dict, scenario: dict) -> str:
    """核心 PCE 對門檻。這張圖的 Y 軸就是版面那條直線，刻度寫在頁邊。

    它畫的是九宮格通膨那一軸的唯一輸入，所以門檻線就是規則本身。缺資料的月份
    （2025-10 政府關門）不連線，由 front.js 畫成虛線橋接。
    """
    bundle = ctx.get("_bundle")
    core = (ctx.get("inflation") or {}).get("headline", {}).get("core_pce")
    series = bundle["PCEPILFE"] if bundle is not None else None
    if core is None or not series:
        return ""
    yoy = series.yoy().tail(36)
    if len(yoy.values) < 6:
        return ""
    low, high = INFLATION_BANDS["low"], INFLATION_BANDS["high"]
    state = scenario.get("inflation_state")
    if state == "high":
        gate, target_zone, gap = high, "中", core - high
        rule = f"降到 {high:.1f}% 以下，通膨才由「高」轉「中」"
    elif state == "low":
        gate, target_zone, gap = low, "中", low - core
        rule = f"升到 {low:.1f}% 以上，通膨才由「低」轉「中」"
    else:
        up, down = high - core, core - low
        gate, target_zone, gap = (high, "高", up) if up <= down else (low, "低", down)
        rule = f"升到 {high:.1f}% 以上轉「高」，降到 {low:.1f}% 以下轉「低」"
    ann3 = (ctx["inflation"].get("momentum") or {}).get("core_pce_3m")
    trend = ""
    if ann3 is not None:
        trend = f"近三月年化 {ann3:.1f}%，" + ("放緩中" if ann3 < core else "仍在加速")
    values = [round(v, 3) for v in yoy.values]
    spec = {
        "dates": [d.isoformat() for d in yoy.dates], "values": values,
        # 值域：涵蓋資料、兩道門檻與目標，上下各留一點
        "lo": math.floor((min(values + [INFLATION_TARGET, low]) - 0.3) * 10) / 10,
        "hi": math.ceil((max(values + [high]) + 0.25) * 10) / 10,
        "grid": 0.5, "digits": 1,
        "thr": [{"v": low, "name": "門檻"}, {"v": high, "name": "門檻"}],
        "gate": gate, "goal": {"v": INFLATION_TARGET, "name": "目標"},
        # 斜線＝本站規則判定為「高」的區域
        "zones": [{"dir": "above", "v": high, "style": "hatch"}],
        "gap": f"{abs(gap):.2f}", "gapWord": "還差", "last": f"{core:.1f}%",
        "ann3": (round(ann3, 2) if ann3 is not None else None), "trend": trend,
    }
    last_period = zh_date(yoy.dates[-1], freq="m")
    label = (f"核心 PCE 年增率折線圖。最新值 {core:.2f}%，本站門檻 {low:.1f}% 與 {high:.1f}%，"
             f"離「{target_zone}」還差 {abs(gap):.2f} 個百分點；聯準會目標 {INFLATION_TARGET:.0f}%。{trend}")
    return (
        '<div class="sec gate">'
        + row(f'<h2>核心 PCE 離「{target_zone}」還差 {fmt(abs(gap), 2)} 個百分點。</h2>'
              f'<p>核心 PCE 年增率，%。門檻是寫死的：{rule}。</p>', cls="sh rv", tag="header")
        + f'<figure class="row gchart rv" role="img" aria-label="{esc(label)}" '
          f'data-gate="{attr_json(spec)}">'
          '<div class="b"><div class="plot"></div></div>'
          '<div class="m yax" aria-hidden="true"></div></figure>'
        + row(f'<p class="fig-src">資料：BEA 核心 PCE 物價指數年增率，至 {esc(last_period)}。'
              f'斜線區是高於 {high:.1f}%（判定為「高」）的時段；沒有資料的月份不連線。'
              f'{low:.1f}% 與 {high:.1f}% 是本站的分類門檻，不是聯準會的決策門檻；'
              f'聯準會的 {INFLATION_TARGET:.0f}% 目標指的是整體 PCE。'
              '<a href="/inflation/">看完整通膨拆解 →</a></p>')
        + '</div>')


# ---------------------------------------------------------------- 門檻尺 ----

def _pos(value: float, lo: float, hi: float) -> float:
    if hi <= lo:
        return 50.0
    return max(0.0, min(100.0, (value - lo) / (hi - lo) * 100.0))


def _edge(position: float) -> str:
    """貼近兩端的標籤改成靠邊對齊，不然會凸出尺外。"""
    return " at-start" if position < 7 else (" at-end" if position > 93 else "")


def ruler(*, lo: float, hi: float, now: float | None, prev: float | None = None,
          ticks: list[tuple[float, str]] | None = None,
          refs: list[tuple[float, str]] | None = None,
          zones: list[tuple[float, float, str]] | None = None,
          kind: str = "threshold", flag: str = "", step: float | None = None,
          label: str = "", dense: bool = False, undecided: bool = False) -> str:
    """一把尺。kind：threshold（寫死的門檻）或 range（只是區間，沒有規則）。

    ticks  規則裡寫死的門檻，畫成長刻度，數字標在尺下
    refs   不是本站門檻、但讀者需要的參考點（聯準會的 2% 目標），標在尺上、畫成空心
    zones  門檻切出來的格位名稱，標在尺下兩個門檻之間；現在落在哪一格，那一格加重
    flag   現在位置上方的小旗（實際讀數）。主數字四捨五入過，離門檻多遠要看這個
    step   小刻度的間距（跟尺同單位）。只有門檻尺有——區間尺沒有刻度可言

    prev 與 now 不同時，中間那一段塗螢光筆。prev 缺或相同就不塗——沒變就是沒變。
    """
    if now is None:
        return '<div class="ruler ruler-empty"><span class="na">—</span></div>'
    at = _pos(now, lo, hi)
    marks = []
    for start, end, name in zones or []:
        left, right = _pos(max(start, lo), lo, hi), _pos(min(end, hi), lo, hi)
        on = " on" if (start <= now < end and not undecided) else ""
        marks.append(f'<i class="rz{on}" style="--p:{(left + right) / 2:.2f}%">{esc(name)}</i>')
    for value, text in ticks or []:
        position = _pos(value, lo, hi)
        marks.append(f'<i class="rt{_edge(position)}" style="--p:{position:.2f}%">'
                     f'<b>{esc(text)}</b></i>')
    for value, text in refs or []:
        position = _pos(value, lo, hi)
        # 參考點的字跟小旗同一排；兩者太近時只留小旗（刻度本身還在）
        name = "" if abs(position - at) < 14 else f'<b>{esc(text)}</b>'
        marks.append(f'<i class="rr{_edge(position)}" style="--p:{position:.2f}%">{name}</i>')
    moved = prev is not None and abs(prev - now) > 1e-9
    if moved:
        a, b = sorted((_pos(prev, lo, hi), at))
        # 移動太小時尺上看不出來：給它一個看得見的最小寬度，但不改位置
        marks.append(f'<i class="rm-move" style="--a:{a:.2f}%;--w:{max(b - a, 0.9):.2f}%"></i>')
        marks.append(f'<i class="rm rm-prev" style="--p:{_pos(prev, lo, hi):.2f}%"></i>')
    tip = f'<b>{esc(flag)}</b>' if flag else ""
    marks.append(f'<i class="rm rm-now{_edge(at)}" style="--p:{at:.2f}%">{tip}</i>')
    style = ""
    if step and kind == "threshold" and hi > lo:
        # 第一條小刻度離左端多遠。刻度畫在一個從那裡開始的偽元素上，
        # 所以間距要換算成「剩下那段寬度」的百分比，不是整把尺的。
        first = ((-lo) % step) / (hi - lo) * 100
        style = (f' style="--first:{first:.3f}%;'
                 f'--step:{step / (hi - lo) * 100 / (100 - first) * 100:.4f}%"')
    extra = " ruler-dense" if dense else ""
    return (f'<div class="ruler ruler-{esc(kind)}{extra}" role="img" aria-label="{esc(label)}">'
            f'<div class="ruler-track"{style}>{"".join(marks)}</div></div>')


# -------------------------------------------------------------- 四個數字 ----

def figure_rows(ctx: dict, scenario: dict, reading_changes: list[dict]) -> list[dict]:
    """四個機構發布的數字，各自帶一把尺。回傳資料，不含 HTML 排版。

    gap＝離最近的門檻還差多少（寫在頁邊，不上色）。change＝跟上一期的差（上色）。
    """
    labor, inflation = ctx["labor"], ctx["inflation"]
    rates = ctx.get("rates") or {}
    stance = rates.get("stance") or {}
    decomp = rates.get("decomposition") or {}
    changed = {c["name"]: c for c in reading_changes or []}

    def prev_of(name: str, now: float | None) -> float | None:
        return changed[name]["was"] if name in changed else now

    rows = []

    # 1. 核心 PCE：九宮格的通膨格位
    core = inflation["headline"]["core_pce"]
    ann3 = inflation["momentum"].get("core_pce_3m")
    low_band, high_band = INFLATION_BANDS["low"], INFLATION_BANDS["high"]
    sub = ""
    if ann3 is not None and core is not None:
        sub = f'3M 年化 {pct(ann3, 1)}，' + ("放緩中" if ann3 < core else "仍在加速")
    gap = None
    if core is not None:
        below = [b for b in (high_band, low_band) if core > b]
        gap = (core - below[0]) if below else (low_band - core)
    top = max(4.0, (core or 0) + 0.4)
    rows.append({
        "name": "核心 PCE 年增", "href": "/inflation/", "value": pct(core, 1),
        "read": f'通膨{scenario["inflation_label"]}',
        "dir": {"high": "hk", "low": "dv"}.get(scenario.get("inflation_state"), "nt"), "sub": sub,
        "change": changed.get("核心 PCE"),
        "ruler": dict(lo=1.5, hi=top, now=core, prev=prev_of("核心 PCE", core),
                      kind="threshold", step=0.1, flag=fmt(core, 2),
                      ticks=[(low_band, f"{low_band:.1f}"), (high_band, f"{high_band:.1f}")],
                      refs=[(INFLATION_TARGET, f"目標 {INFLATION_TARGET:.0f}%")],
                      zones=[(1.5, low_band, "低"), (low_band, high_band, "中"),
                             (high_band, top + 1, "高")],
                      label=f"核心 PCE {pct(core, 2)}；門檻 {low_band}% 與 "
                            f"{high_band}%，目標 {INFLATION_TARGET:.0f}%"),
        "gap": ({"value": fmt(gap, 2), "what": "離下一格", "unit": "個百分點"}
                if gap is not None else None),
    })

    # 2. 失業率：看的是離一年低點多遠，不是絕對水準
    unemployment = labor["unemployment"]
    rate, low12 = unemployment.get("rate"), unemployment.get("low12")
    avg3, breakeven = labor["payrolls"].get("avg3"), labor["breakeven"].get("value")
    sub = ""
    if avg3 is not None:
        sub = f'三月均非農 {thousands_to_wan(avg3)}'
        if breakeven:
            sub += "，低於損益兩平" if avg3 < breakeven else "，高於損益兩平"
    weak_at = (low12 + EMPLOYMENT_BANDS["weak_unrate_gap"]) if low12 is not None else None
    rows.append({
        "name": "失業率", "href": "/labor/", "value": pct(rate, 1),
        "read": f'就業{scenario["employment_label"]}',
        "dir": {"strong": "hk", "weak": "dv"}.get(scenario.get("employment_state"), "nt"), "sub": sub,
        "change": changed.get("失業率"),
        "ruler": (dict(lo=low12 - 0.2, hi=max(low12 + 0.9, (rate or 0) + 0.2), now=rate,
                       prev=prev_of("失業率", rate), kind="threshold", step=0.1,
                       flag=fmt(rate, 1),
                       ticks=[(low12, f"{low12:.1f} 一年低點"), (weak_at, f"{weak_at:.1f} 轉弱")],
                       label=f"失業率 {pct(rate, 1)}；一年低點 {low12:.1f}%，"
                             f"高出 {EMPLOYMENT_BANDS['weak_unrate_gap']} 個百分點視為轉弱")
                  if low12 is not None else dict(lo=0, hi=1, now=None)),
        "gap": ({"value": fmt(weak_at - rate, 1), "what": "離轉弱", "unit": "個百分點"}
                if (weak_at is not None and rate is not None and weak_at > rate) else None),
    })

    # 3. 政策利率：尺量的是實質利率，所以尺上要寫明
    policy, real = stance.get("policy"), stance.get("real_policy")
    prev_real = None
    if real is not None:
        was_policy = prev_of("政策利率上緣", policy)
        was_core = prev_of("核心 PCE", core)
        if was_policy is not None and was_core is not None:
            prev_real = was_policy - was_core
    sub = "尺上量的是扣掉核心 PCE 的實質利率"
    if stance.get("policy_source"):
        sub = "依聯準會聲明，FRED 尚未更新。" + sub
    real_lo, real_hi = min(-0.5, (real or 0) - 0.5), max(2.5, (real or 0) + 0.5)
    near = real is not None and abs(RESTRICTIVE_REAL_RATE - real) < NEAR_THRESHOLD
    if near:
        sub = (f"實質利率貼著 {RESTRICTIVE_REAL_RATE:.1f}% 的門檻，差距在資料誤差內，"
               "不判定落在哪一邊。") + sub
    sub += "。這是用過去一年的通膨算的回顧值，門檻是本站的分類，不是聯準會的定義"
    rows.append({
        "name": "政策利率上緣", "href": "/fed/", "value": pct(policy, 2),
        "read": f"實質 {pct(real, 2)}", "dir": "", "sub": sub,
        "change": changed.get("政策利率上緣"),
        "ruler": dict(lo=real_lo, hi=real_hi, now=real, prev=prev_real,
                      kind="threshold", step=0.25, flag=f"實質 {fmt(real, 2)}",
                      ticks=[(RESTRICTIVE_REAL_RATE, f"{RESTRICTIVE_REAL_RATE:.1f}")],
                      zones=[(real_lo - 1, RESTRICTIVE_REAL_RATE, "中性或偏寬鬆"),
                             (RESTRICTIVE_REAL_RATE, real_hi + 1, "限制性")],
                      undecided=near,
                      label=f"實質政策利率 {pct(real, 2)}；本站以 {RESTRICTIVE_REAL_RATE:.0f}% 為分類門檻"
                            + ("，現在貼著門檻不判定" if near else "")),
        "gap": ({"word": "只差" if near else "還差",
                 "value": fmt(abs(RESTRICTIVE_REAL_RATE - real), 2),
                 "what": "貼著門檻，不判定" if near else "離限制性門檻",
                 "unit": "個百分點"} if real is not None else None),
    })

    # 4. 10 年期公債：沒有寫死的門檻，只能畫區間
    ten = decomp.get("nominal")
    series = decomp.get("nominal_series")
    year = series.tail(252).values if series is not None and len(series) else []
    lo, hi = (min(year), max(year)) if year else (0.0, 1.0)
    rows.append({
        "name": "10 年期公債", "href": "/debt/", "value": pct(ten, 2),
        "read": f'實質 {pct(decomp.get("real"), 2)}', "dir": "",
        "sub": (f'近三月 {fmt(decomp.get("chg_3m"), 2, suffix=" pp", signed=True)}。'
                "沒有寫死的門檻，只標近一年區間"),
        # 市場價格每個交易日都在動，不標「跟上一期不一樣」。頁邊寫近一月累計了多少——
        # 2026 年 8 到 10 月它從 4.72% 升到 5.28%，是 37 次小變動堆出來的，
        # 每天標一次看不出這件事。
        "change": None,
        "trend": ({"value": _signed(decomp["chg_1m"], 2), "what": "近一月", "unit": "個百分點"}
                  if decomp.get("chg_1m") is not None else None),
        "ruler": dict(lo=lo - (hi - lo) * 0.04, hi=hi + (hi - lo) * 0.04, now=ten,
                      prev=None, kind="range", flag=fmt(ten, 2),
                      ticks=[(lo, f"{lo:.2f} 一年低點"), (hi, f"{hi:.2f} 一年高點")],
                      label=f"10 年期公債 {pct(ten, 2)}；近一年區間 {lo:.2f}% 到 {hi:.2f}%。"
                            f"這是區間，不是門檻"),
        "gap": None,
    })
    return rows


def _fact_note(item: dict, base: str | None, comparable: bool = True) -> str:
    """一列數字的頁邊。順序：跟上一期不同（上色）> 離門檻多遠 > 沒變。

    comparable＝上一期有沒有記這個讀數。沒有記就不能寫「未變」——那是沒比，不是沒變。
    """
    since = f"自 {base[5:].replace('-', '/')}" if base else "自上一期"
    change = item.get("change")
    if change:
        digits = change.get("digits", 2)
        return note(f'<i>{_signed(change["change"], digits)}</i>',
                    f'{fmt(change["was"], digits)} → {fmt(change["now"], digits)}　{esc(since)}',
                    kind="chg")
    gap = item.get("gap")
    if gap:
        return note(f'{esc(gap.get("word", "還差"))} <i>{gap["value"]}</i>',
                    f'{esc(gap["what"])}<span class="wide">，{esc(gap["unit"])}</span>')
    if item.get("missing"):
        return note("<i>—</i>", "沒有資料", kind="na")
    trend = item.get("trend")
    if trend:
        # 累計變動：不是「跟上一期不一樣」，所以不上色
        return note(f'<i>{trend["value"]}</i>',
                    f'{esc(trend["what"])}<span class="wide">，{esc(trend["unit"])}</span>')
    if not comparable:
        return note("<i>—</i>", "上期未記", kind="na")
    return note("未變", esc(since), kind="na")


def fact_section(rows: list[dict], base: str | None, *, anchor: str, title: str, sub: str,
                 nav: str = "", comparable: bool = True) -> str:
    """「四個數字」的排版，兩個版共用。"""
    out = [sec_open(anchor, title, kind="實", sub=sub, nav=nav)]
    for item in rows:
        value = item["value"]
        unit = "" if item.get("missing") else (item.get("unit") or ("%" if value.endswith("%") else ""))
        if unit and value.endswith(unit):
            value = value[:-len(unit)]
        if unit:
            value = f'{value}<span class="u">{esc(unit)}</span>'
        direction = f' dir {item["dir"]}' if item.get("dir") else ""
        read = f'<b class="rd{direction}">{esc(item["read"])}</b>' if item.get("read") else ""
        if item.get("missing"):
            # 沒有資料：不畫一把空的尺，直接講是哪個來源沒拿到
            reading = f'<div class="read"><p class="gapnote">{seal("缺")}{esc(item["sub"])}</p></div>'
        else:
            reading = (f'<div class="read">{ruler(**item["ruler"])}'
                       f'<p>{read}{esc(item["sub"])}</p></div>')
        body = (
            f'<h3><a href="{item["href"]}">{esc(item["name"])}</a></h3>'
            f'<p class="val">{value}</p>{reading}')
        out.append(row(body, _fact_note(item, base, comparable), cls="fact ln rv", tag="article"))
    out.append("</section>")
    return "".join(out)


def facts(ctx: dict, scenario: dict, reading_changes: list[dict], prior: dict | None) -> str:
    return fact_section(
        figure_rows(ctx, scenario, reading_changes), (prior or {}).get("date"),
        anchor="facts", title="四個數字",
        sub="機構發布的數字。尺上的門檻是本站寫死的，頁邊是離門檻還差多少。")


# ------------------------------------------------------------ 本站的判定 ----

def _grid_map(scenario: dict) -> str:
    """九宮格縮圖：現在落在哪一格。只畫位置，格名寫在旁邊那一句裡。"""
    from ...compute.scenario import INFLATION_LABELS
    cells, row_names, col_names = [], [], []
    for line in scenario.get("grid") or []:
        row_names.append(line.get("label", ""))
        col_names = [INFLATION_LABELS.get(c.get("inflation"), "") for c in line.get("cells") or []]
        for cell in line.get("cells") or []:
            on = " on" if cell.get("active") else ""
            cells.append(f'<i class="gc{on}" title="{esc(cell.get("name", ""))}"></i>')
    if len(cells) != 9:
        return ""
    return ('<div class="gridmap" role="img" '
            f'aria-label="九宮格：就業{esc(scenario["employment_label"])}、'
            f'通膨{esc(scenario["inflation_label"])}，落在「{esc(scenario["name"])}」">'
            '<span class="gx"><b>通膨</b>' + "".join(f"<span>{esc(n)}</span>" for n in col_names) + '</span>'
            '<span class="gy"><b>就業</b>' + "".join(f"<span>{esc(n)}</span>" for n in row_names) + '</span>'
            f'<div class="gcells">{"".join(cells)}</div></div>')


def calls(scenario: dict, summary: dict) -> str:
    """本站規則的兩個輸出。框起來、打斜線：框起來的才是本站的話。"""
    dovish, hawkish, neutral = summary["dovish"], summary["hawkish"], summary["neutral"]
    tally = ('<i class="dv"></i>' * dovish + '<i class="gp"></i>' + "<i></i>" * neutral
             + '<i class="gp"></i>' + '<i class="hk"></i>' * hawkish)
    return row(
        '<div class="calls">'
        '<div class="call">'
        f'<h3>規則訊號 <i>{summary["total"]}</i> 條</h3>'
        f'<p class="split"><span><i>{dovish}</i>條偏降息</span><span><i>{hawkish}</i>條偏升息</span></p>'
        f'<div class="tally" role="img" aria-label="{summary["total"]} 條規則訊號：{dovish} 條偏降息、'
        f'{neutral} 條不偏、{hawkish} 條偏升息">{tally}</div>'
        f'<p class="tkey"><span class="dir dv">利降息 {dovish}</span><span class="dir">中性 {neutral}</span>'
        f'<span class="dir hk">利升息 {hawkish}</span></p>'
        '</div>'
        '<div class="call call-regime">'
        '<div><h3>情境傾向</h3>'
        f'<p class="big">{esc(scenario["regime_label"])}</p>'
        f'<p class="call-s">就業{esc(scenario["employment_label"])} × 通膨{esc(scenario["inflation_label"])}，'
        f'九宮格落在「<a href="/scenario/">{esc(scenario["name"])}</a>」</p></div>'
        f'{_grid_map(scenario)}'
        '</div>'
        '</div>', cls="rv")


def _signal_row(signal: dict, new_keys: set, *, direction: bool = True) -> str:
    """一條規則訊號。direction=False 時不印升降息方向（台灣的規則沒有方向）。"""
    severity = signal.get("severity") or "low"
    leaning = signal.get("direction") or "neutral"
    dir_tag = (f'<span class="dir {DIR_CLASS.get(leaning, "")}">{DIR_TEXT.get(leaning, "中性")}</span>'
               if direction else "")
    body = (
        f'<p class="tags"><span class="sv {SEV_CLASS.get(severity, "sv-3")}">'
        f'{esc(SEV_TEXT.get(severity, ""))}</span>'
        f'<span class="meta"><span>{esc(signal.get("module", ""))}</span>{dir_tag}</span></p>'
        f'<div><h3><button type="button" class="sig-btn" data-rule="{attr_json(signal)}" '
        f'aria-haspopup="dialog">{esc(signal.get("headline", ""))}</button></h3>'
        f'<p class="det">{esc(signal.get("why", ""))}</p>'
        f'<p class="evi">{esc(signal.get("evidence", ""))}</p></div>')
    margin = note("新增", "上一期沒有這一條", kind="chg") if signal.get("key") in new_keys else ""
    return row(body, margin, cls="sig ln rv", tag="article")


def verdict(scenario: dict, signals: list[dict], summary: dict, diff: dict) -> str:
    """本站的判定：兩個輸出，加上最重的幾條規則訊號。"""
    from ..common import legend_note, signals_block
    new_keys = {s.get("key") for s in diff.get("added") or []}
    high = [s for s in signals if s.get("severity") == "high"]
    rest = [s for s in signals if s.get("severity") != "high"]
    out = [sec_open("verdict", "本站的判定", kind="判",
                    sub="固定規則的輸出，不是機構的數字。每一條都點得開規則。"),
           calls(scenario, summary)]
    if high:
        out.append(row(f'<h3 class="sub-h">最重的 {len(high)} 條規則訊號</h3>', cls="rv"))
        out.extend(_signal_row(signal, new_keys) for signal in high)
    tail = ""
    if rest:
        tail += accordion(f"其餘 {len(rest)} 條訊號", signals_block(rest, grid=True) + legend_note())
    tail += '<p class="more"><a href="/scenario/">這個判斷怎麼來的、對應什麼部位　→</a></p>'
    out.append(row(tail, cls="rv"))
    out.append("</section>")
    return "".join(out)


# ------------------------------------------------------------------ 今天 ----

def _event_row(event: dict) -> str:
    tag_text = event.get("tag") or ""
    head, _, state = tag_text.partition("　")
    severity = SEV_CLASS.get(event.get("sev") or "low", "sv-3")
    gap = " sv-gap" if event.get("policy") == "遺漏" else ""
    body = (
        f'<p class="kind"><b class="sv {severity}{gap}">{esc(head)}</b>'
        + (f'<span>{esc(state)}</span>' if state else "") + '</p>'
        f'<div><h3><a href="{esc(event.get("href") or "/freshness/")}">{esc(event["title"])}</a></h3>'
        + (f'<p class="det">{esc(event["detail"])}</p>' if event.get("detail") else "")
        + '</div>')
    return row(body, cls="nx ln rv", tag="article")


def _update_rows(ctx: dict) -> list[str]:
    """今天更新的序列：頁邊是較前值的變動——它們今天才到，所以上色。"""
    freshness = ctx.get("freshness") or {}
    today_state = freshness.get("today") or {}
    fresh = freshness.get("fresh") or {}
    bundle = ctx.get("_bundle")
    periodic = list(today_state.get("periodic") or [])
    have = {u["id"] for u in periodic}
    for series_id in fresh:
        series = bundle[series_id] if bundle is not None else None
        if series_id in have or not series:
            continue
        before = series.at(-2)
        periodic.append({"id": series_id, "name": series.label or series_id, "unit": series.unit,
                         "frequency": series.frequency, "date": series.last_date,
                         "value": series.last, "prev": before,
                         "change": (series.last - before) if before is not None else None})
    periodic.sort(key=lambda u: u["name"])
    rows = []
    for update in periodic:
        value = update["value"]
        digits = 0 if abs(value or 0) >= 1000 else 2
        unit = f'<span class="u">{esc(update["unit"])}</span>' if update.get("unit") else ""
        body = (
            f'<h3><a href="/explore/?id={esc(update["id"])}">{esc(update["name"])}</a>'
            f'{new_badge(fresh, update["id"])}</h3>'
            f'<p class="lv">{fmt(value, digits)}{unit}</p>'
            f'<p class="cap">資料期間 {zh_date(update["date"], freq=update["frequency"])}'
            + (f'　前值 {fmt(update["prev"], digits)}' if update.get("prev") is not None else "")
            + '</p>')
        change = update.get("change")
        if change is None:
            margin = note("<i>—</i>", "沒有前值", kind="na")
        elif abs(change) < 1e-12:
            margin = note("持平", "較前值", kind="na")
        else:
            margin = note(f'<i>{_signed(change, _delta_digits(change))}</i>', "較前值", kind="chg")
        rows.append(row(body, margin, cls="px upd ln rv", tag="article"))
    return rows


def today(ctx: dict, *, events: dict | None = None, anchor: str = "today", nav: str = "",
          updates: bool = True, gaps: list[str] | None = None, hint: str = "") -> str:
    """今天：重大數據與政策決議，全是機構正式發布的事實。

    會後一週內的央行決議列在「本週稍早」，決議遺漏永遠置頂（events.py 已排好序）。

    events   這一版要看的事件（events.for_region 的結果）；沒給就用全部
    updates  要不要列「今天更新的序列」（那份清單來自 FRED，只有美國版有）
    gaps     這一輪沒抓到的資料來源，逐條印「缺」
    hint     今天沒事時補一句「下一個是什麼」
    """
    ev = (ctx.get("events") or {}) if events is None else events
    day = ev.get("date") or clock.today()
    weekday = ev.get("weekday") or WEEKDAYS[day.weekday()]
    verdict_line = ev.get("verdict") or "今天的重大事件這一輪沒有計算成功，請看下方更新清單。"
    out = [sec_open(anchor, "今天", kind="實", nav=nav,
                    sub=f'{day.month}/{day.day}（{weekday}）台北時間。{esc(verdict_line)}')]
    listed = ev.get("events") or []
    now_rows = [e for e in listed if e["today"]]
    earlier = [e for e in listed if not e["today"]]
    out.extend(_event_row(e) for e in now_rows)
    if earlier:
        out.append(row('<h3 class="sub-h">本週稍早</h3>', cls="rv"))
        out.extend(_event_row(e) for e in earlier)
    warnings = []
    if ev and not ev.get("calendar_ok", True):
        warnings.append("台灣統計發布看板這一輪沒有取得，今天的台灣數據可能漏列。")
    if ev and not ev.get("us_calendar_ok", True):
        warnings.append("美國發布行事曆這一輪沒有取得（"
                        + "、".join(ev.get("us_calendar_failed") or []) + "），今天的美國數據可能漏列。")
    warnings.extend(f"{gap}。" for gap in gaps or [])
    if warnings:
        out.append(row("".join(f'<p class="gapnote">{seal("缺")}{esc(w)}</p>' for w in warnings)))
    if not updates:
        if not listed and hint:
            out.append(row(f'<p class="quiet">{esc(hint)}</p>'))
        out.append("</section>")
        return "".join(out)
    rows = _update_rows(ctx)
    out.append(row('<h3 class="sub-h">今天更新的序列</h3>', cls="rv"))
    if rows:
        out.extend(rows)
    else:
        nxt = next((r for r in ((ctx.get("freshness") or {}).get("rows") or [])
                    if r.get("days_away") is not None), None)
        hint = f'下一個：{esc(nxt["name"])}，{_when(nxt["days_away"])}。' if nxt else ""
        out.append(row(f'<p class="quiet">今天還沒有新公布的總經數據。{hint}</p>'))
    out.append("</section>")
    return "".join(out)


# ---------------------------------------------------------------- 接下來 ----

def _when(days: int | None) -> str:
    if days is None:
        return "日期未定"
    return {0: "今天", 1: "明天"}.get(days, f"{days} 天後")


def _next_opex() -> dict | None:
    """下一個月選擇權到期日（每月第三個星期五）。到期日是美東日期，拿美東的今天比。"""
    from datetime import date, timedelta
    us_today = clock.us_today()
    for offset in (0, 1):
        year = us_today.year + (us_today.month + offset - 1) // 12
        month = (us_today.month + offset - 1) % 12 + 1
        first = date(year, month, 1)
        third = first + timedelta(days=(4 - first.weekday()) % 7 + 14)
        if third >= us_today:
            return {"date": third, "days": (third - us_today).days}
    return None


def upcoming(ctx: dict, fomc: dict | None) -> list[dict]:
    """未來會來的事。回傳 [{days, kind, what}]，days 可能是 None（日期未定）。"""
    from ...sources import treasury
    items: list[dict] = []
    if fomc:
        items.append({"days": fomc["days"], "kind": "央行",
                      "what": f'FOMC 利率決策（{fomc["date"].month}/{fomc["date"].day}）'})
    for item in ((ctx.get("freshness") or {}).get("imminent") or [])[:6]:
        # 日頻序列（公債殖利率）每個交易日都「今天公布」，列進來等於每天多一列雜訊
        if item.get("frequency") == "d":
            continue
        items.append({"days": item.get("days_away"), "kind": "數據", "what": item["name"]})
    for auction in treasury.upcoming():
        items.append({"days": auction["days"], "kind": "標售",
                      "what": f'{auction["term"]}{auction["type"]}標售'})
    us = (ctx.get("equities") or {}).get("us") or {}
    for earning in (us.get("earnings") or [])[:3]:
        items.append({"days": None, "kind": "財報",
                      "what": f'{earning["symbol"]} 財報（{earning["date"][5:].replace("-", "/")}'
                              + (f'　{earning["hour"]}' if earning.get("hour") else "") + "）"})
    expiry = _next_opex()
    if expiry:
        items.append({"days": expiry["days"], "kind": "期權",
                      "what": f'月選擇權到期日（{expiry["date"].month}/{expiry["date"].day}）'})
    return items


def next_up(ctx: dict, scenario: dict, fomc: dict | None, *, horizon: int = 30) -> str:
    """接下來：離門檻多遠、離公布幾天。直線是今天，橫條拉得越長離得越遠。"""
    out = [sec_open("next", "接下來", kind="",
                    sub="直線是今天，線拉得越長離得越遠。"
                        "沒有市場共識預期——那是付費資料，本站不做推估。")]
    gates = 0
    for transition in scenario.get("transitions") or []:
        if transition.get("gap") is None:
            continue
        body = ('<p class="kind"><b>門檻</b></p>'
                f'<div><h3>{esc(transition["name"])}</h3>'
                f'<p class="det">{esc(transition.get("need", ""))}</p></div>')
        out.append(row(body, note(f'還差 <i>{fmt(abs(transition["gap"]), 2)}</i>',
                                  esc(transition.get("unit", ""))),
                       cls="nx ln rv", tag="article"))
        gates += 1
        if gates >= 2:
            break

    items = upcoming(ctx, fomc)
    dated: dict[int, list[dict]] = {}
    for item in items:
        if item["days"] is not None and 0 <= item["days"] <= horizon:
            dated.setdefault(item["days"], []).append(item)
    if dated:
        span = max(max(dated), 7)
        out.append(row('<span>今天</span><span>一格一天</span>', cls="axis rv",
                       attrs=f' style="--span:{span}"'))
        for days in sorted(dated):
            group = dated[days]
            kinds = "、".join(dict.fromkeys(item["kind"] for item in group))
            names = "、".join(item["what"] for item in group)
            margin = (note("今天") if days == 0 else note("明天") if days == 1
                      else note(f'<i>{days}</i> 天後'))
            out.append(row(
                '<div class="run"><span class="bar" aria-hidden="true"></span>'
                f'<div class="txt"><p class="kind"><b>{esc(kinds)}</b></p>'
                f'<h3>{esc(names)}</h3></div></div>',
                margin, cls="when rv", tag="article",
                attrs=f' style="--days:{days};--span:{span}"'))
    undated = [item for item in items if item["days"] is None]
    later = [item for item in items if item["days"] is not None and item["days"] > horizon]
    extra = [f'{esc(item["kind"])}　{esc(item["what"])}' for item in undated]
    extra += [f'{esc(item["kind"])}　{esc(item["what"])}（{item["days"]} 天後）' for item in later]
    if extra:
        out.append(row(f'<p class="quiet">另外：{"；".join(extra)}。</p>', cls="rv"))
    out.append("</section>")
    return "".join(out)


# -------------------------------------------------------------- 今日價格 ----

# 頭版列的兩檔美股指數，以及報價來源沒有今天的資料時改用的 FRED 每日收盤序列
US_INDEX_CLOSES = [("標普 500", "SP500"), ("那斯達克綜合", "NASDAQCOM")]


def price_rows(ctx: dict) -> list[dict]:
    """今日價格的資料列。chg＝(值, 小數位, 單位, 說明)；沒有變動資料就是 None，不補值。"""
    eq = ctx.get("equities") or {}
    market = ctx.get("market") or {}
    rates = ctx.get("rates") or {}
    comm = ctx.get("commodities") or {}
    us = eq.get("us") or {}
    vol = market.get("volatility") or {}
    curve = {r["name"]: r for r in (rates.get("curve") or {}).get("rows") or []}
    shape = rates.get("shape") or {}
    credit = {c["name"]: c for c in (rates.get("credit") or {}).get("rows") or []}

    rows: list[dict] = []
    live = {item["name"]: item for item in us.get("indices") or []}
    bundle = ctx.get("_bundle")
    for name, series_id in US_INDEX_CLOSES:
        item = live.get(name)
        if item:
            rows.append({"name": name, "href": "/equities/", "level": fmt(item["price"], 2),
                         "cap": f'昨收 {fmt(item["previous_close"], 2)}',
                         "chg": (item.get("change_percent"), 2, "%", "")})
            continue
        # 沒有今天的報價（equities.split_expired 已經把停更的存檔分出去了）：
        # 退回 FRED 的每日收盤，日期寫明。兩個收盤價都要有才算得出漲跌。
        series = bundle[series_id] if bundle is not None else None
        if not series or series.last is None:
            continue
        before = series.at(-2)
        change = (series.last / before - 1) * 100 if before else None
        when = series.last_date
        rows.append({"name": name, "href": "/market/", "level": fmt(series.last, 2),
                     "cap": f"{when.month}/{when.day} 收盤，取自 FRED",
                     "chg": (change, 2, "%", "") if change is not None else None})
    ten = curve.get("10Y")
    if ten:
        rows.append({"name": "10 年期公債", "href": "/fed/", "level": fmt(ten["value"], 2),
                     "unit": "%", "cap": "估值的分母", "plain": True,
                     "chg": (ten.get("chg_1m"), 2, " pp", "近一月")})
    if shape.get("slope_10_2") is not None:
        rows.append({"name": "10 年減 2 年", "href": "/fed/",
                     "level": fmt(shape["slope_10_2"], 2, signed=True), "unit": "pp",
                     "cap": "曲線形狀", "text": shape.get("label") or ""})
    high_yield = credit.get("高收益")
    if high_yield:
        rows.append({"name": "高收益利差", "href": "/fed/", "level": fmt(high_yield["value"], 2),
                     "unit": "%", "cap": f'十年第 {fmt(high_yield.get("pct10y"), 0)} 百分位', "chg": None})
    if vol.get("vix") is not None:
        rows.append({"name": "VIX", "href": "/market/", "level": fmt(vol["vix"], 1),
                     "cap": vol.get("verdict") or "", "chg": None})
    pool: list[dict] = []
    for group in comm.get("groups") or []:
        pool.extend(group.get("rows") or [])
    wti = next((r for r in pool if r.get("name") == "WTI 原油"), None)
    if wti and wti.get("value") is not None:
        rows.append({"name": "WTI 原油", "href": "/commodities/", "level": fmt(wti["value"], 2),
                     "cap": "供需與地緣", "chg": (wti.get("chg_1m"), 1, "%", "近一月")})
    return rows


def price_section(rows: list[dict], lines: list[tuple[str, str]], *, anchor: str, sub: str,
                  nav: str = "") -> str:
    """「今日價格」的排版，兩個版共用。lines 是底下那排補充（板塊、法人、融資）。"""
    out = [sec_open(anchor, "今日價格", kind="市", sub=sub, nav=nav)]
    for item in rows:
        unit = f'<span class="u">{esc(item["unit"])}</span>' if item.get("unit") else ""
        body = (f'<h3><a href="{item["href"]}">{esc(item["name"])}</a></h3>'
                f'<p class="lv">{item["level"]}{unit}</p>'
                f'<p class="cap">{esc(item.get("cap", ""))}</p>')
        if item.get("text"):
            margin = note(esc(item["text"]))
        elif item.get("chg") and item["chg"][0] is not None:
            value, digits, suffix, what = item["chg"]
            # 綠漲紅跌只給價格。殖利率上升是債券價格下跌、匯率數字變大是台幣貶值，
            # 上色會讓人讀反
            kind = "" if item.get("plain") else ("up" if value > 0 else ("dn" if value < 0 else "na"))
            margin = note(f'<i>{_signed(value, digits)}{esc(suffix)}</i>', esc(what), kind=kind)
        else:
            margin = note("<i>—</i>", kind="na") + '<span class="sr-only">沒有變動資料</span>'
        out.append(row(body, margin, cls="px ln rv", tag="article"))
    if lines:
        out.append(row('<dl class="also">' + "".join(f"<div><dt>{esc(k)}</dt><dd>{v}</dd></div>"
                                                     for k, v in lines) + "</dl>", cls="rv"))
    out.append("</section>")
    return "".join(out)


def prices(ctx: dict) -> str:
    from .overview_blocks import _rotation
    market = ctx.get("market") or {}
    us = (ctx.get("equities") or {}).get("us") or {}
    risk, liquidity = market.get("risk") or {}, market.get("liquidity") or {}
    lines = []
    rotation = _rotation(us.get("sectors") or [])
    if rotation.get("verdict"):
        lines.append(("板塊輪動", rotation["verdict"]))
    if risk.get("score") is not None:
        lines.append(("風險胃納", f'{risk["score"]:.0f}/100（{esc(risk.get("label", ""))}）'))
    if liquidity.get("latest") is not None:
        lines.append(("聯準會淨流動性",
                      f'{fmt(liquidity["latest"] / 1000, 2, suffix=" 兆美元")}，'
                      f'近三月 {fmt(liquidity.get("chg_3m"), 0, suffix=" 十億", signed=True)}'))
    return price_section(
        price_rows(ctx), lines, anchor="prices",
        sub="頁邊是漲跌。美股與利率為最近一個交易日收盤，各列寫明日期或昨收；"
            "沒有變動資料的畫「—」。")


# ---------------------------------------------------------- 別人怎麼說 ----

def said(brief_html: str, *, anchor: str = "voices", nav: str = "") -> str:
    """別人的報導。責任在報導者，所以這一段直線畫成虛線、頁邊不寫字。"""
    return (sec_open(anchor, "別人怎麼說", kind="聞", cls="said", nav=nav,
                     sub="別人的報導，說錯了責任在報導者。本站不會因為它們改變上面的判定"
                         "——所以這一段直線是虛線，頁邊不寫字。")
            + row(brief_html, cls="said-b rv") + "</section>")


# ------------------------------------------------------------------ 目錄 ----

def contents(ctx: dict) -> str:
    """全站目錄。近 7 天有新資料的頁面旁標出幾檔——這一頁這週沒動，今晚不用點。"""
    from ..layout import NAV
    module_of = {"/labor/": "勞動市場", "/inflation/": "通膨", "/fed/": "利率",
                 "/debt/": "債務", "/growth/": "成長", "/market/": "市場"}
    counts: dict[str, int] = {}
    for item in ((ctx or {}).get("freshness") or {}).get("rows") or []:
        age = item.get("updated_days")
        if age is not None and age <= 7:
            counts[item.get("module", "")] = counts.get(item.get("module", ""), 0) + 1
    groups: dict[str, list[str]] = {}
    number = 0
    for href, label, _icon, group in NAV:
        if not group:
            continue
        number += 1
        fresh = counts.get(module_of.get(href, ""), 0)
        badge = f'<em class="toc-new">近 7 天 {fresh} 檔更新</em>' if fresh else ""
        groups.setdefault(group, []).append(
            f'<li><a href="{href}"><i>{number:02d}</i><span>{esc(label)}</span>{badge}</a></li>')
    columns = "".join(f'<div><h3>{esc(name)}</h3><ul>{"".join(links)}</ul></div>'
                      for name, links in groups.items())
    return (sec_open("contents", "目錄", kind="")
            + row(f'<div class="toc">{columns}</div>', cls="rv", tag="nav",
                  attrs=' aria-label="全站目錄"')
            + "</section>")


# ------------------------------------------------------------------ 頁尾 ----

def colophon(updated: str) -> str:
    """怎麼讀這一頁，加上版權頁。圖例寫在這裡，不是藏在講義裡。"""
    from ..layout import colophon as shared
    legend = (
        '<dl class="howto">'
        '<div><dt>頁邊與正文</dt><dd><span><span class="hlx">+0.01</span>有螢光筆的＝判定、訊號或機構數據'
        '跟上一期不一樣。</span>'
        '<span>每天都在動的市場價格不標（它們在「今日價格」）；沒上色的頁邊是離門檻多遠、'
        '近一月累計、離公布幾天；空白就是沒變。</span></dd></div>'
        f'<div><dt>誰說的</dt><dd><span>{seal("實")}機構發布的數字</span><span>{seal("判")}本站固定規則的判定</span>'
        f'<span>{seal("市")}市場價格</span><span>{seal("聞")}別人的報導，責任在報導者</span>'
        f'<span>{seal("摘")}語言模型寫的摘要（每日排程），只轉述、不另下判斷</span></dd></div>'
        '<div><dt>嚴重度</dt><dd><span class="sv sv-1">嚴重</span><span class="sv sv-2">留意</span>'
        '<span class="sv sv-3">參考</span></dd></div>'
        '<div><dt>聯準會方向</dt><dd><span class="dir hk">利升息（紅）</span><span class="dir dv">利降息（藍）</span>'
        '<span>紅與藍只代表政策方向，不代表漲跌。</span></dd></div>'
        '<div><dt>價格</dt><dd><span><b class="cu">綠漲</b>、<b class="cd">紅跌</b>。</span>'
        '<span>數字不滾動：畫面上出現過的每個值都真的存在過。</span></dd></div>'
        f'<div><dt>缺口</dt><dd><span>沒有資料就畫「<span class="dash">—</span>」，不留白、不補值。</span>'
        f'<span>{seal("缺")}本站該拿到卻沒拿到的，會標出來。</span></dd></div>'
        '</dl>')
    return (
        '<footer class="foot">'
        + row('<h2>怎麼讀這一頁</h2>', cls="sh rv")
        + row(legend, cls="rv")
        + shared(updated)
        + '</footer>')
