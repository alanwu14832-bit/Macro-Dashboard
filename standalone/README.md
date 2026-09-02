# 記帳——獨立網域部署目錄

這個目錄是「記帳」App 的獨立部署包，讓它有**自己的網域**、跟總經儀表板
徹底分開。內容（`site/` 與 `api/expense.js`）由 `build.py` 從
`macro/render/pages/expense.py` 與 `macro/render/static/` 自動產出——
**不要手改這裡的檔案**，改源頭再重新建置。

## 部署（Vercel 第二個專案）

1. Vercel → **Add New… → Project** → 再次匯入這個 repo（同一個 repo 可以建多個專案）
2. 專案名稱取你想要的網域前綴（例如 `alan-expense` → `alan-expense.vercel.app`）
3. **Root Directory** 按 Edit → 選 `standalone`
4. Framework Preset 選 **Other**，Build Command 留空（`vercel.json` 都寫好了）
5. Environment Variables 加 `SUPABASE_SERVICE_ROLE_KEY`（跟儀表板專案同一把）
6. Deploy

部署後 `https://<專案名>.vercel.app/` 就是記帳 App 本體，
`/api/expense` 是自動記帳收單端點。之後買了自訂網域（如 `.com`）
在這個專案的 Settings → Domains 綁上即可，其他什麼都不用改。

帳號與資料都在同一個 Supabase 專案，跟舊網址（儀表板網域的 `/expense/`）
完全互通；iOS 捷徑裡的 URL 換成新網域即可。
