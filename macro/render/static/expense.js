/* ============================================================================
 * expense.js — 記帳頁（/expense/）的全部邏輯。
 *
 * 設計與自選清單同一套哲學：
 *   - localStorage 優先。沒登入、Supabase 沒開通，手動記帳照樣全功能，
 *     資料存在本機（key: exp-items）。
 *   - 登入後雲端同步（Supabase expenses 表，RLS 隔離）。同步採
 *     「推髒資料 → 推刪除 → 拉全量覆蓋」：手機與電腦都能記，最後以雲端為準。
 *   - Apple Pay 自動記帳：iOS 捷徑的「交易」自動化 POST 到 /api/expense，
 *     寫進同一張表；這頁每分鐘拉一次，刷完卡回來看就有了。
 *
 * session 直接共用 account.js 的 sb-session（同一個 localStorage key），
 * 過期時自己 refresh 並存回去——兩支腳本誰先刷新，另一支都拿得到新 token。
 * ========================================================================== */
(() => {
  "use strict";

  const form = document.getElementById("exp-form");
  if (!form) return;                       // 不在記帳頁

  const CONF = window.__SB;
  const SESSION_KEY = "sb-session";
  const ITEMS_KEY = "exp-items";
  const DIRTY_KEY = "exp-dirty";
  const TOMB_KEY = "exp-tomb";

  // 分類與顏色（對應 style.css 的 --series-*；灰色給未分類）
  const CATEGORIES = ["餐飲", "超商", "超市", "交通", "停車費", "相機", "吉他",
                      "網購", "訂閱與娛樂", "醫療", "居住與帳單", "教育",
                      "其他", "未分類"];
  const CAT_COLOR = {
    "餐飲": "var(--series-2)", "超商": "var(--series-4)", "超市": "var(--series-3)",
    "交通": "var(--series-1)", "停車費": "var(--series-6)",
    "相機": "var(--series-7)", "吉他": "var(--series-8)",
    "網購": "var(--series-5)", "訂閱與娛樂": "var(--series-7)",
    "醫療": "var(--series-8)", "居住與帳單": "var(--series-6)", "教育": "var(--series-3)",
    "其他": "var(--neutral)", "未分類": "var(--neutral)",
  };

  // 自訂分類：本機存一份，另外從既有紀錄裡撿（別台裝置加的自訂分類，
  // 隨資料同步過來也要出現在 chips 裡）。
  const CUSTOM_KEY = "exp-custom-cats";
  const customCats = () => {
    const stored = loadJson(CUSTOM_KEY, []);
    const fromItems = items.map((it) => it.category)
      .filter((cat) => cat && !CATEGORIES.includes(cat));
    return [...new Set([...stored, ...fromItems])];
  };
  const addCustomCat = (name) => {
    const stored = loadJson(CUSTOM_KEY, []);
    if (!stored.includes(name)) saveJson(CUSTOM_KEY, [...stored, name]);
  };

  // 與 api/expense.js 的 CATEGORY_RULES 同一套規則——兩邊都改才會一致。
  const CATEGORY_RULES = [
    [/7-?eleven|統一超商|全家|family\s*mart|萊爾富|hi-?life|ok\s*mart|超商/i, "超商"],
    [/全聯|pxmart|家樂福|carrefour|大潤發|愛買|costco|好市多|美廉社|超市|市場/i, "超市"],
    [/麥當勞|mcdonald|肯德基|kfc|摩斯|mos\s*burger|漢堡王|burger\s*king|必勝客|pizza|壽司|sushi|拉麵|火鍋|燒肉|食堂|餐廳|餐飲|小吃|便當|鍋貼|水餃|早餐|豆漿|茶|咖啡|coffee|starbucks|星巴克|路易莎|louisa|cama|85度|五十嵐|50嵐|清心|可不可|迷客夏|珍煮丹|得正|foodpanda|uber\s*eats/i, "餐飲"],
    [/停車|parking|路邊收費|嘟嘟房|times|udpark/i, "停車費"],
    [/台鐵|高鐵|thsr|捷運|metro|悠遊|easycard|一卡通|ipass|客運|公車|uber(?!\s*eats)|計程|taxi|line\s*go|中油|cpc|台亞|全國加油|加油/i, "交通"],
    [/相機|camera|鏡頭|canon|nikon|fujifilm|富士|leica|徠卡|gopro|dji|攝影|底片|沖掃/i, "相機"],
    [/吉他|guitar|貝斯|bass|烏克麗麗|ukulele|效果器|音箱|樂器|弦|pick|移調夾|capo|slide|滑音管/i, "吉他"],
    [/藥局|藥妝|屈臣氏|watsons|康是美|cosmed|診所|醫院|牙醫|clinic|hospital|pharmacy/i, "醫療"],
    [/netflix|spotify|youtube|disney|apple\.com|apple\s*services|itunes|icloud|app\s*store|內購|google\s*(one|play|storage)|steam|nintendo|playstation|訂閱/i, "訂閱與娛樂"],
    [/蝦皮|shopee|momo|pchome|coupang|酷澎|淘寶|taobao|amazon|樂天|rakuten|露天/i, "網購"],
    [/電費|台電|水費|自來水|瓦斯|天然氣|電信|中華電信|台灣大|遠傳|fetnet|房租|租金|管理費/i, "居住與帳單"],
  ];
  const guessCategory = (text) => {
    for (const [pattern, category] of CATEGORY_RULES) {
      if (pattern.test(text)) return category;
    }
    return "";
  };

  /* -------------------------------------------------------------- storage -- */

  const loadJson = (key, fallback) => {
    try { return JSON.parse(localStorage.getItem(key)) ?? fallback; }
    catch { return fallback; }
  };
  const saveJson = (key, value) => {
    try { localStorage.setItem(key, JSON.stringify(value)); } catch {}
  };

  let items = loadJson(ITEMS_KEY, []);          // [{id, amount, currency, merchant, category, note, source, spent_at}]
  let dirty = new Set(loadJson(DIRTY_KEY, [])); // 尚未推上雲端的 id
  let tombs = new Set(loadJson(TOMB_KEY, []));  // 已刪、尚未通知雲端的 id
  const persist = () => {
    saveJson(ITEMS_KEY, items);
    saveJson(DIRTY_KEY, [...dirty]);
    saveJson(TOMB_KEY, [...tombs]);
  };

  const uuid = () => (crypto.randomUUID
    ? crypto.randomUUID()
    : "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
        const r = crypto.getRandomValues(new Uint8Array(1))[0] % 16;
        return (c === "x" ? r : (r & 0x3) | 0x8).toString(16);
      }));

  /* ------------------------------------------------------ Supabase session -- */

  const session = () => loadJson(SESSION_KEY, null);

  async function freshToken() {
    const s = session();                       // 每次重讀：account.js 可能剛刷新過
    if (!s || !CONF) return null;
    if (Date.now() < s.expires - 60_000) return s.access;
    try {
      const response = await fetch(
        CONF.url + "/auth/v1/token?grant_type=refresh_token", {
          method: "POST",
          headers: { apikey: CONF.key, "Content-Type": "application/json" },
          body: JSON.stringify({ refresh_token: s.refresh }),
        });
      const payload = await response.json();
      if (!response.ok || !payload.access_token) throw new Error("refresh 失敗");
      saveJson(SESSION_KEY, {
        access: payload.access_token,
        refresh: payload.refresh_token,
        expires: Date.now() + (payload.expires_in || 3600) * 1000,
        email: (payload.user && payload.user.email) || s.email,
        uid: (payload.user && payload.user.id) || s.uid,
      });
      return payload.access_token;
    } catch {
      return null;
    }
  }

  async function rest(method, path, body, prefer) {
    const token = await freshToken();
    if (!token) throw new Error("未登入");
    const headers = {
      apikey: CONF.key,
      Authorization: "Bearer " + token,
      "Content-Type": "application/json",
    };
    if (prefer) headers.Prefer = prefer;
    const response = await fetch(CONF.url + "/rest/v1" + path, {
      method, headers, body: body ? JSON.stringify(body) : undefined,
    });
    if (!response.ok) throw new Error("HTTP " + response.status);
    return method === "GET" ? response.json() : null;
  }

  /* ----------------------------------------------------------------- sync -- */

  let syncTimer = null;
  let lastSync = null;   // Date | null
  let syncError = "";

  async function syncNow() {
    if (!CONF || !session()) return;
    try {
      const uid = session().uid;
      if (dirty.size) {
        const rows = items.filter((it) => dirty.has(it.id)).map((it) => ({
          id: it.id, user_id: uid, amount: it.amount, currency: it.currency,
          merchant: it.merchant, category: it.category, note: it.note,
          source: it.source, spent_at: it.spent_at,
        }));
        if (rows.length) {
          await rest("POST", "/expenses?on_conflict=id", rows,
                     "resolution=merge-duplicates,return=minimal");
        }
        dirty.clear();
      }
      if (tombs.size) {
        const ids = [...tombs].join(",");
        await rest("DELETE", "/expenses?id=in.(" + ids + ")", null,
                   "return=minimal");
        tombs.clear();
      }
      const cloud = await rest("GET",
        "/expenses?select=id,amount,currency,merchant,category,note,source,spent_at"
        + "&order=spent_at.desc&limit=5000");
      items = cloud.map((row) => ({
        id: row.id, amount: Number(row.amount), currency: row.currency,
        merchant: row.merchant, category: row.category, note: row.note,
        source: row.source, spent_at: row.spent_at,
      }));
      lastSync = new Date();
      syncError = "";
      persist();
      render();
    } catch (error) {
      syncError = String(error.message || error);
      renderStatus();
    }
  }

  const scheduleSync = () => {
    clearTimeout(syncTimer);
    syncTimer = setTimeout(syncNow, 800);
  };

  // 自動記帳的資料是別的裝置寫進來的——頁面開著就每 60 秒拉一次，
  // 切回分頁時立刻拉。沒登入時這些都是 no-op。
  setInterval(() => { if (!document.hidden) syncNow(); }, 60_000);
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) syncNow();
  });
  document.addEventListener("wl-cloud-ready", () => { syncNow(); renderTokens(); });
  document.addEventListener("wl-cloud-gone", () => { renderStatus(); renderTokens(); });

  /* ------------------------------------------------------------- 檢視狀態 -- */

  const today = new Date();
  let viewYear = today.getFullYear();
  let viewMonth = today.getMonth();        // 0-based
  let editingId = null;

  const monthKey = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
  const viewKey = () => `${viewYear}-${String(viewMonth + 1).padStart(2, "0")}`;

  const inView = (it) => {
    const d = new Date(it.spent_at);
    return d.getFullYear() === viewYear && d.getMonth() === viewMonth;
  };

  const money = (amount, currency) => {
    const text = Number(amount).toLocaleString("zh-TW", {
      minimumFractionDigits: 0, maximumFractionDigits: 2,
    });
    return (currency && currency !== "TWD") ? `${text} ${currency}` : `$${text}`;
  };

  const esc = (raw) => String(raw ?? "").replace(/[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;",
              '"': "&quot;", "'": "&#39;" }[c]));

  /* ---------------------------------------------------------------- 摘要 -- */

  function renderSummary() {
    const box = document.getElementById("exp-summary");
    if (!box) return;
    const rows = items.filter(inView).filter((it) => it.currency === "TWD" || !it.currency);
    const foreign = items.filter(inView).length - rows.length;
    const total = rows.reduce((sum, it) => sum + it.amount, 0);

    const prev = new Date(viewYear, viewMonth - 1, 1);
    const prevTotal = items
      .filter((it) => monthKey(new Date(it.spent_at)) === monthKey(prev))
      .filter((it) => it.currency === "TWD" || !it.currency)
      .reduce((sum, it) => sum + it.amount, 0);

    const isCurrent = viewKey() === monthKey(today);
    const daysElapsed = isCurrent ? today.getDate()
      : new Date(viewYear, viewMonth + 1, 0).getDate();
    const perDay = daysElapsed ? total / daysElapsed : 0;
    const deltaPct = prevTotal ? ((total - prevTotal) / prevTotal) * 100 : null;

    const stats = [
      ["本月支出", money(total, "TWD"),
       deltaPct === null ? "上月無資料"
         : `比上月${deltaPct >= 0 ? "多" : "少"} ${Math.abs(deltaPct).toFixed(0)}%`],
      ["筆數", String(items.filter(inView).length), foreign ? `含外幣 ${foreign} 筆（不計入合計）` : "手動與自動合計"],
      ["日均", money(perDay, "TWD"), isCurrent ? `以本月已過 ${daysElapsed} 天計` : "以整月計"],
    ];
    let html = '<div class="grid grid-3">' + stats.map(([label, value, note]) =>
      `<div class="stat"><div class="label">${esc(label)}</div>` +
      `<div class="value">${esc(value)}</div>` +
      `<div class="delta"><span class="muted">${esc(note)}</span></div></div>`).join("") +
      "</div>";

    // 分類長條：金額由大到小，寬度相對最大分類
    const byCat = new Map();
    for (const it of rows) {
      byCat.set(it.category || "未分類",
                (byCat.get(it.category || "未分類") || 0) + it.amount);
    }
    const sorted = [...byCat.entries()].sort((a, b) => b[1] - a[1]);
    const max = sorted.length ? sorted[0][1] : 0;
    if (sorted.length) {
      html += '<div class="exp-cats">' + sorted.map(([cat, amount]) => {
        const width = max ? Math.max(2, (amount / max) * 100) : 0;
        const share = total ? ((amount / total) * 100).toFixed(0) : 0;
        return `<div class="exp-cat-row">` +
          `<span class="exp-cat-name">${esc(cat)}</span>` +
          `<span class="exp-cat-bar"><i style="width:${width}%;background:${CAT_COLOR[cat] || "var(--neutral)"}"></i></span>` +
          `<span class="exp-cat-amt">${esc(money(amount, "TWD"))}<em class="muted"> ${share}%</em></span></div>`;
      }).join("") + "</div>";
    } else {
      html += '<p class="muted">這個月還沒有任何紀錄。</p>';
    }
    box.innerHTML = html;
  }

  /* ---------------------------------------------------------------- 明細 -- */

  function renderList() {
    const nav = document.getElementById("exp-month-nav");
    const box = document.getElementById("exp-list");
    if (!nav || !box) return;

    nav.innerHTML =
      `<button type="button" class="exp-nav-btn" data-nav="-1" aria-label="上一個月">‹</button>` +
      `<span class="exp-month-label">${viewYear} 年 ${viewMonth + 1} 月</span>` +
      `<button type="button" class="exp-nav-btn" data-nav="1" aria-label="下一個月">›</button>` +
      `<button type="button" class="exp-csv" data-csv>匯出 CSV</button>`;
    for (const btn of nav.querySelectorAll("[data-nav]")) {
      btn.addEventListener("click", () => {
        const shift = Number(btn.dataset.nav);
        const d = new Date(viewYear, viewMonth + shift, 1);
        viewYear = d.getFullYear();
        viewMonth = d.getMonth();
        render();
      });
    }
    nav.querySelector("[data-csv]").addEventListener("click", exportCsv);

    const rows = items.filter(inView)
      .sort((a, b) => new Date(b.spent_at) - new Date(a.spent_at));
    if (!rows.length) {
      box.innerHTML = '<p class="muted">這個月沒有紀錄。用上面的表單記一筆，'
        + '或設定好自動記帳後用 Apple Pay 付一筆看看。</p>';
      return;
    }

    const weekdays = ["日", "一", "二", "三", "四", "五", "六"];
    const groups = new Map();      // 'YYYY-MM-DD' → rows
    for (const it of rows) {
      const d = new Date(it.spent_at);
      const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(it);
    }

    let html = "";
    for (const [day, dayRows] of groups) {
      const d = new Date(day + "T12:00:00");
      const dayTotal = dayRows
        .filter((it) => it.currency === "TWD" || !it.currency)
        .reduce((sum, it) => sum + it.amount, 0);
      html += `<div class="exp-day"><span>${d.getMonth() + 1}/${d.getDate()}`
        + `（${weekdays[d.getDay()]}）</span><span>${esc(money(dayTotal, "TWD"))}</span></div>`;
      for (const it of dayRows) {
        const color = CAT_COLOR[it.category] || "var(--neutral)";
        html += `<div class="exp-row" data-id="${esc(it.id)}">`
          + `<span class="exp-dot" style="background:${color}" aria-hidden="true"></span>`
          + `<span class="exp-main"><span class="exp-merchant">${esc(it.merchant || "（未填商家）")}</span>`
          + `<span class="exp-sub muted">${esc(it.category || "未分類")}`
          + (it.source === "applepay" ? '<span class="exp-badge"> Pay</span>' : "")
          + (it.note ? `｜${esc(it.note)}` : "") + `</span></span>`
          + `<span class="exp-amt">${esc(money(it.amount, it.currency))}</span>`
          + `<span class="exp-ops"><button type="button" data-edit aria-label="編輯">改</button>`
          + `<button type="button" data-del aria-label="刪除">刪</button></span></div>`;
      }
    }
    box.innerHTML = html;

    for (const row of box.querySelectorAll(".exp-row")) {
      const id = row.dataset.id;
      row.querySelector("[data-edit]").addEventListener("click", () => startEdit(id));
      row.querySelector("[data-del]").addEventListener("click", () => removeItem(id));
    }
  }

  function exportCsv() {
    const rows = items.filter(inView)
      .sort((a, b) => new Date(a.spent_at) - new Date(b.spent_at));
    const escape = (v) => `"${String(v ?? "").replace(/"/g, '""')}"`;
    const lines = ["date,amount,currency,merchant,category,note,source"];
    for (const it of rows) {
      lines.push([it.spent_at, it.amount, it.currency, it.merchant,
                  it.category, it.note, it.source].map(escape).join(","));
    }
    const blob = new Blob(["﻿" + lines.join("\n")], { type: "text/csv" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `expenses-${viewKey()}.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  /* ---------------------------------------------------------------- 表單 -- */

  const field = (name) => form.querySelector(`[name="${name}"]`);
  const chipBox = document.getElementById("exp-chips");

  function renderChips(selected) {
    // 固定分類 + 自訂分類 +（不在清單裡的當前選擇，例如編輯舊紀錄時）
    const all = [...CATEGORIES, ...customCats()];
    if (selected && !all.includes(selected)) all.push(selected);
    chipBox.innerHTML = all.map((cat) =>
      `<button type="button" class="exp-chip${cat === selected ? " on" : ""}" data-cat="${esc(cat)}">${esc(cat)}</button>`
    ).join("") +
      '<button type="button" class="exp-chip exp-chip-add" data-add-cat>＋自訂</button>';
    for (const chip of chipBox.querySelectorAll("[data-cat]")) {
      chip.addEventListener("click", () => {
        field("category").value = chip.dataset.cat;
        renderChips(chip.dataset.cat);
      });
    }
    chipBox.querySelector("[data-add-cat]").addEventListener("click", () => {
      const name = (prompt("新分類名稱（例：寵物、健身）") || "").trim().slice(0, 20);
      if (!name) return;
      if (![...CATEGORIES, ...customCats()].includes(name)) addCustomCat(name);
      field("category").value = name;
      renderChips(name);
    });
  }

  const todayStr = () => {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  };

  function resetForm() {
    editingId = null;
    form.reset();
    field("date").value = todayStr();
    field("category").value = "未分類";
    renderChips("未分類");
    form.querySelector("[data-submit]").textContent = "記一筆";
    form.querySelector("[data-cancel]").hidden = true;
  }

  function startEdit(id) {
    const it = items.find((x) => x.id === id);
    if (!it) return;
    editingId = id;
    field("amount").value = it.amount;
    field("merchant").value = it.merchant;
    field("note").value = it.note;
    field("category").value = it.category || "未分類";
    field("date").value = it.spent_at.slice(0, 10);
    renderChips(it.category || "未分類");
    form.querySelector("[data-submit]").textContent = "儲存修改";
    form.querySelector("[data-cancel]").hidden = false;
    form.scrollIntoView({ behavior: "smooth", block: "center" });
    field("amount").focus();
  }

  function removeItem(id) {
    const it = items.find((x) => x.id === id);
    if (!it) return;
    if (!confirm(`刪掉這筆「${it.merchant || "未填商家"} ${money(it.amount, it.currency)}」？`)) return;
    items = items.filter((x) => x.id !== id);
    dirty.delete(id);
    tombs.add(id);
    if (editingId === id) resetForm();
    persist();
    render();
    scheduleSync();
  }

  // 商家欄失焦時，分類還是未分類就照關鍵字猜一個——猜錯點一下就改。
  field("merchant").addEventListener("blur", () => {
    if (field("category").value !== "未分類" || editingId) return;
    const guess = guessCategory(field("merchant").value);
    if (guess) {
      field("category").value = guess;
      renderChips(guess);
    }
  });

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const amount = Math.abs(Number(field("amount").value));
    if (!amount || !Number.isFinite(amount)) { field("amount").focus(); return; }

    const dateStr = field("date").value || todayStr();
    let spentAt;
    if (dateStr === todayStr()) {
      spentAt = new Date().toISOString();          // 今天 → 保留當下時刻
    } else {
      spentAt = new Date(dateStr + "T12:00:00").toISOString();
    }

    if (editingId) {
      const it = items.find((x) => x.id === editingId);
      if (it) {
        it.amount = amount;
        it.merchant = field("merchant").value.trim();
        it.category = field("category").value || "未分類";
        it.note = field("note").value.trim();
        it.spent_at = spentAt;
        dirty.add(it.id);
      }
    } else {
      const it = {
        id: uuid(), amount, currency: "TWD",
        merchant: field("merchant").value.trim(),
        category: field("category").value || "未分類",
        note: field("note").value.trim(),
        source: "manual", spent_at: spentAt,
      };
      items.unshift(it);
      dirty.add(it.id);
    }
    persist();
    resetForm();
    render();
    scheduleSync();
  });

  form.querySelector("[data-cancel]").addEventListener("click", resetForm);

  /* --------------------------------------------------------- 同步狀態列 -- */

  function renderStatus() {
    const box = document.getElementById("exp-status");
    if (!box) return;
    if (!CONF) {
      box.textContent = "純本機模式：資料只存在這台裝置的瀏覽器。";
      return;
    }
    if (!session()) {
      box.textContent = "未登入：資料只存在這台裝置。登入後自動跨裝置同步，並可開啟 Apple Pay 自動記帳。";
      return;
    }
    if (syncError) {
      box.textContent = `雲端同步失敗（${syncError}），資料仍在本機，稍後會自動重試。`;
      return;
    }
    box.textContent = lastSync
      ? `已登入，雲端同步於 ${lastSync.toLocaleTimeString("zh-TW", { hour12: false })}`
      : "已登入，同步中…";
  }

  /* --------------------------------------------- 自動記帳（token 管理） -- */

  async function renderTokens() {
    const box = document.getElementById("exp-token");
    if (!box) return;
    if (!CONF) {
      box.innerHTML = '<p class="muted">Supabase 未開通，自動記帳無法使用。</p>';
      return;
    }
    if (!session()) {
      box.innerHTML = '<p class="muted">先在上方登入（或註冊）帳號，'
        + '這裡就會出現你的專屬金鑰與設定教學。</p>';
      return;
    }
    box.innerHTML = '<p class="muted">載入中…</p>';
    let tokens;
    try {
      tokens = await rest("GET", "/expense_tokens?select=token,label,created_at&order=created_at.desc");
    } catch (error) {
      // PostgREST 對不存在的資料表回 404——代表建表 SQL 還沒執行
      if (/404/.test(String(error.message))) {
        box.innerHTML = '<p class="muted"><strong>資料表還沒建立</strong>，'
          + "所以讀不到金鑰。到 Supabase 儀表板 → SQL Editor，貼上 "
          + "repo 裡 tools/expense_schema.sql 的內容按 Run（結果顯示 "
          + "Success. No rows returned 就是成功），完成後回來重新整理這一頁。"
          + "若你有多個 Supabase 專案，要在「這個網站用的那個」執行。</p>";
        return;
      }
      box.innerHTML = `<p class="muted">讀取金鑰失敗（${esc(error.message)}），`
        + "稍後重新整理再試。</p>";
      return;
    }

    const endpoint = location.origin + "/api/expense";
    let html = "";
    if (!tokens.length) {
      html += '<p>還沒有金鑰。按下面的按鈕產生一組，貼進 iOS 捷徑就能自動記帳。</p>';
    } else {
      html += tokens.map((t) =>
        `<div class="exp-token-row"><code>${esc(t.token)}</code>` +
        `<button type="button" class="exp-copy" data-copy="${esc(t.token)}">複製</button>` +
        `<button type="button" class="exp-revoke" data-revoke="${esc(t.token)}">撤銷</button></div>`
      ).join("");
      const first = tokens[0].token;
      html += `<p class="exp-token-hint">捷徑「取得 URL 內容」的設定：URL 填 `
        + `<code>${esc(endpoint)}</code>、方法 POST、請求本文 JSON。</p>`
        + `<p class="exp-token-hint">Apple Pay 自動記帳（「交易」自動化）的欄位——`
        + `<code>token</code> 填上面的金鑰，其餘選捷徑提供的變數：</p>`
        + `<pre class="exp-json">{\n  "token": "${esc(first)}",\n  "amount": 快速指令輸入 › 金額,\n  "merchant": 快速指令輸入 › 商家,\n  "card": 快速指令輸入 › 卡片\n}</pre>`
        + `<p class="exp-token-hint">快速記帳捷徑（LINE Pay、現金）的欄位——`
        + `金額與商家選「要求輸入」的結果：</p>`
        + `<pre class="exp-json">{\n  "token": "${esc(first)}",\n  "amount": 要求輸入 › 金額,\n  "merchant": 要求輸入 › 商家,\n  "source": "manual",\n  "note": "LINE Pay"\n}</pre>`;
    }
    html += '<button type="button" class="exp-gen" data-gen>產生新金鑰</button>';
    box.innerHTML = html;

    for (const btn of box.querySelectorAll("[data-copy]")) {
      btn.addEventListener("click", async () => {
        try {
          await navigator.clipboard.writeText(btn.dataset.copy);
          btn.textContent = "已複製";
          setTimeout(() => { btn.textContent = "複製"; }, 1500);
        } catch {}
      });
    }
    for (const btn of box.querySelectorAll("[data-revoke]")) {
      btn.addEventListener("click", async () => {
        if (!confirm("撤銷後，用這組金鑰的捷徑會立刻失效。確定？")) return;
        try {
          await rest("DELETE",
            "/expense_tokens?token=eq." + encodeURIComponent(btn.dataset.revoke),
            null, "return=minimal");
        } catch {}
        renderTokens();
      });
    }
    box.querySelector("[data-gen]").addEventListener("click", async () => {
      const bytes = crypto.getRandomValues(new Uint8Array(24));
      const token = [...bytes].map((b) => b.toString(16).padStart(2, "0")).join("");
      try {
        await rest("POST", "/expense_tokens",
                   { token, user_id: session().uid, label: "iOS 捷徑" },
                   "return=minimal");
      } catch (error) {
        alert("產生失敗：" + error.message);
      }
      renderTokens();
    });
  }

  /* ----------------------------------------------------------------- 起動 -- */

  function render() {
    renderSummary();
    renderList();
    renderStatus();
  }

  resetForm();
  render();
  renderTokens();
  if (session()) syncNow();
})();
