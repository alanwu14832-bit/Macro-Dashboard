"""頭版（/）：決定順序與版面預算。排版在 front_blocks.py，頭條規則在 frontpage.py。"""
from __future__ import annotations

import re

from ... import archive
from ...compute import events as events_mod
from ...compute import signals as signals_mod
from ...compute.news import _headline, _is_market, _same_story, _tokens
from ...fomc import next_meeting
from . import front_blocks as front
from . import front_tw
from ..html import esc

TAIWAN = "台灣"       # 訊號的 module、事件的 region、要聞的分類，三個地方都叫這個名字


def _curated_brief(brief: dict, region: str = "") -> str:
    """整理過的要聞：四類，預設只出標題。

    region：「美國」只出台灣以外的三類，「台灣」只出台灣那一類；空字串＝全部。
    「與本期判斷的交集」講的是九宮格的判定，只跟著美國版。

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
        if region and (sec["title"] == TAIWAN) != (region == TAIWAN):
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
    synthesis = ""
    if brief.get("synthesis") and region != TAIWAN:
        text = re.sub(r"^與本期判斷的交集[：:]\s*", "", brief["synthesis"])
        synthesis = f'<p class="bf-syn"><strong>與本期判斷的交集</strong>　{esc(text)}</p>'
    stamp = brief["date"].isoformat()
    if not groups:
        return (f'<p class="quiet">{esc(stamp)} 整理的要聞裡沒有{esc(region)}的項目。'
                '<a href="/news/">看國際新聞頁 →</a></p>')
    return ("".join(groups) + synthesis
            + f'<p class="mc-foot-note">整理於 {esc(stamp)}，由排程任務讀完 64 個來源後寫成；'
              f'<a href="/news/">看原始的今日焦點與分類 →</a></p>')


_UNSET = object()


def market_brief(ctx: dict, *, limit: int = 6, region: str = "", curated=_UNSET) -> str:
    """今日資本市場要聞。

    有整理過的 data/brief.json 就用它（中文 headline、四類）；沒有或過期時
    退回關鍵字挑出的原始標題，並在頁面上明講這是未整理的版本。

    curated：已經讀好的 brief（頭版一次建置要用它四次，只讀一次檔）；沒給就自己讀。
    """
    from ... import brief as brief_module
    if curated is _UNSET:
        curated = brief_module.load()
    if curated:
        return _curated_brief(curated, region)
    if region == TAIWAN:
        # 退路的關鍵字清單挑的是國際財經報導，硬分一份給台灣版只會是同一批標題
        return ('<p class="quiet">今天沒有整理過的台灣要聞（整理版由排程任務每天寫入）。'
                '<a href="/news/">看國際新聞頁 →</a></p>')

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


def _only(diff: dict, keep) -> dict:
    """訊號的增減只留某一邊的。"""
    added = [s for s in diff.get("added") or [] if keep(s)]
    removed = [s for s in diff.get("removed") or [] if keep(s)]
    retired = [s for s in diff.get("retired") or [] if keep(s)]
    return {**diff, "added": added, "removed": removed, "retired": retired,
            "same": not added and not removed and not retired}


def edition(key: str, html: str) -> str:
    """一個版的一段。兩個版都在同一份 HTML 裡，<html data-ed> 決定顯示哪一個；
    前後的註解是給 measure() 量各版的版面預算用的。"""
    return f'<!--ed:{key}--><div class="edn" data-ed="{key}">{html}</div><!--/ed:{key}-->'


def render(ctx: dict, signals: list[dict], summary: dict, scenario: dict,
           diff: dict, reading_changes: list[dict], updated: str,
           prior: dict | None = None) -> str:
    # 頭版是一份日報的頭版：左邊一條頁邊，正文講現況、頁邊講變化。
    # 排版在 front_blocks.py（美國版與共用零件）與 front_tw.py（台灣版）；這裡只決定順序。
    #
    # 兩個版：美國｜台灣，同一個網址，刊頭底下切換。兩版的段落一一對應，
    # 各自受同一份版面預算（BUDGET）約束——每一版都是八個區塊。
    from ... import brief as brief_module
    from ..layout import _trust_row
    is_tw = lambda s: s.get("module") == TAIWAN
    ev = ctx.get("events") or {}
    # 要聞與今日導讀都來自同一個檔（排程任務寫的 data/brief.json）
    curated = brief_module.load()

    # ---- 美國版：九宮格只吃美國的就業與通膨，所以訊號條數也只算美國的 ----
    us_signals = [s for s in signals if not is_tw(s)]
    us_summary = signals_mod.summarise(us_signals) if us_signals else {**summary, "total": 0, "neutral": 0}
    us_diff = _only(diff, lambda s: not is_tw(s))
    us_events = events_mod.for_region(ev, "美國")
    us_top, us_changed = front.hero(ctx, scenario, us_summary, us_diff, reading_changes, prior,
                                    events=us_events, story=brief_module.story(curated, "us"))
    us_rest = "".join([
        front.gate_chart(ctx, scenario),                          # 頭條的圖，不另算區塊
        front.facts(ctx, scenario, reading_changes, prior),       # 2 四個數字（機構事實）
        front.verdict(scenario, us_signals, us_summary, us_diff), # 3 本站的判定
        front.today(ctx, events=us_events),                       # 4 今天
        front.next_up(ctx, scenario, next_meeting()),             # 5 接下來
        front.prices(ctx),                                        # 6 今日價格
        front.said(market_brief(ctx, region="美國", curated=curated)),   # 7 別人怎麼說
    ])

    # ---- 台灣版：同樣的七段，沒有九宮格 ----
    tw_signals = [s for s in signals if is_tw(s)]
    tw_diff = _only(diff, is_tw)
    tw_events = events_mod.for_region(ev, TAIWAN)
    tw_changes = archive.taiwan_changes(archive.taiwan_readings(ctx), prior)
    tw_top, tw_changed = front_tw.hero(ctx, tw_signals, tw_diff, tw_changes, prior, tw_events,
                                       story=brief_module.story(curated, "tw"))
    tw_rest = "".join([
        front_tw.signal_chart(ctx),
        front_tw.facts(ctx, tw_changes, prior),
        front_tw.verdict(tw_signals, tw_diff),
        front_tw.today(ctx, tw_events),
        front_tw.next_up(ctx, tw_events),
        front_tw.prices(ctx),
        front.said(market_brief(ctx, region=TAIWAN, curated=curated),
                   anchor="tw-voices", nav="台灣｜別人怎麼說"),
    ])

    # 頁邊的色帶跟著「這一版有沒有變動」：兩版各有各的旗標
    flags = (" us-chg" if us_changed else "") + (" tw-chg" if tw_changed else "")
    body = [
        f'<div class="fp{flags}">',
        # 刊頭與版別（品牌與導覽，不算區塊）＋ 1 頭條：有事報事，沒事報判定
        f'<div class="top">{front.masthead(_trust_row(updated))}{front.edition_row()}'
        f'{edition("us", us_top)}{edition("tw", tw_top)}</div>',
        edition("us", us_rest),
        edition("tw", tw_rest),
        front.contents(ctx),                                      # 8 目錄（兩版共用）
        front.colophon(updated),
        "</div>",
    ]
    return "".join(body)


# --------------------------------------------------------------- 版面預算 --

# 總覽在四個月內被抱怨過兩次「東西太多」。前一次的修法是把表收進摺疊——
# 那是把「決定不了」變成「先收起來」，所以復發了。這一次改成預算加驅逐律：
# 要加第 9 個區塊，必須指名擠掉現有八個裡的哪一個。
# （2026-10 改版「邊際」：原本的「目前情境」拆成「頭條」與「規則訊號」兩塊，
# 被擠掉的是「雙目標」——它的四個數字搬進了頭條底下的讀數表。上限仍然是 8。）
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
# 2026-10-10 使用者要在頭條底下加一篇「今日導讀」，篇幅選的是兩段約 250 字（已告知
# 這會讓頭版字數接近上限）。這是具名的額度，不是把上限悄悄調高：導讀自己的硬上限
# 在 brief.STORY_HARD，超過就不上版；加上標題列與那行說明約 60 字。
STORY_ALLOWANCE = 420
VISIBLE_CHARS_SOFT = 2600 + STORY_ALLOWANCE  # 2600 是沒有導讀時的額度（重構當下實測 2,537）


EDITION_RE = re.compile(r"<!--ed:(\w+)-->(.*?)<!--/ed:\1-->", re.S)
EDITION_NAMES = {"us": "美國版", "tw": "台灣版"}


def editions(body: str) -> dict[str, str]:
    """把頭版拆回一版一份：該版自己的段落＋兩版共用的部分（刊頭、目錄、頁尾）。
    沒有版別標記的 HTML（測試、舊版面）原樣當成一份。"""
    chunks: dict[str, list[str]] = {}
    for key, html in EDITION_RE.findall(body):
        chunks.setdefault(key, []).append(html)
    if not chunks:
        return {"": body}
    shared = EDITION_RE.sub("", body)
    return {key: "".join(parts) + shared for key, parts in chunks.items()}


def measure(body: str) -> dict:
    """量一份頭版的版面用量。輸入是渲染完的 body HTML（單一版；整頁請先過 editions）。"""
    visible = re.sub(r'<div class="acc-body">.*?</div></details>', "</details>",
                     body, flags=re.S)
    visible = re.sub(r'<div class="bf-body">.*?</div></details>', "</details>",
                     visible, flags=re.S)
    # 頁尾的「怎麼讀這一頁」與版權頁是版面設施，不是當天的內容；改版前的頁尾由
    # layout 加在 body 之外，本來就不在計數裡。
    visible = re.sub(r'<footer class="foot">.*?</footer>', "", visible, flags=re.S)
    text = re.sub(r"\s+", "", re.sub(r"<[^>]+>", "", visible))
    return {
        "sections": body.count("<section id="),
        "tables": body.count("<table"),
        "accordions": max(0, body.count("<details") - NEWS_DISCLOSURES),
        "cells": (body.count('class="stat') + body.count('class="key"')
                  + body.count('class="lg-row"') + body.count('class="row fact ')
                  + body.count('class="row px ln') + body.count('class="call')),
        "visible_chars": len(text),
    }


def budget_report(body: str) -> tuple[list[str], list[str]]:
    """回傳 (硬性超標, 軟性警告)。硬性超標要讓建置失敗。

    兩個版各量各的：讀者一次只看一版，預算管的是「一版有多長」，不是 HTML 有多大。
    """
    hard, soft = [], []
    for key, html in editions(body).items():
        used = measure(html)
        name = EDITION_NAMES.get(key, key)
        hard += [f'{name}{k} {used[k]} 超過上限 {v}——要加東西必須指名擠掉哪一個'
                 for k, v in BUDGET.items() if used[k] > v]
        if used["visible_chars"] > VISIBLE_CHARS_SOFT:
            soft.append(f'{name}可見字元 {used["visible_chars"]} 超過 {VISIBLE_CHARS_SOFT}')
    return hard, soft
