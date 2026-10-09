"""頭版（/）：決定順序與版面預算。排版在 front_blocks.py，頭條規則在 frontpage.py。"""
from __future__ import annotations

import re

from ...compute.news import _headline, _is_market, _same_story, _tokens
from ...fomc import next_meeting
from . import front_blocks as front
from ..html import esc


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
    synthesis = ""
    if brief.get("synthesis"):
        text = re.sub(r"^與本期判斷的交集[：:]\s*", "", brief["synthesis"])
        synthesis = f'<p class="bf-syn"><strong>與本期判斷的交集</strong>　{esc(text)}</p>'
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


def render(ctx: dict, signals: list[dict], summary: dict, scenario: dict,
           diff: dict, reading_changes: list[dict], updated: str,
           prior: dict | None = None) -> str:
    # 頭版是一份日報的頭版：左邊一條頁邊，正文講現況、頁邊講變化。
    # 排版全部在 front_blocks.py；這裡只決定順序。八個區塊，上限仍然寫死在 BUDGET。
    from ..layout import _trust_row
    top, changed = front.hero(ctx, scenario, summary, diff, reading_changes, prior)
    body = [
        f'<div class="fp{" has-changes" if changed else ""}">',
        # 刊頭（品牌，不算區塊）＋ 1 頭條：有事報事，沒事報判定
        f'<div class="top">{front.masthead(_trust_row(updated))}{top}</div>',
        front.gate_chart(ctx, scenario),                          # 頭條的圖，不另算區塊
        front.facts(ctx, scenario, reading_changes, prior),       # 2 四個數字（機構事實）
        front.verdict(scenario, signals, summary, diff),          # 3 本站的判定
        front.today(ctx),                                         # 4 今天
        front.next_up(ctx, scenario, next_meeting()),             # 5 接下來
        front.prices(ctx),                                        # 6 今日價格
        front.said(market_brief(ctx)),                            # 7 別人怎麼說
        front.contents(ctx),                                      # 8 目錄
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
VISIBLE_CHARS_SOFT = 2600  # 重構當下實測 2,537，留 2.5% 餘裕


def measure(body: str) -> dict:
    """量總覽的版面用量。輸入是渲染完的 body HTML。"""
    import re
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
    """回傳 (硬性超標, 軟性警告)。硬性超標要讓建置失敗。"""
    used = measure(body)
    hard = [f'{k} {used[k]} 超過上限 {v}——要加東西必須指名擠掉哪一個'
            for k, v in BUDGET.items() if used[k] > v]
    soft = ([f'可見字元 {used["visible_chars"]} 超過 {VISIBLE_CHARS_SOFT}']
            if used["visible_chars"] > VISIBLE_CHARS_SOFT else [])
    return hard, soft
