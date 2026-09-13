"""尋找：打字前先瀏覽的目錄。

第四個分頁刻意不是「更多」。「更多」只是把 18 個無排序的同儕往深處搬一格，
而且從此變成每一個新功能的垃圾抽屜。這一頁的工作是：**在你還沒想好關鍵字
之前就讓你找得到東西**——所以先給最近看過的、再給按分組排好的全部目的地，
搜尋框只是同一份清單的過濾器。

它同時是「切分頁會掉導覽深度」這個誠實缺口的唯一復原路徑：靜態多頁站沒有
per-tab 的導覽堆疊，回不去的時候，「最近看過」就是那條路。
"""
from __future__ import annotations

import json

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


KIND_LABELS = {
    "page": "頁面",
    "section": "區塊",
    "series": "序列",
    "term": "名詞",
    "deep": "深度專題",
}


def build_index(section_map: dict | None = None,
                reports: list[dict] | None = None) -> list[dict]:
    """全站索引。

    四份資料本來就存在，只是沒有人把它們放在同一個輸入框後面：頁面來自 NAV、
    區塊來自兩段式建置本來就抽好的錨點、序列來自 catalogue、名詞來自 glossary。
    索引在建置時算好、烘進頁面裡，所以離線一樣搜得到——搜尋不該是一個需要
    連線的功能。

    每一筆是 {t 標題, u 網址, k 類型, c 脈絡}，欄位名縮到一個字母是因為這份
    JSON 會原封不動進到 HTML 裡，190 檔序列乘上長欄位名不是免費的。
    """
    from ... import catalogue, glossary

    entries: list[dict] = []

    for href, label, _icon, group in NAV:
        if href == "/find/":
            continue
        entries.append({"t": label, "u": href, "k": "page", "c": group or "總覽"})

    page_titles = {href: label for href, label, _i, _g in NAV}
    for path, sections in (section_map or {}).items():
        for anchor, title, _level in sections:
            entries.append({"t": title, "u": f"{path}#{anchor}", "k": "section",
                            "c": page_titles.get(path, path)})

    group_names = {"labor": "勞動市場", "inflation": "通膨", "rates": "利率",
                   "debt": "債務", "growth": "成長", "market": "市場",
                   "world": "全球", "commodities": "大宗商品"}
    for group, specs in catalogue.ALL_GROUPS.items():
        for series_id, (name, _unit, _freq, _start) in specs.items():
            entries.append({"t": name, "u": f"/explore/?id={series_id}",
                            "k": "series", "c": f'{group_names.get(group, group)}　{series_id}'})

    for key, term in glossary.TERMS.items():
        entries.append({"t": term.get("term") or key, "u": f"/guide/#{key}",
                        "k": "term", "c": (term.get("what") or "")[:40]})

    for report in reports or []:
        entries.append({"t": str(report.get("title") or report.get("slug", "")),
                        "u": f'/deep-dive/{report.get("slug", "")}/',
                        # date 物件不能序列化——這份索引會原封不動進 HTML
                        "k": "deep", "c": str(report.get("date") or "深度專題")})

    return entries


def render(ctx: dict | None = None, section_map: dict | None = None,
           reports: list[dict] | None = None) -> str:
    body = []

    index = build_index(section_map, reports)
    counts = {}
    for entry in index:
        counts[entry["k"]] = counts.get(entry["k"], 0) + 1
    scope = "、".join(f'{KIND_LABELS[k]} {counts[k]}'
                     for k in ("page", "section", "series", "term", "deep")
                     if counts.get(k))

    body.append(section(
        "search", "尋找",
        '<input class="find-search" id="find-search" type="search"'
        ' placeholder="搜尋頁面、區塊、序列代號、名詞" autocomplete="off"'
        ' aria-label="搜尋全站" aria-controls="find-results">'
        '<div id="find-results" role="region" aria-live="polite" aria-atomic="false">'
        '<div class="find-empty" id="find-none" hidden>沒有符合的項目。</div>'
        '</div>'
        + '<script type="application/json" id="find-index">'
        + json.dumps(index, ensure_ascii=False, separators=(",", ":"))
        + '</script>',
        note=f"索引範圍：{scope}。索引烘在這一頁裡，離線一樣搜得到"))

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
