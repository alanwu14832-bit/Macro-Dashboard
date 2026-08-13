/**
 * 序列代理 — 讓 /explore/ 能即時取任一檔序列。
 *
 * 為什麼不烤成靜態 JSON：196 檔全量約 9 MB，而每天兩次建置會讓四十幾檔
 * 日資料重寫，一年下來 repo 會膨脹到 GB 等級。改成即時取還有個好處——
 * 資料永遠是 FRED 上的最新版，不必等下一次建置。
 *
 * 路由：/api/series?id=UNRATE&start=2000-01-01
 * FRED 金鑰放在環境變數，不會出現在瀏覽器端。
 */

const FRED = "https://api.stlouisfed.org/fred/series/observations";

// FRED 對密集呼叫會回 429 並升級成 403。同一檔序列在 TTL 內共用一次上游。
const TTL_MS = 10 * 60 * 1000;
const MAX_CACHE = 120;
const cache = new Map();

/** 只允許 FRED 的代號格式，避免把任意字串轉送到上游。 */
const VALID_ID = /^[A-Za-z0-9._@-]{1,64}$/;

function setCors(res) {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "GET, OPTIONS");
  res.setHeader("Cache-Control", "public, max-age=600");
  res.setHeader("Content-Type", "application/json; charset=utf-8");
}

function remember(key, value) {
  if (cache.size >= MAX_CACHE) cache.delete(cache.keys().next().value);
  cache.set(key, { at: Date.now(), value });
}

module.exports = async (req, res) => {
  setCors(res);
  if (req.method === "OPTIONS") return res.status(204).end();

  const id = String(req.query.id || "").trim();
  const start = String(req.query.start || "1990-01-01").trim();

  if (!VALID_ID.test(id)) return res.status(400).json({ error: "bad id" });
  if (!/^\d{4}-\d{2}-\d{2}$/.test(start)) {
    return res.status(400).json({ error: "bad start" });
  }

  const token = process.env.FRED_API_KEY;
  if (!token) return res.status(503).json({ error: "server missing FRED_API_KEY" });

  const key = `${id}:${start}`;
  const hit = cache.get(key);
  if (hit && Date.now() - hit.at < TTL_MS) {
    return res.status(200).json({ ...hit.value, cached: true });
  }

  const url = `${FRED}?series_id=${encodeURIComponent(id)}`
    + `&api_key=${token}&file_type=json&observation_start=${start}`;

  let payload;
  try {
    const response = await fetch(url, { signal: AbortSignal.timeout(20_000) });
    if (!response.ok) {
      return res.status(502).json({ error: `upstream ${response.status}` });
    }
    payload = await response.json();
  } catch (error) {
    return res.status(502).json({ error: String(error?.message || error) });
  }

  const dates = [];
  const values = [];
  for (const row of payload.observations || []) {
    if (!row || row.value === "." || row.value === "" || row.value == null) continue;
    const n = Number(row.value);
    if (!Number.isFinite(n)) continue;
    dates.push(row.date);
    values.push(n);
  }

  const result = {
    id, start, n: dates.length, dates, values,
    fetched_at: new Date().toISOString(),
  };
  remember(key, result);
  return res.status(200).json(result);
};
