"""The page shell: sidebar, topbar, theme, and the <head>.

Layout is a two-column grid — a collapsible sidebar rail plus the content
column. The rail width lives in a CSS custom property so collapsing is one
transition on `grid-template-columns` rather than a reflow of every child.

Below 960px the rail leaves the grid and becomes an off-canvas drawer: a
13-item nav does not belong permanently on a phone screen.
"""
from __future__ import annotations

import os

from .. import paths
from .html import esc

# 20×20 stroke icons, inline so the shell stays dependency-free.
ICONS = {
    "overview": "M3 3h7v7H3zM14 3h7v4h-7zM14 11h7v10h-7zM3 14h7v7H3z",
    "labor": "M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8M22 21v-2a4 4 0 0 0-3-3.87",
    "inflation": "M3 17l6-6 4 4 8-8M21 7h-6M21 7v6",
    "fed": "M3 21h18M5 21V10M9 21V10M15 21V10M19 21V10M2 10h20L12 3z",
    "debt": "M12 2v20M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6",
    "growth": "M3 3v18h18M7 15l4-4 3 3 5-6",
    "global": "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18M3 12h18M12 3a15 15 0 0 1 0 18 15 15 0 0 1 0-18",
    "news": "M4 5h13v14H4zM17 9h3v8a2 2 0 0 1-3 2M7 9h7M7 13h7M7 17h4",
    "commodities": "M12 2l9 5v10l-9 5-9-5V7zM12 12l9-5M12 12v10M12 12L3 7",
    "equities": "M3 3v18h18M7 14l3-3 3 3 5-5M18 9h3v3",
    "market": "M4 20V10M10 20V4M16 20v-7M22 20V7",
    "scenario": "M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h7v7h-7z",
    "freshness": "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18M12 7v5l3 2",
    "archive": "M3 7h18v13H3zM3 3h18v4H3zM9 12h6",
}

# (href, label, icon, group). Grouping is what makes 14 items scannable.
NAV = [
    ("/", "總覽", "overview", None),

    ("/labor/", "勞動市場", "labor", "美國總經"),
    ("/inflation/", "通膨", "inflation", "美國總經"),
    ("/fed/", "聯準會與利率", "fed", "美國總經"),
    ("/debt/", "長端與債務", "debt", "美國總經"),
    ("/growth/", "成長與信用", "growth", "美國總經"),

    ("/news/", "國際新聞", "news", "全球與市場"),
    ("/global/", "全球對照", "global", "全球與市場"),
    ("/commodities/", "大宗商品", "commodities", "全球與市場"),
    ("/equities/", "股市報價", "equities", "全球與市場"),
    ("/market/", "市場面", "market", "全球與市場"),

    ("/scenario/", "情境與部位", "scenario", "判讀與紀錄"),
    ("/freshness/", "資料新鮮度", "freshness", "判讀與紀錄"),
    ("/archive/", "存檔", "archive", "判讀與紀錄"),
]

SITE_NAME = "總經儀表板"

# Theme and rail state are applied before first paint so neither flashes.
BOOT = """
(function(){var d=document.documentElement;try{
var t=localStorage.getItem('theme');if(t==='dark'||t==='light')d.setAttribute('data-theme',t);
if(localStorage.getItem('rail')==='collapsed')d.classList.add('rail-collapsed');
}catch(e){}})();
"""


def _icon(name: str) -> str:
    path = ICONS.get(name, ICONS["overview"])
    return (f'<svg class="nav-icon" viewBox="0 0 24 24" fill="none" '
            f'stroke="currentColor" stroke-width="1.7" stroke-linecap="round" '
            f'stroke-linejoin="round" aria-hidden="true"><path d="{path}"/></svg>')


def _sidebar(path: str) -> str:
    items, seen = [], None
    for href, label, icon, group in NAV:
        if group != seen:
            seen = group
            if group:
                items.append(f'<div class="nav-group"><span>{esc(group)}</span></div>')
        current = ' aria-current="page"' if href == path else ""
        items.append(
            f'<a class="nav-item" href="{esc(href)}"{current}>'
            f'{_icon(icon)}<span class="nav-label">{esc(label)}</span>'
            f'<span class="nav-tip">{esc(label)}</span></a>')

    return f"""
  <aside class="rail" id="rail">
    <div class="rail-head">
      <a class="rail-brand" href="/">
        <span class="rail-mark" aria-hidden="true"></span>
        <span class="nav-label">{esc(SITE_NAME)}</span>
      </a>
      <button type="button" class="rail-toggle" id="rail-toggle"
              aria-expanded="true" aria-controls="rail" aria-label="收合側邊選單">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"
             stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <path d="M15 6l-6 6 6 6"/>
        </svg>
      </button>
    </div>
    <nav class="nav" aria-label="主選單">{"".join(items)}</nav>
  </aside>
  <div class="rail-scrim" id="rail-scrim" hidden></div>"""


def asset_version() -> str:
    """Cache-buster from the static files' mtimes.

    The site is rebuilt daily and served from a CDN; without this a reader
    keeps yesterday's chart.js against today's markup.
    """
    stamp = 0.0
    for name in ("style.css", "chart.js", "sidebar.js", "quotes.js"):
        candidate = os.path.join(paths.STATIC_DIR, name)
        if os.path.exists(candidate):
            stamp = max(stamp, os.path.getmtime(candidate))
    return str(int(stamp))


def page(*, title: str, path: str, body: str, lede: str = "",
         heading: str = "", updated: str = "", description: str = "",
         toc: list[tuple[str, str]] | None = None) -> str:
    version = asset_version()

    head_block = ""
    if heading:
        head_block = (
            '<header class="page-head">'
            f'<h1>{esc(heading)}</h1>'
            + (f'<p class="lede">{esc(lede)}</p>' if lede else "")
            + "</header>")

    return f"""<!doctype html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}｜{esc(SITE_NAME)}</title>
<meta name="description" content="{esc(description or lede)}">
<meta name="color-scheme" content="light dark">
<link rel="stylesheet" href="/style.css?v={version}">
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'><text y='13' font-size='14'>📊</text></svg>">
<script>{BOOT}</script>
</head>
<body>
<a class="skip" href="#content">跳到主要內容</a>
<div class="app">
{_sidebar(path)}
  <div class="shell">
    <header class="topbar">
      <button type="button" class="icon-btn drawer-btn" id="rail-open"
              aria-label="開啟選單" aria-controls="rail" aria-expanded="false">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"
             stroke-linecap="round" aria-hidden="true"><path d="M4 7h16M4 12h16M4 17h16"/></svg>
      </button>
      <div class="topbar-title">{esc(title)}</div>
      <div class="topbar-meta">{esc(updated)}</div>
      <button type="button" class="icon-btn" id="theme-toggle" aria-label="切換深淺色">主題</button>
    </header>
    <main class="content" id="content">
      <div class="wrap">
{head_block}
{body}
      </div>
      <footer class="site">
        <p>資料來源：FRED（BLS、BEA、DOL、Treasury、Federal Reserve、EIA、IMF 原始資料）、OECD SDMX、ECB Data Portal、行政院主計總處、LBMA、證交所、Finnhub。新聞來源目錄取自 <a href="https://github.com/koala73/worldmonitor" target="_blank" rel="noopener noreferrer">WorldMonitor</a>（AGPL-3.0），新聞內容版權屬各原始媒體。</p>
        <p>所有量化判定由固定規則產生，同一份資料每次執行結果一致。指標定義與門檻見各區塊底部的名詞說明。</p>
        <p>本站為個人資料整理，不構成投資建議。{esc(updated)}</p>
      </footer>
    </main>
  </div>
</div>
<script src="/sidebar.js?v={version}" defer></script>
<script src="/chart.js?v={version}" defer></script>
<script src="/quotes.js?v={version}" defer></script>
</body>
</html>
"""


def write_page(relative_path: str, content: str) -> str:
    """Write `content` to site/<relative_path>/index.html."""
    directory = os.path.join(paths.SITE_DIR, relative_path.strip("/"))
    os.makedirs(directory, exist_ok=True)
    target = os.path.join(directory, "index.html")
    with open(target, "w", encoding="utf-8") as fh:
        fh.write(content)
    return target


def copy_static() -> None:
    import shutil
    for name in os.listdir(paths.STATIC_DIR):
        shutil.copy2(os.path.join(paths.STATIC_DIR, name),
                     os.path.join(paths.SITE_DIR, name))
