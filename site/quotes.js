/* ============================================================================
 * quotes.js — 讓報價頁在部署環境下自己更新。
 *
 * 頁面上每個報價欄位都帶 data-quote="代號" 與 data-field="price|change|..."，
 * 這支腳本向 /api/quotes（serverless function 代理）拿新報價後就地換掉數字。
 *
 * 沒有 /api/quotes 時（本機用 python http.server 預覽、或部署到不支援
 * functions 的主機）會安靜停用，頁面就維持建置時烤進去的快照——不顯示
 * 錯誤，也不會讓使用者誤以為數字有在更新。
 * ========================================================================== */
(() => {
  "use strict";

  const root = document.querySelector("[data-quotes-live]");
  if (!root) return;

  // 兩種節奏。台股 5 秒——證交所 MIS 每 5 秒對外發布一次行情快照，
  // 這是它公開資料的即時上限，再快也只會拿到同一筆。
  // 美股與新興市場 45 秒——頁面上有四十幾個非台股代號，而 Finnhub
  // 免費層是每分鐘 60 次呼叫，45 秒是單一訪客不超額的最短間隔。
  const TW_REFRESH_MS = 5_000;
  const OTHER_REFRESH_MS = 45_000;
  const status = document.getElementById("quote-status");
  const cells = [...document.querySelectorAll("[data-quote]")];
  if (!cells.length) return;

  const twSymbols = [...new Set(cells.filter(c => c.dataset.market === "tw")
                                     .map(c => c.dataset.quote))];
  const otherSymbols = [...new Set(cells.filter(c => c.dataset.market !== "tw")
                                        .map(c => c.dataset.quote))];

  let failures = 0;
  let disabled = false;
  // 兩個群組各自輪詢，狀態列要合起來講，所以記住彼此的最新狀態
  const state = { provider: null, notSupported: false };

  // 自適應節奏：連兩輪完全沒有任何欄位變化（收盤、週末、假日）就把
  // 間隔加倍，一路放慢到上限；一偵測到變化立刻回到基本節奏。
  // 台股一天只有 4.5 小時盤中，這一招把其餘 19.5 小時的呼叫量
  // 砍掉九成以上，而且不用維護交易日曆——假日自己會慢下來。
  const CADENCE = {
    tw:    { base: TW_REFRESH_MS,    max: 90_000 },
    other: { base: OTHER_REFRESH_MS, max: 300_000 },
  };
  const pace = {
    tw:    { wait: CADENCE.tw.base,    idle: 0, timer: null },
    other: { wait: CADENCE.other.base, idle: 0, timer: null },
  };

  const fmt = (value, digits) =>
    value === null || value === undefined || Number.isNaN(value)
      ? "—"
      : value.toLocaleString("en-US", { minimumFractionDigits: digits,
                                        maximumFractionDigits: digits });

  const signed = (value, digits, suffix = "") =>
    value === null || value === undefined ? "—"
      : (value > 0 ? "+" : "") + fmt(value, digits) + suffix;

  function setText(node, text) {
    if (node.textContent === text) return false;
    node.textContent = text;
    node.classList.remove("q-flash");
    void node.offsetWidth;            // 重新觸發動畫
    node.classList.add("q-flash");
    return true;
  }

  // 熱力圖磁磚底色。跟 Python 端 heat_style() 同一套公式：
  // ±3% 封頂，之內線性調透明度，綠漲紅跌。改一邊就要一起改另一邊。
  function heatColor(pct) {
    if (pct === null || pct === undefined) return "rgba(137,135,129,0.10)";
    const clamped = Math.max(-3, Math.min(3, pct));
    const alpha = 0.06 + (Math.abs(clamped) / 3) * 0.42;
    const rgb = clamped > 0 ? "12,132,58"
              : clamped < 0 ? "199,55,55" : "137,135,129";
    return `rgba(${rgb},${alpha.toFixed(3)})`;
  }

  function apply(quotes) {
    const bySymbol = new Map(quotes.map(q => [String(q.symbol), q]));
    let changed = 0;

    for (const tile of document.querySelectorAll("[data-heat]")) {
      const quote = bySymbol.get(tile.dataset.heat);
      if (!quote || quote.change_percent === undefined) continue;
      tile.style.background = heatColor(quote.change_percent);
    }

    for (const cell of cells) {
      const quote = bySymbol.get(cell.dataset.quote);
      if (!quote) continue;
      const field = cell.dataset.field;
      const digits = Number(cell.dataset.digits || 2);
      const value = quote[field];
      if (value === null || value === undefined) continue;

      let text;
      if (field === "change_percent") text = signed(value, 2, "%");
      else if (field === "change") text = signed(value, digits);
      else text = fmt(value, digits);

      if (setText(cell, text)) changed++;

      // 漲跌欄位的顏色跟著新數字走
      if (field === "change" || field === "change_percent") {
        cell.classList.toggle("pos", value > 0);
        cell.classList.toggle("neg", value < 0);
        cell.classList.toggle("muted", value === 0);
      }
    }

    // 市場狀態以台股那筆為準（其他市場的供應商不一定給）
    const withStatus = quotes.find(q => q.market_status);
    for (const node of document.querySelectorAll("[data-market-status]")) {
      if (withStatus && node.dataset.marketStatus === "tw") {
        node.textContent = withStatus.market_status;
      }
    }
    return changed;
  }

  function report(text, kind = "") {
    if (!status) return;
    status.textContent = text;
    status.className = "quote-status" + (kind ? " " + kind : "");
  }

  function stopTimers() {
    for (const p of Object.values(pace)) {
      clearTimeout(p.timer);
      p.timer = null;
    }
  }

  function schedule(kind, delay) {
    clearTimeout(pace[kind].timer);
    pace[kind].timer = setTimeout(() => refresh(kind), delay ?? pace[kind].wait);
  }

  function startTimers() {
    if (twSymbols.length) schedule("tw");
    if (otherSymbols.length) schedule("other");
  }

  async function refresh(kind) {
    if (disabled) return;
    const params = new URLSearchParams();
    if (kind === "tw") params.set("tw", twSymbols.join(","));
    else params.set("us", otherSymbols.join(","));

    let payload;
    try {
      const response = await fetch("/api/quotes?" + params.toString(),
                                   { cache: "no-store" });
      if (!response.ok) throw new Error("HTTP " + response.status);
      payload = await response.json();
    } catch (error) {
      failures++;
      // 沒有 functions 的環境（本機預覽、其他靜態主機）第一次就會失敗。
      // 快速重試一次確認不是暫時性的，再確定停用——不要讓「live」燈號在
      // 根本不會更新的頁面上繼續跳。
      if (failures === 1) {
        stopTimers();
        setTimeout(() => refresh(kind), 2000);
      } else {
        stopTimers();
        disabled = true;
        root.classList.add("is-static");
        report("此環境沒有報價代理，顯示的是建置當下的快照", "muted");
      }
      return;
    }

    const recovering = failures > 0;
    failures = 0;
    const changed = apply([...(payload.tw || []), ...(payload.other || [])]);

    // 自適應：有變化 → 回到基本節奏；連兩輪沒變化 → 間隔加倍到上限
    const p = pace[kind];
    if (changed > 0) {
      p.idle = 0;
      p.wait = CADENCE[kind].base;
    } else if (++p.idle >= 2) {
      p.wait = Math.min(p.wait * 2, CADENCE[kind].max);
    }
    if (recovering) startTimers();   // 失敗時兩組都停了，一起接回來
    else schedule(kind);

    if (kind === "other") {
      state.notSupported = payload.other_supported === false
                           && otherSymbols.length > 0;
      state.provider = payload.provider || null;
    }
    const when = new Date(payload.fetched_at || Date.now());
    const clock = when.toLocaleTimeString("zh-TW", { hour12: false });
    const via = state.provider ? `　·　美股經 ${state.provider}` : "";
    // 拆頁後單一頁面可能只有其中一組，節奏說明只列存在的那組
    const slowed = (twSymbols.length && pace.tw.wait > CADENCE.tw.base)
                || (otherSymbols.length && pace.other.wait > CADENCE.other.base);
    const parts = [];
    if (twSymbols.length) parts.push(`台股每 ${pace.tw.wait / 1000} 秒`);
    if (otherSymbols.length && !state.notSupported) {
      parts.push(`美股每 ${pace.other.wait / 1000} 秒`);
    }
    const cadence = parts.join("、")
      + (slowed ? "（盤外沒有變化，自動放慢）" : "");
    report(state.notSupported
      ? `台股已更新 ${clock}（每 ${pace.tw.wait / 1000} 秒）　·　`
        + "美股與新興市場維持建置快照（代理未設定 Finnhub 金鑰）"
      : `已更新 ${clock}${via}　·　${cadence}`);
    if (payload.errors?.length) {
      status.title = payload.errors.join("；");   // 詳情放 tooltip，不佔版面
    }
  }

  if (twSymbols.length) refresh("tw");
  if (otherSymbols.length) refresh("other");
  startTimers();

  // 分頁在背景時不必一直打 API
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
      stopTimers();
    } else if (!disabled) {
      if (twSymbols.length) refresh("tw");
      if (otherSymbols.length) refresh("other");
      startTimers();
    }
  });
})();
