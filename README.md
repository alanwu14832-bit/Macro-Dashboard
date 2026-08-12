# 總經儀表板

把勞動、通膨、聯準會與利率、長端與債務、成長與信用、全球對照、大宗商品、市場面
八個面向，用固定規則收斂成一個**可追蹤、可回溯、可反駁**的判斷。

產出是純靜態網站（`site/`），可直接部署到 Netlify 或任何靜態主機。

## 跑起來

```bash
python3 build.py
```

只需要 Python 3.10+，**沒有任何第三方套件**。首次執行約 3 分鐘（抓 196 檔序列），
之後有快取，重建約 1 秒。

```bash
python3 build.py --fresh       # 忽略快取，全部重抓
python3 build.py --offline     # 只用快取，完全不連網
python3 build.py --no-archive  # 不寫入當天存檔
```

本機預覽：

```bash
python3 -m http.server 8787 --directory site
```

## 設計上的幾個取捨

**零第三方依賴。** 圖表是自己寫的 SVG 引擎（`macro/render/static/chart.js`），
模板是 Python 字串組件（`macro/render/html.py`）。理由是這東西要每天自動跑、
要能離線看、要十年後還跑得動。

**抓取層一定要有節流與快取。** FRED 對密集呼叫會回 429 並升級成 403 暫封。
`macro/http.py` 對每個主機做最小間隔、指數退避、磁碟快取，失敗時退回舊快取，
讓單一來源掛掉不會毀掉整份報告。

**判定門檻全部寫死、集中在一處。** 見 `macro/compute/scenario.py` 的
`EMPLOYMENT_BANDS` / `INFLATION_BANDS` / `REGIME_RULES`，以及
`macro/compute/signals.py` 每條規則內的數字。同一份資料每次執行結果一致，
也才能拿去跟上期比對。改門檻等於改判斷，不會藏在別處。

**沒有來源就留白。** 日本 CPI 在 FRED 與 OECD 都停在 2021-06，頁面會標示
「停更於 2021-06」並且**不拿它去算實質殖利率**。缺口在 `/global/` 頁明列。

## 資料來源

| 來源 | 用途 | 備註 |
|---|---|---|
| FRED | 美國全部、國際公債殖利率、匯率、IMF 商品價格 | 需 `FRED_API_KEY` |
| OECD SDMX | 各國 CPI 年增率 | 免金鑰 |
| ECB Data Portal | 歐元區失業率、核心 HICP | 免金鑰 |
| 行政院主計總處 | 台灣 CPI | 免金鑰；走 curl（見下） |
| LBMA | 黃金、白銀官方定盤價 | 免金鑰 |

FRED 金鑰讀取順序：環境變數 `FRED_API_KEY` → `~/.config/fincept/keys.json`。
金鑰不會進版控，快取寫入前也會 redact 掉 URL 中的金鑰參數。

主計總處的伺服器沒有送出中介憑證，OpenSSL 補不齊憑證鏈（macOS 會透過憑證的
AIA 欄位自動補，所以 curl 可以）。`macro/http.py` 的 `CURL_HOSTS` 讓這些主機
改走 curl —— **TLS 驗證仍然完整開啟**，由系統信任庫執行，沒有關掉任何檢查。

## 目錄

```
build.py                    建置入口
macro/
  http.py                   節流 + 快取 + 重試的抓取層
  series.py                 時間序列容器與轉換（yoy、年化、z 分數、相關係數）
  catalogue.py              指標目錄：series id → 中文名／單位／頻率
  data.py                   載入目錄，記錄缺漏
  archive.py                每日判斷快照與期間比對
  sources/                  fred / sdmx / taiwan / lbma
  compute/                  labor inflation rates debt growth world market
                            commodities signals scenario
  render/
    html.py                 元件庫（跳脫、格式化、卡片、表格）
    layout.py               頁面外殼、導覽、深淺色
    common.py               圖表規格建構
    static/                 style.css、chart.js
    pages/                  每頁一個 renderer
data/cache/                 原始 API 回應（可安全刪除）
data/archive/               每日判斷快照（刪掉就失去歷史）
site/                       產出，部署這個目錄
```

## 每天自動更新

```bash
cd /path/to/macro-dashboard && python3 build.py
```

把上面這行掛到排程（cron 或 scheduled-tasks）即可。每次執行會寫入一筆
`data/archive/YYYY-MM-DD.json`，隔天起 `/archive/` 頁與總覽的「跟上期比，
什麼變了」就會有內容。

## 免責

本站為資料整理，不構成投資建議。`/scenario/` 的部位對照是情境到方向的機械
對照，未考慮任何個人的風險承受度、稅務與既有部位。
