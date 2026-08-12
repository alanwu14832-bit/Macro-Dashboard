/**
 * 報價代理 — 讓靜態頁面能取得會跳動的報價。
 *
 * 存在的理由：twse.com.tw 與 Yahoo 都沒有送 Access-Control-Allow-Origin，
 * 瀏覽器直接抓會被 CORS 擋掉。這個 function 在伺服器端抓（沒有 CORS 限制），
 * 再用我們自己的標頭送回瀏覽器。
 *
 * 路由：
 *   /api/quotes?tw=2330,0050          台股 → 證交所 MIS，免金鑰
 *   /api/quotes?us=AAPL,SPY           其他市場 → 需要 FINNHUB_API_KEY
 *   兩個參數可同時給。
 *
 * 沒設定金鑰時，us 部分會回 supported:false，前端就維持
 * 建置時烤進去的快照——不會顯示錯誤，也不會假裝有更新。
 */

const TWSE_MIS = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp";
const UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)";

// 瀏覽器每 20 秒問一次，但對上游最多 10 秒一次，避免被證交所擋。
const UPSTREAM_TTL_MS = 10_000;
const cache = new Map();

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, OPTIONS",
  "Cache-Control": "public, max-age=10",
  "Content-Type": "application/json; charset=utf-8",
};

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
  const parts = Object.fromEntries(fmt.formatToParts(new Date(quotedMs)).map(p => [p.type, p.value]));
  const nowParts = Object.fromEntries(fmt.formatToParts(new Date()).map(p => [p.type, p.value]));

  const quoteDay = `${parts.year}-${parts.month}-${parts.day}`;
  const today = `${nowParts.year}-${nowParts.month}-${nowParts.day}`;
  if (quoteDay < today) return `已收盤（${quoteDay} 最後交易日資料）`;

  const quoteMinutes = Number(parts.hour) * 60 + Number(parts.minute);
  const nowMinutes = Number(nowParts.hour) * 60 + Number(nowParts.minute);
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
  const change = price !== null && prev ? Number((price - prev).toFixed(4)) : null;
  const pct = change !== null && prev ? Number(((change / prev) * 100).toFixed(4)) : null;
  const quotedMs = row.tlong ? Number(row.tlong) : null;
  const status = marketStatus(quotedMs);

  return {
    symbol: row.c,
    name: row.n,
    price, change, change_percent: pct,
    open: twNum(row.o), high: twNum(row.h), low: twNum(row.l),
    previous_close: prev,
    volume: twNum(row.v),
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
  const hit = cache.get(key);
  if (hit && Date.now() - hit.at < UPSTREAM_TTL_MS) return hit.data;

  const channels = codes.flatMap(c => [`tse_${c}.tw`, `otc_${c}.tw`]).join("|");
  const url = `${TWSE_MIS}?ex_ch=${encodeURIComponent(channels)}&json=1&delay=0`;

  const response = await fetch(url, {
    headers: { "User-Agent": UA, Referer: "https://mis.twse.com.tw/stock/index.jsp" },
    signal: AbortSignal.timeout(12_000),
  });
  if (!response.ok) throw new Error(`TWSE HTTP ${response.status}`);
  const payload = await response.json();
  if (payload.rtcode !== "0000") throw new Error(`TWSE rtcode ${payload.rtcode}`);

  const found = new Map((payload.msgArray || []).filter(r => r.c).map(r => [r.c, r]));
  const data = codes.filter(c => found.has(c)).map(c => shapeTaiwan(found.get(c)));
  cache.set(key, { at: Date.now(), data });
  return data;
}

/* ---------------------------------------------------------- 其他市場 ------
 * Yahoo 擋資料中心 IP 且無官方免費 API，所以走可設定的供應商。
 * 兩家的 API 形狀完全不同，這裡都實作，第一次呼叫時自動判斷是哪一家，
 * 之後記住——使用者不必額外設定 provider。
 * 要強制指定的話設 MARKETDATA_PROVIDER=marketdata 或 finnhub。
 * ------------------------------------------------------------------------ */

let resolvedProvider = process.env.MARKETDATA_PROVIDER || null;

/** marketdata.app：指數與股票分屬不同路徑，^GSPC 這種要轉成 SPX。 */
async function quoteMarketdata(symbol, token) {
  const isIndex = symbol.startsWith("^");
  const bare = isIndex ? symbol.slice(1).replace(/^GSPC$/, "SPX") : symbol;
  const kind = isIndex ? "indices" : "stocks";
  const url = `https://api.marketdata.app/v1/${kind}/quotes/${encodeURIComponent(bare)}/`;

  const response = await fetch(url, {
    headers: { Authorization: `Token ${token}` },
    signal: AbortSignal.timeout(10_000),
  });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  const q = await response.json();
  if (q.s !== "ok" || !q.last?.length) throw new Error(`status ${q.s}`);

  const last = q.last[0];
  const change = q.change?.[0] ?? null;
  return {
    symbol,
    price: last,
    change,
    change_percent: q.changepct?.[0] != null ? q.changepct[0] * 100 : null,
    open: null,
    high: q.high?.[0] ?? null,
    low: q.low?.[0] ?? null,
    previous_close: change != null ? Number((last - change).toFixed(4)) : null,
    volume: q.volume?.[0] ?? null,
    quoted_at: q.updated?.[0] ? new Date(q.updated[0] * 1000).toISOString() : null,
    market_status: "",
    is_intraday: true,
    source: "marketdata.app",
  };
}

/** Finnhub：免費層支援美股個股與 ETF，指數需付費層。 */
async function quoteFinnhub(symbol, token) {
  const url = `https://finnhub.io/api/v1/quote?symbol=${encodeURIComponent(symbol)}&token=${token}`;
  const response = await fetch(url, { signal: AbortSignal.timeout(10_000) });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  const q = await response.json();
  if (q.c === undefined || q.c === 0) throw new Error("no quote");
  return {
    symbol,
    price: q.c,
    change: q.d ?? null,
    change_percent: q.dp ?? null,
    open: q.o ?? null, high: q.h ?? null, low: q.l ?? null,
    previous_close: q.pc ?? null,
    quoted_at: q.t ? new Date(q.t * 1000).toISOString() : null,
    market_status: "",
    is_intraday: true,
    source: "finnhub.io",
  };
}

const PROVIDERS = { finnhub: quoteFinnhub, marketdata: quoteMarketdata };

/**
 * 用一個常見代號試出金鑰屬於哪一家。
 *
 * 順序很重要：marketdata.app 對「未認證」請求也會回資料，所以它一定會
 * 「通過」測試，先試它就永遠選中它，使用者真正的金鑰反而沒被用到——
 * 而未認證額度只夠一兩次請求，結果是幾乎每檔都失敗。
 * Finnhub 的無效金鑰會明確回 401，是可靠的否定訊號，所以先試它。
 */
async function detectProvider(token) {
  for (const [name, fn] of Object.entries(PROVIDERS)) {
    try {
      await fn("AAPL", token);
      return name;
    } catch { /* 換下一家 */ }
  }
  return null;
}

function readToken() {
  if (process.env.FINNHUB_API_KEY) {
    // 變數名稱本身就說明了供應商，不需要（也不該）再猜。
    return { token: process.env.FINNHUB_API_KEY, provider: "finnhub", from: "FINNHUB_API_KEY" };
  }
  if (process.env.MARKETDATA_API_KEY) {
    return { token: process.env.MARKETDATA_API_KEY, provider: null, from: "MARKETDATA_API_KEY" };
  }
  return { token: null, provider: null, from: null };
}

/* 供應商的每檔報價都要一次呼叫，而 Finnhub 免費層是 60 次/分。頁面上有
 * 四十幾個非台股代號，若每個訪客每次刷新都直接打上游，一個人就會超額。
 * 這裡用逐檔快取：同一個代號在 TTL 內只打一次上游，所有訪客共用。       */
const QUOTE_TTL_MS = 45_000;
const quoteCache = new Map();

/** Finnhub 免費層不含指數，^ 開頭的一定失敗，別浪費額度去打。 */
function servableBy(provider, symbol) {
  return provider === "finnhub" ? !symbol.startsWith("^") : true;
}

async function cachedQuote(provider, symbol, token) {
  const key = `${provider}:${symbol}`;
  const hit = quoteCache.get(key);
  if (hit && Date.now() - hit.at < QUOTE_TTL_MS) {
    if (hit.error) throw hit.error;
    return hit.value;
  }
  try {
    const value = await PROVIDERS[provider](symbol, token);
    quoteCache.set(key, { at: Date.now(), value });
    return value;
  } catch (error) {
    // 失敗也要快取，否則每次刷新都會重打一輪注定失敗的請求
    quoteCache.set(key, { at: Date.now(), error });
    throw error;
  }
}

async function fetchOther(symbols) {
  const { token, provider: declared, from } = readToken();
  if (!token) return { supported: false, data: [], provider: null, key_source: null };
  if (!symbols.length) {
    return { supported: true, data: [], provider: declared || resolvedProvider, key_source: from };
  }

  let provider = declared || resolvedProvider;
  if (!provider) {
    provider = await detectProvider(token);
    resolvedProvider = provider;
  }
  if (!provider) {
    return { supported: false, data: [], provider: null, key_source: from,
             note: "金鑰無法對應到已知的供應商（finnhub / marketdata.app）" };
  }

  const servable = symbols.filter(s => servableBy(provider, s));
  const skipped = symbols.length - servable.length;
  const results = await Promise.allSettled(
    servable.map(symbol => cachedQuote(provider, symbol, token)));

  const failures = results.filter(r => r.status === "rejected");
  const notes = [];
  if (skipped) notes.push(`${skipped} 檔指數不在此供應商的免費層，維持建置快照`);
  if (failures.length) {
    notes.push(`${failures.length}/${servable.length} 檔取不到：`
               + (failures[0].reason?.message || failures[0].reason));
  }

  return {
    supported: true,
    provider,
    key_source: from,
    data: results.filter(r => r.status === "fulfilled").map(r => r.value),
    note: notes.length ? notes.join("；") : undefined,
  };
}

const splitParam = (raw) =>
  (raw || "").split(",").map(s => s.trim()).filter(Boolean).slice(0, 60);

export default async (request) => {
  if (request.method === "OPTIONS") return new Response("", { headers: CORS });

  const params = new URL(request.url).searchParams;
  const twCodes = splitParam(params.get("tw"))
    .map(c => c.toUpperCase().split(".")[0])
    .filter(c => /^\d{4,6}[A-Z]?$/.test(c));
  const others = splitParam(params.get("us"));

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
    body.key_source = otherResult.value.key_source || null;
    if (otherResult.value.note) body.errors.push(otherResult.value.note);
  } else {
    body.other_supported = false;
    body.errors.push(`other: ${otherResult.reason?.message || otherResult.reason}`);
  }

  return new Response(JSON.stringify(body), { headers: CORS });
};

export const config = { path: "/api/quotes" };
