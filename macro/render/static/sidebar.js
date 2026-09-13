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

  /* ------------------------------------- 彈簧：可攔截、會接手當下的速度 -- */
  // 為什麼不是 CSS transition：過渡一開始就把時間與曲線綁死，手指再碰它
  // 只能從頭播一次。彈簧是狀態機——任何一帧都能用「現在的位置＋現在的
  // 速度」接手，這是抽屜可以被半路抓住、反向拖回去的前提。
  function runSpring(from, to, v0, { damping, response }, onFrame, onEnd) {
    let x = from, v = v0, last = performance.now(), raf = 0, alive = true;
    const w = (2 * Math.PI) / response;
    const k = w * w, c = 2 * damping * w;     // 質量取 1
    const step = (now) => {
      let dt = Math.min((now - last) / 1000, 0.064);  // 切回前景的大 dt 會炸開
      last = now;
      while (dt > 0) {                        // 固定小步長積分才數值穩定
        const h = Math.min(dt, 1 / 240);
        dt -= h;
        v += (-k * (x - to) - c * v) * h;
        x += v * h;
      }
      if (Math.abs(x - to) < 0.4 && Math.abs(v) < 24) {
        x = to; v = 0; alive = false;
        onFrame(x); if (onEnd) onEnd();
        return;
      }
      onFrame(x);
      raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return {
      cancel() { alive = false; cancelAnimationFrame(raf); },
      get x() { return x; },
      get v() { return v; },
      get alive() { return alive; },
    };
  }

  /* ------------------------------------------------------ 行動版抽屜 ----- */
  // 位置模型：x = 0 全開，x = -W 全關，單位 px。整段動態都由這一個數字
  // 驅動 transform 與遮罩透明度，所以「拖到一半放手」跟「按鈕開關」走的
  // 是同一條路徑（spatial consistency），不會有兩種不同的動法。
  const DRAWER = { damping: 1.0, response: 0.3 };        // 臨界阻尼：不回彈
  const FLICK = { damping: 0.82, response: 0.3 };        // 有動量才允許微彈
  const PROJECT = 0.45;   // 秒：用放手速度投射停止點
  const FLICK_V = 480;    // px/s 以上算甩動，方向直接定案
  const HYST = 10;        // px：超過才認定這是水平手勢

  let anim = null, x = null, W = 0, suppressClick = false;

  const railWidth = () => (rail ? rail.getBoundingClientRect().width : 300);
  const isOpen = () => root.classList.contains("drawer-open");
  const focusFirst = () =>
    rail?.querySelector(".nav-item")?.focus({ preventScroll: true });

  function paint(nx) {
    x = nx;
    if (rail) rail.style.transform = `translate3d(${nx.toFixed(2)}px,0,0)`;
    if (scrim) {
      const t = 1 + nx / W;                  // 遮罩跟著位置走，不是自己計時
      scrim.style.opacity = String(Math.max(0, Math.min(1, t)));
    }
  }

  function clearInline() {
    if (anim) anim.cancel();
    anim = null; x = null;
    if (rail) rail.style.transform = "";
    if (scrim) scrim.style.opacity = "";
  }

  function setDrawer(open, velocity) {
    const wasOpen = isOpen();
    root.classList.toggle("drawer-open", open);
    if (opener) opener.setAttribute("aria-expanded", String(open));
    document.body.style.overflow = open ? "hidden" : "";

    if (!MOBILE.matches) {                   // 桌機沒有抽屜，交還給 CSS
      clearInline();
      if (scrim) scrim.hidden = !open;
      return;
    }

    W = railWidth();
    if (scrim) scrim.hidden = false;         // 動畫期間要在場才收得到點擊
    if (x === null) x = wasOpen ? 0 : -W;

    const to = open ? 0 : -W;
    const v0 = velocity !== undefined ? velocity
             : (anim && anim.alive ? anim.v : 0);
    if (anim) anim.cancel();

    if (REDUCED.matches) {                   // 減少動態：直接到位，狀態照舊
      paint(to);
      if (!open && scrim) scrim.hidden = true;
      if (open) focusFirst();
      return;
    }
    anim = runSpring(x, to, v0,
                     Math.abs(v0) > FLICK_V ? FLICK : DRAWER, paint,
                     () => { if (!isOpen() && scrim) scrim.hidden = true; });
    if (open) focusFirst();
  }

  /* ------------------------------- 拖曳關閉：1:1 跟手，放手接續當前速度 -- */
  // 橡皮筋：拖過全開位置後位移遞減趨緩，而不是撞到一道看不見的牆。
  const rubber = (over, dim) => (1 - 1 / (over / (dim * 0.55) + 1)) * dim * 0.55;

  let drag = null;

  function velocityOf(d) {
    if (d.samples.length < 2) return 0;
    const [t0, x0] = d.samples[0];
    const [t1, x1] = d.samples[d.samples.length - 1];
    const dt = t1 - t0;
    return dt > 8 ? ((x1 - x0) / dt) * 1000 : 0;   // px/s
  }

  function onDown(event) {
    if (!MOBILE.matches || !isOpen() || event.button) return;
    W = railWidth();
    if (x === null) x = 0;
    drag = { id: event.pointerId, sx: event.clientX, sy: event.clientY,
             base: x, claimed: false, samples: [], el: event.currentTarget };
  }

  function onMove(event) {
    if (!drag || event.pointerId !== drag.id) return;
    const dx = event.clientX - drag.sx;
    const dy = event.clientY - drag.sy;
    if (!drag.claimed) {
      // 平行辨識：水平與垂直同時候選，誰先超過門檻誰贏，輸的直接取消。
      if (Math.abs(dx) < HYST && Math.abs(dy) < HYST) return;
      if (Math.abs(dx) <= Math.abs(dy)) { drag = null; return; }
      drag.claimed = true;
      if (anim) { anim.cancel(); anim = null; }   // 半路攔截飛行中的彈簧
      try { drag.el.setPointerCapture(drag.id); } catch (e) { /* 滑鼠即可 */ }
    }
    event.preventDefault();
    let nx = drag.base + dx;
    if (nx > 0) nx = rubber(nx, W);          // 往右拖過頭：橡皮筋
    if (nx < -W) nx = -W;                    // 往左不必，關到底就是關
    drag.samples.push([performance.now(), nx]);
    if (drag.samples.length > 4) drag.samples.shift();
    paint(nx);
  }

  function onUp(event) {
    if (!drag || event.pointerId !== drag.id) return;
    const d = drag;
    drag = null;
    if (!d.claimed) return;                  // 只是點一下，交給 click 處理
    suppressClick = true;                    // 別讓這次拖曳尾隨一個 click
    requestAnimationFrame(() => { suppressClick = false; });
    const v = velocityOf(d);
    // 動量投射：用速度推算停止點再決定去哪一端，而不是看放手瞬間的位置。
    // 慢慢拖到 40% 會關回去，快速甩一下即使只移動 20% 也會關。
    const open = Math.abs(v) > FLICK_V ? v > 0 : (x + v * PROJECT) > -W / 2;
    // 拖曳關閉也要把 history 退回去，否則返回鍵會多出一格空按。先清旗標
    // 再 back()，popstate 就會看到 pushed=false 而不重複關一次——這裡要
    // 立刻用帶速度的 setDrawer 接手，速度交接不能讓給 popstate。
    if (!open && pushed) { pushed = false; history.back(); }
    setDrawer(open, v);
  }

  // 頁面被切到背景時 rAF 會被瀏覽器凍結，彈簧就停在半空——iOS 上把 APP
  // 切走再切回來很常見。沒人在看就不要跑動畫：直接讓它到位。
  document.addEventListener("visibilitychange", () => {
    if (document.hidden && anim && anim.alive) {
      anim.cancel();
      anim = null;
      paint(isOpen() ? 0 : -W);
      if (!isOpen() && scrim) scrim.hidden = true;
    }
  });

  [rail, scrim].forEach((el) => {
    if (!el) return;
    el.addEventListener("pointerdown", onDown);
    el.addEventListener("pointermove", onMove, { passive: false });
    el.addEventListener("pointerup", onUp);
    el.addEventListener("pointercancel", onUp);
  });
  root.classList.add("rail-js");              // 通知 CSS：過渡讓開，JS 接手

  /* ------------------------------------------- 抽屜的返回鍵契約 --------- */
  // 開抽屜要推一筆 history entry，否則 iOS 的系統邊緣返回手勢會在抽屜開著
  // 的狀態下把整個 app 導走——使用者以為自己在關抽屜，結果離開了頁面。
  // 推了之後所有「關閉」動作一律走 history.back()，讓 popstate 成為唯一的
  // 關閉路徑，狀態與歷史永遠一致。
  let pushed = false;
  let pendingHref = null;

  function openDrawer() {
    if (!pushed) {
      try { history.pushState({ drawer: true }, ""); pushed = true; } catch (e) { /* 無痕 */ }
    }
    setDrawer(true);
  }

  function closeDrawer() {
    if (pushed) history.back();   // → popstate 收尾
    else setDrawer(false);
  }

  window.addEventListener("popstate", () => {
    if (!pushed) return;
    pushed = false;
    setDrawer(false);
    if (pendingHref) {            // 從抽屜點連結：先退掉抽屜那一格再走
      const href = pendingHref;
      pendingHref = null;
      location.href = href;
    }
  });

  toggle?.addEventListener("click", () => {
    if (MOBILE.matches) closeDrawer();
    else setCollapsed(!root.classList.contains("rail-collapsed"));
  });

  opener?.addEventListener("click", () => openDrawer());
  scrim?.addEventListener("click", () => {
    if (!suppressClick) closeDrawer();
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && root.classList.contains("drawer-open")) {
      closeDrawer();
      opener?.focus();
    }
    // 跟大多數側邊欄一致的快捷鍵
    if (event.key === "[" && (event.metaKey || event.ctrlKey)) {
      event.preventDefault();
      if (!MOBILE.matches) setCollapsed(!root.classList.contains("rail-collapsed"));
    }
  });

  // 點選單項目就關抽屜（行動版）。剛拖曳過就不算點擊。
  rail?.addEventListener("click", (event) => {
    if (suppressClick) { event.preventDefault(); return; }
    const link = event.target.closest(".nav-item");
    if (!link || !MOBILE.matches) return;
    if (pushed && link.href) {
      // 攔下來先退掉抽屜那筆 history，再由 popstate 導航——否則從 B 頁
      // 按返回會回到「A 頁但抽屜是開的」那一格，白按一次。
      event.preventDefault();
      pendingHref = link.href;
      closeDrawer();
      return;
    }
    setDrawer(false);
  });

  // 換到桌機尺寸時把抽屜狀態清掉，避免殘留 overflow:hidden
  MOBILE.addEventListener("change", (event) => {
    if (!event.matches) {
      if (pushed) { pushed = false; history.back(); }
      setDrawer(false);
    }
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
    const applyTheme = (next) => {
      root.setAttribute("data-theme", next);
      store("theme", next);
      label();
      document.dispatchEvent(new Event("themechange"));
    };
    themeButton.addEventListener("click", () => {
      const current = root.getAttribute("data-theme");
      const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
      const next = current
        ? (current === "dark" ? "light" : "dark")
        : (prefersDark ? "light" : "dark");
      // 整頁調色盤瞬間翻面很刺眼。有 View Transition 就交叉淡入，
      // 沒有（或使用者要求減少動態）就照舊瞬間切換——兩邊都是對的結果。
      if (!REDUCED.matches && document.startViewTransition) {
        document.startViewTransition(() => applyTheme(next));
      } else {
        applyTheme(next);
      }
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

  /* ------------------------------------------------------ 回到頂端 ------- */
  const toTop = document.getElementById("to-top");
  if (toTop) {
    let ticking = false;
    const update = () => {
      ticking = false;
      toTop.hidden = window.scrollY < 600;
    };
    window.addEventListener("scroll", () => {
      if (!ticking) { ticking = true; requestAnimationFrame(update); }
    }, { passive: true });
    toTop.addEventListener("click", () => {
      window.scrollTo({ top: 0, behavior: REDUCED.matches ? "auto" : "smooth" });
    });
    update();
  }

  /* ------------------------------------ 側欄捲動同步（看到哪亮到哪） ----- */
  // 只針對目前頁展開的小標清單。用 scroll + rAF 而不是 IntersectionObserver：
  // 要的是「最後一個越過頂端的區塊」這種單調狀態，不是可視比例。
  const subLinks = [...document.querySelectorAll(".nav-details[open] .nav-sub a")]
    .filter((a) => a.hash);
  if (subLinks.length) {
    const targets = subLinks
      .map((a) => {
        try { return [document.getElementById(a.hash.slice(1)), a]; }
        catch { return [null, a]; }
      })
      .filter(([t]) => t);
    let current = null;
    let spyTick = false;
    // 位置先量好存起來：在 scroll 處理器裡讀 offsetTop 會每帧強迫版面重算，
    // 那正是捲動掉帧的典型來源。摺疊展開或換尺寸才需要重量。
    let marks = [];
    const measure = () => {
      marks = targets.map(([node, link]) => [node.offsetTop, link]);
    };
    const spy = () => {
      spyTick = false;
      const line = window.scrollY + 120;   // topbar 高度 + 一點緩衝
      let hit = null;
      for (const [top, link] of marks) {
        if (top <= line) hit = link;
        else break;
      }
      if (hit !== current) {
        current?.classList.remove("now");
        hit?.classList.add("now");
        current = hit;
      }
    };
    const remeasure = () => { measure(); spy(); };
    measure();
    window.addEventListener("scroll", () => {
      if (!spyTick) { spyTick = true; requestAnimationFrame(spy); }
    }, { passive: true });
    window.addEventListener("resize", remeasure);
    document.addEventListener("layoutchange", remeasure);
    // <details> 的 toggle 不冒泡，用捕獲階段收；展開會把後面的區塊往下推。
    document.addEventListener("toggle", remeasure, true);
    spy();
  }
})();
