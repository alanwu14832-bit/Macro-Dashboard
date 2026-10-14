"""每日晨報：/morning/（最新一期加往期清單）與每期自己的網址 /morning/YYYY-MM-DD/。

晨報是語言模型寫的（tools/morning_brief.py），所以頁面跟頭版的今日導讀一樣蓋「摘」的印、
寫明什麼時候寫的、用什麼寫的、檢查了什麼。這裡不改寫任何一個字——檔案怎麼存就怎麼登；
不合格的期數在讀檔時（macro/morning.load_all）就被擋掉了，不會走到這裡。

今天這一期沒有出刊時，/morning/ 照登最近一期，但開頭先講明「這是哪一天的、今天的還沒有」，
不放佔位的字，也不把舊的一期裝成今天的。
"""
from __future__ import annotations

from datetime import date

from ... import clock, morning
from ..html import esc, section


def _short(day: date) -> str:
    return f"{day.month}/{day.day} {morning.weekday(day)}"


def _seal() -> str:
    return '<span class="seal s-sum" aria-hidden="true">摘</span>'


def _paragraphs(items: list[str]) -> str:
    return "".join(f"<p>{esc(p)}</p>" for p in items)


def _sources(sources: list[dict]) -> str:
    links = "".join(
        f'<li><a href="{esc(s["url"])}" rel="noopener">{esc(s.get("outlet") or "來源")}'
        + (f'<span>〈{esc(s["title"])}〉</span>' if s.get("title") else "")
        + "</a></li>"
        for s in sources)
    return f'<ul class="mb-src" aria-label="來源">{links}</ul>'


def _meta(issue: dict) -> str:
    written = morning.written_at(issue)
    stamp = written.astimezone(clock.TAIPEI) if written else None
    when = (f'<span>台北 <time datetime="{esc(stamp.isoformat(timespec="minutes"))}">'
            f'{stamp:%H:%M}</time> 寫成</span>' if stamp else "")
    return (f'<p class="mb-meta">{_seal()}'
            f'<time class="mb-date" datetime="{esc(issue["date"])}">'
            f'{esc(issue["date"])} {morning.weekday(issue["day"])}</time>'
            f'{when}<span>約 {morning.body_length(issue):,} 字</span></p>')


def stale_notice(latest: dict, today: date, reason: str = "") -> str:
    """最近一期不是今天的：先講清楚這是哪一天的，再講今天的為什麼沒有。"""
    if latest["day"] == today:
        return ""
    why = f"（{esc(reason[:90])}{'…' if len(reason) > 90 else ''}）" if reason else ""
    return (f'<p class="mb-stale"><strong>這是 {_short(latest["day"])} 的晨報。'
            f'今天（{_short(today)}）的還沒有出刊{why}。</strong>'
            f'下面的市場與行程都停在 {_short(latest["day"])}。</p>')


def article(issue: dict, *, notice: str = "") -> str:
    """一期的全文：抬頭、導言、要聞、四個固定欄目、這篇怎麼來的。"""
    out = [f'<div class="mb-head">{_meta(issue)}{notice}'
           f'<h2 class="mb-title">{esc(issue["title"])}</h2>'
           f'<p class="mb-lede">{esc(issue["lede"])}</p></div>']

    stories = "".join(
        f'<article class="mb-story"><h3>{esc(story["headline"])}</h3>'
        f'{_paragraphs(story["paragraphs"])}{_sources(story["sources"])}</article>'
        for story in issue["stories"])
    out.append(section("stories", "今日要聞", f'<div class="dd-prose mb-prose">{stories}</div>',
                       note="新聞的出處列在每一則底下；說法歸報導者。"))

    notes = {
        "us": "數字取自本站的建置資料，跟各頁同一份。",
        "watch": "公布前的預期只寫模型預估與期貨定價，並寫明來源；它們都不是市場共識。",
        "verdict": "只轉述本站固定規則算出的結果，不另下判斷。",
    }
    for key, default in morning.SECTIONS:
        block = issue["sections"][key]
        out.append(section(key, block.get("heading") or default,
                           f'<div class="dd-prose mb-prose">{_paragraphs(block["paragraphs"])}</div>',
                           note=notes.get(key, "")))

    checks = issue.get("checks") or {}
    usage = issue.get("usage") or {}
    facts = []
    if checks.get("numbers") is not None:
        facts.append(f"市場與判定四欄的 {checks['numbers']} 個數字，程式逐一比對過寫稿時的資料")
    if checks.get("sources") is not None:
        facts.append(f"{checks['sources']} 個新聞來源都是這次網頁搜尋實際回傳的網址")
    if usage.get("attempts", 1) > 1:
        facts.append(f"第一稿沒過檢查，改了 {usage['attempts'] - 1} 次才出刊")
    model = issue.get("model") or "語言模型"
    out.append(section(
        "method", "這篇怎麼來的",
        f'<p class="note">{_seal()}由 {esc(model)} 讀完本站當天的建置資料、再用網頁搜尋找新聞後寫成，'
        '只轉述、不另下判斷。' + "；".join(esc(f) for f in facts) + ("。" if facts else "")
        + '程式檢查不了內容寫得對不對，只檢查數字、來源、長度與用語；'
          '以各頁的數字為準。個人資料整理，不構成投資建議。</p>'))
    return "".join(out)


def _past(issues: list[dict], *, current: dict | None = None) -> str:
    groups: list[tuple[str, list[str]]] = []
    for issue in issues:
        label = f'{issue["day"].year} 年 {issue["day"].month} 月'
        if not groups or groups[-1][0] != label:
            groups.append((label, []))
        here = ' aria-current="page"' if current is not None and issue is current else ""
        groups[-1][1].append(
            f'<a class="dd-item" href="{esc(issue["path"])}"{here}>'
            f'<div class="dd-when"><span class="dd-date">{_short(issue["day"])}</span></div>'
            f'<div class="dd-main"><div class="dd-title">{esc(issue["title"])}</div>'
            f'<p class="dd-sum">{esc(issue["lede"])}</p></div></a>')
    return "".join(f'<div class="dd-month">{esc(label)}<span>{len(items)} 期</span></div>'
                   f'<div class="dd-list">{"".join(items)}</div>' for label, items in groups)


def render_index(issues: list[dict], *, today: date | None = None, reason: str = "") -> str:
    """/morning/：最新一期全文，底下是往期。推播點開就是這一頁。"""
    today = today or clock.today()
    if not issues:
        # 第一期出刊之前。不是佔位：講明這一頁什麼時候會有東西。
        return section("past", "往期",
                       '<p class="note">還沒有任何一期。晨報每天台北 7 點前後出刊，'
                       '第一期寫成之後會出現在這裡。</p>')
    latest = issues[0]
    body = article(latest, notice=stale_notice(latest, today, reason))
    body += section("past", "往期", _past(issues, current=latest),
                    note=f"共 {len(issues)} 期，新的在上面")
    return body


def render_issue(issue: dict, *, newer: dict | None = None, older: dict | None = None) -> str:
    nav = []
    if newer:
        nav.append(f'<a class="dd-nav-prev" href="{esc(newer["path"])}">'
                   f'← 新一期　{_short(newer["day"])}　{esc(newer["title"])}</a>')
    if older:
        nav.append(f'<a class="dd-nav-next" href="{esc(older["path"])}">'
                   f'舊一期　{_short(older["day"])}　{esc(older["title"])} →</a>')
    return (article(issue)
            + '<section id="nav" class="dd-foot">'
              '<div class="section-head"><h2>其他期</h2></div>'
              f'<div class="dd-nav">{"".join(nav)}</div>'
              '<p class="note"><a href="/morning/">回最新一期與往期清單</a></p></section>')


def front_row(issues: list[dict], today: date | None = None) -> str:
    """頭版刊頭底下的一行入口。最近一期超過一天就不出現——舊的晨報不該掛在頭版。"""
    today = today or clock.today()
    if not issues or (today - issues[0]["day"]).days > 1:
        return ""
    latest = issues[0]
    when = "今天" if latest["day"] == today else _short(latest["day"])
    return (f'<div class="row mbrow"><div class="b"><a href="/morning/">'
            f'{_seal()}<b>晨報</b><span class="mbrow-d">{esc(when)}</span>'
            f'<span class="mbrow-t">{esc(latest["title"])}</span></a></div></div>')


def failure_reason(today: date | None = None) -> str:
    """今天沒出刊的原因（寫稿腳本留下的紀錄）。給 /morning/ 的開頭用。"""
    record = morning.failure(today or clock.today())
    if not record:
        return ""
    reason = str(record.get("reason") or "")
    # 檢查沒過的細節（哪個數字對不上）是給修的人看的，讀者只需要知道是被檢查擋下的
    if reason.startswith("檢查沒過"):
        return "寫好的稿沒過自動檢查，所以沒有登"
    if "花費上限" in reason or "MONTHLY_BUDGET" in reason or "每月" in reason:
        return "這個月的 API 額度用完了"
    return "寫稿沒有成功"
