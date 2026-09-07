/**
 * 掃描用的查詢代理 — GET /api/lookup
 *
 *   ?ban=12345678     賣方統編 → 公司／商業名稱（財政部商工登記公開資料）
 *   ?code=4710088…    商品條碼（EAN/UPC）→ 品名（Open Food Facts）
 *
 * 為什麼要一層代理：電子發票的 QR 只有賣方統編、沒有店名，而商工登記的
 * 開放資料 API 沒開 CORS；前端的 CSP 也只放行自己與 Supabase。兩個來源
 * 都是公開資料、不需要金鑰，這裡只做轉發、逾時與快取。
 *
 * 查不到一律回 { name: null }：寧可讓使用者自己填，不要猜一個錯的店名。
 * 回應帶 s-maxage 讓 Vercel 邊緣快取一天——同一家店不會每掃一次就打一次
 * 政府的 API。
 */

const GCIS = "https://data.gcis.nat.gov.tw/od/data/api/";
// 公司登記（股份有限公司、有限公司）與商業登記（商行、企業社）是兩份資料集
const COMPANY_SET = "5F64D864-61CB-4D0D-8AD9-492047CC1EA6";
const BUSINESS_SET = "7E6AFA72-AD6A-46D3-8681-ED77951D912D";
const OFF = "https://world.openfoodfacts.org/api/v2/product/";

async function fetchJson(url, headers) {
  const response = await fetch(url, {
    headers: { Accept: "application/json", ...headers },
    signal: AbortSignal.timeout(6000),
  });
  if (!response.ok) return null;
  const text = await response.text();
  if (!text.trim()) return null;               // 商工登記查無資料時回空白
  try { return JSON.parse(text); } catch { return null; }
}

/** 統編 → 名稱。先查公司登記，沒有再查商業登記。 */
async function sellerName(ban) {
  const filter = "$format=json&$filter="
    + encodeURIComponent(`Business_Accounting_NO eq ${ban}`) + "&$skip=0&$top=1";
  const company = await fetchJson(GCIS + COMPANY_SET + "?" + filter).catch(() => null);
  if (Array.isArray(company) && company[0] && company[0].Company_Name) {
    return String(company[0].Company_Name).trim();
  }
  const business = await fetchJson(GCIS + BUSINESS_SET + "?" + filter).catch(() => null);
  if (Array.isArray(business) && business[0] && business[0].Business_Name) {
    return String(business[0].Business_Name).trim();
  }
  return null;
}

/** 商品條碼 → 「品牌 品名」。 */
async function productName(code) {
  const payload = await fetchJson(
    OFF + encodeURIComponent(code) + ".json?fields=product_name,product_name_zh,brands",
    { "User-Agent": "expense-app/1.0 (personal expense tracker)" },
  ).catch(() => null);
  const product = payload && payload.product;
  if (!product) return null;
  const name = product.product_name_zh || product.product_name || "";
  const brand = String(product.brands || "").split(",")[0].trim();
  const full = [brand, name].filter(Boolean).join(" ").trim();
  return full || null;
}

module.exports = async (req, res) => {
  if (req.method !== "GET") {
    res.setHeader("Allow", "GET");
    return res.status(405).json({ error: "GET only" });
  }
  const ban = String(req.query.ban || "").trim();
  const code = String(req.query.code || "").trim();

  let name = null;
  if (/^\d{8}$/.test(ban)) {
    name = await sellerName(ban);
  } else if (/^\d{8,14}$/.test(code)) {
    name = await productName(code);
  } else {
    return res.status(400).json({ error: "ban 要 8 位數字，或 code 要 8–14 位數字" });
  }

  res.setHeader("Cache-Control",
    name ? "public, s-maxage=86400, stale-while-revalidate=604800"
         : "public, s-maxage=3600");
  return res.status(200).json({ name });
};
