/**
 * 自動記帳的收單端點 — 給 iOS 捷徑的「交易」自動化用。
 *
 * 為什麼需要這一層：iOS 不讓第三方 App 直接讀 Apple Pay 交易，唯一的官方
 * 管道是捷徑的「交易」自動化——刷卡當下觸發捷徑，把金額與商家 POST 出來。
 * 捷徑沒辦法做 OAuth 登入，所以用「ingest token」認人：使用者在 /expense/
 * 頁登入後產生一組 token（存在 expense_tokens 表，RLS 保護），貼進捷徑；
 * 這支 function 用 service role key 查 token → user_id，再寫入 expenses 表。
 *
 * 路由：POST /api/expense
 *   body（JSON 或 form-encoded）：
 *     token     必填，/expense/ 頁產生的 ingest token
 *     amount    必填，數字或含幣別符號的字串（"NT$120.00" 也可）
 *     merchant  商家名稱（捷徑的「商家」變數）
 *     name      交易名稱（捷徑的「名稱」變數，商家空白時的備援）
 *     card      卡片名稱（記進備註，知道刷的是哪張卡）
 *     currency  幣別，預設 TWD
 *     note      備註
 *     date      ISO 時間，預設現在
 *     source    "applepay"（預設）或 "manual"——快速記帳捷徑
 *               （LINE Pay、現金）傳 manual，這種是人主動按的，
 *               不做兩分鐘去重（連買兩杯一樣的飲料是真的兩筆）
 *
 * 需要的環境變數（Vercel Project Settings）：
 *   SUPABASE_SERVICE_ROLE_KEY   Supabase 的 service role key。沒設回 503。
 *   SUPABASE_URL                選填，預設用前端同一個專案網址。
 *
 * 用 CommonJS 是因為專案沒有 package.json，.js 會被當成 CommonJS。
 */

const SUPABASE_URL = process.env.SUPABASE_URL
  || "https://nwbfjoroqnhpymdtdbwu.supabase.co";
const SERVICE_KEY = process.env.SUPABASE_SERVICE_ROLE_KEY
  || process.env.SUPABASE_SERVICE_KEY || "";

// 商家 → 分類的關鍵字規則。前端手動輸入時也有同一套（expense.js），
// 兩邊都改才會一致。猜不到就留「未分類」，使用者在頁面上改一次即可。
const CATEGORY_RULES = [
  [/7-?eleven|統一超商|全家|family\s*mart|萊爾富|hi-?life|ok\s*mart|超商/i, "超商"],
  [/全聯|pxmart|家樂福|carrefour|大潤發|愛買|costco|好市多|美廉社|超市|市場/i, "超市"],
  [/麥當勞|mcdonald|肯德基|kfc|摩斯|mos\s*burger|漢堡王|burger\s*king|必勝客|pizza|壽司|sushi|拉麵|火鍋|燒肉|食堂|餐廳|餐飲|小吃|便當|鍋貼|水餃|早餐|豆漿|茶|咖啡|coffee|starbucks|星巴克|路易莎|louisa|cama|85度|五十嵐|50嵐|清心|可不可|迷客夏|珍煮丹|得正|foodpanda|uber\s*eats/i, "餐飲"],
  [/台鐵|高鐵|thsr|捷運|metro|悠遊|easycard|一卡通|ipass|客運|公車|uber(?!\s*eats)|計程|taxi|line\s*go|停車|parking|中油|cpc|台亞|全國加油|加油/i, "交通"],
  [/藥局|藥妝|屈臣氏|watsons|康是美|cosmed|診所|醫院|牙醫|藥師|clinic|hospital|pharmacy/i, "醫療"],
  [/netflix|spotify|youtube|disney|apple\.com|apple\s*services|itunes|icloud|google\s*(one|play|storage)|steam|nintendo|playstation|game|訂閱/i, "訂閱與娛樂"],
  [/蝦皮|shopee|momo|pchome|coupang|酷澎|淘寶|taobao|amazon|樂天|rakuten|yahoo|露天/i, "網購"],
  [/電費|台電|水費|自來水|瓦斯|天然氣|電信|中華電信|cht|台灣大|遠傳|fetnet|房租|租金|管理費/i, "居住與帳單"],
];

function guessCategory(text) {
  for (const [pattern, category] of CATEGORY_RULES) {
    if (pattern.test(text)) return category;
  }
  return "未分類";
}

/** 捷徑傳來的金額可能是 120、"120.00"、"NT$120" 或 "$1,234.56"。 */
function parseAmount(raw) {
  if (typeof raw === "number") return Number.isFinite(raw) ? Math.abs(raw) : null;
  if (typeof raw !== "string") return null;
  const text = raw.replace(/[^0-9.\-]/g, "");
  if (!text) return null;
  const n = Number(text);
  return Number.isFinite(n) ? Math.abs(n) : null;
}

function readBody(req) {
  return new Promise((resolve) => {
    // Vercel 對 JSON / form content-type 已經解好放在 req.body
    if (req.body !== undefined && req.body !== null) return resolve(req.body);
    let raw = "";
    req.on("data", (chunk) => {
      raw += chunk;
      if (raw.length > 64 * 1024) { req.destroy(); resolve(null); }
    });
    req.on("end", () => {
      try { resolve(JSON.parse(raw)); }
      catch { resolve(Object.fromEntries(new URLSearchParams(raw))); }
    });
    req.on("error", () => resolve(null));
  });
}

async function sb(path, options) {
  const response = await fetch(SUPABASE_URL + "/rest/v1" + path, {
    ...options,
    headers: {
      apikey: SERVICE_KEY,
      Authorization: "Bearer " + SERVICE_KEY,
      "Content-Type": "application/json",
      ...(options && options.headers),
    },
  });
  return response;
}

module.exports = async (req, res) => {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "POST, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type");
  res.setHeader("Content-Type", "application/json; charset=utf-8");
  res.setHeader("Cache-Control", "no-store");

  if (req.method === "OPTIONS") return res.status(204).end();
  if (req.method !== "POST") {
    return res.status(405).json({
      ok: false,
      error: "用 POST。設定方式見網站的 /expense/ 頁「自動記帳」一節。",
    });
  }
  if (!SERVICE_KEY) {
    return res.status(503).json({
      ok: false,
      error: "伺服器未設定 SUPABASE_SERVICE_ROLE_KEY，自動記帳未開通。",
    });
  }

  const body = await readBody(req);
  if (!body || typeof body !== "object") {
    return res.status(400).json({ ok: false, error: "讀不懂 request body" });
  }

  const token = String(body.token || req.headers["x-expense-token"] || "").trim();
  if (!/^[A-Za-z0-9_-]{16,128}$/.test(token)) {
    return res.status(401).json({ ok: false, error: "token 缺少或格式不對" });
  }

  const amount = parseAmount(body.amount);
  if (amount === null || amount <= 0) {
    return res.status(400).json({ ok: false, error: "amount 缺少或不是正數" });
  }

  // token → user_id（service role 繞過 RLS，所以這裡查得到）
  const tokenResp = await sb(
    "/expense_tokens?select=user_id&token=eq." + encodeURIComponent(token),
    { method: "GET" });
  if (!tokenResp.ok) {
    return res.status(502).json({ ok: false, error: "資料庫查詢失敗 HTTP " + tokenResp.status });
  }
  const tokenRows = await tokenResp.json();
  if (!tokenRows.length) {
    return res.status(401).json({ ok: false, error: "token 無效或已撤銷" });
  }
  const userId = tokenRows[0].user_id;

  const source = body.source === "manual" ? "manual" : "applepay";
  const merchant = String(body.merchant || body.name || "").trim().slice(0, 120);
  const card = String(body.card || "").trim().slice(0, 80);
  const currency = (String(body.currency || "TWD").trim().toUpperCase() || "TWD").slice(0, 8);
  let note = String(body.note || "").trim().slice(0, 300);
  if (card) note = note ? `${note}（${card}）` : card;

  let spentAt = new Date();
  if (body.date) {
    const parsed = new Date(body.date);
    if (!Number.isNaN(parsed.getTime())) spentAt = parsed;
  }

  // 去重：交易自動化偶爾會對同一筆刷卡觸發兩次。同人同商家同金額、
  // 兩分鐘內已有一筆，就當同一筆，回 ok 但不重複入帳。
  // 只對 applepay 做——手動快速記帳是人按的，連兩筆一樣的是真的兩筆。
  if (source === "applepay") {
    const windowStart = new Date(spentAt.getTime() - 2 * 60 * 1000).toISOString();
    const dupResp = await sb(
      "/expenses?select=id&user_id=eq." + userId
      + "&amount=eq." + amount
      + "&merchant=eq." + encodeURIComponent(merchant)
      + "&source=eq.applepay"
      + "&spent_at=gte." + encodeURIComponent(windowStart)
      + "&limit=1",
      { method: "GET" });
    if (dupResp.ok) {
      const dupRows = await dupResp.json();
      if (dupRows.length) {
        return res.status(200).json({ ok: true, duplicate: true, id: dupRows[0].id });
      }
    }
  }

  const row = {
    user_id: userId,
    amount,
    currency,
    merchant,
    category: guessCategory(merchant + " " + note),
    note,
    source,
    spent_at: spentAt.toISOString(),
  };
  const insertResp = await sb("/expenses?select=id,category", {
    method: "POST",
    headers: { Prefer: "return=representation" },
    body: JSON.stringify(row),
  });
  if (!insertResp.ok) {
    const detail = await insertResp.text().catch(() => "");
    return res.status(502).json({
      ok: false,
      error: "寫入失敗 HTTP " + insertResp.status + (detail ? "：" + detail.slice(0, 200) : ""),
    });
  }
  const inserted = await insertResp.json();
  return res.status(201).json({
    ok: true,
    id: inserted[0] && inserted[0].id,
    category: row.category,
  });
};
