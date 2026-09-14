# 給 Claude 的專案守則

這個檔案是寫給「沒有前後文的新 session」讀的——包含手機上的 claude.ai/code。
下面每一條都是踩過才寫下來的，不是偏好。

## 這是什麼

把美國總經（勞動、通膨、聯準會與利率、長端與債務、成長與信用）與台股，
用**寫死的門檻**收斂成一個可追蹤、可回溯、可反駁的判斷。產出是純靜態網站
（`site/`），部署在 Vercel。單一使用者＝作者本人。

## 三條硬約束

違反這三條的改動一律不要做，即使它會讓版面更好看。

1. **零第三方依賴。** 純 Python 標準庫 + 原生 JS/CSS/SVG。沒有 package.json、
   沒有 requirements.txt、沒有 CSS 框架、沒有圖表庫。唯一例外是
   `tools/send_push.py` 在 CI 裡用的 `pywebpush`（Web Push 的簽章加密不在
   標準庫能力內），依賴止步於發送端、不進網站。
2. **判定由固定規則產生。** 所有結論來自寫死的門檻，同一份資料每次執行結果
   一致。不做預測、不做機器學習、不做人工調整。規則沒涵蓋的情況就沉默，
   不猜答案。
3. **資料缺口誠實標明。** 沒有市場共識預期、沒有 CME FedWatch 官方機率、
   沒有主權 CDS、沒有台股融資維持率——這些都在頁面上就地講明並說明替代指標。
   **絕不為了版面整齊讓缺口消失**：圖表的 null 不連線（虛線橋接）、沿用前值
   要標記、空儲存格畫「—」不留白。缺口標記是唯一寧可醜也不能淡的元素。

另外：**任何畫面都不得讀起來像投資建議**。用「情境對照」不用「建議」，
方向色用鷹派／鴿派（政策方向）不用漲跌。

## 跑起來

```bash
python3 build.py              # 一般建置（6 小時內的快取直接用）
python3 build.py --fresh      # 忽略快取全部重抓
python3 build.py --offline    # 只用快取、不連網
python3 build.py --ttl 3000   # 自訂快取有效期（排程用）
python3 -m unittest discover tests   # 95 個測試，CI 會先跑這個
```

**乾淨 clone 跑不動 `--offline`**：`data/cache/` 在 .gitignore 裡。第一次要用
`FRED_API_KEY` 連網抓（約 3 分鐘、兩百多檔序列）。可選的還有 `FINNHUB_API_KEY`
（美股報價）與 `MARKETDATA_API_KEY`。沒有金鑰時多數頁面會是「—」，而
`build.py` 的缺漏守門會在缺超過 10 檔時**中止建置**——那是刻意的，別把它拿掉。

本機預覽用 `.claude/launch.json` 裡的設定（Browser pane 的 preview_start），
不要用 Bash 跑伺服器。

## 部署與排程

- `site/` **進版控**。Vercel 只 serve `site/` 與 `api/`，不重跑 build，
  所以 Vercel 那邊不需要金鑰。
- GitHub Actions 每小時排程 + **push 觸發**（作者是 bot 時跳過，避免它自己
  commit `site/` 造成無限迴圈）。實測 GitHub 對公開 repo 的 schedule 只是
  best-effort，實際間隔 2–6 小時、分鐘隨機——**所以頁面上不承諾「下次建置
  還有幾分鐘」**，只說資料多舊。
- 改了源碼要上站，push 就會觸發建置；**不要**推本機用 `--offline` 建出來的
  `site/`，那會把陳舊資料蓋上線。

## 絕對不要手動合併生成檔

`site/`、`data/quotes_snapshot.json`、`data/fedfunds_snapshot.json`、
`data/series_dates.json`、`data/archive/*.json` 都是建置產物。跟雲端建置撞到時：

```bash
git checkout HEAD -- site data        # 取已提交版本
git clean -fd site                    # 清掉擋住 rebase 的未追蹤產物
git pull --rebase --autostash origin main
```

然後重建。**絕不逐行解衝突。**

## 台灣的資料源跟其他頁不一樣

台灣不在 FRED 也不在 OECD，所以 `/taiwan/` 的資料來自三個直接解析的來源，
每一個都有自己的脆弱點：

- **國發會景氣指標**（`macro/sources/ndc.py`）。一個 ZIP 涵蓋景氣對策信號、
  領先／同時／落後指標與**全部構成項目**（外銷訂單、M1B、工業生產、海關出口、
  失業率、五大銀行放款利率、金融機構放款與投資⋯共 23 檔）。下載網址**不要寫死**
  ——國發會每月重新上傳，路徑裡的 GUID 會換；走政府資料開放平臺
  `data.gov.tw/api/v2/rest/dataset/6099` 解析當前網址，寫死的那條只是退路。
  解析**按欄名**不按位置：欄名對不上就留空序列，不准用鄰近欄位頂替
  （有測試釘住，因為頂替之後失業率那條線畫的會是單位產出勞動成本，而且不報錯）。
- **中央銀行重貼現率**（`macro/sources/cbc.py`）。央行沒有把政策利率放進任何
  開放資料檔，只有 HTML 表格。它是**階梯函數**：月度展開要重複前值，
  不准內插——兩次理監事會議之間畫出斜線等於捏造從未存在的利率。
- **主計總處 CPI**（`macro/sources/taiwan.py`）。DGBAS 的伺服器少送中介憑證，
  所以走 `macro/http.py` 的 curl 路徑（驗證仍然完整執行，沒有關掉任何東西）。

ZIP 要用 `http.get_bytes()`，不是 `get()`——後者會把二進位解成 UTF-8 弄壞它。

**台灣的訊號規則一律 `direction="neutral"`。** 鷹派紅／鴿派藍在這個站上專指
聯準會的政策方向；台灣的景氣循環不是聯準會的理由，讓它去加減 tilt 會讓總覽的
判斷被無關的資訊推走。有測試釘住。

## 時間一律用 `macro/clock.py`

`datetime.now()` 與 `date.today()` 在 CI 上是 UTC，曾經造成兩個不會當場爆炸的
bug：頁面上的「最後更新」標著台北卻差 8 小時；每日存檔用 UTC 日期歸檔，
台北凌晨 0–8 點的建置會覆蓋掉前一天的判斷快照。有迴歸測試釘住，別繞過。

## 版面預算（會讓建置失敗）

總覽被抱怨過兩次「東西太多」。現在預算寫在 `macro/render/pages/overview.py`
的 `BUDGET` 並由 `build.py` 檢查：

- 結構超標（區塊 ≤8、表 ≤3、摺疊 ≤3、讀數格 ≤22）→ **建置失敗**
- 可見字元超過 2,600 → 只印警告（它隨訊號條數與新聞長度浮動，用硬失敗擋它
  等於讓網站因為版面而停止更新資料）

要加第 9 個區塊，**必須指名擠掉現有八個裡的哪一個**。摺疊不是出口——摺疊只准
把「同一層、同一類、更多筆」收起來。要聞的 12 個行內展開是**具名例外**
（`NEWS_DISCLOSURES`），不是偷偷放行。

分類的規則：每個區塊要答出三題——今天跟昨天不一樣的機率多少（用
`data/archive/` 實測，不是直覺）、哪個深頁已經有區塊吃同一批資料（有的話
**刪除不是搬移**，`/fed/` 已經 228KB，往那裡倒只是把過載換個地方）、
它的錯誤責任在誰（機構事實／本站門檻／市場定價／記者說法，四種不准並排）。

## 設計 token：只能挑，不能加

`style.css` 的字階凍結成 7 階（`--t-12` 到 `--t-30`，每階綁死行高）、間距 8 階
（`--s1`…`--m16`，刻意跳過 20/28/36/40/56）、字重 4 類、圓角 4 級。

**不要再新增任何字級或非 4 倍數的間距。** 挑不到就代表那個元件的層級定義有
問題，該回頭想層級。（改造前有 42 種字級，11–15.8px 之間就有 21 種。）

## 動態

- 時長三檔：`--dur-1` 90ms（顏色/邊框）、`--dur-2` 160ms（位移/展開）、
  `--dur-3` 300ms（sheet/面板）。
- 兩條彈簧曲線 `--spring-firm` / `--spring-soft` 的數字是從 `sidebar.js` 的
  `runSpring` 參數積分而來——CSS 與 JS 是同一套物理，改一邊要改另一邊。
- **手勢驅動的東西不准改用 CSS `linear()`**：它固定時長、被打斷時不保留速度，
  抽屜拖到一半放手再抓住會瞬移。`sidebar.js` 那段彈簧不要動。
- 抽屜與 sheet 開啟**必須** `history.pushState`，否則 iOS 邊緣返回會把整個
  app 導走。
- `:hover` 一律包在 `@media (hover: hover) and (pointer: fine)` 裡，
  觸控端用 `:active`。

**不做**：數字 count-up（會經過從未存在的值，違反硬約束 2）、斑馬紋（背景色
要留給缺口與更新標記）、陰影分級（`--shadow: none` 是刻意的）、骨架屏
（頁面是靜態產出，first paint 就有值）。

## 顏色語意不可混用

- 鷹派紅 `--hawkish` / 鴿派藍 `--dovish` ＝**政策方向**
- 綠漲紅跌 ＝**價格結果**（台股慣例，全站單一極性，不做偏好設定）
- 嚴重度用**形狀＋顏色雙通道**（`■ ▲ ●` 加 `sr-only` 文字）

同一頁出現兩套紅色語意，讀者在數據公布後那一眼一定會誤讀。

## 測試

95 個測試，CI 在建置前跑。新增測試時針對「壞了不會報錯、只會靜默給錯答案」
那一類：時區、變動排序、分頁歸屬、追蹤清單與落點頁的同步、版面預算計數。

寫批次修改腳本時**每個字串替換都要 `assert`**——`str.replace` 找不到目標時
會靜默 no-op，曾經因此讓全站 `var(--t-*)` 指向未定義變數。

`tests/test_undefined_names.py` 用標準庫的 `ast` 掃過 `macro/`、`tools/` 與
`build.py`，找「函式裡讀到從未被綁定的名字」。2026-09-14 的總覽改版刪掉了
`_related_reading()` 卻留下 `... if reading else ""`，測試全綠、匯入正常，
只有建置走到那一行才炸 NameError——結果整站的自動更新停了一天多，首頁
看起來完全正常（它只是停在前一天）。CI 先跑測試再建置，所以這類錯要在測試
裡擋。它刻意對 lambda 參數放寬，因為**一有誤報這個檢查就會被關掉**。

## 秘密

`data/secrets/` 在 .gitignore 裡（VAPID 私鑰）。GitHub Actions 用四個 secret：
`FRED_API_KEY`、`FINNHUB_API_KEY`、`VAPID_PRIVATE_KEY`、`SUPABASE_SERVICE_KEY`。
Supabase 的 anon key 是設計上公開的前端金鑰（靠 RLS 隔離），寫在
`macro/render/layout.py` 裡不是外洩。
