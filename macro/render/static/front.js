/* 頭版的圖與互動。只有 / 這一頁載入；沒有它，頁面仍然讀得完（圖以外的每個數字
 * 都是伺服器端烘進 HTML 的）。
 *
 *   1. 頭條的圖（美國版：核心 PCE 對門檻；台灣版：景氣分數對燈號）
 *      ——Y 軸就是版面那條直線，刻度寫在頁邊
 *   2. 「只看頁邊」：把正文調淡，只沿著直線讀今天的變化（快捷鍵 M）
 *   3. 版別：美國｜台灣，切換時停在同一段
 *   4. 捲到才出現：正文先到，頁邊的批註晚一拍「寫上去」
 */
(function () {
  "use strict";
  var root = document.documentElement;
  window.__fp = true;      // 告訴 <head> 裡的保險計時器：這支腳本有跑起來

  /* ------------------------------------------------------------ 只看頁邊 -- */
  // 兩個版各有一顆按鈕（各在自己的頭條旁邊），狀態是同一個。
  var scanBtns = Array.prototype.slice.call(document.querySelectorAll(".fp .scan"));
  function scan(on) {
    root.classList.toggle("scanning", on);
    scanBtns.forEach(function (btn) { btn.setAttribute("aria-pressed", String(on)); });
  }
  if (scanBtns.length) {
    scanBtns.forEach(function (btn) {
      btn.addEventListener("click", function () { scan(!root.classList.contains("scanning")); });
    });
    document.addEventListener("keydown", function (event) {
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      var tag = event.target && event.target.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
      if (document.querySelector("dialog[open]") || root.classList.contains("drawer-open")) return;
      if (event.key === "m" || event.key === "M") scan(!root.classList.contains("scanning"));
      else if (event.key === "Escape") scan(false);
    });
  }

  /* -------------------------------------------- 圖：一條線對寫死的分界 -- */
  // 兩個版各一張：美國版是核心 PCE 對本站的門檻，台灣版是景氣分數對國發會的燈號。
  // 值域、分界、要塗的區域都由伺服器端算好放在 data-gate，這裡只管畫。
  var charts = Array.prototype.map.call(document.querySelectorAll(".fp .gchart"), function (figure, index) {
    var spec = null;
    try { spec = JSON.parse(figure.dataset.gate); } catch (e) { spec = null; }
    return { index: index, spec: spec, lastW: 0,
             plot: figure.querySelector(".plot"), yax: figure.querySelector(".yax") };
  }).filter(function (c) { return c.spec && c.plot; });
  function r(x) { return Math.round(x * 10) / 10; }
  function monthIndex(iso) { return Number(iso.slice(0, 4)) * 12 + Number(iso.slice(5, 7)) - 1; }

  function draw(c) {
    var spec = c.spec, plot = c.plot;
    // 另一個版的圖是 display:none，寬度量出來是 0——等它被切出來再畫
    var W = Math.floor(plot.getBoundingClientRect().width);
    if (!W || W === c.lastW) return;
    c.lastW = W;
    var mob = W < 440;
    var H = mob ? 228 : Math.round(Math.max(250, Math.min(330, W * 0.29)));
    var pT = mob ? 20 : 26, pB = 34, pR = mob ? 80 : 132, pw = W - pR;
    var D = spec.values, months = spec.dates.map(monthIndex);
    var m0 = months[0], span = Math.max(1, months[months.length - 1] - m0), n = D.length;
    var lo = spec.lo, hi = spec.hi, dg = spec.digits;
    var thr = spec.thr || [], goal = spec.goal;
    function X(i) { return pw * (months[i] - m0) / span; }
    function Y(v) { return pT + (H - pT - pB) * (1 - (v - lo) / (hi - lo)); }

    // 連續月份才連線。缺月（例如政府關門沒有發布的那一個月）切成兩段，
    // 中間只畫一條虛線橋接——不讓讀者看到一條不存在的趨勢。
    var segs = [], cur = [0];
    for (var i = 1; i < n; i++) {
      if (months[i] - months[i - 1] === 1) cur.push(i);
      else { segs.push(cur); cur = [i]; }
    }
    segs.push(cur);
    function pt(i) { return r(X(i)) + "," + r(Y(D[i])); }

    var yGate = r(Y(spec.gate));
    var xe = r(X(n - 1)), ye = r(Y(D[n - 1])), yb = H - pB, xb = xe + (mob ? 10 : 15);
    var zones = spec.zones || [];
    var s = '<svg viewBox="0 0 ' + W + " " + H + '" width="' + W + '" height="' + H + '" aria-hidden="true" focusable="false">';
    s += "<defs>";
    zones.forEach(function (zone, zi) {
      var edge = r(Y(zone.v));
      s += '<clipPath id="gz-' + c.index + "-" + zi + '"><rect x="0" width="' + W + '"'
        + (zone.dir === "above" ? ' y="0" height="' + edge + '"' : ' y="' + edge + '" height="' + Math.max(0, H - edge) + '"')
        + "/></clipPath>";
    });
    // 斜線的圖樣只有打斜線的那張圖需要（CSS 用 #gate-hatch 指到它）
    if (zones.some(function (zone) { return zone.style === "hatch"; })) {
      s += '<pattern id="gate-hatch" width="7" height="7" patternUnits="userSpaceOnUse" patternTransform="rotate(-45)">';
      s += '<rect class="hz-bg" width="7" height="7"/><line class="hz" x1="0" y1="0" x2="0" y2="7"/></pattern>';
    }
    s += "</defs>";

    // 格線：避開分界與目標
    var named = thr.map(function (t) { return t.v; }).concat(goal ? [goal.v] : []), grid = [];
    for (var g = Math.ceil(lo / spec.grid) * spec.grid; g <= hi + 1e-9; g += spec.grid) {
      var near = named.some(function (v) { return Math.abs(v - g) < spec.grid * 0.28; });
      if (!near && g > lo + spec.grid * 0.1) grid.push(Math.round(g * 10) / 10);
    }
    grid.forEach(function (v) { s += '<line class="g" x1="0" x2="' + pw + '" y1="' + r(Y(v)) + '" y2="' + r(Y(v)) + '"/>'; });
    s += '<line class="g" x1="0" x2="' + pw + '" y1="' + yb + '" y2="' + yb + '"/>';
    if (goal) s += '<line class="goal" x1="0" x2="' + pw + '" y1="' + r(Y(goal.v)) + '" y2="' + r(Y(goal.v)) + '"/>';

    // 越過分界的時段。斜線＝本站規則判定的區域；灰底＝官方定義的區間。兩者都不是變動
    zones.forEach(function (zone, zi) {
      var edge = r(Y(zone.v));
      segs.forEach(function (seg) {
        if (seg.length < 2) return;
        var a = r(X(seg[0])), b = r(X(seg[seg.length - 1]));
        s += '<path class="' + (zone.style === "hatch" ? "area" : "area zone") + '" clip-path="url(#gz-' + c.index + "-" + zi + ')" d="M'
          + a + "," + edge + "L" + seg.map(pt).join("L") + "L" + b + "," + edge + 'Z"/>';
      });
    });

    // 分界線：最近的那一道加重，其餘退後
    thr.forEach(function (t) {
      var key = Math.abs(t.v - spec.gate) < 1e-9, y = r(Y(t.v));
      s += '<line class="thr' + (key ? "" : " thr2") + '" x1="0" x2="' + (key ? xb : pw) + '" y1="' + y + '" y2="' + y + '"/>';
    });

    // X 軸：每年一月
    spec.dates.forEach(function (iso, i) {
      if (iso.slice(5, 7) !== "01") return;
      var x = r(X(i));
      if (x < 24 || x > pw - 24) return;
      s += '<line class="xt" x1="' + x + '" x2="' + x + '" y1="' + yb + '" y2="' + (yb + 6) + '"/>';
      s += '<text class="xl" x="' + x + '" y="' + (yb + 23) + '" text-anchor="middle">' + iso.slice(0, 4) + "</text>";
    });
    // 線：實線段＋缺口的虛線橋
    for (var k = 1; k < segs.length; k++) {
      var p = segs[k - 1][segs[k - 1].length - 1], q = segs[k][0];
      s += '<path class="bridge" d="M' + pt(p) + "L" + pt(q) + '"/>';
    }
    segs.forEach(function (seg) {
      if (seg.length < 2) { s += '<circle class="lone" cx="' + r(X(seg[0])) + '" cy="' + r(Y(D[seg[0]])) + '" r="2.6"/>'; return; }
      s += '<path class="ln" d="M' + seg.map(pt).join("L") + '"/>';
    });

    // 近三月年化：同一個月的另一個讀法，畫成空心圓（只有核心 PCE 那張有）
    s += '<g class="late">';
    if (spec.ann3 !== null && spec.ann3 !== undefined && spec.ann3 > lo && spec.ann3 < hi) {
      var ya = r(Y(spec.ann3)), side = ya > ye ? 1 : -1;
      if (Math.abs(ya - ye) > 20) s += '<line class="conn" x1="' + xe + '" x2="' + xe + '" y1="' + (ye + 9 * side) + '" y2="' + (ya - 8 * side) + '"/>';
      s += '<circle class="m3" cx="' + xe + '" cy="' + ya + '" r="4.5"/>';
      var nearGoal = goal && Math.abs(ya - r(Y(goal.v))) < 26;
      s += '<text class="lab" x="' + (xe - 12) + '" y="' + (ya + (nearGoal ? (mob ? 19 : 21) : -10)) + '" text-anchor="end">' + spec.trend + "</text>";
    }
    s += '<circle class="dot" cx="' + xe + '" cy="' + ye + '" r="5.5"/>';
    s += '<text class="endv" x="' + (xe + (mob ? 9 : 13)) + '" y="' + (ye - (mob ? 11 : 14)) + '">' + spec.last + "</text></g>";

    // 現在離最近那道分界的距離
    if (Math.abs(ye - yGate) > 6) {
      s += '<g class="late2"><path class="br" d="M' + (xb - 5) + "," + (ye + 0.5) + "H" + xb + "V" + yGate + "H" + (xb - 5) + '"/>';
      s += '<text class="gapt" x="' + (xb + (mob ? 8 : 12)) + '" y="' + r((ye + yGate) / 2 + 5) + '">' + spec.gapWord + ' <tspan class="num">' + spec.gap + "</tspan></text></g>";
    }
    s += "</svg>";
    plot.innerHTML = s;
    plot.style.minHeight = H + "px";
    Array.prototype.forEach.call(plot.querySelectorAll(".ln"), function (line) {
      try { line.style.setProperty("--len", Math.ceil(line.getTotalLength()) + 2); } catch (e) { /* 舊瀏覽器 */ }
    });

    // 刻度寫在頁邊，短橫線穿過直線——Y 軸就是版面那條線
    var labels = [];
    thr.forEach(function (t) {
      var key = Math.abs(t.v - spec.gate) < 1e-9;
      var name = mob && t.short ? t.short : t.name;
      labels[key ? "unshift" : "push"]({ y: r(Y(t.v)), html: name + " <i>" + t.v.toFixed(dg) + "</i>", key: key });
    });
    if (goal) labels.splice(1, 0, { y: r(Y(goal.v)), html: goal.name + " <i>" + goal.v.toFixed(dg) + "</i>" });
    // 兩個分界靠太近時，後面那個的字讓開（線還在圖上）
    labels = labels.filter(function (l, at) {
      return labels.slice(0, at).every(function (prev) { return Math.abs(prev.y - l.y) > 17; });
    });
    grid.forEach(function (v) {
      var y = r(Y(v));
      if (labels.every(function (l) { return Math.abs(l.y - y) > 21; })) labels.push({ y: y, html: "<i>" + v.toFixed(dg) + "</i>" });
    });
    if (c.yax) {
      c.yax.innerHTML = labels.map(function (l) {
        return '<span class="yl' + (l.key ? " key" : "") + '" style="top:' + l.y + 'px">' + l.html + "</span>";
      }).join("");
    }
  }
  function drawAll(force) {
    charts.forEach(function (c) { if (force) c.lastW = 0; draw(c); });
  }
  if (charts.length) {
    drawAll();
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(function () { drawAll(true); });
    var timer;
    window.addEventListener("resize", function () { clearTimeout(timer); timer = setTimeout(drawAll, 120); });
  }

  /* ------------------------------------------------------ 版別：美國｜台灣 -- */
  // 兩個版都在同一份 HTML 裡，<html data-ed> 決定顯示哪一個（<head> 的 BOOT 在第一次
  // 繪製前就設好了）。兩版的段落一一對應、錨點只差一個 tw- 前綴，所以切換時讀者
  // 停在同一段：正在看美國版的「今日價格」，切過去就是台灣版的「今日價格」。
  var tabs = Array.prototype.slice.call(document.querySelectorAll("[data-ed-set]"));
  function edition() { return root.getAttribute("data-ed") === "tw" ? "tw" : "us"; }
  function counterpart(id, to) {
    var base = id.replace(/^tw-/, "");
    return to === "tw" ? "tw-" + base : base;
  }
  function syncTabs() {
    var now = edition();
    tabs.forEach(function (tab) {
      if (tab.getAttribute("data-ed-set") === now) tab.setAttribute("aria-current", "true");
      else tab.removeAttribute("aria-current");
    });
  }
  // 視窗上緣現在落在哪一段（看得見的段落裡，最後一個頂端已經越過上緣的）
  function anchorSection() {
    var hit = null;
    Array.prototype.forEach.call(document.querySelectorAll(".fp section[id]"), function (sec) {
      if (!sec.offsetParent && sec.getClientRects().length === 0) return;
      var top = sec.getBoundingClientRect().top;
      if (top <= 150) hit = { el: sec, top: top };
    });
    return hit;
  }
  function setEdition(to, opts) {
    if (to !== "tw") to = "us";
    if (to === edition()) return;
    var from = (opts && opts.keep === false) ? null : anchorSection();
    root.classList.add("again");                 // 刊頭的進場不再演一遍
    root.setAttribute("data-ed", to);
    try { localStorage.setItem("ed", to); } catch (e) { /* 私密瀏覽 */ }
    syncTabs();
    drawAll();
    if (from) {
      var inEdition = from.el.closest(".edn");
      var target = inEdition ? document.getElementById(counterpart(from.el.id, to)) : from.el;
      if (target) window.scrollBy(0, target.getBoundingClientRect().top - from.top);
    }
    if (!root.classList.contains("still")) {
      root.classList.remove("ed-swap");
      void root.offsetWidth;                     // 重新觸發一次淡入
      root.classList.add("ed-swap");
    }
    try {
      var url = new URL(location.href);
      if (to === "tw") url.searchParams.set("ed", "tw"); else url.searchParams.delete("ed");
      url.hash = "";
      history.replaceState(null, "", url.pathname + url.search);
    } catch (e) { /* file:// 或舊瀏覽器 */ }
    // 側欄的捲動同步要重新量：另一版的段落剛剛才有位置
    document.dispatchEvent(new Event("layoutchange"));
  }
  if (tabs.length) {
    syncTabs();
    tabs.forEach(function (tab) {
      tab.addEventListener("click", function (event) {
        if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
        event.preventDefault();
        setEdition(tab.getAttribute("data-ed-set"));
      });
    });
    // 站內搜尋或抽屜連到另一版的段落（/#tw-facts）：先換版，再捲過去
    window.addEventListener("hashchange", function () {
      var id = decodeURIComponent(location.hash.slice(1));
      var target = id && document.getElementById(id);
      var home = target && target.closest(".edn");
      if (!home || home.getAttribute("data-ed") === edition()) return;
      setEdition(home.getAttribute("data-ed"), { keep: false });
      target.scrollIntoView();
    });
  }

  /* ---------------------------------------------------------- 捲到才出現 -- */
  var reveal = Array.prototype.slice.call(document.querySelectorAll(".fp .rv"));
  if (root.classList.contains("still") || !("IntersectionObserver" in window)) {
    reveal.forEach(function (el) { el.classList.add("seen"); });
  } else {
    var observer = new IntersectionObserver(function (entries) {
      var order = 0;
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) return;
        entry.target.style.setProperty("--rd", (order++ * 70) + "ms");
        entry.target.classList.add("seen");
        observer.unobserve(entry.target);
      });
    }, { rootMargin: "0px 0px -7% 0px", threshold: 0.08 });
    reveal.forEach(function (el) { observer.observe(el); });
  }

  /* -------------------------------------------- 切換日報／夜報時一起過渡 -- */
  document.addEventListener("themechange", function () {
    root.classList.add("theming");
    setTimeout(function () { root.classList.remove("theming"); }, 460);
  });
})();
