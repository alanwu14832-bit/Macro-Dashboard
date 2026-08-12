/**
 * 報價代理 — 讓靜態頁面能取得會跳動的報價。
 *
 * 存在的理由：twse.com.tw 與 Yahoo 都沒有送 Access-Control-Allow-Origin，
 * 瀏覽器直接抓會被 CORS 擋掉。這個 function 在伺服器端抓（沒有 CORS 限制），
 * 再用我們自己的標頭送回瀏覽器。
 *
 * 路由：
 *   /api/quotes?tw=2330,0050          台股 → 證交所 MIS，免金鑰
 *   /api/quotes?us=^GSPC,AAPL         其他市場 → 需要 MARKETDATA_API_KEY
 *   兩個參數可同時給。
 *
 * 沒設定 MARKETDATA_API_KEY 時，us 部分會回 supported:false，前端就維持
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

/**
 * 其他市場。Yahoo 會擋資料中心 IP 且無官方免費 API，所以走可設定的供應商。
 * 目前實作 Finnhub（免費層支援美股個股與 ETF；指數需付費層）。
 */
async function fetchOther(symbols) {
  const token = process.env.MARKETDATA_API_KEY;
  if (!token) return { supported: false, data: [] };
  if (!symbols.length) return { supported: true, data: [] };

  const results = await Promise.allSettled(symbols.map(async (symbol) => {
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
  }));

  return {
    supported: true,
    data: results.filter(r => r.status === "fulfilled").map(r => r.value),
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
  } else {
    body.other_supported = false;
    body.errors.push(`other: ${otherResult.reason?.message || otherResult.reason}`);
  }

  return new Response(JSON.stringify(body), { headers: CORS });
};

export const config = { path: "/api/quotes" };
