"""記帳頁：手動輸入 + Apple Pay 自動記帳（iOS 捷徑）。

內容是靜態骨架與教學文本，不吃建置資料——render() 不需要 ctx。
所有動態內容（摘要、明細、表單行為、金鑰管理、雲端同步）在
static/expense.js，資料存 localStorage，登入後同步到 Supabase。

骨架裡的佔位（.exp-skeleton）讓 JS 載入前不是一片空白；
JS 一跑就整塊換掉。
"""
from __future__ import annotations

from .. import layout
from ..html import section


def _skeleton(rows: int = 3) -> str:
    """JS 尚未接手前的骨架佔位——比空白或轉圈誠實，樣式在 style.css。"""
    return ('<div class="exp-skeleton" aria-hidden="true">'
            + '<span class="exp-sk-bar"></span>' * rows
            + "</div>")


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
<p class="note">現金或別人的請款不會經過 Apple Pay——用上面的表單手動補一筆就好。
實體卡直接插卡／感應（沒過 Apple Pay）的交易，iOS 收不到通知，同樣手動補。</p>
"""


def render() -> str:
    body = []

    body.append(
        '<div id="exp-status" class="exp-status" role="status" aria-live="polite">'
        "載入中…</div>")

    body.append(section(
        "summary", "本月總覽",
        f'<div id="exp-summary">{_skeleton(4)}</div>',
        note="金額統計以台幣計；外幣筆數會列出但不併入合計。"))

    body.append(section(
        "add", "記一筆",
        FORM,
        note="填商家後分類會自動猜（全聯→超市、星巴克→餐飲），猜錯點分類改掉。"))

    body.append(section(
        "list", "明細",
        f'<div id="exp-month-nav" class="exp-month-nav"></div>'
        f'<div id="exp-list">{_skeleton(6)}</div>',
        note="點「改」進入編輯、「刪」移除。CSV 匯出的是目前檢視的月份。"))

    body.append(section(
        "auto", "Apple Pay 自動記帳",
        '<p>iOS 不讓 App 直接讀取 Apple Pay 交易——官方唯一的管道是捷徑的'
        '<strong>「交易」自動化</strong>：刷卡當下觸發捷徑，把金額與商家送到'
        '這個網站的 <code>/api/expense</code>，寫進你的帳。設定一次，之後全自動。</p>'
        '<div class="exp-auto-grid">'
        '<div class="exp-auto-col"><h3>你的金鑰</h3>'
        '<div data-account-slot></div>'
        f'<div id="exp-token">{_skeleton(2)}</div></div>'
        f'<div class="exp-auto-col"><h3>捷徑設定步驟</h3>{SHORTCUT_STEPS}</div>'
        "</div>",
        note="金鑰等同你的記帳權限：只給自己的捷徑用，外洩就到這裡撤銷重發。"))

    body.append(section(
        "privacy", "資料存在哪",
        '<p><strong>沒登入：</strong>只存在這台裝置瀏覽器的 localStorage，'
        '不離開你的手機。清瀏覽器資料會清掉，記得先匯出 CSV。</p>'
        '<p><strong>登入後：</strong>同步到本站的 Supabase 資料庫，'
        '由資料庫的 Row Level Security 隔離——每個帳號只能讀寫自己的紀錄。'
        '手機記的帳，電腦上登入同一帳號就看得到；Apple Pay 自動記帳需要登入'
        '（金鑰要綁在帳號上）。</p>'
        '<p>把這一頁加到主畫面（分享 → 加入主畫面）就是一個獨立的記帳 App，'
        '離線也能開。</p>'))

    body.append(f'<script src="/expense.js?v={layout.asset_version()}" defer></script>')
    return "".join(body)
