# 總經儀表板

把勞動、通膨、聯準會與利率、長端與債務、成長與信用、全球對照、大宗商品、市場面
八個面向，用固定規則收斂成一個**可追蹤、可回溯、可反駁**的判斷，
再配一頁國際新聞，讓當天的事件跟這些數字對得起來。

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
| 證交所 mis.twse.com.tw | 台股個股與 ETF 報價 | 免金鑰 |
| Fincept Terminal | 美股、台股與新興市場指數報價 | 需本機安裝，見下 |

FRED 金鑰讀取順序：環境變數 `FRED_API_KEY` → `~/.config/fincept/keys.json`。
金鑰不會進版控，快取寫入前也會 redact 掉 URL 中的金鑰參數。

主計總處的伺服器沒有送出中介憑證，OpenSSL 補不齊憑證鏈（macOS 會透過憑證的
AIA 欄位自動補，所以 curl 可以）。`macro/http.py` 的 `CURL_HOSTS` 讓這些主機
改走 curl —— **TLS 驗證仍然完整開啟**，由系統信任庫執行，沒有關掉任何檢查。

## 股市報價

`/equities/` 有三個區塊：美股、台股、其他新興市場。分工照來源特性：

- **指數與美股／新興市場個股** → Fincept Terminal 的 `yfinance_data.py`，
  以子行程呼叫。預設路徑 `~/Desktop/fincept-mcp`，可用環境變數 `FINCEPT_ROOT`
  覆寫。Fincept 不在時這一頁會顯示提示訊息，其餘 12 頁不受影響。
- **台股個股與 ETF** → 直接打證交所 `mis.twse.com.tw`，用 stdlib 實作
  （fincept 的 twse_source 需要 requests，與本專案的零依賴原則衝突）。
  含漲跌停價，並依「報價日期 vs 今天」判斷盤中／收盤／盤前。

### 即時更新（Netlify Function 代理）

`netlify/functions/quotes.mjs` 在伺服器端代抓報價再加上 CORS 標頭送回瀏覽器，
`macro/render/static/quotes.js` 每 45 秒就地換掉頁面上的數字。
間隔是 45 秒而不是更短，是因為頁面上有四十幾個非台股代號，而 Finnhub
免費層是每分鐘 60 次呼叫；代理端另有逐檔 45 秒快取，所有訪客共用。

| 區塊 | 部署後是否即時 | 條件 |
|---|---|---|
| 台股個股與 ETF | ✅ | 免金鑰，證交所 MIS |
| 美股個股、類股 ETF、大盤 ETF、新興市場 ETF | ✅ | 需設定 `FINNHUB_API_KEY` |
| 原始指數（^GSPC、^TWII、^KS11…） | ❌ | 報價 API 免費層不開放，維持建置快照 |

要啟用美股與新興市場的即時更新：到 https://finnhub.io 申請免費金鑰，
在 Netlify 的 Site configuration → Environment variables 新增
`FINNHUB_API_KEY`（`MARKETDATA_API_KEY` 為相容用的舊名）。
沒設定時那些欄位維持建置快照，狀態列會明說，不會假裝有更新。

原始指數改用追蹤同標的的 ETF 代表（SPY／QQQ／DIA／IWM 等），那一組是會動的。

**沒有代理的環境會安靜降級。** 本機用 `python3 -m http.server` 預覽時
`/api/quotes` 不存在，腳本重試一次後就停用，燈號轉灰並標示「顯示的是建置
當下的快照」——不會讓 live 燈號在根本不更新的頁面上繼續跳。

不能用 Fincept Terminal 當這個代理的資料源：它是跑在本機的 Python 程式，
Netlify Function 在雲端，碰不到；底層的 Yahoo 也會擋資料中心 IP。
Fincept 的角色是**建置時**取得快照，那部分照舊。

## 國際新聞（`/news/`）

新聞來源目錄取自 [WorldMonitor](https://github.com/koala73/worldmonitor)——一個
開源的全球情勢儀表板，維護著 287 個 RSS feed、16 個分類的來源清單。

**接的是它的目錄，不是它的服務。** 它的 REST API 與 MCP server 都要 API key
（`tools/list` 公開，`tools/call` 一律 401/403），但來源目錄就寫在原始碼裡
（`src/config/feeds.ts`），公開可讀。所以這裡在建置時抓那個檔、解析出 feed 清單，
再自己去抓各家 RSS。不需要金鑰、不需要 Node、不需要在本機跑它那套前端，
而且它換掉死掉的來源時，我們下次建置就跟著換。

**排序看「幾家報導」，不看「誰先報」。** 標題去停用詞後比對實詞重疊，共用 3 個
以上且重疊率達 34% 視為同一件事。單一媒體的獨家會沉下去，這是刻意的：對總經
判讀來說，一件事的重要性比較接近它被多少家編輯台同時認為重要。

只取英文來源（目錄裡還有匈牙利文、克羅埃西亞文等在地媒體），時間窗 36 小時，
每次約 64 個來源、耗時 45 秒左右。單一來源抓不到不影響其他來源，
失敗清單列在頁面底部。

授權：WorldMonitor 是 AGPL-3.0。這裡取用的是 feed 網址與分類名稱這類事實資料，
沒有內含或改作它的原始碼；新聞內容版權屬各原始媒體，頁面只存標題與連結。

## 目錄

```
build.py                    建置入口
macro/
  http.py                   節流 + 快取 + 重試的抓取層
  series.py                 時間序列容器與轉換（yoy、年化、z 分數、相關係數）
  catalogue.py              指標目錄：series id → 中文名／單位／頻率
  data.py                   載入目錄，記錄缺漏
  archive.py                每日判斷快照與期間比對
  sources/                  fred / sdmx / taiwan / lbma / quotes / worldmonitor
  compute/                  labor inflation rates debt growth world market
                            commodities equities news freshness signals scenario
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

## 自動更新

```bash
cd /path/to/macro-dashboard && python3 build.py
```

掛到排程即可。目前的設定是 **每天 08:45 與 21:45（台北時間）**：

| 時間（台北） | 對應 | 抓得到什麼 |
|---|---|---|
| 08:45 | 美國前一交易日收盤後 | 公債殖利率、匯率、股價、信用利差 |
| 21:45 | 美國 8:30am ET 數據發布後約 75 分鐘 | 非農、CPI、PCE、零售、初領失業金 |

**為什麼沒有「即時」。** 這個儀表板的資料本身不是即時的：非農與 CPI 月頻、
GDP 季頻、JOLTS 還延遲一個月，而 FRED 的日頻序列也是收盤後隔天才發布。
再高的重建頻率也改變不了這件事。

所以本站的做法不是提高重整頻率，而是把新鮮度攤開：`/freshness/` 頁列出每個
指標的最新資料日期、FRED 上次更新時間、**下次發布日與倒數天數**（取自 FRED
官方發布行事曆），總覽頁也會用一列 chip 標出七天內即將發布的項目。

每次執行會寫入一筆 `data/archive/YYYY-MM-DD.json`（同一天重跑會覆蓋），
隔天起 `/archive/` 頁與總覽的「跟上期比，什麼變了」就會有內容。

## 免責

本站為資料整理，不構成投資建議。`/scenario/` 的部位對照是情境到方向的機械
對照，未考慮任何個人的風險承受度、稅務與既有部位。
