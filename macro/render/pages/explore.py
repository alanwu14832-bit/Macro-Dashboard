"""自選指標瀏覽器。

這一頁刻意沒有伺服器端內容——它的全部意義就是讓讀者自己組合。
序列資料向 /api/series 即時取，所以看到的是 FRED 上的最新版，
不是建置當下的快照。
"""
from __future__ import annotations

from ..common import glossary
from ..html import accordion, callout, esc, section


RANGES = [("1Y", 1), ("3Y", 3), ("5Y", 5), ("10Y", 10), ("全期", 0)]


def render(ctx: dict) -> str:
    count = len((ctx.get("catalogue_ids") or [])) or None
    body = []

    controls = "".join(
        f'<button type="button" data-years="{years}" '
        f'aria-pressed="{"true" if years == 10 else "false"}">{esc(label)}</button>'
        for label, years in RANGES)

    body.append(section(
        "explore", "自選指標比較",
        f'''<div id="explore">
  <div class="ex-bar">
    <label class="ex-field">
      <span>轉換</span>
      <select id="ex-transform"></select>
    </label>
    <label class="ex-field">
      <span>分類</span>
      <select id="ex-group"><option value="">全部</option></select>
    </label>
    <div class="range-group" role="group" aria-label="時間區間">{controls}</div>
    <span class="quote-status" id="ex-status"></span>
  </div>

  <div id="ex-chosen" class="ex-chosen"></div>
  <p class="muted" id="ex-note" style="font-size:.85rem"></p>
  <div id="ex-chart"></div>
  <div id="ex-stats" style="margin-top:14px"></div>

  <div class="ex-picker">
    <input type="search" id="ex-search" placeholder="搜尋指標名稱或 FRED 代號…"
           autocomplete="off" aria-label="搜尋指標">
    <div id="ex-list" class="ex-list"></div>
  </div>
</div>''',
        note="最多同時比較 4 個指標；狀態會寫進網址，可以直接分享"))

    body.append(section("about", "這一頁怎麼運作", callout(
        "序列資料不是烤在頁面裡的，而是選到時才向 <code>/api/series</code> 取——"
        "那是一個代理 FRED 的 serverless function，所以你看到的永遠是 FRED 上的最新版本，"
        "不必等下一次建置。<br><br>"
        "本機以 <code>http.server</code> 預覽時沒有這個代理，"
        "頁面會顯示取不到資料，這是預期行為。")
        + accordion("為什麼單位不同就強制指數化", glossary([
            ("雙軸圖的問題",
             "把兩個單位不同的序列畫在同一張圖上、各給一條 Y 軸，兩條線的交叉點"
             "完全由你怎麼縮放決定——換個刻度就換個故事。它是最容易誤導人的圖表形式。"),
            ("指數化",
             "把每條序列的起點都設成 100，之後只看相對變化。這樣比較的是「誰漲得多」，"
             "而那是單位不同的序列之間唯一有意義的比較。"),
            ("z 分數",
             "把每條序列換算成「距離自己的平均幾個標準差」。適合比較「誰現在比較極端」，"
             "而不是誰的絕對水準高。"),
        ]))))

    return "".join(body)
