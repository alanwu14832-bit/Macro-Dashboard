"""The page shell: <head>, nav, footer, theme toggle."""
from __future__ import annotations

import os

from .. import paths
from .html import esc

NAV = [
    ("/", "總覽"),
    ("/labor/", "勞動市場"),
    ("/inflation/", "通膨"),
    ("/fed/", "聯準會與利率"),
    ("/debt/", "長端與債務"),
    ("/growth/", "成長與信用"),
    ("/global/", "全球對照"),
    ("/commodities/", "大宗商品"),
    ("/equities/", "股市報價"),
    ("/market/", "市場面"),
    ("/scenario/", "情境與部位"),
    ("/freshness/", "資料新鮮度"),
    ("/archive/", "存檔"),
]

SITE_NAME = "總經儀表板"

# Theme toggle runs before paint so a dark-mode reader never sees a light flash.
THEME_BOOT = """
(function(){try{var t=localStorage.getItem('theme');
if(t==='dark'||t==='light')document.documentElement.setAttribute('data-theme',t);}catch(e){}})();
"""

THEME_TOGGLE = """
(function(){var b=document.getElementById('theme-toggle');if(!b)return;
var root=document.documentElement;
function label(){var t=root.getAttribute('data-theme');
b.textContent=t==='dark'?'淺色':t==='light'?'深色':'主題';}
label();
b.addEventListener('click',function(){
var cur=root.getAttribute('data-theme');
var mql=window.matchMedia('(prefers-color-scheme: dark)');
var next=cur?(cur==='dark'?'light':'dark'):(mql.matches?'light':'dark');
root.setAttribute('data-theme',next);
try{localStorage.setItem('theme',next);}catch(e){}
label();document.dispatchEvent(new Event('themechange'));});})();
"""


def asset_version() -> str:
    """Cache-buster from the static files' mtimes.

    The site is rebuilt daily and served from a CDN; without this a reader
    keeps yesterday's chart.js against today's markup.
    """
    stamp = 0.0
    for name in ("style.css", "chart.js"):
        candidate = os.path.join(paths.STATIC_DIR, name)
        if os.path.exists(candidate):
            stamp = max(stamp, os.path.getmtime(candidate))
    return str(int(stamp))


def page(*, title: str, path: str, body: str, lede: str = "",
         heading: str = "", updated: str = "", description: str = "",
         toc: list[tuple[str, str]] | None = None) -> str:
    version = asset_version()
    nav = "".join(
        f'<a href="{esc(href)}"{" aria-current=\"page\"" if href == path else ""}>{esc(name)}</a>'
        for href, name in NAV)

    toc_html = ""
    if toc:
        links = "".join(f'<a href="#{esc(a)}">{esc(t)}</a>' for a, t in toc)
        toc_html = f'<nav class="nav" style="margin:14px 0 0">{links}</nav>'

    head_block = ""
    if heading:
        head_block = (
            '<div class="page-head">'
            f'<h1>{esc(heading)}</h1>'
            + (f'<p class="lede">{esc(lede)}</p>' if lede else "")
            + toc_html + "</div>")

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
<script>{THEME_BOOT}</script>
</head>
<body>
<header class="topbar">
  <div class="topbar-inner">
    <div class="brand">{esc(SITE_NAME)}<small>{esc(updated)}</small></div>
    <nav class="nav">{nav}</nav>
    <button type="button" class="icon-btn" id="theme-toggle" aria-label="切換深淺色">主題</button>
  </div>
</header>
<main class="wrap">
{head_block}
{body}
</main>
<footer class="site">
  <div class="wrap">
    <p>資料來源：FRED（BLS、BEA、DOL、Treasury、Federal Reserve、EIA、IMF 原始資料）、OECD SDMX、ECB Data Portal、行政院主計總處、LBMA。</p>
    <p>所有量化判定由固定規則產生，同一份資料每次執行結果一致。指標定義與門檻見各頁「判讀說明」。</p>
    <p>本站為個人資料整理，不構成投資建議。{esc(updated)}</p>
  </div>
</footer>
<script src="/chart.js?v={version}" defer></script>
<script>{THEME_TOGGLE}</script>
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
