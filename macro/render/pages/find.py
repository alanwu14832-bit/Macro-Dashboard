"""尋找：打字前先瀏覽的目錄。

第四個分頁刻意不是「更多」。「更多」只是把 18 個無排序的同儕往深處搬一格，
而且從此變成每一個新功能的垃圾抽屜。這一頁的工作是：**在你還沒想好關鍵字
之前就讓你找得到東西**——所以先給最近看過的、再給按分組排好的全部目的地，
搜尋框只是同一份清單的過濾器。

它同時是「切分頁會掉導覽深度」這個誠實缺口的唯一復原路徑：靜態多頁站沒有
per-tab 的導覽堆疊，回不去的時候，「最近看過」就是那條路。
"""
from __future__ import annotations

from ..html import esc, section
from ..layout import ICONS, NAV


def _icon(name: str) -> str:
    path = ICONS.get(name, ICONS["overview"])
    return (f'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            f'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" '
            f'aria-hidden="true"><path d="{path}"/></svg>')


def _row(href: str, label: str, icon: str) -> str:
    return (f'<a class="find-row" href="{esc(href)}" data-find="{esc(label)}">'
            f'{_icon(icon)}<span>{esc(label)}</span>'
            f'<span class="find-go" aria-hidden="true">›</span></a>')


def render(ctx: dict | None = None) -> str:
    body = []

    body.append(section(
        "search", "尋找",
        '<input class="find-search" id="find-search" type="search"'
        ' placeholder="輸入頁面名稱過濾" autocomplete="off"'
        ' aria-label="過濾下方的目的地清單" aria-controls="find-results">'
        '<div id="find-results">'
        '<div class="find-empty" id="find-none" hidden>沒有符合的頁面。</div>'
        '</div>',
        note="目前過濾的是頁面名稱；全站區塊與序列的索引之後再加"))

    # 最近看過：由 JS 從 localStorage 填，沒有紀錄就整塊不出現
    body.append(
        '<section id="recent" class="sub-section" hidden data-recent>'
        '<div class="section-head"><h2>最近看過</h2></div>'
        '<div class="find-list" id="recent-list"></div></section>')

    groups: dict[str, list[str]] = {}
    order: list[str] = []
    for href, label, icon, group in NAV:
        if href == "/find/":
            continue
        key = group or "總覽"
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(_row(href, label, icon))

    blocks = []
    for key in order:
        blocks.append(f'<div class="find-group" data-find-group>'
                      f'<h3>{esc(key)}</h3>'
                      f'<div class="find-list">{"".join(groups[key])}</div></div>')

    body.append(section("all", "全部目的地", "".join(blocks),
                        note=f"共 {sum(len(v) for v in groups.values())} 個頁面"))

    return "".join(body)
