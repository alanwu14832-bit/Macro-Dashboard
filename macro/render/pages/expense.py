"""記帳——獨立的 PWA，跟總經儀表板是兩個不同的 App。

同一個 repo、同一個網域部署（共用 style.css、account.js、/api/expense 與
Supabase 帳號），但對使用者是另一個 App：
  - 自己的 manifest（/expense-manifest.webmanifest，scope 限在 /expense/）、
    自己的名字與圖示——加入主畫面後是獨立的「記帳」App，
    與「總經儀表板」互不相干
  - 自己的外殼：沒有儀表板的側欄、導覽與頁尾，只有一條 App bar
  - 不走 layout.page()——render_page() 直接產出完整 HTML 文件，
    build.py 用 layout.write_page() 落地

動態邏輯都在 static/expense.js；帳號介面沿用 account.js（掛在
data-account-slot）。骨架佔位（.exp-skeleton）讓 JS 載入前不是一片空白。
"""
from __future__ import annotations

import json
import os

from .. import layout


def _skeleton(rows: int = 3) -> str:
    """JS 尚未接手前的骨架佔位——比空白或轉圈誠實，樣式在 style.css。"""
    return ('<div class="exp-skeleton" aria-hidden="true">'
            + '<span class="exp-sk-bar"></span>' * rows
            + "</div>")


def _section(anchor: str, title: str, body: str, *, note: str = "") -> str:
    note_html = f'<p class="note">{note}</p>' if note else ""
    return (f'<section id="{anchor}">'
            f'<div class="section-head"><h2>{title}</h2>{note_html}</div>'
            f"{body}</section>")


QUICK = """
<div class="exp-quick">
  <input id="exp-nl" type="text" autocomplete="off"
         placeholder="一句話記帳：昨天 全家 120 現金">
  <button type="button" id="exp-nl-go">解析</button>
</div>
<p id="exp-nl-hint" class="note">會拆出日期、商家、金額與付款方式，填進下面的表單讓你確認。</p>
"""

FORM = """
<form id="exp-form" class="exp-form" autocomplete="off">
  <div class="exp-form-grid">
    <label class="exp-field exp-field-amt">
      <span>金額</span>
      <input name="amount" type="number" inputmode="decimal" step="0.01"
             min="0" placeholder="0" required>
    </label>
    <label class="exp-field">
      <span>商家或項目</span>
      <input name="merchant" type="text" maxlength="120" placeholder="例：全聯、午餐">
    </label>
    <label class="exp-field">
      <span>日期</span>
      <input name="date" type="date">
    </label>
    <label class="exp-field">
      <span>備註（可空）</span>
      <input name="note" type="text" maxlength="300" placeholder="">
    </label>
  </div>
  <div class="exp-field">
    <span>分類</span>
    <div id="exp-chips" class="exp-chips"></div>
    <input name="category" type="hidden" value="未分類">
  </div>
  <div class="exp-field">
    <span>付款方式</span>
    <div id="exp-pay-chips" class="exp-chips"></div>
    <input name="pay" type="hidden" value="現金">
  </div>
  <div class="exp-field">
    <span>收據照片（可空）</span>
    <div class="exp-photo-row">
      <label class="exp-ghost exp-photo-pick">
        拍照或選圖
        <input name="photo" type="file" accept="image/*" hidden>
      </label>
      <div id="exp-photo-preview" class="exp-photo-preview"></div>
    </div>
  </div>
  <div class="exp-actions">
    <button type="submit" class="exp-primary" data-submit>記一筆</button>
    <button type="button" class="exp-ghost" data-cancel hidden>取消編輯</button>
  </div>
</form>
"""

SHORTCUT_STEPS = """
<ol class="exp-steps">
  <li>打開 iPhone 的<strong>「捷徑」App</strong> → 底部「自動化」→ 右上「＋」新增。</li>
  <li>觸發條件往下找到<strong>「交易」</strong>（Transaction）→ 勾選你的
      Apple Pay 卡片（可多張）→ 選<strong>「立即執行」</strong>，這樣刷卡當下就記帳，
      不會跳出來問你。</li>
  <li>動作選<strong>「取得 URL 內容」</strong>（Get Contents of URL），照左邊
      金鑰區塊顯示的設定填：URL、方法 POST、請求本文 JSON，
      金額、商家、卡片三個欄位從「快速指令輸入」變數裡選。</li>
  <li>完成。之後每一筆 Apple Pay（含 Apple Watch）付款會自動出現在這一頁，
      商家會照關鍵字自動分類，猜錯的點「改」修一次即可。</li>
</ol>
<p class="note">實體卡直接插卡／感應（沒過 Apple Pay）的交易，iOS 收不到通知——
能用 Apple Pay 感應就用 Apple Pay，記帳與回饋都不會少。</p>
"""

QUICK_STEPS = """
<p>LINE Pay 掃碼、現金這類<strong>不經過 Apple Pay</strong> 的消費，iOS 攔不到
（LINE Pay 沒有開放個人交易 API，捷徑的「交易」觸發器只認 Apple Pay）。
替代做法是放一顆「快速記帳」在主畫面：付完點一下、輸入金額，2 秒入帳。</p>
<ol class="exp-steps">
  <li>捷徑 App → 底部「捷徑」分頁（不是自動化）→ 右上「＋」新增，
      名稱取「快速記帳」。</li>
  <li>加動作<strong>「要求輸入」</strong>：輸入類型選「數字」，提示文字填「金額」。</li>
  <li>再加一個<strong>「要求輸入」</strong>：類型「文字」，提示填「商家」
      （分類會照商家自動猜）。</li>
  <li>加動作<strong>「取得 URL 內容」</strong>：URL 與金鑰照左邊區塊，
      方法 POST、JSON，欄位照左邊的「快速記帳」範例——<code>source</code>
      固定填 <code>manual</code>，<code>note</code> 可填「LINE Pay」方便辨識。</li>
  <li>捷徑詳細資訊 → <strong>「加入主畫面」</strong>。完成——LINE Pay 付完
      順手點一下就記好。</li>
</ol>
<p class="note">小訣竅：LINE Pay 聯名卡或 LINE Bank 簽帳卡加進 Apple Wallet 後，
實體店改用 Apple Pay 感應——回饋照拿（回饋綁卡片，不綁付款方式），
而且會被上面的自動記帳直接抓到，連點都不用點。</p>
"""

# App bar 的主題切換：獨立 App 不載 sidebar.js，這裡自帶最小版，
# 用同一個 localStorage key（theme），跟儀表板互通深淺色偏好。
THEME_TOGGLE = """
(function () {
  var root = document.documentElement;
  var btn = document.getElementById("exp-theme");
  if (!btn) return;
  var label = function () {
    var t = root.getAttribute("data-theme");
    btn.textContent = t === "dark" ? "淺色" : t === "light" ? "深色" : "主題";
  };
  label();
  btn.addEventListener("click", function () {
    var t = root.getAttribute("data-theme");
    var dark = matchMedia("(prefers-color-scheme: dark)").matches;
    var next = t ? (t === "dark" ? "light" : "dark") : (dark ? "light" : "dark");
    root.setAttribute("data-theme", next);
    try { localStorage.setItem("theme", next); } catch (e) {}
    label();
  });
})();
"""


def _body() -> str:
    parts = []

    parts.append(
        '<div id="exp-status" class="exp-status" role="status" aria-live="polite">'
        "載入中…</div>")

    parts.append(_section(
        "summary", "本月總覽",
        f'<div id="exp-summary">{_skeleton(4)}</div>',
        note="金額統計以台幣計；外幣筆數會列出但不併入合計。"))

    parts.append(_section(
        "budget", "預算",
        f'<div id="exp-budget">{_skeleton(3)}</div>',
        note="設每月總預算與分類預算；超支會標紅，接近上限標黃。"))

    parts.append(_section(
        "add", "記一筆",
        QUICK + FORM,
        note="填商家後分類會自動猜（全聯→超市、星巴克→餐飲），猜錯點分類改掉。"))

    parts.append(_section(
        "list", "明細",
        f'<div id="exp-month-nav" class="exp-month-nav"></div>'
        f'<div id="exp-list">{_skeleton(6)}</div>',
        note="點「改」進入編輯、「刪」移除。CSV 匯出的是目前檢視的月份。"))

    parts.append(_section(
        "auto", "Apple Pay 自動記帳",
        '<p>iOS 不讓 App 直接讀取 Apple Pay 交易——官方唯一的管道是捷徑的'
        '<strong>「交易」自動化</strong>：刷卡當下觸發捷徑，把金額與商家送到'
        '<code>/api/expense</code>，寫進你的帳。設定一次，之後全自動。</p>'
        '<div class="exp-auto-grid">'
        '<div class="exp-auto-col"><h3>你的金鑰</h3>'
        '<div data-account-slot></div>'
        f'<div id="exp-token">{_skeleton(2)}</div></div>'
        f'<div class="exp-auto-col"><h3>捷徑設定步驟</h3>{SHORTCUT_STEPS}</div>'
        "</div>",
        note="金鑰等同你的記帳權限：只給自己的捷徑用，外洩就到這裡撤銷重發。"))

    parts.append(_section(
        "quick", "LINE Pay 與現金：快速記帳捷徑",
        QUICK_STEPS,
        note="這條路走的是同一組金鑰與同一個端點，只是由你主動觸發。"))

    parts.append(_section(
        "privacy", "資料存在哪",
        '<p><strong>沒登入：</strong>只存在這台裝置瀏覽器的 localStorage，'
        '不離開你的手機。清瀏覽器資料會清掉，記得先匯出 CSV。</p>'
        '<p><strong>登入後：</strong>同步到雲端資料庫（Supabase），'
        '由 Row Level Security 隔離——每個帳號只能讀寫自己的紀錄。'
        '手機記的帳，電腦上登入同一帳號就看得到；Apple Pay 自動記帳需要登入'
        '（金鑰要綁在帳號上）。</p>'
        '<p>在 Safari 打開這一頁 → 分享 → <strong>加入主畫面</strong>，'
        '就是一個獨立的「記帳」App，有自己的圖示，離線也能開。</p>'))

    return "".join(parts)


def render_page(*, standalone: bool = False) -> str:
    """完整 HTML 文件——獨立 App 外殼，不經過 layout.page()。

    standalone=True 是「獨立網域」的變體（standalone/ 部署目錄）：
    manifest 與圖示用根目錄的通用檔名，scope 是整個網域。
    False 是掛在儀表板網域 /expense/ 底下的版本，資產帶 expense- 前綴
    避免跟儀表板自己的 manifest 與圖示撞名。
    """
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

    return f"""<!doctype html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>記帳</title>
<meta name="description" content="手動記一筆，或讓 iOS 捷徑在 Apple Pay 刷卡當下自動入帳；登入後跨裝置同步。">
<meta name="color-scheme" content="light dark">
<meta name="theme-color" content="#f9f9f7" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#0d0d0d" media="(prefers-color-scheme: dark)">
<link rel="manifest" href="{manifest}">
<link rel="apple-touch-icon" href="{touch_icon}">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="記帳">
<link rel="stylesheet" href="/style.css?v={version}">
<link rel="icon" href="{favicon}">
<script>{layout.BOOT}</script>
</head>
<body class="exp-app">
<header class="exp-topbar">
  <span class="exp-brand"><span class="exp-brand-mark" aria-hidden="true">$</span>記帳</span>
  <button type="button" class="icon-btn" id="exp-theme" aria-label="切換深淺色">主題</button>
</header>
<main class="content exp-main" id="content">
  <div class="wrap">
    <header class="page-head">
      <h1>記帳</h1>
      <p class="lede">手動記一筆，或讓 iOS 捷徑在 Apple Pay 刷卡當下自動入帳；登入後跨裝置同步。</p>
    </header>
{_body()}
  </div>
</main>
{sb}<script>{THEME_TOGGLE}</script>
<script src="/account.js?v={version}" defer></script>
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
  "background_color": "#f9f9f7",
  "theme_color": "#0e7a4f",
  "icons": [
    { "src": "/icon-192.png", "sizes": "192x192", "type": "image/png" },
    { "src": "/icon-512.png", "sizes": "512x512", "type": "image/png" },
    { "src": "/icon-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable" }
  ]
}
"""

# 極簡 service worker：只求可安裝與離線開啟上次的頁面。network-first——
# 記帳資料在 localStorage/Supabase，殼過期沒有代價，舊殼才有。
STANDALONE_SW = """const CACHE = "expense-static-v1";
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
    """把獨立網域用的完整部署目錄寫到 <root_dir>/standalone/site。

    這個目錄是給 Vercel 第二個專案用的（Root Directory 設成 standalone），
    部署後有自己的網域，跟儀表板徹底分開。standalone/api 與
    standalone/vercel.json 是手寫檔案、不在這裡產生；這裡只負責
    站台內容，讓每次建置都跟 /expense/ 用同一份程式。
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
        "style.css": "style.css",
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

    # API 也複製一份進去——Root Directory 設 standalone 的專案看不到
    # 上層的 api/，靠建置同步讓兩邊永遠同一份程式。
    api_dir = os.path.join(root_dir, "standalone", "api")
    os.makedirs(api_dir, exist_ok=True)
    shutil.copy2(os.path.join(paths.ROOT_DIR, "api", "expense.js"),
                 os.path.join(api_dir, "expense.js"))
