"""深度專題：每日一篇的資本市場研究，索引頁與各篇文章頁。

內容不是這個網站算出來的——報告由另一個排程任務每天寫成 Markdown，這裡
只負責呈現。所以這兩頁刻意不加任何解讀或摘要改寫：原文怎麼寫就怎麼上，
索引頁的摘要直接取「結論先行」的第一段。網站其他頁的規則是「同一份資料
每次執行結果一致」，這一頁的版本是「同一個檔案每次渲染結果一致」。
"""
from __future__ import annotations

import re

from ... import deepdive
from .. import markdown
from ..html import esc, section, table

LEADING_NUMBER = re.compile(r"^[一二三四五六七八九十]+、\s*")
META_LINE = re.compile(r"^\*\*.*\*\*$")

CAT_ORDER = ["A", "B", "C", "D", "E"]


def _cat_chip(report: dict) -> str:
    # 類別是分類，不是方向——全站的顏色留給多空與嚴重度，這裡只用字母。
    code = report.get("category") or ""
    if not code:
        return '<span class="dd-cat dd-cat-none">未標類別</span>'
    label = report.get("category_label") or ""
    return f'<span class="dd-cat"><b>{esc(code)}</b>{esc(label)}</span>'



def _flags(report: dict) -> str:
    flags = []
    if report.get("backfill"):
        flags.append('<span class="dd-flag">補做</span>')
    if report.get("failed"):
        flags.append('<span class="dd-flag dd-flag-bad">執行失敗</span>')
    return "".join(flags)


def _item(report: dict) -> str:
    targets = report.get("targets") or ""
    return (
        f'<a class="dd-item" href="{esc(report["path"])}">'
        f'<div class="dd-when"><span class="dd-date">'
        f'{report["date"].strftime("%m-%d")}</span>{_cat_chip(report)}</div>'
        f'<div class="dd-main">'
        f'<div class="dd-title">{esc(report["title"])}{_flags(report)}</div>'
        + (f'<p class="dd-sum">{esc(report["summary"])}</p>'
           if report.get("summary") else "")
        + (f'<p class="dd-targets">標的　{esc(targets)}</p>' if targets else "")
        + '</div></a>')


def _hero(report: dict) -> str:
    targets = report.get("targets") or ""
    return (
        '<div class="card dd-hero">'
        f'<div class="dd-when">{_cat_chip(report)}'
        f'<span class="dd-date">{report["date"].isoformat()}</span>{_flags(report)}</div>'
        f'<h3 class="dd-hero-title">'
        f'<a href="{esc(report["path"])}">{esc(report["title"])}</a></h3>'
        + (f'<p class="dd-hero-sum">{esc(report["summary"])}</p>'
           if report.get("summary") else "")
        + (f'<p class="dd-targets">標的　{esc(targets)}</p>' if targets else "")
        + f'<p class="dd-more"><a href="{esc(report["path"])}">讀全文 →</a>'
          f'<span class="dd-len">約 {report["chars"]:,} 字</span></p>'
        '</div>')


def render_index(reports: list[dict]) -> str:
    if not reports:
        return ('<div class="card"><p class="muted">目前沒有報告。'
                '深度專題由排程任務每天台北 06:00 產出，'
                '建置時從 deep-dive/reports/ 同步進來；'
                '同步不到就會看到這段文字。</p></div>')

    body = []
    latest = reports[0]

    counts = {code: sum(1 for r in reports if r.get("category") == code)
              for code in CAT_ORDER}
    spread = "　".join(f"{code} {counts[code]}" for code in CAT_ORDER if counts[code])
    span = f'{reports[-1]["date"].isoformat()} 起'

    body.append(section(
        "latest", "最新一篇",
        f'<div class="dd-stats">'
        f'<div class="stat"><div class="label">累計</div>'
        f'<div class="value">{len(reports)} <span class="unit">篇</span></div>'
        f'<div class="asof">{esc(span)}</div></div>'
        f'<div class="stat"><div class="label">最新</div>'
        f'<div class="value">{latest["date"].strftime("%m-%d")}</div>'
        f'<div class="asof">{esc(latest.get("category_label") or "—")}</div></div>'
        f'<div class="stat"><div class="label">類別分布</div>'
        f'<div class="value dd-spread">{esc(spread or "—")}</div>'
        f'<div class="asof">A 產業　B 傳導　C 個股　D 跨市場　E 回顧</div></div>'
        f'</div>{_hero(latest)}',
        note="每天台北 06:00 一篇，選題依星期輪值"))

    # ---- 全部報告：按月分組 ----
    groups: list[tuple[str, list[str]]] = []
    for report in reports:
        label = f'{report["date"].year} 年 {report["date"].month} 月'
        if not groups or groups[-1][0] != label:
            groups.append((label, []))
        groups[-1][1].append(_item(report))
    listing = "".join(
        f'<div class="dd-month">{esc(label)}<span>{len(items)} 篇</span></div>'
        f'<div class="dd-list">{"".join(items)}</div>'
        for label, items in groups)
    body.append(section("all", "全部報告", listing,
                        note=f"共 {len(reports)} 篇，新的在上面"))

    # ---- 方法 ----
    rows = [[esc(code), esc(deepdive.CATEGORY_FULL[code].split("：", 1)[1]),
             f'{counts[code]} 篇'] for code in CAT_ORDER]
    method = (
        table(["類別", "寫的是什麼", "累計"], rows)
        + '<p class="note">輪值：週一 B、週二 A、週三 C、週四 A、週五 D、'
          '週六 C、週日 E。同一標的 21 天內不重複當主角。</p>'
        '<p class="note">來源分級：[S1] 工具直接回傳、[S2] 官方一手'
        '（證交所 OpenAPI、SEC、公司財報原檔、TrendForce）、[S3] 媒體與'
        '二手轉述。規格規定支柱論點不得由 [S3] 支撐，正文上限 3,500 字，'
        '每篇都要附反方觀點與證偽條件。</p>'
        '<p class="note">這些報告是個人研究紀錄，不構成投資建議；'
        '數字的期別以各篇標註為準，不會隨本站其他頁面每小時更新。</p>')
    body.append(section("method", "這些報告怎麼來的", method))

    return "".join(body)


def _intro(text: str) -> str:
    """抬頭區：拿掉 H1 與已經顯示在頁首的粗體抬頭行，留下說明性的引用。"""
    kept = []
    for raw in text.split("\n"):
        line = raw.strip()
        if line.startswith("# ") or META_LINE.match(line) or line in ("---", "***"):
            continue
        kept.append(raw)
    return markdown.to_html("\n".join(kept).strip())


def render_article(report: dict, *, newer: dict | None = None,
                   older: dict | None = None) -> str:
    body = []

    targets = report.get("targets") or ""
    meta = (
        '<div class="dd-meta">'
        f'{_cat_chip(report)}'
        f'<span class="dd-date">{report["date"].isoformat()}</span>'
        f'{_flags(report)}'
        f'<span class="dd-len">約 {report["chars"]:,} 字</span>'
        '</div>'
        + (f'<p class="dd-targets">標的　{esc(targets)}</p>' if targets else ""))

    blocks = markdown.split_h2(report["markdown"])
    intro = ""
    for heading, chunk in blocks:
        if not heading:
            intro = _intro(chunk)
            break
    body.append(f'<div class="dd-article-head">{meta}{intro}</div>')

    index = 0
    for heading, chunk in blocks:
        if not heading:
            continue
        index += 1
        title = LEADING_NUMBER.sub("", heading)     # 區塊編號由版型自己數
        body.append(section(f"sec-{index}", title,
                            f'<div class="dd-prose">{markdown.to_html(chunk)}</div>'))

    nav = []
    if newer:
        nav.append(f'<a class="dd-nav-prev" href="{esc(newer["path"])}">'
                   f'← 新一篇　{esc(newer["title"])}</a>')
    if older:
        nav.append(f'<a class="dd-nav-next" href="{esc(older["path"])}">'
                   f'舊一篇　{esc(older["title"])} →</a>')
    body.append(
        '<section id="nav" class="dd-foot">'
        '<div class="section-head"><h2>其他報告</h2></div>'
        f'<div class="dd-nav">{"".join(nav)}</div>'
        '<p class="note"><a href="/deep-dive/">回深度專題列表</a>　·　'
        '報告為個人研究紀錄，不構成投資建議；數字期別以文中標註為準。</p>'
        '</section>')

    return "".join(body)
