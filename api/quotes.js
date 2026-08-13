/**
 * 報價代理 — 讓靜態頁面能取得會跳動的報價。
 *
 * 存在的理由：twse.com.tw 與 Finnhub 都沒有送 Access-Control-Allow-Origin，
 * 瀏覽器直接抓會被 CORS 擋掉。這支在伺服器端抓（沒有 CORS 限制），再用
 * 我們自己的標頭送回瀏覽器。
 *
 * 路由：Vercel 依檔案路徑對應，這個檔就是 /api/quotes
 *   /api/quotes?tw=2330,0050      台股 → 證交所 MIS，免金鑰
 *   /api/quotes?us=AAPL,SPY       其他市場 → 需要 FINNHUB_API_KEY
 *
 * 用 CommonJS 是因為專案沒有 package.json，.js 會被當成 CommonJS；
 * Node 18+ 有全域 fetch，所以不影響功能。
 */

const TWSE_MIS = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp";
const UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)";

// 瀏覽器每 45 秒問一次，但對上游最多 10 秒一次，避免被證交所擋。
const UPSTREAM_TTL_MS = 10_000;
// 供應商每檔報價都要一次呼叫，而 Finnhub 免費層是 60 次/分。頁面上有
// 四十幾個非台股代號，逐檔快取讓所有訪客共用同一次上游呼叫。
const QUOTE_TTL_MS = 45_000;

const twCache = new Map();
const quoteCache = new Map();

function setCors(res) {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "GET, OPTIONS");
  res.setHeader("Cache-Control", "public, max-age=10");
  res.setHeader("Content-Type", "application/json; charset=utf-8");
}

/** 台股數字：帶千分位逗號，停牌或無成交時是 '-'。 */
function twNum(value) {
  if (value === null || value === undefined) return null;
  const text = String(value).replace(/,/g, "").replace(/\+/g, "").trim();
  if (["", "-", "--", "X"].includes(text)) return null;
  const n = Number(text);
  return Number.isFinite(n) ? n : null;
}

/** 依報價日期而非時鐘判斷，才能正確處理週末與國定假日。 */
function marketStatus(quotedMs) {
  if (!quotedMs) return "未知";
  const fmt = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Taipei",
    year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", hour12: false,
  });
  const at = Object.fromEntries(
    fmt.formatToParts(new Date(quotedMs)).map((p) => [p.type, p.value]));
  const now = Object.fromEntries(
    fmt.formatToParts(new Date()).map((p) => [p.type, p.value]));

  const quoteDay = `${at.year}-${at.month}-${at.day}`;
  const today = `${now.year}-${now.month}-${now.day}`;
  if (quoteDay < today) return `已收盤（${quoteDay} 最後交易日資料）`;

  const quoteMinutes = Number(at.hour) * 60 + Number(at.minute);
  const nowMinutes = Number(now.hour) * 60 + Number(now.minute);
  if (quoteMinutes >= 13 * 60 + 30) return "已收盤（本日收盤價）";
  if (nowMinutes < 9 * 60) return "盤前";
  return "盤中";
}

function shapeTaiwan(row) {
  let price = twNum(row.z);
  if (price === null) {
    price = twNum((row.b || "").split("_")[0]) ?? twNum((row.a || "").split("_")[0]);
  }
  const prev = twNum(row.y);
  // 盤前連掛單都還沒有，這時該顯示昨收而不是空白——市場狀態欄位已標明
  if (price === null) price = prev;

  const change = price !== null && prev ? Number((price - prev).toFixed(4)) : null;
  const pct = change !== null && prev ? Number(((change / prev) * 100).toFixed(4)) : null;
  const quotedMs = row.tlong ? Number(row.tlong) : null;
  const status = marketStatus(quotedMs);

  return {
    symbol: row.c, name: row.n,
    price, change, change_percent: pct,
    open: twNum(row.o), high: twNum(row.h), low: twNum(row.l),
    previous_close: prev, volume: twNum(row.v),
    limit_up: twNum(row.u), limit_down: twNum(row.w),
    trade_time: row.t,
    quoted_at: quotedMs ? new Date(quotedMs).toISOString() : null,
    market_status: status,
    is_intraday: status === "盤中",
    source: "mis.twse.com.tw",
  };
}

async function fetchTaiwan(codes) {
  if (!codes.length) return [];
  const key = "tw:" + codes.join(",");
  const hit = twCache.get(key);
  if (hit && Date.now() - hit.at < UPSTREAM_TTL_MS) return hit.data;

  const channels = codes.flatMap((c) => [`tse_${c}.tw`, `otc_${c}.tw`]).join("|");
  const url = `${TWSE_MIS}?ex_ch=${encodeURIComponent(channels)}&json=1&delay=0`;

  const response = await fetch(url, {
    headers: { "User-Agent": UA, Referer: "https://mis.twse.com.tw/stock/index.jsp" },
    signal: AbortSignal.timeout(12_000),
  });
  if (!response.ok) throw new Error(`TWSE HTTP ${response.status}`);
  const payload = await response.json();
  // 證交所限流時回的是 HTTP 200 加非 0000 的 rtcode，只看狀態碼會誤判成功
  if (payload.rtcode !== "0000") throw new Error(`TWSE rtcode ${payload.rtcode}`);

  const found = new Map(
    (payload.msgArray || []).filter((r) => r.c).map((r) => [r.c, r]));
  const data = codes.filter((c) => found.has(c)).map((c) => shapeTaiwan(found.get(c)));
  twCache.set(key, { at: Date.now(), data });
  return data;
}

/* ------------------------------------------------------------- 其他市場 -- */

async function quoteFinnhub(symbol, token) {
  const url = `https://finnhub.io/api/v1/quote?symbol=${encodeURIComponent(symbol)}&token=${token}`;
  const response = await fetch(url, { signal: AbortSignal.timeout(10_000) });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  const q = await response.json();
  if (q.c === undefined || q.c === 0) throw new Error("no quote");
  return {
    symbol, price: q.c,
    change: q.d ?? null, change_percent: q.dp ?? null,
    open: q.o ?? null, high: q.h ?? null, low: q.l ?? null,
    previous_close: q.pc ?? null,
    quoted_at: q.t ? new Date(q.t * 1000).toISOString() : null,
    market_status: "", is_intraday: true, source: "finnhub.io",
  };
}

async function cachedQuote(symbol, token) {
  const key = `finnhub:${symbol}`;
  const hit = quoteCache.get(key);
  if (hit && Date.now() - hit.at < QUOTE_TTL_MS) {
    if (hit.error) throw hit.error;
    return hit.value;
  }
  try {
    const value = await quoteFinnhub(symbol, token);
    quoteCache.set(key, { at: Date.now(), value });
    return value;
  } catch (error) {
    // 失敗也快取，否則每次刷新都重打一輪注定失敗的請求
    quoteCache.set(key, { at: Date.now(), error });
    throw error;
  }
}

async function fetchOther(symbols) {
  const token = process.env.FINNHUB_API_KEY || process.env.MARKETDATA_API_KEY;
  if (!token) return { supported: false, data: [] };
  if (!symbols.length) return { supported: true, data: [] };

  // Finnhub 免費層不含指數，^ 開頭的一定失敗，別浪費額度去打
  const servable = symbols.filter((s) => !s.startsWith("^"));
  const skipped = symbols.length - servable.length;

  const results = await Promise.allSettled(
    servable.map((symbol) => cachedQuote(symbol, token)));
  const failures = results.filter((r) => r.status === "rejected");

  const notes = [];
  if (skipped) notes.push(`${skipped} 檔指數不在此供應商的免費層，維持建置快照`);
  if (failures.length) {
    notes.push(`${failures.length}/${servable.length} 檔取不到：`
      + (failures[0].reason?.message || failures[0].reason));
  }

  return {
    supported: true,
    provider: "finnhub",
    data: results.filter((r) => r.status === "fulfilled").map((r) => r.value),
    note: notes.length ? notes.join("；") : undefined,
  };
}

const splitParam = (raw) =>
  String(raw || "").split(",").map((s) => s.trim()).filter(Boolean).slice(0, 60);

module.exports = async (req, res) => {
  setCors(res);
  if (req.method === "OPTIONS") return res.status(204).end();

  const twCodes = splitParam(req.query.tw)
    .map((c) => c.toUpperCase().split(".")[0])
    .filter((c) => /^\d{4,6}[A-Z]?$/.test(c));
  const others = splitParam(req.query.us);

  const body = { fetched_at: new Date().toISOString(), tw: [], other: [], errors: [] };

  const [twResult, otherResult] = await Promise.allSettled([
    fetchTaiwan(twCodes),
    fetchOther(others),
  ]);

  if (twResult.status === "fulfilled") body.tw = twResult.value;
  else body.errors.push(`tw: ${twResult.reason?.message || twResult.reason}`);

  if (otherResult.status === "fulfilled") {
    body.other = otherResult.value.data;
    body.other_supported = otherResult.value.supported;
    body.provider = otherResult.value.provider || null;
    if (otherResult.value.note) body.errors.push(otherResult.value.note);
  } else {
    body.other_supported = false;
    body.errors.push(`other: ${otherResult.reason?.message || otherResult.reason}`);
  }

  return res.status(200).json(body);
};
