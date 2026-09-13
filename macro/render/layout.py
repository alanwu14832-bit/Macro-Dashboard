"""The page shell: sidebar, topbar, theme, and the <head>.

Layout is a two-column grid — a collapsible sidebar rail plus the content
column. The rail width lives in a CSS custom property so collapsing is one
transition on `grid-template-columns` rather than a reflow of every child.

Below 960px the rail leaves the grid and becomes an off-canvas drawer: a
13-item nav does not belong permanently on a phone screen.
"""
from __future__ import annotations

import html as html_module
import os
import re

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
    "twstock": "M4 20v-6M9 20V9M14 20v-8M19 20V5M4 9l5-4 5 3 5-4",
    "guide": "M4 19.5A2.5 2.5 0 0 1 6.5 17H20M4 19.5A2.5 2.5 0 0 0 6.5 22H20V2H6.5A2.5 2.5 0 0 0 4 4.5zM8 7h8M8 11h8",
    "market": "M4 20V10M10 20V4M16 20v-7M22 20V7",
    "scenario": "M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h7v7h-7z",
    "freshness": "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18M12 7v5l3 2",
    "archive": "M3 7h18v13H3zM3 3h18v4H3zM9 12h6",
    "explore": "M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16M21 21l-4.35-4.35M8 11h6M11 8v6",
    "search": "M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16M21 21l-4.35-4.35",
    "sources": "M12 3l8 4v6c0 4-3.4 7.2-8 8-4.6-.8-8-4-8-8V7zM9 12l2 2 4-4",
    "deepdive": "M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h4M14 3l5 5M14 3v5h5M8 9h3M8 13h4M16 14a3 3 0 1 0 0 6 3 3 0 0 0 0-6M21 21l-2.2-2.2",
}

# (href, label, icon, group). Grouping is what makes 15 items scannable.
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
    ("/equities/", "美股與國際", "equities", "全球與市場"),
    ("/tw/", "台股", "twstock", "全球與市場"),
    ("/market/", "市場面", "market", "全球與市場"),

    ("/deep-dive/", "深度專題", "deepdive", "判讀與紀錄"),
    ("/explore/", "自選比較", "explore", "判讀與紀錄"),
    ("/scenario/", "情境與部位", "scenario", "判讀與紀錄"),
    ("/freshness/", "資料新鮮度", "freshness", "判讀與紀錄"),
    ("/guide/", "使用講義", "guide", "判讀與紀錄"),
    ("/find/", "尋找", "search", "判讀與紀錄"),
    ("/sources/", "資料來源", "sources", "判讀與紀錄"),
    ("/archive/", "存檔", "archive", "判讀與紀錄"),
]

SITE_NAME = "總經儀表板"

# Supabase（帳號與自選清單同步）。anon key 是「設計上就公開」的前端金鑰，
# 資料隔離靠資料庫的 Row Level Security，不靠把 key 藏起來。
# 兩個值都留空時，登入介面整個不出現，自選清單維持純 localStorage。
SUPABASE_URL = "https://nwbfjoroqnhpymdtdbwu.supabase.co"
SUPABASE_ANON_KEY = "sb_publishable_qEglLVVzOkMr1-ZzwX-H0w_5OWnmcUx"

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


CARET = ('<span class="nav-caret" aria-hidden="true">'
         '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" '
         'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
         '<path d="M9 6l6 6-6 6"/></svg></span>')


def _sidebar(path: str, sections: dict[str, list[tuple[str, str]]] | None = None) -> str:
    """側欄。每個大標下列出該頁的區塊小標（<details> 展開，目前頁預設開）。

    小標清單由 build.py 從各頁渲染完的 HTML 抽出來（兩段式建置），
    所以永遠跟頁面實際有的區塊一致，不需要另外維護一份目錄。
    """
    sections = sections or {}
    items, seen = [], None
    for href, label, icon, group in NAV:
        if group != seen:
            seen = group
            if group:
                items.append(f'<div class="nav-group"><span>{esc(group)}</span></div>')
        current = ' aria-current="page"' if href == path else ""
        link = (
            f'<a class="nav-item" href="{esc(href)}"{current}>'
            f'{_icon(icon)}<span class="nav-label">{esc(label)}</span>'
            f'<span class="nav-tip">{esc(label)}</span></a>')
        subs = sections.get(href) or []
        if subs:
            sub_links = "".join(
                f'<a href="{esc(href)}#{esc(anchor)}"'
                + (' class="sub2"' if level == 2 else "")
                + f'>{esc(title)}</a>'
                for anchor, title, level in subs)
            open_attr = " open" if href == path else ""
            items.append(
                f'<details class="nav-details"{open_attr}>'
                f'<summary>{link}{CARET}</summary>'
                f'<div class="nav-sub">{sub_links}</div></details>')
        else:
            items.append(link)

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


# 四個分頁。這是行動版的主要導覽，桌機（≥768px）則維持 18 項側邊 rail，
# 兩者永不共存。刻意用真 <a> 與 aria-current="page" 而不是 role="tablist"：
# 這是文件導覽，不是頁內分頁；tablist 會讓螢幕閱讀器宣告成同一份文件裡的
# 分頁切換，而每一次點擊其實是整頁載入。
TABS = [
    ("/", "今日", "tab-today"),
    ("/scenario/", "判定", "tab-verdict"),
    ("/tw/", "台股", "tab-tw"),
    ("/find/", "尋找", "tab-find"),
]

TAB_ICONS = {
    "tab-today": "M4 5h13v14H4zM17 9h3v8a2 2 0 0 1-3 2M7 9h7M7 13h7M7 17h4",
    "tab-verdict": "M3 3h18v18H3zM9 3v18M15 3v18M3 9h18M3 15h18",
    "tab-tw": "M4 20v-6M9 20V9M14 20v-8M19 20V5M4 9l5-4 5 3 5-4",
    "tab-find": "M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16M21 21l-4.35-4.35",
}


def _tabbar(path: str) -> str:
    """行動版底部分頁列。

    歸屬規則：三個分頁各自擁有自己的路徑，其餘 18 個目的地一律歸「尋找」
    ——因為那正是瀏覽它們的入口。從「今日」點進去的頁面要維持「今日」
    高亮，靠 JS 讀 sessionStorage 修正，伺服器端只給這個靜態預設。
    """
    items = []
    owned = {href for href, _, _ in TABS}
    for href, label, icon in TABS:
        current = href == path or (href == "/find/" and path not in owned)
        items.append(
            f'<a class="tab" href="{esc(href)}" data-tab="{esc(href)}"'
            + (' aria-current="page"' if current else "")
            + f'><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" '
              f'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" '
              f'aria-hidden="true"><path d="{TAB_ICONS[icon]}"/></svg>'
              f'<span>{esc(label)}</span></a>')
    return (f'<nav class="tabbar" aria-label="主要分頁">{"".join(items)}</nav>')


def _trust_row(updated: str) -> str:
    """常駐信任列：這一頁每個數字的可信度都由它決定。

    桌機的 .topbar-meta 在手機上是 display:none，所以行動版現在根本看不到
    資料多新——那正是「我不知道這是不是最新的」這個痛點的一半。時間戳同時
    給機器可讀的 datetime（帶 +08:00），JS 用它算下一次建置與過期判定。
    """
    from .. import clock
    stamp = clock.now()
    iso = stamp.isoformat(timespec="minutes")
    shown = updated.replace("最後更新 ", "")
    label = f'最後更新 {stamp.strftime("%m 月 %d 日 %H 時 %M 分")} 台北時間，開啟資料狀態'
    return (f'<a class="trust" href="/freshness/" data-build="{esc(iso)}" '
            f'aria-label="{esc(label)}">'
            f'<span class="trust-dot" aria-hidden="true"></span>'
            f'<span>最後更新 <time datetime="{esc(iso)}">{esc(shown)}</time> 台北</span>'
            f'<span class="trust-next" data-trust-next></span>'
            f'<span class="trust-go" aria-hidden="true">›</span></a>')


def _supabase_config() -> str:
    """帳號功能的前端設定。沒填就輸出空字串，account.js 會自動休眠。"""
    if not (SUPABASE_URL and SUPABASE_ANON_KEY):
        return ""
    import json
    return ("<script>window.__SB=" +
            json.dumps({"url": SUPABASE_URL, "key": SUPABASE_ANON_KEY}) +
            "</script>\n")


def asset_version() -> str:
    """Cache-buster from the static files' mtimes.

    The site is rebuilt daily and served from a CDN; without this a reader
    keeps yesterday's chart.js against today's markup.
    """
    stamp = 0.0
    for name in ("style.css", "chart.js", "sidebar.js", "quotes.js",
                 "explore.js", "account.js", "expense.js"):
        candidate = os.path.join(paths.STATIC_DIR, name)
        if os.path.exists(candidate):
            stamp = max(stamp, os.path.getmtime(candidate))
    return str(int(stamp))


SECTION_RE = re.compile(
    r'<section id="([^"]+)"( class="sub-section")?>'
    r'<div class="section-head"><h2>([^<]+)</h2>')


def extract_sections(body: str) -> list[tuple[str, str, int]]:
    """從渲染完的頁面 HTML 抽出 (錨點, 標題, 層級) 清單，給側欄目錄用。

    層級 1 是小標、2 是小小標（section(sub=True) 的區塊）。
    """
    return [(anchor, html_module.unescape(title), 2 if sub else 1)
            for anchor, sub, title in SECTION_RE.findall(body)]


def page(*, title: str, path: str, body: str, lede: str = "",
         heading: str = "", updated: str = "", description: str = "",
         sections: dict[str, list[tuple[str, str]]] | None = None,
         nav_path: str = "") -> str:
    """nav_path：側欄要標成「目前頁」的那一項。

    深度專題的文章頁各有各的網址，但在側欄裡應該仍然是「深度專題」亮著，
    否則讀者一點進文章，側欄就整個失去位置感。
    """
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
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{esc(title)}｜{esc(SITE_NAME)}</title>
<meta name="description" content="{esc(description or lede)}">
<meta name="color-scheme" content="light dark">
<meta name="theme-color" content="#f9f9f7" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#0d0d0d" media="(prefers-color-scheme: dark)">
<link rel="manifest" href="/manifest.webmanifest">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="總經儀表板">
<link rel="stylesheet" href="/style.css?v={version}">
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'><text y='13' font-size='14'>📊</text></svg>">
<script>{BOOT}</script>
</head>
<body>
<a class="skip" href="#content">跳到主要內容</a>
<div class="app">
{_sidebar(nav_path or path, sections)}
  <div class="shell">
    <header class="topbar">
      <button type="button" class="icon-btn drawer-btn" id="rail-open"
              aria-label="開啟選單" aria-controls="rail" aria-expanded="false">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"
             stroke-linecap="round" aria-hidden="true"><path d="M4 7h16M4 12h16M4 17h16"/></svg>
      </button>
      <div class="topbar-title">{esc(title)}</div>
      <a class="topbar-guide" href="/guide/">使用講義</a>
      <div class="topbar-meta">{esc(updated)}</div>
      <button type="button" class="icon-btn" id="reload-btn" aria-label="重新載入">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"
             stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"
             style="width:17px;height:17px">
          <path d="M21 12a9 9 0 1 1-2.64-6.36M21 3v6h-6"/></svg>
      </button>
      <button type="button" class="icon-btn" id="push-toggle" hidden
              aria-label="每日財經推播" aria-pressed="false">通知</button>
      <button type="button" class="icon-btn" id="theme-toggle" aria-label="切換深淺色">主題</button>
    </header>
    <main class="content" id="content">
      <div class="wrap">
{_trust_row(updated)}
{head_block}
{body}
      </div>
      <footer class="site">
        <p class="foot-main">所有判定由固定規則產生，同一份資料每次執行結果一致。<a href="/sources/">資料來源與判斷方法</a></p>
        <p class="foot-fine">個人資料整理，不構成投資建議。{esc(updated)}</p>
      </footer>
    </main>
  </div>
{_tabbar(path)}
</div>
<dialog class="sheet" id="rule-sheet" aria-labelledby="rule-title">
  <div class="sheet-grab" aria-hidden="true"></div>
  <div class="sheet-head">
    <span class="sheet-eyebrow" id="rule-mod"></span>
    <button type="button" class="icon-btn" data-sheet-close aria-label="關閉">關閉</button>
  </div>
  <h2 class="sheet-title" id="rule-title"></h2>
  <div class="sheet-body" id="rule-body"></div>
  <p class="sheet-foot">判定由固定規則產生，門檻寫死在程式裡，不隨行情調整。
    同一份資料每次執行都會得到同一個結果。<a href="/scenario/">看全部規則與換檔門檻 →</a></p>
</dialog>
<button type="button" class="to-top" id="to-top" hidden aria-label="回到頁首">
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
       stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
    <path d="M12 19V5M5 12l7-7 7 7"/>
  </svg>
</button>
{_supabase_config()}<script src="/sidebar.js?v={version}" defer></script>
<script src="/chart.js?v={version}" defer></script>
<script src="/account.js?v={version}" defer></script>
<script src="/quotes.js?v={version}" defer></script>
<script src="/explore.js?v={version}" defer></script>
<script src="/notify.js?v={version}" defer></script>
<script>if ("serviceWorker" in navigator) addEventListener("load", () => navigator.serviceWorker.register("/sw.js"));</script>
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
