"""記帳——獨立的 PWA，跟總經儀表板是兩個不同的 App。

同一個 repo 部署（共用 Supabase 帳號與 /api/expense），但對使用者是
另一個 App，而且**介面骨架也不同**：儀表板是資訊密度優先的側欄佈局，
這裡是單手操作的行動 App——頂欄薄、內容分頁、底部分頁列、浮動記帳鈕，
記帳表單走底部彈出（打斷式任務做完就回到原本在看的地方）。

樣式在 static/expense-app.css（自己一套設計系統，不吃儀表板的
style.css）；動態邏輯在 static/expense.js；帳號介面沿用 account.js。

render_page(standalone=True) 是獨立網域版（manifest 與圖示用根路徑
通用檔名）；False 是掛在儀表板網域 /expense/ 底下的版本。
"""
from __future__ import annotations

import json
import os

from .. import layout


def _skeleton(rows: int = 3) -> str:
    """JS 接手前的骨架佔位——比空白或轉圈誠實。"""
    return ('<div class="skeleton" aria-hidden="true">'
            + '<span class="sk-bar"></span>' * rows
            + "</div>")


# 20×20 線性圖示，跟著文字走（分頁列的身份不靠顏色單獨表意）
TAB_ICONS = {
    "home": "M3 10.5 12 3l9 7.5M5.5 9.5V20h13V9.5",
    "list": "M4 6h16M4 12h16M4 18h10",
    "budget": "M3 8a2 2 0 0 1 2-2h13a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2zM16 6V4.9a1 1 0 0 0-1.25-.97L4.6 6.4M16.6 12.5h.01",
    "settings": "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6M19.4 15a1.6 1.6 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.6 1.6 0 0 0-1.8-.3 1.6 1.6 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1A1.6 1.6 0 0 0 9 19.4a1.6 1.6 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.6 1.6 0 0 0 .3-1.8 1.6 1.6 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1A1.6 1.6 0 0 0 4.6 9a1.6 1.6 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.6 1.6 0 0 0 1.8.3H9a1.6 1.6 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.6 1.6 0 0 0 1 1.5 1.6 1.6 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.6 1.6 0 0 0-.3 1.8V9a1.6 1.6 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.6 1.6 0 0 0-1.5 1z",
}

TABS = [("home", "總覽"), ("list", "明細"), ("budget", "預算"), ("settings", "設定")]


def _tab(key: str, label: str) -> str:
    selected = "true" if key == "home" else "false"
    return (f'<button type="button" class="tab" data-tab="{key}" role="tab"'
            f' aria-selected="{selected}">'
            f'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"'
            f' stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
            f'<path d="{TAB_ICONS[key]}"/></svg>'
            f"<span>{label}</span></button>")


def _tabbar() -> str:
    """四個分頁＋中央記帳鈕。

    記帳鈕本來是右下角的浮動按鈕，但它會壓在圓餅圖圖例的金額上——
    永遠遮住內容的按鈕是設計缺陷，不是風格。放進分頁列中央後不遮任何
    東西，而且落在單手拇指最順的位置。
    """
    left = "".join(_tab(key, label) for key, label in TABS[:2])
    right = "".join(_tab(key, label) for key, label in TABS[2:])
    add = ('<button type="button" class="tab-add" id="exp-fab" aria-label="記一筆">'
           '<span class="tab-add-btn" aria-hidden="true">'
           '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"'
           ' stroke-width="2.4" stroke-linecap="round" aria-hidden="true">'
           '<path d="M12 6v12M6 12h12"/></svg></span></button>')
    return f'<nav class="tabbar" role="tablist">{left}{add}{right}</nav>'


HOME_VIEW = f"""
<section class="view" id="view-home" data-view="home">
  <div class="hero">
    <div class="hero-label">本月支出</div>
    <div class="hero-amount" id="hero-amount">—</div>
    <div class="hero-delta" id="hero-delta" hidden></div>
    <div class="hero-foot">
      <div><div class="hero-stat-label">筆數</div>
           <div class="hero-stat-value" id="hero-count">—</div></div>
      <div><div class="hero-stat-label">日均</div>
           <div class="hero-stat-value" id="hero-daily">—</div></div>
      <div><div class="hero-stat-label">預算剩餘</div>
           <div class="hero-stat-value" id="hero-budget">—</div></div>
    </div>
  </div>
  <div id="exp-status" class="status-pill" role="status" aria-live="polite"></div>
  <div id="exp-charts">{_skeleton(4)}</div>
  <div class="card">
    <h2 class="card-title">最近紀錄</h2>
    <div id="exp-recent">{_skeleton(3)}</div>
  </div>
</section>
"""

LIST_VIEW = f"""
<section class="view" id="view-list" data-view="list" hidden>
  <h1 class="view-title">明細</h1>
  <div id="exp-month-nav" class="month-nav"></div>
  <div id="exp-list">{_skeleton(5)}</div>
</section>
"""

BUDGET_VIEW = f"""
<section class="view" id="view-budget" data-view="budget" hidden>
  <h1 class="view-title">預算</h1>
  <div class="card">
    <h2 class="card-title">本月進度</h2>
    <div id="exp-budget">{_skeleton(3)}</div>
  </div>
</section>
"""

SHORTCUT_STEPS = """
<ol class="steps">
  <li>捷徑 App → 底部「自動化」→ 右上「＋」新增。</li>
  <li>觸發條件找到<strong>「交易」</strong>→ 勾選 Apple Pay 卡片 →
      選<strong>「立即執行」</strong>。</li>
  <li>動作選<strong>「取得 URL 內容」</strong>，照上面金鑰區的設定填：
      URL、POST、JSON，金額與商家用「快速指令輸入」變數。</li>
  <li>完成。之後每筆 Apple Pay 付款自動入帳，商家會自動分類。</li>
</ol>
"""

QUICK_STEPS = """
<ol class="steps">
  <li>捷徑 App →「捷徑」分頁 → 新增，命名「快速記帳」。</li>
  <li>加兩個<strong>「要求輸入」</strong>：數字（金額）、文字（商家）。</li>
  <li>加<strong>「取得 URL 內容」</strong>，照上面「快速記帳」的 JSON 範例填。</li>
  <li>捷徑詳細資訊 →<strong>「加入主畫面」</strong>。付完款點一下就記好。</li>
</ol>
"""

SETTINGS_VIEW = f"""
<section class="view" id="view-settings" data-view="settings" hidden>
  <h1 class="view-title">設定</h1>

  <div class="card setting-group">
    <h2 class="card-title">帳號</h2>
    <div data-account-slot></div>
    <p class="note">登入後紀錄、預算與收據照片跨裝置同步；沒登入也能完整使用，
       資料存在這台裝置。</p>
  </div>

  <div class="card setting-group">
    <h2 class="card-title">自動記帳金鑰</h2>
    <div id="exp-token">{_skeleton(2)}</div>
  </div>

  <div class="card setting-group">
    <h3>Apple Pay 自動記帳</h3>
    <p>iOS 不讓 App 直接讀 Apple Pay 交易，官方唯一管道是捷徑的
       <strong>「交易」自動化</strong>：刷卡當下觸發，把金額與商家送到
       <code>/api/expense</code>。設定一次，之後全自動。</p>
    {SHORTCUT_STEPS}
  </div>

  <div class="card setting-group">
    <h3>LINE Pay 與現金</h3>
    <p>掃碼付款不經過 Apple Pay，iOS 攔不到。放一顆「快速記帳」在主畫面，
       付完點一下、輸入金額，2 秒入帳。</p>
    {QUICK_STEPS}
    <p class="note">小訣竅：LINE Pay 聯名卡加進 Apple Wallet 後改用 Apple Pay
       感應，回饋照拿，而且會被上面的自動記帳直接抓到。</p>
  </div>

  <div class="card setting-group">
    <h3>資料存在哪</h3>
    <p><strong>沒登入：</strong>只存在這台裝置的瀏覽器，不離開你的手機。
       清瀏覽器資料會清掉，記得先匯出 CSV。</p>
    <p><strong>登入後：</strong>同步到雲端資料庫，由 Row Level Security 隔離
       ——每個帳號只能讀寫自己的紀錄。</p>
    <p class="note">在 Safari 開這一頁 → 分享 → 加入主畫面，就是獨立的
       「記帳」App，離線也能開。</p>
  </div>
</section>
"""

SHEET = """
<div class="scrim" id="exp-scrim" hidden></div>
<div class="sheet" id="exp-sheet" role="dialog" aria-modal="true"
     aria-labelledby="exp-sheet-title" hidden>
  <div class="sheet-inner">
    <div class="sheet-grip" aria-hidden="true"></div>
    <div class="sheet-head">
      <span class="sheet-title" id="exp-sheet-title">記一筆</span>
      <button type="button" class="sheet-close" id="exp-sheet-close">關閉</button>
    </div>

    <div class="quick">
      <input id="exp-nl" type="text" autocomplete="off"
             placeholder="一句話記帳：昨天 全家 120 現金">
      <button type="button" id="exp-nl-go">解析</button>
    </div>
    <p id="exp-nl-hint" class="quick-hint">會拆出日期、商家、金額與付款方式，填進下面讓你確認。</p>

    <form id="exp-form" autocomplete="off">
      <div class="form-grid">
        <label class="field field-amount">
          <span>金額</span>
          <input name="amount" type="number" inputmode="decimal" step="0.01"
                 min="0" placeholder="0" required>
        </label>
        <label class="field field-wide">
          <span>商家或項目</span>
          <input name="merchant" type="text" maxlength="120" placeholder="例：全聯、午餐">
        </label>
        <label class="field">
          <span>日期</span>
          <input name="date" type="date">
        </label>
        <label class="field">
          <span>備註（可空）</span>
          <input name="note" type="text" maxlength="300">
        </label>
      </div>
      <div class="field">
        <span>分類</span>
        <div id="exp-chips" class="chips"></div>
        <input name="category" type="hidden" value="未分類">
      </div>
      <div class="field">
        <span>付款方式</span>
        <div id="exp-pay-chips" class="chips"></div>
        <input name="pay" type="hidden" value="現金">
      </div>
      <div class="field">
        <span>收據照片（可空）</span>
        <div class="photo-row">
          <label class="photo-pick">拍照或選圖
            <input name="photo" type="file" accept="image/*" hidden>
          </label>
          <div id="exp-photo-preview" class="photo-preview"></div>
        </div>
      </div>
      <div class="actions">
        <button type="submit" class="btn-primary" data-submit>記一筆</button>
        <button type="button" class="btn-ghost" data-cancel hidden>取消</button>
      </div>
    </form>
  </div>
</div>
"""


def render_page(*, standalone: bool = False) -> str:
    """完整 HTML 文件——App 外殼，不經過 layout.page()。"""
    version = layout.asset_version()
    manifest = "/manifest.webmanifest" if standalone else "/expense-manifest.webmanifest"
    touch_icon = "/apple-touch-icon.png" if standalone else "/expense-apple-touch-icon.png"
    favicon = "/icon-192.png" if standalone else "/expense-icon-192.png"

    sb = ""
    if layout.SUPABASE_URL and layout.SUPABASE_ANON_KEY:
        sb = ("<script>window.__SB=" +
              json.dumps({"url": layout.SUPABASE_URL,
                          "key": layout.SUPABASE_ANON_KEY}) +
              "</script>\n")

    # 主題在第一次繪製前套用，避免深色模式閃白
    boot = ("(function(){try{var t=localStorage.getItem('theme');"
            "if(t==='dark'||t==='light')document.documentElement"
            ".setAttribute('data-theme',t);}catch(e){}})();")

    return f"""<!doctype html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>記帳</title>
<meta name="description" content="手動記一筆，或讓 iOS 捷徑在 Apple Pay 刷卡當下自動入帳；登入後跨裝置同步。">
<meta name="color-scheme" content="light dark">
<meta name="theme-color" content="#f6f4f0" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#12110f" media="(prefers-color-scheme: dark)">
<link rel="manifest" href="{manifest}">
<link rel="apple-touch-icon" href="{touch_icon}">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="default">
<meta name="apple-mobile-web-app-title" content="記帳">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Noto+Serif+TC:wght@400;600&family=Noto+Serif:wght@400;600&display=swap">
<link rel="stylesheet" href="/expense-app.css?v={version}">
<link rel="icon" href="{favicon}">
<script>{boot}</script>
</head>
<body>
<div class="app-shell">
  <header class="topbar">
    <span class="brand"><span class="brand-mark" aria-hidden="true">$</span>記帳</span>
    <span class="topbar-spacer"></span>
    <button type="button" class="icon-btn" id="exp-theme" aria-label="切換深淺色"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="8.4" fill="none" stroke="currentColor" stroke-width="1.2"/><path d="M12 3.6a8.4 8.4 0 0 0 0 16.8z" fill="currentColor"/></svg></button>
  </header>

  <main class="views" id="exp-views">
{HOME_VIEW}
{LIST_VIEW}
{BUDGET_VIEW}
{SETTINGS_VIEW}
  </main>

{_tabbar()}
</div>
{SHEET}
{sb}<script src="/account.js?v={version}" defer></script>
<script src="/expense.js?v={version}" defer></script>
<script>if ("serviceWorker" in navigator) addEventListener("load", () => navigator.serviceWorker.register("/sw.js"));</script>
</body>
</html>
"""


# ------------------------------------------------- 獨立網域部署（standalone/）

STANDALONE_MANIFEST = """{
  "name": "記帳",
  "short_name": "記帳",
  "description": "手動記一筆，或讓 iOS 捷徑在 Apple Pay 刷卡當下自動入帳；登入後跨裝置同步。",
  "lang": "zh-Hant",
  "start_url": "/",
  "scope": "/",
  "display": "standalone",
  "background_color": "#f6f4f0",
  "theme_color": "#33584a",
  "icons": [
    { "src": "/icon-192.png", "sizes": "192x192", "type": "image/png" },
    { "src": "/icon-512.png", "sizes": "512x512", "type": "image/png" },
    { "src": "/icon-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable" }
  ]
}
"""

# 極簡 service worker：只求可安裝與離線開啟。network-first——記帳資料在
# localStorage/Supabase，殼過期沒有代價，舊殼才有。
STANDALONE_SW = """const CACHE = "expense-static-v3";
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => {
  event.waitUntil(caches.keys()
    .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});
self.addEventListener("fetch", (event) => {
  if (event.request.method !== "GET") return;
  const url = new URL(event.request.url);
  if (url.pathname.startsWith("/api/")) return;
  // 跨網域（Google Fonts）交給瀏覽器自己的 HTTP 快取：它們回的是 opaque
  // response，存進 Cache Storage 也讀不回來用，只會佔空間。離線時字型
  // 請求失敗會退回系統的宋體（iOS 是 Songti TC），版面不會壞。
  if (url.origin !== self.location.origin) return;
  event.respondWith(
    fetch(event.request)
      .then((response) => {
        const copy = response.clone();
        caches.open(CACHE).then((cache) => cache.put(event.request, copy));
        return response;
      })
      .catch(() => caches.match(event.request)));
});
"""


def write_standalone(root_dir: str) -> None:
    """把獨立網域用的完整部署目錄寫到 <root_dir>/standalone。

    給 expense-app repo（自己的網域）同步用；內容由建置產出，
    不手改。standalone/vercel.json 是手寫檔案，不在這裡產生。
    """
    import shutil

    from ... import paths

    site = os.path.join(root_dir, "standalone", "site")
    os.makedirs(site, exist_ok=True)

    with open(os.path.join(site, "index.html"), "w", encoding="utf-8") as fh:
        fh.write(render_page(standalone=True))
    with open(os.path.join(site, "manifest.webmanifest"), "w", encoding="utf-8") as fh:
        fh.write(STANDALONE_MANIFEST)
    with open(os.path.join(site, "sw.js"), "w", encoding="utf-8") as fh:
        fh.write(STANDALONE_SW)

    copies = {
        "expense-app.css": "expense-app.css",
        "account.js": "account.js",
        "expense.js": "expense.js",
        "expense-icon-192.png": "icon-192.png",
        "expense-icon-512.png": "icon-512.png",
        "expense-icon-maskable-512.png": "icon-maskable-512.png",
        "expense-apple-touch-icon.png": "apple-touch-icon.png",
    }
    for source, target in copies.items():
        shutil.copy2(os.path.join(paths.STATIC_DIR, source),
                     os.path.join(site, target))

    # API 也複製一份：Root Directory 設 standalone 的專案看不到上層的 api/
    api_dir = os.path.join(root_dir, "standalone", "api")
    os.makedirs(api_dir, exist_ok=True)
    shutil.copy2(os.path.join(paths.ROOT_DIR, "api", "expense.js"),
                 os.path.join(api_dir, "expense.js"))
