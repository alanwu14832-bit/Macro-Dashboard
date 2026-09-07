/**
 * 掃描用的查詢代理 — GET /api/lookup
 *
 *   ?ban=12345678     賣方統編 → 公司／商業名稱（財政部商工登記公開資料）
 *   ?code=4710088…    商品條碼（EAN/UPC）→ 品名、品牌、容量、小圖、來源
 *                     （Open Food Facts，查不到再問 Beauty／Products／Pet Food 三個姊妹庫）
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
// Open Food Facts 與它的三個姊妹庫（美妝、一般商品、寵物食品）共用同一套
// API 與資料格式；食品查不到就順著問下去，非食品的商品才有機會查到。
const OPEN_FACTS = [
  ["Open Food Facts", "https://world.openfoodfacts.org", "images.openfoodfacts.org"],
  ["Open Beauty Facts", "https://world.openbeautyfacts.org", "images.openbeautyfacts.org"],
  ["Open Products Facts", "https://world.openproductsfacts.org", "images.openproductsfacts.org"],
  ["Open Pet Food Facts", "https://world.openpetfoodfacts.org", "images.openpetfoodfacts.org"],
];

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

/** 商品條碼 → 品名、品牌、容量、小圖、來源。品名是「品牌 品名」，直接能填商家欄。 */
async function productInfo(code) {
  for (const [source, host, imageHost] of OPEN_FACTS) {
    const payload = await fetchJson(
      host + "/api/v2/product/" + encodeURIComponent(code)
        + ".json?fields=product_name,product_name_zh,brands,quantity,image_front_small_url",
      { "User-Agent": "expense-app/1.0 (personal expense tracker)" },
    ).catch(() => null);
    const product = payload && payload.product;
    if (!product) continue;
    const name = String(product.product_name_zh || product.product_name || "").trim();
    const brand = String(product.brands || "").split(",")[0].trim();
    const full = [brand, name].filter(Boolean).join(" ").trim();
    if (!full) continue;
    // 圖只收該庫自己的圖床——前端 CSP 只放行這幾個網域
    const image = String(product.image_front_small_url || "");
    return {
      name: full,
      product: name || null,
      brand: brand || null,
      quantity: String(product.quantity || "").trim() || null,
      image: image.startsWith("https://" + imageHost + "/") ? image : null,
      source,
    };
  }
  return null;
}

module.exports = async (req, res) => {
  if (req.method !== "GET") {
    res.setHeader("Allow", "GET");
    return res.status(405).json({ error: "GET only" });
  }
  const ban = String(req.query.ban || "").trim();
  const code = String(req.query.code || "").trim();

  let info = null;
  if (/^\d{8}$/.test(ban)) {
    const name = await sellerName(ban);
    info = name ? { name } : null;
  } else if (/^\d{8,14}$/.test(code)) {
    info = await productInfo(code);
  } else {
    return res.status(400).json({ error: "ban 要 8 位數字，或 code 要 8–14 位數字" });
  }

  res.setHeader("Cache-Control",
    info ? "public, s-maxage=86400, stale-while-revalidate=604800"
         : "public, s-maxage=3600");
  return res.status(200).json(info || { name: null });
};
