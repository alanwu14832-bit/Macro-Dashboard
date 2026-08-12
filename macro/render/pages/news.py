"""國際新聞頁。

版面刻意跟訊號頁共用 `.signal` 那組樣式：左邊一個數字、中間標題與來源、
右邊時間。對讀者來說「幾家報導」跟訊號的嚴重度是同一種東西——一個要先看
的權重——所以不另外發明一套視覺語言，也不需要新增 CSS。
"""
from __future__ import annotations

from datetime import datetime, timezone

from ..html import accordion, callout, card, esc, kv, section, stat


def _clock(moment: datetime | None) -> str:
    if moment is None:
        return "—"
    local = moment.astimezone()
    return f"{local.month}/{local.day} {local.hour:02d}:{local.minute:02d}"


def _row(*, badge: str, badge_class: str, headline: str, link: str,
         note: str, side: str, extra: str = "") -> str:
    title = esc(headline)
    if link:
        title = (f'<a href="{esc(link)}" target="_blank" rel="noopener noreferrer">'
                 f'{title}</a>')
    return (
        '<div class="signal">'
        f'<div class="sev {esc(badge_class)}">{esc(badge)}</div>'
        '<div>'
        f'<div class="headline">{title}</div>'
        f'<div class="why">{esc(note)}</div>'
        + (f'<div class="evidence">{esc(extra)}</div>' if extra else "")
        + '</div>'
        f'<div class="side"><div class="evidence">{esc(side)}</div></div>'
        '</div>'
    )


def _weight(count: int) -> str:
    """幾家報導對應到哪一級的視覺重量。"""
    if count >= 4:
        return "high"
    return "medium" if count == 3 else "low"


def _focus_block(clusters: list[dict]) -> str:
    if not clusters:
        return ('<p class="muted">這個時間窗內沒有兩家以上同時報導的事件。'
                '不是新聞變少了，是各家今天沒有交集。</p>')
    rows = []
    for group in clusters[:14]:
        others = group.get("others") or []
        rows.append(_row(
            badge=str(group["count"]), badge_class=_weight(group["count"]),
            headline=group["headline"], link=group.get("link", ""),
            note="　·　".join(group["sources"][:6])
                 + ("　…" if len(group["sources"]) > 6 else ""),
            side=_clock(group.get("latest")),
            extra=("另一種寫法：" + others[0]) if others else ""))
    return '<div class="signal-list">' + "".join(rows) + "</div>"


def _items_block(items: list[dict], *, limit: int, show_category: bool = False) -> str:
    if not items:
        return '<p class="muted">這個時間窗內沒有命中的條目。</p>'
    rows = []
    for item in items[:limit]:
        note = item["source"]
        if show_category:
            note = f'{item.get("category_label", "")}　·　{note}'
        rows.append(_row(badge="·", badge_class="low", headline=item["title"],
                         link=item.get("link", ""), note=note,
                         side=_clock(item.get("published"))))
    return '<div class="signal-list">' + "".join(rows) + "</div>"


def _method_block(stats: dict) -> str:
    tried = stats.get("feeds_tried", 0)
    failed = stats.get("feeds_failed", 0)
    body = kv([
        ("來源目錄", f'WorldMonitor（koala73/worldmonitor）的 '
                  f'{stats.get("catalogue_feeds", 0)} 個 feed，'
                  f'{stats.get("catalogue_categories", 0)} 個分類'),
        ("本次取用", f"{tried} 個英文來源，成功 {tried - failed} 個"),
        ("時間窗", f'{stats.get("window_hours", 0)} 小時內發布的條目'),
        ("聚合方式", "標題去除停用詞後比對實詞重疊，共用 3 個以上且重疊率達 "
                 "34% 視為同一件事；排序看幾家報導，不看誰先報"),
        ("排序意義", "「幾家報導」衡量的是各家編輯台當下同時認為重要的程度，"
                 "不是事件本身的重要性，更不是可信度"),
    ])
    if stats.get("failed_names"):
        body += (f'<p class="muted" style="font-size:.8rem">抓不到的來源：'
                 f'{esc("、".join(stats["failed_names"]))}。'
                 f'單一來源失敗不影響其他來源。</p>')
    return body


def render(ctx: dict) -> str:
    data = ctx.get("news") or {}

    if not data.get("available"):
        reason = data.get("error", "來源目錄讀取失敗")
        return section("news", "國際新聞", callout(
            f'<strong>這一頁這次沒有資料。</strong>'
            f'<p class="muted">無法讀取 WorldMonitor 的來源目錄：{esc(reason)}</p>'
            f'<p class="muted">目錄來自 GitHub 上的公開原始碼，'
            f'上游改版或網路中斷都會讓這一頁空著，其他頁不受影響。</p>'))

    stats = data.get("stats", {})
    clusters = data.get("clusters", [])
    top = clusters[0]["count"] if clusters else 0

    stat_row = (
        '<div class="grid grid-4">'
        + stat("焦點事件", f'{len(clusters)}<span class="unit"> 件</span>',
               asof="至少 2 家同時報導")
        + stat("最多幾家同報", f'{top}<span class="unit"> 家</span>',
               asof="今日最高交集")
        + stat("條目", f'{stats.get("items", 0)}<span class="unit"> 則</span>',
               asof=f'{stats.get("window_hours", 0)} 小時內，已去重')
        + stat("來源", f'{stats.get("feeds_tried", 0) - stats.get("feeds_failed", 0)}'
                     f'<span class="unit"> 個</span>',
               asof=f'共嘗試 {stats.get("feeds_tried", 0)} 個')
        + '</div>')

    category_blocks = "".join(
        accordion(f'{group["label"]}（{len(group["items"])} 則）',
                  _items_block(group["items"], limit=8))
        for group in data.get("categories", []))

    return (
        section("focus", "今日焦點",
                stat_row + _focus_block(clusters),
                note="多家獨立媒體在同一個時間窗內報導同一件事，依交集家數排序。")
        + section("macro", "與總經相關",
                  _items_block(data.get("macro", []), limit=16, show_category=True),
                  note="標題命中聯準會、通膨、關稅、公債、就業、油價等本站在追的主題。")
        + section("categories", "依分類",
                  category_blocks or '<p class="muted">沒有分類資料。</p>',
                  note="分類沿用 WorldMonitor 的目錄結構，每類取最新 8 則。")
        + section("method", "方法與來源", card("", _method_block(stats)),
                  note="這一頁怎麼來的，以及它不能拿來做什麼。")
    )
