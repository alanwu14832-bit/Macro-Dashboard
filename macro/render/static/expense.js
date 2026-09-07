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
 *   - 掃描：電子發票的 QR 直接解出金額、日期、品項與賣方統編；商品條碼
 *     查品名並記住上次價格。解碼在裝置上做，只有店名／品名查詢打 /api/lookup。
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
    "相機": "var(--series-9)", "吉他": "var(--series-10)",
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

  // 付款方式：手動記帳預設現金（會手動記的多半是現金），可自訂。
  const PAY_METHODS = ["現金", "LINE Pay", "刷卡", "轉帳"];
  const CUSTOM_PAY_KEY = "exp-custom-pays";

  // 卡片存成「刷卡（凱基銀行）」——跟 Apple Pay 自動記帳寫進來的
  // 「Apple Pay（凱基銀行）」同一個格式。沿用既有慣例就不必動資料庫，
  // 也不必為了一個欄位再寫一套同步退回邏輯。
  const cardOf = (pay) => {
    const m = String(pay || "").match(/^(.+)（(.+)）$/);
    return m ? m[2] : "";
  };
  const baseMethod = (pay) => String(pay || "").replace(/（.+）$/, "");
  const withCard = (base, card) => (card ? `${base}（${card}）` : base);

  // 只有這兩種付款方式需要問「哪一張卡」：現金、轉帳、LINE Pay 自己就講完了。
  // 收 Apple Pay 是為了讓捷徑抓錯卡名時能在編輯畫面改掉。
  const CARD_METHODS = new Set(["刷卡", "Apple Pay"]);

  const customPays = () => {
    const stored = loadJson(CUSTOM_PAY_KEY, []);
    // 取 base：不然「刷卡（凱基銀行）」會被當成一個新的付款方式跑進 chips
    const fromItems = items.map((it) => baseMethod(it.pay))
      .filter((pay) => pay && !PAY_METHODS.includes(pay) && !/^Apple /.test(pay));
    return [...new Set([...stored, ...fromItems])];
  };
  const CARD_KEY = "exp-cards";
  const LAST_CARD_KEY = "exp-last-card";
  const knownCards = () => {
    const stored = loadJson(CARD_KEY, []);
    const fromItems = items
      .map((it) => cardOf(it.pay) || cardOf(payMethod(it)))
      .filter(Boolean);
    return [...new Set([...stored, ...fromItems])];
  };
  const addCard = (name) => {
    const stored = loadJson(CARD_KEY, []);
    if (!stored.includes(name)) saveJson(CARD_KEY, [...stored, name]);
  };

  const addCustomPay = (name) => {
    const stored = loadJson(CUSTOM_PAY_KEY, []);
    if (!stored.includes(name)) saveJson(CUSTOM_PAY_KEY, [...stored, name]);
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

  /* ------------------------------------------------------- 自然語言解析 -- */

  // 規則式解析，不呼叫任何 AI——記帳的句子結構固定（日期、商家、金額、
  // 付款方式），規則比模型穩定、離線可用、零延遲。解析結果一律填回表單
  // 讓使用者確認後才送出，猜錯的成本只是改一個欄位。
  const REL_DAYS = { "今天": 0, "今日": 0, "昨天": -1, "昨日": -1, "前天": -2, "大前天": -3 };

  function parseNatural(text) {
    let rest = ` ${String(text).trim()} `;
    const out = {};

    // 日期：相對詞 → M/D 或 M月D日
    for (const [word, offset] of Object.entries(REL_DAYS)) {
      if (rest.includes(word)) {
        const d = new Date();
        d.setDate(d.getDate() + offset);
        out.date = d;
        rest = rest.replace(word, " ");
        break;
      }
    }
    if (!out.date) {
      const md = rest.match(/(\d{1,2})\s*[\/月]\s*(\d{1,2})\s*日?/);
      if (md) {
        const today = new Date();
        const d = new Date(today.getFullYear(), Number(md[1]) - 1, Number(md[2]), 12);
        // 日期比今天晚很多 → 當作去年的（12 月底記 1 月的帳很少見）
        if (d - today > 7 * 86400e3) d.setFullYear(d.getFullYear() - 1);
        out.date = d;
        rest = rest.replace(md[0], " ");
      }
    }

    // 付款方式：先比對已知的（含自訂），命中就從字串移除
    const known = [...PAY_METHODS, ...customPays(), "apple pay", "applepay",
                   "悠遊卡", "一卡通", "街口", "信用卡"];
    for (const name of known) {
      const idx = rest.toLowerCase().indexOf(name.toLowerCase());
      if (idx >= 0) {
        const canonical = { "apple pay": "Apple Pay", "applepay": "Apple Pay",
                            "信用卡": "刷卡" }[name.toLowerCase()] || name;
        out.pay = canonical;
        rest = rest.slice(0, idx) + " " + rest.slice(idx + name.length);
        break;
      }
    }

    // 金額：帶錢字樣的優先（120元、$120），否則取最後一個獨立數字
    const withUnit = rest.match(/(?:\$|NT\$?)?\s*(\d+(?:\.\d+)?)\s*(?:元|塊|圓)/i);
    if (withUnit) {
      out.amount = Number(withUnit[1]);
      rest = rest.replace(withUnit[0], " ");
    } else {
      const nums = [...rest.matchAll(/(?:\$|NT\$)?\s*(\d+(?:\.\d+)?)/gi)];
      if (nums.length) {
        const last = nums[nums.length - 1];
        out.amount = Number(last[1]);
        rest = rest.slice(0, last.index) + " " + rest.slice(last.index + last[0].length);
      }
    }

    // 剩下的就是商家／品項；分類照既有規則猜
    out.merchant = rest.replace(/\s+/g, " ").trim().slice(0, 120);
    const guess = guessCategory(out.merchant);
    if (guess) out.category = guess;
    return out;
  }

  /* ------------------------------------------------------------ 照片壓縮 -- */

  // 收據只要看得懂金額，不需要原始解析度：長邊縮到 1200、JPEG 0.55，
  // 一張約 60–120KB。太大的圖同步會拖慢、也吃 localStorage。
  function compressImage(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onerror = () => reject(new Error("讀取失敗"));
      reader.onload = () => {
        const img = new Image();
        img.onerror = () => reject(new Error("不是有效的圖片"));
        img.onload = () => {
          const scale = Math.min(1, 1200 / Math.max(img.width, img.height));
          const canvas = document.createElement("canvas");
          canvas.width = Math.round(img.width * scale);
          canvas.height = Math.round(img.height * scale);
          canvas.getContext("2d").drawImage(img, 0, 0, canvas.width, canvas.height);
          resolve(canvas.toDataURL("image/jpeg", 0.55));
        };
        img.src = reader.result;
      };
      reader.readAsDataURL(file);
    });
  }

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

  // 預算：{ "": 每月總預算, "餐飲": 3000, … }。空字串鍵是總預算。
  const BUDGET_KEY = "exp-budgets";
  let budgets = loadJson(BUDGET_KEY, {});
  let budgetsDirty = loadJson(BUDGET_KEY + "-dirty", false);
  const persistBudgets = () => {
    saveJson(BUDGET_KEY, budgets);
    saveJson(BUDGET_KEY + "-dirty", budgetsDirty);
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
    if (!response.ok) {
      // 錯誤內文要帶出來：欄位缺失的退回邏輯靠它分辨少的是哪個欄位
      const detail = await response.text().catch(() => "");
      throw new Error("HTTP " + response.status + " " + detail.slice(0, 300));
    }
    return method === "GET" ? response.json() : null;
  }

  /* ----------------------------------------------------------------- sync -- */

  let syncTimer = null;
  let lastSync = null;   // Date | null
  let syncError = "";
  // pay_method 欄位是後來加的：資料庫還沒跑 migration 時（400），
  // 自動退回不帶這個欄位的同步,付款方式先只存本機,不擋整個同步。
  let hasPayColumn = true;
  // 照片同理：photo 欄位存 data URL，但列表同步只抓 has_photo（產生欄位），
  // 照片本體等使用者點開那筆才取——否則每次同步都要拖幾 MB。
  let hasPhotoColumn = true;

  /** 從 PostgREST 的 400 錯誤挑出「哪個欄位不存在」，只關掉那一個。
      回傳 true 代表這個錯誤已被辨識、呼叫端可以退回重試。 */
  function dropMissingColumns(error) {
    const message = String(error && error.message);
    if (!/400/.test(message)) return false;
    let matched = false;
    if (/pay_method/.test(message)) { hasPayColumn = false; matched = true; }
    if (/\bphoto\b|has_photo/.test(message)) { hasPhotoColumn = false; matched = true; }
    if (!matched && /does not exist|42703|PGRST20[0-9]/.test(message)) {
      // 認得出是欄位問題但認不出是哪個 → 保守地兩個都關
      hasPayColumn = false;
      hasPhotoColumn = false;
      matched = true;
    }
    return matched;
  }

  async function syncNow() {
    if (!CONF || !session()) return;
    try {
      const uid = session().uid;
      if (dirty.size) {
        const rows = items.filter((it) => dirty.has(it.id)).map((it) => ({
          id: it.id, user_id: uid, amount: it.amount, currency: it.currency,
          merchant: it.merchant, category: it.category, note: it.note,
          source: it.source, spent_at: it.spent_at,
          ...(hasPayColumn ? { pay_method: it.pay || "" } : {}),
          ...(hasPhotoColumn && it.photo !== undefined ? { photo: it.photo || "" } : {}),
        }));
        if (rows.length) {
          try {
            await rest("POST", "/expenses?on_conflict=id", rows,
                       "resolution=merge-duplicates,return=minimal");
          } catch (error) {
            if (!dropMissingColumns(error)) throw error;
            // 只拿掉真的不存在的欄位——某個欄位缺席不該連累另一個
            await rest("POST", "/expenses?on_conflict=id", rows.map((row) => {
              const copy = { ...row };
              if (!hasPayColumn) delete copy.pay_method;
              if (!hasPhotoColumn) delete copy.photo;
              return copy;
            }), "resolution=merge-duplicates,return=minimal");
          }
        }
        dirty.clear();
      }
      if (tombs.size) {
        const ids = [...tombs].join(",");
        await rest("DELETE", "/expenses?id=in.(" + ids + ")", null,
                   "return=minimal");
        tombs.clear();
      }
      const baseSelect = "id,amount,currency,merchant,category,note,source,spent_at";
      let cloud;
      try {
        cloud = await rest("GET",
          "/expenses?select=" + baseSelect + (hasPayColumn ? ",pay_method" : "")
          + (hasPhotoColumn ? ",has_photo" : "")
          + "&order=spent_at.desc&limit=5000");
      } catch (error) {
        if (!dropMissingColumns(error)) throw error;
        cloud = await rest("GET",
          "/expenses?select=" + baseSelect + (hasPayColumn ? ",pay_method" : "")
          + (hasPhotoColumn ? ",has_photo" : "")
          + "&order=spent_at.desc&limit=5000");
      }
      // 照片本體不隨列表下載：雲端有照片就記 hasPhoto，點開才抓。
      // 本機還沒同步上去的照片（photo 有值）要保留，否則會被覆蓋掉。
      const localPhotos = new Map(items.filter((it) => it.photo)
        .map((it) => [it.id, it.photo]));
      items = cloud.map((row) => ({
        id: row.id, amount: Number(row.amount), currency: row.currency,
        merchant: row.merchant, category: row.category, note: row.note,
        source: row.source, spent_at: row.spent_at,
        pay: row.pay_method || "",
        hasPhoto: !!row.has_photo || localPhotos.has(row.id),
      }));
      await syncBudgets();
      lastSync = new Date();
      syncError = "";
      persist();
      render();
    } catch (error) {
      syncError = String(error.message || error);
      renderStatus();
    }
  }

  // 預算資料量小（一個分類一列），改過就整份覆寫，不做逐列 diff。
  let hasBudgetTable = true;
  async function syncBudgets() {
    if (!hasBudgetTable) return;
    const uid = session().uid;
    try {
      if (budgetsDirty) {
        const rows = Object.entries(budgets)
          .filter(([, amount]) => Number(amount) > 0)
          .map(([category, amount]) => ({ user_id: uid, category, amount }));
        await rest("DELETE", "/expense_budgets?user_id=eq." + uid, null, "return=minimal");
        if (rows.length) {
          await rest("POST", "/expense_budgets", rows, "return=minimal");
        }
        budgetsDirty = false;
      }
      const cloud = await rest("GET", "/expense_budgets?select=category,amount");
      budgets = Object.fromEntries(cloud.map((row) => [row.category, Number(row.amount)]));
      persistBudgets();
    } catch (error) {
      // 資料表還沒建（migration 未跑）→ 預算先只存本機，不擋主同步
      if (/40[04]/.test(String(error.message))) hasBudgetTable = false;
      else throw error;
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

  /* -------------------------------------------------------------- 總覽頁 -- */

  // Hero 是這個 App 的頭條：本月花了多少。其餘（筆數、日均、預算剩餘）
  // 是支撐數字，放在同一張卡的下緣，不另開卡片搶注意力。
  function renderHome() {
    const all = items.filter(inView);
    const rows = all.filter((it) => it.currency === "TWD" || !it.currency);
    const total = rows.reduce((sum, it) => sum + it.amount, 0);

    const prev = new Date(viewYear, viewMonth - 1, 1);
    const prevTotal = items
      .filter((it) => monthKey(new Date(it.spent_at)) === monthKey(prev))
      .filter((it) => it.currency === "TWD" || !it.currency)
      .reduce((sum, it) => sum + it.amount, 0);
    const isCurrent = viewKey() === monthKey(today);
    const daysElapsed = isCurrent ? today.getDate()
      : new Date(viewYear, viewMonth + 1, 0).getDate();

    const setText = (id, text) => {
      const node = document.getElementById(id);
      if (node) node.textContent = text;
    };
    setText("hero-amount", money(total, "TWD"));
    setText("hero-count", String(all.length));
    setText("hero-daily", money(daysElapsed ? total / daysElapsed : 0, "TWD"));

    const limit = Number(budgets[""]) || 0;
    setText("hero-budget", limit ? money(limit - total, "TWD") : "未設定");

    const delta = document.getElementById("hero-delta");
    if (delta) {
      if (prevTotal) {
        // 上個月只記了幾筆時，百分比會變成「多 1481%」這種沒有資訊量的數字。
        // 超過 3 倍就改講金額差，讀者要的是「差多少錢」不是「差幾趴」。
        const pct = ((total - prevTotal) / prevTotal) * 100;
        const up = pct >= 0;
        const arrow = up ? "▲" : "▼";
        const word = up ? "多" : "少";
        delta.textContent = Math.abs(pct) > 300
          ? `${arrow} 比上月${word} ${money(Math.abs(total - prevTotal), "TWD")}`
          : `${arrow} 比上月${word} ${Math.abs(pct).toFixed(0)}%`;
        delta.hidden = false;
      } else {
        delta.hidden = true;
      }
    }

    renderCharts(rows);
    renderRecent(all);
  }

  // 兩張圓餅圖問的是同一筆錢的兩個問題（花在什麼、用什麼付），
  // 疊成兩張卡會把「最近紀錄」擠到螢幕外兩頁遠。合成一張卡、上面切換，
  // 中間的合計也不用重複寫兩次。
  let chartTab = "cat";

  function renderCharts(rows) {
    const box = document.getElementById("exp-charts");
    if (!box) return;
    if (!rows.length) {
      box.innerHTML = '<div class="card"><div class="empty">'
        + `<div class="empty-mark" aria-hidden="true">${ICON.receipt}</div>`
        + '<div class="empty-title">這個月還沒有紀錄</div>'
        + '<div class="empty-note">按下方的＋記第一筆，或設定好自動記帳後刷一次 Apple Pay。</div>'
        + "</div></div>";
      return;
    }
    const byCat = new Map();
    const byPay = new Map();
    for (const it of rows) {
      const cat = it.category || "未分類";
      byCat.set(cat, (byCat.get(cat) || 0) + it.amount);
      const method = payMethod(it);
      byPay.set(method, (byPay.get(method) || 0) + it.amount);
    }

    const panes = [
      ["cat", "花費分類", donut(byCat, (name) => CAT_COLOR[name] || fallbackColor(name))],
      ["pay", "支付方式", donut(byPay, payColor, payLabel)],
    ];
    box.innerHTML = '<div class="card">'
      + '<div class="seg" role="tablist">'
      + panes.map(([key, title]) =>
          `<button type="button" class="seg-btn" role="tab" data-seg="${key}"`
          + ` aria-selected="${key === chartTab}">${esc(title)}</button>`).join("")
      + "</div>"
      + panes.map(([key, , body]) =>
          `<div data-pane="${key}"${key === chartTab ? "" : " hidden"}>${body}</div>`).join("")
      + "</div>";

    for (const btn of box.querySelectorAll("[data-seg]")) {
      btn.addEventListener("click", () => {
        chartTab = btn.dataset.seg;
        for (const other of box.querySelectorAll("[data-seg]")) {
          other.setAttribute("aria-selected", String(other.dataset.seg === chartTab));
        }
        for (const pane of box.querySelectorAll("[data-pane]")) {
          pane.hidden = pane.dataset.pane !== chartTab;
        }
      });
    }
  }

  // 總覽只放最近 5 筆——它的任務是「有沒有漏記」，完整明細在明細頁。
  function renderRecent(all) {
    const box = document.getElementById("exp-recent");
    if (!box) return;
    const rows = [...all].sort((a, b) => new Date(b.spent_at) - new Date(a.spent_at)).slice(0, 5);
    if (!rows.length) {
      box.innerHTML = '<p class="muted">這個月還沒有紀錄。</p>';
      return;
    }
    box.innerHTML = '<div class="rows">' + rows.map((it) => itemRow(it, true)).join("") + "</div>";
    bindRows(box);
  }

  /* --------------------------------------------------------- 甜甜圈圖 -- */

  // 從每筆紀錄推付款方式：Apple Pay 自動記帳的備註帶卡片名、
  // 快速記帳標 LINE Pay、蝦皮貨到付款算現金、收據匯入是帳號扣款。
  function payMethod(it) {
    if (it.pay) return it.pay;             // 明確標了就用標的（表單或 API 的 pay 欄位）
    const note = it.note || "";
    if (/line\s*pay/i.test(note)) return "LINE Pay";
    if (/貨到付款|現金/.test(note)) return "現金";
    if (it.source === "applepay") {
      const wrapped = note.match(/（([^）]+)）$/);
      const card = (wrapped ? wrapped[1] : note).trim();
      return withCard("Apple Pay", card);
    }
    if (/Apple 收據/.test(note)) return "Apple 帳號扣款";
    if (/foodpanda|蝦皮/.test(note)) return "線上付款";
    return "未標付款方式";
  }

  // 付款方式的固定配色（顏色跟著身份走，不跟著排名走）；
  // Apple Pay 的各張卡照名稱排序穩定分到剩下的色槽。
  const PAY_COLOR = {
    "LINE Pay": "var(--series-6)", "現金": "var(--series-4)",
    "刷卡": "var(--series-2)", "轉帳": "var(--series-3)",
    "Apple 帳號扣款": "var(--series-7)", "線上付款": "var(--series-5)",
    "未標付款方式": "var(--neutral)", "其他項目": "var(--neutral)",
  };
  function payColor(name) {
    // 每張卡自己一個色槽。先前所有 Apple Pay 共用同一支藍，兩張卡在圓餅圖
    // 上是同一個顏色——圖例分得出來、圖本身分不出來，那張圖就白畫了。
    if (cardOf(name)) return fallbackColor(name);
    return PAY_COLOR[name] || fallbackColor(name);
  }

  function rowPay(it) {
    const name = payMethod(it);
    if (name === "未標付款方式") return "";
    // 有卡就只寫卡名：一列裡「刷了哪張卡」才是資訊，
    // 「刷卡」兩個字從卡名就推得出來，寫了只是佔掉會被截斷的寬度。
    const card = cardOf(name);
    if (card) return card;
    if (name === "Apple 帳號扣款") return "Apple 扣款";
    return name;
  }

  // 圖例只有一行寬度，「Apple Pay（凱基）」與「刷卡（國泰世華）」
  // 會雙雙被方式的字樣吃掉——把識別度最高的卡名放前面。
  function payLabel(name) {
    const card = cardOf(name);
    if (card) {
      const base = baseMethod(name);
      return `${card}・${base === "Apple Pay" ? "Pay" : base}`;
    }
    if (name === "未標付款方式") return "未標註";
    return name;
  }

  // 自訂分類沒有固定色：拿名稱做穩定雜湊分到色槽，同名永遠同色。
  function fallbackColor(name) {
    let hash = 0;
    for (const ch of String(name)) hash = (hash * 31 + ch.codePointAt(0)) >>> 0;
    return `var(--series-${(hash % 10) + 1})`;
  }

  function donut(byName, colorOf, labelOf) {
    const label = labelOf || ((name) => name);
    let entries = [...byName.entries()].sort((a, b) => b[1] - a[1]);
    const total = entries.reduce((sum, [, amount]) => sum + amount, 0);
    if (!total) return "";
    if (entries.length > 6) {
      const rest = entries.slice(5).reduce((sum, [, amount]) => sum + amount, 0);
      entries = [...entries.slice(0, 5), ["其他項目", rest]];
    }

    const R = 50, W = 18, SIZE = 142, C = 2 * Math.PI * R;
    const gap = entries.length > 1 ? 2 : 0;     // 片與片之間留 2px 底色
    let offset = 0;
    const slices = entries.map(([name, amount]) => {
      const len = (amount / total) * C;
      const dash = Math.max(len - gap, 0.5);
      const color = name === "其他項目" ? "var(--neutral)" : colorOf(name);
      const pct = ((amount / total) * 100).toFixed(0);
      const circle =
        `<circle r="${R}" cx="${SIZE / 2}" cy="${SIZE / 2}" fill="none"` +
        ` stroke="${color}" stroke-width="${W}"` +
        ` stroke-dasharray="${dash} ${C - dash}" stroke-dashoffset="${-offset}">` +
        `<title>${esc(name)}：${esc(money(amount, "TWD"))}（${pct}%）</title></circle>`;
      offset += len;
      return circle;
    }).join("");

    const legend = entries.map(([name, amount]) => {
      const color = name === "其他項目" ? "var(--neutral)" : colorOf(name);
      const pct = ((amount / total) * 100).toFixed(0);
      return `<div class="legend-row">` +
        `<span class="dot" style="background:${color}" aria-hidden="true"></span>` +
        `<span class="legend-name" title="${esc(name)}">${esc(label(name))}</span>` +
        `<span class="legend-amt">${esc(money(amount, "TWD"))}<em> ${pct}%</em></span></div>`;
    }).join("");

    return `<div class="pie-body">` +
      `<svg viewBox="0 0 ${SIZE} ${SIZE}" width="${SIZE}" height="${SIZE}" role="img">` +
      `<g transform="rotate(-90 ${SIZE / 2} ${SIZE / 2})">${slices}</g>` +
      `<text x="${SIZE / 2}" y="${SIZE / 2 - 3}" text-anchor="middle" class="pie-total">${esc(money(total, "TWD"))}</text>` +
      `<text x="${SIZE / 2}" y="${SIZE / 2 + 14}" text-anchor="middle" class="pie-sub">合計</text>` +
      `</svg>` +
      `<div class="legend">${legend}</div></div>`;
  }

  /* ---------------------------------------------------------------- 預算 -- */

  // 進度條顏色是狀態不是身份：安全→中性、接近上限→警示、超支→嚴重，
  // 三者都配文字（剩餘／超支金額），不靠顏色單獨表意。
  function budgetState(spent, limit) {
    if (!limit) return "none";
    const ratio = spent / limit;
    if (ratio > 1) return "over";
    if (ratio >= 0.85) return "warn";
    return "ok";
  }

  function renderBudget() {
    const box = document.getElementById("exp-budget");
    if (!box) return;
    const rows = items.filter(inView).filter((it) => it.currency === "TWD" || !it.currency);
    const total = rows.reduce((sum, it) => sum + it.amount, 0);
    const spentByCat = new Map();
    for (const it of rows) {
      const cat = it.category || "未分類";
      spentByCat.set(cat, (spentByCat.get(cat) || 0) + it.amount);
    }

    const bar = (label, spent, limit) => {
      const state = budgetState(spent, limit);
      const pct = limit ? Math.min((spent / limit) * 100, 100) : 0;
      const left = limit - spent;
      const note = !limit ? "未設定"
        : left >= 0 ? `剩 ${money(left, "TWD")}`
        : `超支 ${money(-left, "TWD")}`;
      const key = label === "每月總預算" ? "" : label;
      return `<div class="budget-row">` +
        `<div class="budget-head"><span class="budget-name">${esc(label)}</span>` +
        `<span class="budget-note b-${state}">${esc(note)}</span></div>` +
        `<span class="budget-bar"><i class="b-${state}" style="width:${pct}%"></i></span>` +
        `<div class="budget-foot">${esc(money(spent, "TWD"))}` +
        (limit ? ` / ${esc(money(limit, "TWD"))}` : "") +
        `<button type="button" class="budget-set" data-set-budget="${esc(key)}">` +
        (limit ? "改預算" : "設預算") + `</button></div></div>`;
    };

    let html = bar("每月總預算", total, Number(budgets[""]) || 0);
    const catKeys = Object.keys(budgets).filter((k) => k && Number(budgets[k]) > 0)
      .sort((a, b) => (spentByCat.get(b) || 0) - (spentByCat.get(a) || 0));
    html += catKeys.map((cat) => bar(cat, spentByCat.get(cat) || 0, Number(budgets[cat]))).join("");

    const available = [...new Set([...CATEGORIES, ...customCats()])]
      .filter((cat) => !catKeys.includes(cat));
    html += '<select class="budget-pick" id="exp-budget-pick">'
      + '<option value="">＋ 為分類設預算…</option>'
      + available.map((cat) => `<option value="${esc(cat)}">${esc(cat)}</option>`).join("")
      + "</select>";
    if (!hasBudgetTable) {
      html += '<p class="note">預算目前只存在這台裝置：資料表尚未建立，'
        + "到 Supabase 執行 expense_schema.sql 後就會跨裝置同步。</p>";
    }
    box.innerHTML = html;

    const ask = (cat) => {
      const label = cat || "每月總預算";
      const current = Number(budgets[cat]) || "";
      const input = prompt(`${label}的預算金額（留白或 0 取消預算）`, current);
      if (input === null) return;
      const amount = Math.abs(Number(String(input).replace(/[^0-9.]/g, "")));
      if (amount > 0) budgets[cat] = amount;
      else delete budgets[cat];
      budgetsDirty = true;
      persistBudgets();
      renderBudget();
      renderHome();
      scheduleSync();
    };
    for (const btn of box.querySelectorAll("[data-set-budget]")) {
      btn.addEventListener("click", () => ask(btn.dataset.setBudget));
    }
    const pick = box.querySelector("#exp-budget-pick");
    if (pick) pick.addEventListener("change", () => { if (pick.value) ask(pick.value); });
  }

  /* ---------------------------------------------------------------- 明細 -- */

  // 一列的樣子：分類色的淡底圓形當頭像（放商家首字）、商家＋分類/付款、
  // 金額、操作。頭像讓長列表能靠顏色掃讀，但用淡底而不是整塊填色——
  // 一排實心色塊會蓋過宋體的調性，也會跟圓餅圖搶顏色的注意力。
  const svg = (d, extra) =>
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"'
    + ' stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
    + (extra || "") + `<path d="${d}"/></svg>`;
  const ICON = {
    photo: svg("M4 8.5A1.5 1.5 0 0 1 5.5 7h2L9 5h6l1.5 2h2A1.5 1.5 0 0 1 20 8.5v8A1.5 1.5 0 0 1 18.5 18h-13A1.5 1.5 0 0 1 4 16.5z",
               '<circle cx="12" cy="12.3" r="3.2"/>'),
    edit: svg("M4 20h4L19 9a2.1 2.1 0 0 0-3-3L5 17v3M14.5 7.5l2 2"),
    del: svg("M6 6l12 12M18 6 6 18"),
    receipt: svg("M6 3.5h12v17l-2.4-1.6-2.4 1.6-2.4-1.6-2.4 1.6-2.4-1.6zM9.5 8.5h5M9.5 12.5h5"),
    calendar: svg("M4 7.5a1.5 1.5 0 0 1 1.5-1.5h13A1.5 1.5 0 0 1 20 7.5v11a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 4 18.5zM4 10.5h16M8.5 3.5v5M15.5 3.5v5"),
  };

  /* ------------------------------------------------------------ 待補篩選 -- */

  // 兩個「洞」：分類沒填、付款方式推不出來。這兩件事只能人工補
  // （自動管道都會帶自己的標記），所以它們是待辦事項，不是一般的篩選條件。
  const isCatGap = (it) => !it.category || it.category === "未分類";
  const isPayGap = (it) => payMethod(it) === "未標付款方式";

  // 勾選狀態不進 localStorage：這是「現在來清一輪」的暫時模式，
  // 不是使用者對這個 App 的長期偏好，下次打開該回到看全部。
  const gaps = { cat: false, pay: false };

  // 兩個都勾＝「所有需要我處理的」，所以是聯集不是交集。
  // 交集（同時缺兩樣）在真實資料裡幾乎是空集合，那個答案沒有人要。
  const gapOn = () => gaps.cat || gaps.pay;
  const gapHit = (it) => (gaps.cat && isCatGap(it)) || (gaps.pay && isPayGap(it));

  function renderGaps(monthRows) {
    const box = document.getElementById("exp-gaps");
    if (!box) return;
    const catN = monthRows.filter(isCatGap).length;
    const payN = monthRows.filter(isPayGap).length;

    // 沒有洞就整排收起來——它是待辦清單，沒事做的時候不該佔版面。
    // 但正在篩選時一定要留著，否則補完最後一筆時勾選框會在手指下消失。
    if (!catN && !payN && !gapOn()) { box.innerHTML = ""; return; }

    // 數字歸零就停用——但勾著的絕對不能停用：補完最後一筆時，
    // 使用者正需要把勾取消才回得去全部，停用它等於把人鎖在空畫面裡。
    const check = (key, label, count) => {
      const on = gaps[key];
      const dim = !count && !on;
      return `<label class="gap-check" data-on="${on}"${dim ? ' data-empty="true"' : ""}>`
        + `<input type="checkbox" data-gap="${key}"${on ? " checked" : ""}`
        + `${dim ? " disabled" : ""}>`
        + `<span>${esc(label)}</span>`
        + `<span class="gap-count">${count}</span></label>`;
    };

    box.innerHTML =
      '<div class="gaps-head">未分類</div>'
      + '<div class="gaps-row">'
      + check("cat", "花費分類", catN)
      + check("pay", "支付方式", payN)
      + "</div>";

    for (const input of box.querySelectorAll("[data-gap]")) {
      input.addEventListener("change", () => {
        gaps[input.dataset.gap] = input.checked;
        renderList();
      });
    }
  }

  function itemRow(it, compact) {
    const color = CAT_COLOR[it.category] || fallbackColor(it.category || "未分類");
    const name = (it.merchant || "").trim();
    const initial = name ? [...name][0] : "·";
    // 缺的欄位就地標成「待補」——要「一眼看出」，就不能等使用者去勾篩選；
    // 用虛線底線而不是實心徽章，一排徽章會讓列表看起來像錯誤清單。
    const catText = isCatGap(it)
      ? '<em class="gap-mark">未分類</em>' : esc(it.category);
    const payText = isPayGap(it)
      ? '<em class="gap-mark">未標付款</em>' : esc(rowPay(it));
    const sub = [catText, payText].filter(Boolean).join("・");
    // 備註如果只是「（凱基銀行）」這種卡名，上一行已經寫過了——
    // 同一件事寫兩行只會讓列表看起來很吵。
    let note = compact ? "" : (it.note || "").trim();
    if (note && sub.includes(note.replace(/^（|）$/g, ""))) note = "";
    return `<div class="row" data-id="${esc(it.id)}">`
      + `<span class="row-avatar" style="color:${color}" aria-hidden="true">${esc(initial)}</span>`
      + `<span class="row-main">`
      + `<span class="row-title">${esc(name || "（未填商家）")}`
      + (it.source === "applepay" ? '<span class="row-badge">Pay</span>' : "")
      + `</span><span class="row-sub">${sub}</span>`
      + (note ? `<span class="row-note">${esc(note)}</span>` : "")
      + "</span>"
      + `<span class="row-amt">${esc(money(it.amount, it.currency))}</span>`
      + `<span class="row-ops">`
      + (it.photo || it.hasPhoto
         ? `<button type="button" data-photo aria-label="看收據">${ICON.photo}</button>` : "")
      + `<button type="button" data-edit aria-label="編輯">${ICON.edit}</button>`
      + (compact ? "" : `<button type="button" data-del aria-label="刪除">${ICON.del}</button>`)
      + "</span></div>";
  }

  function bindRows(scope) {
    for (const row of scope.querySelectorAll(".row")) {
      const id = row.dataset.id;
      const edit = row.querySelector("[data-edit]");
      if (edit) edit.addEventListener("click", () => startEdit(id));
      const del = row.querySelector("[data-del]");
      if (del) del.addEventListener("click", () => removeItem(id));
      const photoBtn = row.querySelector("[data-photo]");
      if (photoBtn) photoBtn.addEventListener("click", () => showPhoto(id, photoBtn));
    }
  }

  function renderList() {
    const nav = document.getElementById("exp-month-nav");
    const box = document.getElementById("exp-list");
    if (!nav || !box) return;

    nav.innerHTML =
      '<button type="button" class="month-btn" data-nav="-1" aria-label="上一個月">‹</button>' +
      `<span class="month-label">${viewYear} 年 ${viewMonth + 1} 月</span>` +
      '<button type="button" class="month-btn" data-nav="1" aria-label="下一個月">›</button>' +
      '<button type="button" class="pill-btn" data-csv>匯出 CSV</button>';
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

    const monthRows = items.filter(inView)
      .sort((a, b) => new Date(b.spent_at) - new Date(a.spent_at));
    renderGaps(monthRows);

    if (!monthRows.length) {
      box.innerHTML = '<div class="card"><div class="empty">'
        + `<div class="empty-mark" aria-hidden="true">${ICON.calendar}</div>`
        + '<div class="empty-title">這個月沒有紀錄</div>'
        + '<div class="empty-note">按下方的＋記一筆，或切到其他月份看看。</div>'
        + "</div></div>";
      return;
    }

    const rows = gapOn() ? monthRows.filter(gapHit) : monthRows;
    if (!rows.length) {
      box.innerHTML = '<div class="card"><div class="empty">'
        + `<div class="empty-mark" aria-hidden="true">${ICON.receipt}</div>`
        + '<div class="empty-title">這個月沒有待補的紀錄</div>'
        + '<div class="empty-note">取消上面的勾選就能看回全部。</div>'
        + "</div></div>";
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

    // 篩選時日期小計只是「被篩出來那幾筆」的和，不是那天的總花費。
    // 先用一行說清楚下面在看什麼，數字才不會被誤讀。
    let html = gapOn()
      ? `<p class="gap-note">篩選中：${rows.length} 筆待補（共 ${monthRows.length} 筆）</p>`
      : "";
    for (const [day, dayRows] of groups) {
      const d = new Date(day + "T12:00:00");
      const dayTotal = dayRows
        .filter((it) => it.currency === "TWD" || !it.currency)
        .reduce((sum, it) => sum + it.amount, 0);
      html += `<div class="day-head"><span>${d.getMonth() + 1}/${d.getDate()}`
        + `（${weekdays[d.getDay()]}）</span><span>${esc(money(dayTotal, "TWD"))}</span></div>`
        + '<div class="rows">' + dayRows.map((it) => itemRow(it, false)).join("") + "</div>";
    }
    box.innerHTML = html;
    bindRows(box);
  }

  // 照片本體不在列表資料裡：本機有就直接看，否則跟雲端要那一筆的 photo。
  async function showPhoto(id, btn) {
    const it = items.find((x) => x.id === id);
    if (!it) return;
    let src = it.photo;
    if (!src) {
      const before = btn.textContent;
      btn.textContent = "…";
      try {
        const rows = await rest("GET", "/expenses?select=photo&id=eq." + encodeURIComponent(id));
        src = rows[0] && rows[0].photo;
      } catch {}
      btn.textContent = before;
      if (!src) { alert("讀不到這張收據（可能還沒同步上雲端）"); return; }
    }
    const overlay = document.createElement("div");
    overlay.className = "photo-modal";
    overlay.innerHTML = `<img alt="收據照片" src="${esc(src)}">`
      + `<button type="button" class="photo-close" aria-label="關閉">${ICON.del}</button>`;
    overlay.addEventListener("click", () => overlay.remove());
    document.body.appendChild(overlay);
  }

  function exportCsv() {
    const rows = items.filter(inView)
      .sort((a, b) => new Date(a.spent_at) - new Date(b.spent_at));
    const escape = (v) => `"${String(v ?? "").replace(/"/g, '""')}"`;
    const lines = ["date,amount,currency,merchant,category,pay,note,source"];
    for (const it of rows) {
      lines.push([it.spent_at, it.amount, it.currency, it.merchant,
                  it.category, it.pay || "", it.note, it.source].map(escape).join(","));
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
  const payBox = document.getElementById("exp-pay-chips");

  // 付款方式與卡片是同一個值的兩段（存成「刷卡（凱基銀行）」），
  // 所以永遠一起寫、一起重畫，不會出現「選了卡但方式已經換掉」的中間狀態。
  function setPay(base, card) {
    const value = withCard(base, CARD_METHODS.has(base) ? card : "");
    field("pay").value = value;
    if (card) saveJson(LAST_CARD_KEY, card);
    renderPayChips(value);
  }

  function renderPayChips(selected) {
    if (!payBox) return;
    const base = baseMethod(selected) || "現金";
    const card = cardOf(selected);

    const all = [...PAY_METHODS, ...customPays()];
    if (base && !all.includes(base)) all.push(base);
    payBox.innerHTML = all.map((pay) =>
      `<button type="button" class="chip${pay === base ? " on" : ""}" data-pay="${esc(pay)}">${esc(pay)}</button>`
    ).join("") +
      '<button type="button" class="chip chip-add" data-add-pay>＋自訂</button>';

    for (const chip of payBox.querySelectorAll("[data-pay]")) {
      chip.addEventListener("click", () => {
        const next = chip.dataset.pay;
        // 換到需要卡片的方式時，先帶上次刷的那張——多數人反覆刷同一張，
        // 預選對了就是零次點擊，預選錯了也只是再點一下。
        const keep = next === base ? card
          : (knownCards().includes(loadJson(LAST_CARD_KEY, "")) ? loadJson(LAST_CARD_KEY, "") : "");
        setPay(next, keep);
      });
    }
    payBox.querySelector("[data-add-pay]").addEventListener("click", () => {
      const name = (prompt("新付款方式（例：悠遊卡、街口）") || "").trim().slice(0, 20);
      if (!name) return;
      if (![...PAY_METHODS, ...customPays()].includes(name)) addCustomPay(name);
      setPay(name, "");
    });

    renderCardChips(base, card);
  }

  // 卡片只在需要時才出現：現金、轉帳不會有「哪一張卡」這個問題，
  // 永遠攤在那裡只是讓表單看起來比實際複雜。
  function renderCardChips(base, card) {
    const row = document.getElementById("exp-card-row");
    const box = document.getElementById("exp-card-chips");
    if (!row || !box) return;
    if (!CARD_METHODS.has(base)) { row.hidden = true; box.innerHTML = ""; return; }
    row.hidden = false;

    const all = knownCards();
    if (card && !all.includes(card)) all.push(card);
    // 「未指定」放第一個：預選了上次那張卡之後，使用者要有辦法退回不指定。
    box.innerHTML =
      `<button type="button" class="chip${card ? "" : " on"}" data-card="">未指定</button>`
      + all.map((name) =>
          `<button type="button" class="chip${name === card ? " on" : ""}" data-card="${esc(name)}">${esc(name)}</button>`
        ).join("")
      + '<button type="button" class="chip chip-add" data-add-card>＋新增卡片</button>';

    for (const chip of box.querySelectorAll("[data-card]")) {
      chip.addEventListener("click", () => setPay(base, chip.dataset.card));
    }
    box.querySelector("[data-add-card]").addEventListener("click", () => {
      const name = (prompt("卡片名稱（例：凱基銀行、國泰世華）") || "").trim().slice(0, 20);
      if (!name) return;
      addCard(name);
      setPay(base, name);
    });
  }

  function renderChips(selected) {
    // 固定分類 + 自訂分類 +（不在清單裡的當前選擇，例如編輯舊紀錄時）
    const all = [...CATEGORIES, ...customCats()];
    if (selected && !all.includes(selected)) all.push(selected);
    chipBox.innerHTML = all.map((cat) =>
      `<button type="button" class="chip${cat === selected ? " on" : ""}" data-cat="${esc(cat)}">${esc(cat)}</button>`
    ).join("") +
      '<button type="button" class="chip chip-add" data-add-cat>＋自訂</button>';
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


  /* ------------------------------------------------------------ 照片欄位 -- */

  const photoBox = document.getElementById("exp-photo-preview");
  let formPhoto = "";                      // 目前表單掛著的照片（data URL）
  let formScan = null;                     // 表單內容來自掃描時：{ kind, number|code }

  function renderPhotoPreview() {
    if (!photoBox) return;
    photoBox.innerHTML = formPhoto
      ? `<img alt="收據預覽" src="${esc(formPhoto)}">`
        + '<button type="button" class="mini-btn" data-drop-photo>移除</button>'
      : '<span class="muted">未附照片</span>';
    const drop = photoBox.querySelector("[data-drop-photo]");
    if (drop) drop.addEventListener("click", () => { formPhoto = ""; renderPhotoPreview(); });
  }

  const photoInput = form.querySelector('[name="photo"]');
  if (photoInput) {
    photoInput.addEventListener("change", async () => {
      const file = photoInput.files && photoInput.files[0];
      photoInput.value = "";               // 同一張圖再選一次也要能觸發
      if (!file) return;
      photoBox.innerHTML = '<span class="muted">壓縮中…</span>';
      try {
        formPhoto = await compressImage(file);
      } catch (error) {
        formPhoto = "";
        alert("照片處理失敗：" + error.message);
      }
      renderPhotoPreview();
    });
  }

  function resetForm() {
    editingId = null;
    form.reset();
    formPhoto = "";
    formScan = null;
    renderProduct(null);
    renderPhotoPreview();
    field("date").value = todayStr();
    field("category").value = "未分類";
    renderChips("未分類");
    field("pay").value = "現金";       // 手動記的多半是現金——自動管道都有自己的標記
    renderPayChips("現金");
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
    const pay = it.pay || payMethod(it);   // 舊紀錄沒存 pay 就帶推斷值
    field("pay").value = pay === "未標付款方式" ? "現金" : pay;
    renderPayChips(field("pay").value);
    formPhoto = it.photo || "";            // 雲端照片不預載，編輯時不動它
    renderPhotoPreview();
    form.querySelector("[data-submit]").textContent = "儲存修改";
    form.querySelector("[data-cancel]").hidden = false;
    openSheet("編輯紀錄");
  }

  function removeItem(id) {
    const it = items.find((x) => x.id === id);
    if (!it) return;
    if (!confirm(`刪掉這筆「${it.merchant || "未填商家"} ${money(it.amount, it.currency)}」？`)) return;
    items = items.filter((x) => x.id !== id);
    dirty.delete(id);
    tombs.add(id);
    if (editingId === id) closeSheet();
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
        it.pay = field("pay").value || "現金";
        it.spent_at = spentAt;
        if (formPhoto) { it.photo = formPhoto; it.hasPhoto = true; }
        dirty.add(it.id);
      }
    } else {
      const it = {
        id: uuid(), amount, currency: "TWD",
        merchant: field("merchant").value.trim(),
        category: field("category").value || "未分類",
        note: field("note").value.trim(),
        pay: field("pay").value || "現金",
        source: "manual", spent_at: spentAt,
        ...(formPhoto ? { photo: formPhoto, hasPhoto: true } : {}),
      };
      items.unshift(it);
      dirty.add(it.id);
    }
    rememberProduct();
    persist();
    closeSheet();
    render();
    scheduleSync();
  });

  form.querySelector("[data-cancel]").addEventListener("click", closeSheet);

  /* ------------------------------------------------------ 一句話記帳 -- */

  const nlInput = document.getElementById("exp-nl");
  const nlHint = document.getElementById("exp-nl-hint");

  function applyNatural() {
    const raw = nlInput.value.trim();
    if (!raw) return;
    const parsed = parseNatural(raw);
    if (!parsed.amount) {
      nlHint.textContent = "找不到金額——句子裡要有數字，例如「昨天 全家 120 現金」。";
      return;
    }
    field("amount").value = parsed.amount;
    if (parsed.merchant) field("merchant").value = parsed.merchant;
    if (parsed.date) {
      const d = parsed.date;
      field("date").value =
        `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
    }
    const category = parsed.category || "未分類";
    field("category").value = category;
    renderChips(category);
    const pay = parsed.pay || "現金";
    field("pay").value = pay;
    renderPayChips(pay);

    const bits = [`${money(parsed.amount, "TWD")}`];
    if (parsed.merchant) bits.push(parsed.merchant);
    bits.push(category, pay);
    if (parsed.date) bits.push(field("date").value);
    nlHint.textContent = "已填入：" + bits.join("｜") + "——確認後按「記一筆」。";
    nlInput.value = "";
    field("amount").focus();
  }

  if (nlInput) {
    document.getElementById("exp-nl-go").addEventListener("click", applyNatural);
    nlInput.addEventListener("keydown", (event) => {
      if (event.key === "Enter") { event.preventDefault(); applyNatural(); }
    });
  }

  /* --------------------------------------------------- 掃描：發票與條碼 -- */

  // 電子發票證明聯左邊那顆 QR：前 77 字是固定欄位——字軌號碼(10)、民國
  // 日期(7)、隨機碼(4)、銷售額(8, 十六進位)、總計(8, 十六進位)、買方統編(8)、
  // 賣方統編(8)、驗證碼(24)——之後以冒號分隔：營業人自用區、總品目數、
  // 本碼品目數、編碼（0 Big5／1 UTF-8／2 Base64），再來是「品名:數量:單價」
  // 重複。右邊那顆以 ** 開頭，只有品項。QR 裡沒有店名（只有統編）也沒有
  // 付款方式，這兩樣分別靠 /api/lookup 查與使用者點一下。
  const INVOICE_HEAD = /^([A-Z]{2}\d{8})(\d{3})(\d{2})(\d{2})\d{4}([0-9A-Fa-f]{8})([0-9A-Fa-f]{8})\d{8}(\d{8}).{24}(.*)$/s;
  const SELLER_KEY = "exp-sellers";     // 統編 → 店名（同一家店第二次起免查）
  const PRODUCT_KEY = "exp-products";   // 條碼 → { name, price }（第二次掃自動帶價）

  function decodeItems(parts, encoding) {
    let fields = parts;
    if (encoding === "2") {
      // Base64：整段品項是一個 token，解開後才是冒號分隔
      try {
        const bytes = Uint8Array.from(atob(parts.join("").replace(/\s/g, "")),
                                      (c) => c.charCodeAt(0));
        fields = new TextDecoder("utf-8").decode(bytes).split(":");
      } catch { /* 不是合法 Base64 就當純文字 */ }
    }
    const items = [];
    for (let i = 0; i + 2 < fields.length; i += 3) {
      const name = fields[i].trim();
      const qty = Number(fields[i + 1]);
      const price = Number(fields[i + 2]);
      if (!name || !Number.isFinite(qty)) continue;
      items.push({ name, qty, price: Number.isFinite(price) ? price : 0 });
    }
    return items;
  }

  function parseInvoice(text) {
    const raw = String(text || "").trim();
    if (raw.startsWith("**")) {
      return { side: "right", parts: raw.slice(2).split(":") };
    }
    const m = raw.match(INVOICE_HEAD);
    if (!m) return null;
    const [, number, y, mo, d, sales, total, seller, rest] = m;
    const month = Number(mo), day = Number(d);
    if (month < 1 || month > 12 || day < 1 || day > 31) return null;
    const parts = rest.startsWith(":") ? rest.slice(1).split(":") : [];
    const encoding = (parts[3] || "1").trim();
    return {
      side: "left", number, seller, encoding,
      date: new Date(Number(y) + 1911, month - 1, day, 12),
      total: parseInt(total, 16), sales: parseInt(sales, 16),
      items: decodeItems(parts.slice(4), encoding),
      itemCount: Number(parts[1]) || 0,
    };
  }

  // 「御飯糰 35、拿鐵×2 90…等 5 項」——備註只有一行寬，全列會被截掉；
  // 完整的品項表在確認卡上。
  function describeItems(items, max = 4) {
    const shown = items.slice(0, max)
      .map((it) => it.name + (it.qty > 1 ? `×${it.qty}` : "") + (it.price ? ` ${it.price}` : ""));
    let text = shown.join("、");
    if (items.length > max) text += `…等 ${items.length} 項`;
    return text;
  }

  // 商工登記的名稱是「統一超商股份有限公司」，備註與圖例都放不下——
  // 去掉組織型態後綴，留下大家叫它的名字。
  const tidySeller = (name) =>
    String(name || "").replace(/(股份)?有限公司$|企業社$|商行$|工作室$|事業$/, "").trim();

  const dateOf = (d) =>
    `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

  // 分類還是未分類時才照關鍵字猜——使用者已經點過的不動
  function guessInto(text) {
    if (field("category").value !== "未分類") return;
    const guess = guessCategory(text);
    if (guess) { field("category").value = guess; renderChips(guess); }
  }

  // 回 { name, product, brand, quantity, image }；失敗或查無回空物件
  async function lookup(params) {
    try {
      const response = await fetch("/api/lookup?" + params,
                                   { signal: AbortSignal.timeout(8000) });
      if (!response.ok) return {};
      const payload = await response.json();
      return payload && payload.name ? payload : {};
    } catch {
      return {};
    }
  }

  // 掃到商品時的確認卡：小圖、品名、品牌與容量——讓人一眼確認掃對了東西，
  // 而不是看著商家欄的一串字猜。
  const productBox = document.getElementById("exp-product");
  function renderProduct(info) {
    if (!productBox) return;
    if (!info || !info.name) {
      productBox.hidden = true;
      productBox.innerHTML = "";
      return;
    }
    const sub = [info.brand, info.quantity].filter(Boolean).join("・");
    const src = "Open Food Facts" + (info.price ? `・上次 ${money(info.price, "TWD")}` : "");
    productBox.className = "product-card";
    productBox.innerHTML =
      (info.image
        ? `<img class="product-img" alt="" src="${esc(info.image)}">`
        : '<span class="product-img product-img-empty" aria-hidden="true">—</span>')
      + '<span class="product-main">'
      + `<span class="product-name">${esc(info.product || info.name)}</span>`
      + (sub ? `<span class="product-sub">${esc(sub)}</span>` : "")
      + `<span class="product-src">${esc(src)}</span></span>`;
    productBox.hidden = false;
  }
  const noteFor = (code, quantity) => `條碼 ${code}` + (quantity ? `｜${quantity}` : "");
  const fmtInvoice = (number) => number.slice(0, 2) + "-" + number.slice(2);

  // 發票品項卡：品名、數量、單價一列一列，總計在底下——掃了什麼、
  // 各多少錢直接看得到，不用去備註裡找。
  function renderInvoiceItems(inv) {
    if (!productBox) return;
    const row = (name, qty, price, cls) =>
      `<span class="inv-row${cls ? " " + cls : ""}"><span class="inv-name">${esc(name)}</span>`
      + `<span class="inv-qty">${qty > 1 ? "×" + esc(qty) : ""}</span>`
      + `<span class="inv-price">${esc(money(price, "TWD"))}</span></span>`;
    const shown = inv.items.slice(0, 8).map((it) => row(it.name, it.qty, it.price, "")).join("");
    const notes = [];
    if (inv.items.length > 8) notes.push(`…等 ${inv.items.length} 項`);
    if (inv.itemCount > inv.items.length) {
      notes.push(`這顆 QR 只載了 ${inv.items.length}／${inv.itemCount} 項，掃右邊那顆可補齊`);
    }
    productBox.className = "product-card inv-card";
    productBox.innerHTML =
      `<span class="inv-head"><span>發票 ${esc(fmtInvoice(inv.number))}</span>`
      + `<span>${esc(dateOf(inv.date))}</span></span>`
      + shown
      + notes.map((text) => `<span class="inv-more">${esc(text)}</span>`).join("")
      + row("總計", 1, inv.total, "inv-total");
    productBox.hidden = false;
  }

  function applyInvoice(inv) {
    resetFormKeepPay();
    formScan = { kind: "invoice", number: inv.number };
    field("amount").value = inv.total;
    field("date").value = dateOf(inv.date);
    const itemText = describeItems(inv.items);
    field("note").value = `發票 ${fmtInvoice(inv.number)}${itemText ? "｜" + itemText : ""}`.slice(0, 300);
    renderInvoiceItems(inv);

    const sellers = loadJson(SELLER_KEY, {});
    const known = sellers[inv.seller] || "";
    // 編輯既有紀錄時，查不到店名就別把人家填好的商家清掉
    if (known || !editingId) field("merchant").value = known;
    guessInto([known, ...inv.items.map((it) => it.name)].join(" "));

    // 同一張發票記過就直說；同天同金額的紀錄也提一下——Apple Pay 自動
    // 記帳可能已經先記了這筆，發票只是它的明細。正在編輯的那筆不算。
    const others = items.filter((it) => it.id !== editingId);
    const dup = others.find((it) => (it.note || "").replace("-", "").includes(inv.number));
    const sameDay = !dup && others.find((it) =>
      it.amount === inv.total && it.spent_at.slice(0, 10) === field("date").value);
    const summary = `已填入：${money(inv.total, "TWD")}｜${field("date").value}`
      + (inv.items.length ? `｜${inv.items.length} 項` : "");
    if (dup) {
      nlHint.textContent = `這張發票已經記過（${dup.spent_at.slice(5, 10).replace("-", "/")} `
        + `${dup.merchant || "未填商家"} ${money(dup.amount, "TWD")}）——再按「記一筆」會變成兩筆。`;
    } else if (sameDay) {
      nlHint.textContent = summary + `。同一天已有一筆同金額（${sameDay.merchant || "未填商家"}，`
        + `${payMethod(sameDay)}）——若是同一筆消費，改編輯那筆就好。`;
    } else {
      nlHint.textContent = summary + "——確認付款方式後按「記一筆」。";
    }
    if (known) return;

    // 店名非同步補：查到時表單還是這張發票、商家又還空著才填
    lookup("ban=" + inv.seller).then((info) => {
      const tidy = tidySeller(info.name);
      if (!tidy) {
        if (formScan && formScan.number === inv.number && !dup) {
          nlHint.textContent = summary + "。查不到賣方名稱，商家請自己填。";
        }
        return;
      }
      saveJson(SELLER_KEY, { ...loadJson(SELLER_KEY, {}), [inv.seller]: tidy });
      if (!formScan || formScan.number !== inv.number) return;
      if (!field("merchant").value.trim()) {
        field("merchant").value = tidy;
        guessInto([tidy, ...inv.items.map((it) => it.name)].join(" "));
      }
    });
  }

  async function applyBarcode(code) {
    resetFormKeepPay();
    formScan = { kind: "barcode", code };
    const known = loadJson(PRODUCT_KEY, {})[code];
    if (known) {
      field("merchant").value = known.name;
      if (known.price) field("amount").value = known.price;
      field("note").value = noteFor(code, known.quantity);
      renderProduct(known);
      guessInto(known.name);
      nlHint.textContent = `已填入上次的「${known.name}」`
        + (known.price ? `${money(known.price, "TWD")}` : "")
        + "——價格不同就改。";
      return;
    }
    field("note").value = noteFor(code);
    nlHint.textContent = "查詢商品中…";
    const info = await lookup("code=" + code);
    if (!formScan || formScan.code !== code) return;   // 表單已經換了
    if (info.name) {
      formScan.info = info;                  // 存檔時連品牌、容量、圖一起記住
      field("merchant").value = info.name;
      field("note").value = noteFor(code, info.quantity);
      renderProduct(info);
      guessInto(info.name);
      nlHint.textContent = `已填入「${info.name}」——補上金額。這個條碼下次掃就會自動帶入這次的價格。`;
      field("amount").focus();
    } else {
      nlHint.textContent = "資料庫沒有這個商品——填上名稱與金額，下次掃同一個條碼就自動帶入。";
      field("merchant").focus();
    }
  }

  // 記過的商品：條碼 → 名稱與這次的價格。條碼本身不含價格（價格是店家
  // 定的，不在商品上），只能記住你上次付的。
  function rememberProduct() {
    if (!formScan || formScan.kind !== "barcode") return;
    const name = field("merchant").value.trim();
    const price = Math.abs(Number(field("amount").value)) || 0;
    if (!name) return;
    const all = loadJson(PRODUCT_KEY, {});
    const info = formScan.info || all[formScan.code] || {};
    saveJson(PRODUCT_KEY, { ...all, [formScan.code]: {
      name, price, at: Date.now(),
      product: info.product || null, brand: info.brand || null,
      quantity: info.quantity || null, image: info.image || null,
    } });
  }

  // 掃描結果填進表單前先清掉上一次的內容，但付款方式留著——它是使用者
  // 剛點的，發票與條碼都不知道這件事。
  function resetFormKeepPay() {
    renderProduct(null);
    if (editingId) return;                   // 編輯中不動既有欄位
    const pay = field("pay").value;
    field("amount").value = "";
    field("merchant").value = "";
    field("note").value = "";
    field("date").value = todayStr();
    field("category").value = "未分類";
    renderChips("未分類");
    field("pay").value = pay;
  }

  /* 取景器：html5-qrcode 包了 getUserMedia、iOS 的 playsinline 細節與
     ZXing 解碼；瀏覽器有原生 BarcodeDetector 時它會優先用。庫本身
     370KB，所以按了掃描才載入，載過一次 service worker 就快取住了。 */
  const scanner = document.getElementById("exp-scanner");
  const scanView = document.getElementById("exp-scan-view");
  const scanHint = document.getElementById("exp-scan-hint");
  const scanFile = document.getElementById("exp-scan-file");
  const torchBtn = document.getElementById("exp-scan-torch");
  let reader = null;
  let scanning = false;
  let torchOn = false;
  let lastScan = { text: "", at: 0 };
  let rightParts = null;                    // 先掃到右邊那顆時暫存的品項

  function loadScanLib() {
    if (window.Html5Qrcode) return Promise.resolve();
    return new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.src = "/html5-qrcode.min.js?v=2.3.8";
      script.onload = resolve;
      script.onerror = () => reject(new Error("掃描元件載入失敗——離線時要先連過一次網路。"));
      document.head.appendChild(script);
    });
  }

  async function ensureReader() {
    await loadScanLib();
    if (!reader) {
      const F = window.Html5QrcodeSupportedFormats;
      reader = new window.Html5Qrcode(scanView.id, {
        formatsToSupport: [F.QR_CODE, F.EAN_13, F.EAN_8, F.UPC_A, F.UPC_E, F.CODE_128, F.CODE_39],
        useBarCodeDetectorIfSupported: true,
        verbose: false,
      });
    }
    return reader;
  }

  function cameraMessage(error) {
    const name = error && error.name;
    if (name === "NotAllowedError" || /permission|denied/i.test(String(error))) {
      return "沒有相機權限——到 iPhone 設定 › Safari › 相機 選「允許」（加到主畫面的 App 在設定裡有自己的一項），或改用「從相簿選圖」。";
    }
    if (name === "NotFoundError" || /no camera|not found|devices/i.test(String(error))) {
      return "找不到相機——改用「從相簿選圖」。";
    }
    return (error && error.message ? error.message : String(error)) + "——或改用「從相簿選圖」。";
  }

  async function openScanner() {
    scanner.hidden = false;
    rightParts = null;
    lastScan = { text: "", at: 0 };
    torchOn = false;
    torchBtn.hidden = true;
    scanHint.textContent = "對準發票左邊那顆 QR code，或商品條碼";
    try {
      const r = await ensureReader();
      await r.start({ facingMode: "environment" }, {
        fps: 10,
        // 橫長的框：QR 與一維條碼都放得進去
        qrbox: (w, h) => {
          const base = Math.min(w, h);
          return { width: Math.round(base * 0.86), height: Math.round(base * 0.6) };
        },
      }, (text) => handleScan(text), () => {});
      scanning = true;
      try {
        const caps = r.getRunningTrackCapabilities();
        if (caps && caps.torch) torchBtn.hidden = false;
      } catch {}
    } catch (error) {
      scanHint.textContent = cameraMessage(error);
    }
  }

  function closeScanner() {
    scanner.hidden = true;
    lastScan = { text: "", at: 0 };          // 去重只針對取景器連續解碼
    if (reader && scanning) {
      scanning = false;
      reader.stop().then(() => reader.clear()).catch(() => {});
    }
  }

  function handleScan(text) {
    const now = Date.now();
    if (text === lastScan.text && now - lastScan.at < 2500) return;  // 同一顆連續解到
    lastScan = { text, at: now };

    const inv = parseInvoice(text);
    if (inv && inv.side === "right") {
      rightParts = inv.parts;
      scanHint.textContent = "這是右邊那顆（只有品項）——再對準左邊那顆，金額和日期在那裡。";
      return;
    }
    if (inv) {
      if (rightParts) inv.items = inv.items.concat(decodeItems(rightParts, inv.encoding));
      rightParts = null;
      closeScanner();
      applyInvoice(inv);
      return;
    }
    if (/^\d{8}$|^\d{12,14}$/.test(text)) {
      closeScanner();
      applyBarcode(text);
      return;
    }
    scanHint.textContent = "看不懂這個條碼——發票要掃左邊那顆 QR，商品掃包裝上的黑白條碼。";
  }

  document.getElementById("exp-scan").addEventListener("click", openScanner);
  document.getElementById("exp-scan-close").addEventListener("click", closeScanner);

  scanFile.addEventListener("change", async () => {
    const file = scanFile.files && scanFile.files[0];
    scanFile.value = "";
    if (!file) return;
    scanHint.textContent = "辨識中…";
    try {
      const r = await ensureReader();
      if (scanning) { scanning = false; await r.stop(); }
      const text = await r.scanFile(file, false);
      handleScan(text);
    } catch {
      scanHint.textContent = "照片裡找不到條碼——拍近一點、避開反光，或直接手動輸入。";
    }
  });

  torchBtn.addEventListener("click", async () => {
    if (!reader || !scanning) return;
    torchOn = !torchOn;
    try {
      await reader.applyVideoConstraints({ advanced: [{ torch: torchOn }] });
      torchBtn.textContent = torchOn ? "關閉手電筒" : "手電筒";
    } catch {
      torchBtn.hidden = true;
    }
  });

  // 給捷徑或測試用的入口：把解碼後的字串丟進來，走同一條路
  document.addEventListener("exp:scan", (event) => {
    const detail = event.detail || {};
    if (typeof detail.text === "string") handleScan(detail.text);
  });

  /* --------------------------------------------------------- 同步狀態列 -- */

  // 狀態是背景資訊：一行灰字、一顆狀態點；需要使用者處理時（沒登入、
  // 同步失敗）才多給一個可按的連結，按了直接跳到能處理的地方。
  function renderStatus() {
    const box = document.getElementById("exp-status");
    if (!box) return;

    const line = (tone, text, action) =>
      `<span class="status-dot ${tone}" aria-hidden="true"></span>`
      + `<span>${esc(text)}</span>`
      + (action ? `<button type="button" data-go-settings>${esc(action)}</button>` : "");

    if (!CONF) {
      box.innerHTML = line("", "純本機模式：資料只存在這台裝置。");
    } else if (!session()) {
      box.innerHTML = line("", "資料只存在這台裝置", "登入以同步");
    } else if (syncError) {
      box.innerHTML = line("warn", `雲端同步失敗，稍後自動重試（${syncError}）`);
    } else if (lastSync) {
      box.innerHTML = line("ok",
        `已同步 ${lastSync.toLocaleTimeString("zh-TW", { hour12: false })}`);
    } else {
      box.innerHTML = line("", "同步中…");
    }

    const go = box.querySelector("[data-go-settings]");
    if (go) go.addEventListener("click", () => showTab("settings"));
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
        `<div class="token-row"><code>${esc(t.token)}</code>` +
        `<button type="button" class="mini-btn" data-copy="${esc(t.token)}">複製</button>` +
        `<button type="button" class="mini-btn danger" data-revoke="${esc(t.token)}">撤銷</button></div>`
      ).join("");
      const first = tokens[0].token;
      html += `<p class="note">捷徑「取得 URL 內容」的設定：URL 填 `
        + `<code>${esc(endpoint)}</code>、方法 POST、請求本文 JSON。</p>`
        + `<p class="note">Apple Pay 自動記帳（「交易」自動化）的欄位——`
        + `<code>token</code> 填上面的金鑰，其餘選捷徑提供的變數：</p>`
        + `<pre class="json-block">{\n  "token": "${esc(first)}",\n  "amount": 快速指令輸入 › 金額,\n  "merchant": 快速指令輸入 › 商家,\n  "card": 快速指令輸入 › 卡片\n}</pre>`
        + `<p class="note">快速記帳捷徑（LINE Pay、現金）的欄位——`
        + `金額與商家選「要求輸入」的結果：</p>`
        + `<pre class="json-block">{\n  "token": "${esc(first)}",\n  "amount": 要求輸入 › 金額,\n  "merchant": 要求輸入 › 商家,\n  "source": "manual",\n  "pay": "LINE Pay"\n}</pre>`;
    }
    html += '<button type="button" class="mini-btn" data-gen>產生新金鑰</button>';
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

  /* --------------------------------------------------- 分頁與彈出表單 -- */

  // 分頁只是切換可見區塊——不換路由，因為加到主畫面的 PWA 沒有網址列，
  // 使用者對「上一頁」的預期是關閉表單而不是回到上一個分頁。
  const views = [...document.querySelectorAll("[data-view]")];
  const tabs = [...document.querySelectorAll("[data-tab]")];

  function showTab(name) {
    for (const view of views) view.hidden = view.dataset.view !== name;
    for (const tab of tabs) {
      tab.setAttribute("aria-selected", String(tab.dataset.tab === name));
    }
    window.scrollTo({ top: 0, behavior: "instant" in window ? "instant" : "auto" });
    if (name === "settings") renderTokens();
  }
  for (const tab of tabs) {
    tab.addEventListener("click", () => showTab(tab.dataset.tab));
  }

  const sheet = document.getElementById("exp-sheet");
  const scrim = document.getElementById("exp-scrim");

  function openSheet(title) {
    document.getElementById("exp-sheet-title").textContent = title || "記一筆";
    sheet.hidden = false;
    scrim.hidden = false;
    document.body.style.overflow = "hidden";
    // 手機上鍵盤會頂掉版面，所以不自動 focus 金額；使用者自己點
  }
  function closeSheet() {
    closeScanner();
    sheet.hidden = true;
    scrim.hidden = true;
    document.body.style.overflow = "";
    resetForm();
  }

  document.getElementById("exp-fab").addEventListener("click", () => {
    resetForm();
    openSheet("記一筆");
  });
  document.getElementById("exp-sheet-close").addEventListener("click", closeSheet);
  scrim.addEventListener("click", closeSheet);
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    if (!scanner.hidden) closeScanner();      // 先關取景器，表單留著
    else if (!sheet.hidden) closeSheet();
  });

  /* --------------------------------------------------------------- 主題 -- */

  const themeBtn = document.getElementById("exp-theme");
  if (themeBtn) {
    themeBtn.addEventListener("click", () => {
      const root = document.documentElement;
      const current = root.getAttribute("data-theme");
      const prefersDark = matchMedia("(prefers-color-scheme: dark)").matches;
      const next = current ? (current === "dark" ? "light" : "dark")
                           : (prefersDark ? "light" : "dark");
      root.setAttribute("data-theme", next);
      try { localStorage.setItem("theme", next); } catch {}
    });
  }

  /* ----------------------------------------------------------------- 起動 -- */

  function render() {
    renderHome();
    renderBudget();
    renderList();
    renderStatus();
  }

  resetForm();
  render();
  renderTokens();
  if (session()) syncNow();
})();
