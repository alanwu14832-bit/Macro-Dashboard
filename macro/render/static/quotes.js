/* ============================================================================
 * quotes.js — 讓報價頁在部署環境下自己更新。
 *
 * 頁面上每個報價欄位都帶 data-quote="代號" 與 data-field="price|change|..."，
 * 這支腳本向 /api/quotes（Netlify Function 代理）拿新報價後就地換掉數字。
 *
 * 沒有 /api/quotes 時（本機用 python http.server 預覽、或部署到不支援
 * functions 的主機）會安靜停用，頁面就維持建置時烤進去的快照——不顯示
 * 錯誤，也不會讓使用者誤以為數字有在更新。
 * ========================================================================== */
(() => {
  "use strict";

  const root = document.querySelector("[data-quotes-live]");
  if (!root) return;

  const REFRESH_MS = 20_000;
  const status = document.getElementById("quote-status");
  const cells = [...document.querySelectorAll("[data-quote]")];
  if (!cells.length) return;

  const twSymbols = [...new Set(cells.filter(c => c.dataset.market === "tw")
                                     .map(c => c.dataset.quote))];
  const otherSymbols = [...new Set(cells.filter(c => c.dataset.market !== "tw")
                                        .map(c => c.dataset.quote))];

  let timer = null;
  let failures = 0;

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

  function apply(quotes) {
    const bySymbol = new Map(quotes.map(q => [String(q.symbol), q]));
    let changed = 0;

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

  async function refresh() {
    const params = new URLSearchParams();
    if (twSymbols.length) params.set("tw", twSymbols.join(","));
    if (otherSymbols.length) params.set("us", otherSymbols.join(","));

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
      // 根本不會更新的頁面上繼續跳 20 秒。
      if (failures === 1) {
        clearInterval(timer);
        setTimeout(refresh, 2000);
      } else {
        clearInterval(timer);
        root.classList.add("is-static");
        report("此環境沒有報價代理，顯示的是建置當下的快照", "muted");
      }
      return;
    }

    if (failures) {           // 從失敗中恢復，把定時器接回來
      failures = 0;
      clearInterval(timer);
      timer = setInterval(refresh, REFRESH_MS);
    }
    const quotes = [...(payload.tw || []), ...(payload.other || [])];
    apply(quotes);

    const when = new Date(payload.fetched_at || Date.now());
    const clock = when.toLocaleTimeString("zh-TW", { hour12: false });
    const notSupported = payload.other_supported === false && otherSymbols.length;
    report(notSupported
      ? `台股已更新 ${clock}　·　美股與新興市場維持建置快照（未設定報價金鑰）`
      : `已更新 ${clock}　·　每 ${REFRESH_MS / 1000} 秒自動更新`);
  }

  refresh();
  timer = setInterval(refresh, REFRESH_MS);

  // 分頁在背景時不必一直打 API
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
      clearInterval(timer);
    } else if (failures < 2) {
      refresh();
      timer = setInterval(refresh, REFRESH_MS);
    }
  });
})();
