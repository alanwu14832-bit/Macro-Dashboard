/* ============================================================================
 * sidebar.js — 側邊選單的收合、行動版抽屜、主題切換。
 *
 * 設計上避免「卡頓感」的三件事：
 *   1. 只動 grid-template-columns 與 transform，不去改每個子元素的寬度
 *   2. 收合／展開期間把圖表的重繪暫停到動畫結束，避免動畫中一直重排 SVG
 *   3. 尊重 prefers-reduced-motion：整段動畫關掉，狀態照樣正確
 * ========================================================================== */
(() => {
  "use strict";

  const root = document.documentElement;
  const rail = document.getElementById("rail");
  const scrim = document.getElementById("rail-scrim");
  const toggle = document.getElementById("rail-toggle");
  const opener = document.getElementById("rail-open");
  const MOBILE = window.matchMedia("(max-width: 959px)");
  const REDUCED = window.matchMedia("(prefers-reduced-motion: reduce)");

  const store = (key, value) => {
    try { localStorage.setItem(key, value); } catch { /* 無痕模式 */ }
  };

  /* ------------------------------------------------------------ 桌機收合 -- */
  function setCollapsed(collapsed) {
    root.classList.toggle("rail-collapsed", collapsed);
    if (toggle) toggle.setAttribute("aria-expanded", String(!collapsed));
    store("rail", collapsed ? "collapsed" : "expanded");

    // 動畫期間先讓圖表停手，結束後再量一次寬度重繪
    root.classList.add("rail-animating");
    const done = () => {
      root.classList.remove("rail-animating");
      document.dispatchEvent(new Event("layoutchange"));
    };
    if (REDUCED.matches) done();
    else setTimeout(done, 280);
  }

  /* ------------------------------------------------------ 行動版抽屜 ----- */
  function setDrawer(open) {
    root.classList.toggle("drawer-open", open);
    if (scrim) scrim.hidden = !open;
    if (opener) opener.setAttribute("aria-expanded", String(open));
    document.body.style.overflow = open ? "hidden" : "";
    if (open) {
      const first = rail?.querySelector(".nav-item");
      first?.focus({ preventScroll: true });
    }
  }

  toggle?.addEventListener("click", () => {
    if (MOBILE.matches) setDrawer(false);
    else setCollapsed(!root.classList.contains("rail-collapsed"));
  });

  opener?.addEventListener("click", () => setDrawer(true));
  scrim?.addEventListener("click", () => setDrawer(false));

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && root.classList.contains("drawer-open")) {
      setDrawer(false);
      opener?.focus();
    }
    // 跟大多數側邊欄一致的快捷鍵
    if (event.key === "[" && (event.metaKey || event.ctrlKey)) {
      event.preventDefault();
      if (!MOBILE.matches) setCollapsed(!root.classList.contains("rail-collapsed"));
    }
  });

  // 點選單項目就關抽屜（行動版）
  rail?.addEventListener("click", (event) => {
    if (event.target.closest(".nav-item") && MOBILE.matches) setDrawer(false);
  });

  // 換到桌機尺寸時把抽屜狀態清掉，避免殘留 overflow:hidden
  MOBILE.addEventListener("change", (event) => {
    if (!event.matches) setDrawer(false);
    document.dispatchEvent(new Event("layoutchange"));
  });

  /* ---------------------------------------------------------- 主題切換 --- */
  const themeButton = document.getElementById("theme-toggle");
  if (themeButton) {
    const label = () => {
      const current = root.getAttribute("data-theme");
      themeButton.textContent =
        current === "dark" ? "淺色" : current === "light" ? "深色" : "主題";
    };
    label();
    themeButton.addEventListener("click", () => {
      const current = root.getAttribute("data-theme");
      const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
      const next = current
        ? (current === "dark" ? "light" : "dark")
        : (prefersDark ? "light" : "dark");
      root.setAttribute("data-theme", next);
      store("theme", next);
      label();
      document.dispatchEvent(new Event("themechange"));
    });
  }

  /* --------------------------------------------- 進場動畫（分段浮現） ---- */
  // 只跑一次，且只在使用者沒有要求減少動態時。
  if (!REDUCED.matches) {
    const blocks = [...document.querySelectorAll(".content section, .verdict, .live-bar")];
    blocks.forEach((node, index) => {
      node.style.setProperty("--enter-delay", `${Math.min(index * 45, 320)}ms`);
      node.classList.add("enter");
    });
    requestAnimationFrame(() => {
      requestAnimationFrame(() => root.classList.add("entered"));
    });
  }
})();
