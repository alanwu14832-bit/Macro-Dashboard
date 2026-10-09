/* 頭版的圖與互動。只有 / 這一頁載入；沒有它，頁面仍然讀得完（圖以外的每個數字
 * 都是伺服器端烘進 HTML 的）。
 *
 *   1. 核心 PCE 對門檻的圖——Y 軸就是版面那條直線，刻度寫在頁邊
 *   2. 「只看頁邊」：把正文調淡，只沿著直線讀今天的變化（快捷鍵 M）
 *   3. 捲到才出現：正文先到，頁邊的批註晚一拍「寫上去」
 */
(function () {
  "use strict";
  var root = document.documentElement;

  /* ------------------------------------------------------------ 只看頁邊 -- */
  var scanBtn = document.querySelector(".fp .scan");
  function scan(on) {
    root.classList.toggle("scanning", on);
    if (scanBtn) scanBtn.setAttribute("aria-pressed", String(on));
  }
  if (scanBtn) {
    scanBtn.addEventListener("click", function () { scan(!root.classList.contains("scanning")); });
    document.addEventListener("keydown", function (event) {
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      var tag = event.target && event.target.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
      if (document.querySelector("dialog[open]") || root.classList.contains("drawer-open")) return;
      if (event.key === "m" || event.key === "M") scan(!root.classList.contains("scanning"));
      else if (event.key === "Escape") scan(false);
    });
  }

  /* -------------------------------------------- 圖：核心 PCE 對寫死的門檻 -- */
  var figure = document.querySelector(".fp .gchart");
  var plot = figure && figure.querySelector(".plot");
  var yax = figure && figure.querySelector(".yax");
  var spec = null;
  if (figure) { try { spec = JSON.parse(figure.dataset.gate); } catch (e) { spec = null; } }
  var lastW = 0;
  function r(x) { return Math.round(x * 10) / 10; }
  function monthIndex(iso) { return Number(iso.slice(0, 4)) * 12 + Number(iso.slice(5, 7)) - 1; }

  function draw() {
    if (!spec || !plot) return;
    var W = Math.floor(plot.getBoundingClientRect().width);
    if (!W || W === lastW) return;
    lastW = W;
    var mob = W < 440;
    var H = mob ? 272 : Math.round(Math.max(330, Math.min(440, W * 0.41)));
    var pT = mob ? 22 : 30, pB = 38, pR = mob ? 86 : 146, pw = W - pR;
    var D = spec.values, months = spec.dates.map(monthIndex);
    var m0 = months[0], span = Math.max(1, months[months.length - 1] - m0), n = D.length;

    // 值域：涵蓋資料、兩道門檻與目標，上下各留一點；取到 0.1
    var lo = Math.min.apply(null, D.concat([spec.goal, spec.low])) - 0.3;
    var hi = Math.max.apply(null, D.concat([spec.high])) + 0.25;
    lo = Math.floor(lo * 10) / 10; hi = Math.ceil(hi * 10) / 10;
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

    var yHigh = r(Y(spec.high)), yLow = r(Y(spec.low)), yGate = r(Y(spec.gate)), yGoal = r(Y(spec.goal));
    var xe = r(X(n - 1)), ye = r(Y(D[n - 1])), yb = H - pB, xb = xe + (mob ? 10 : 15);
    var s = '<svg viewBox="0 0 ' + W + " " + H + '" width="' + W + '" height="' + H + '" aria-hidden="true" focusable="false">';
    s += '<defs><clipPath id="gate-above"><rect x="0" y="0" width="' + W + '" height="' + yHigh + '"/></clipPath>';
    s += '<pattern id="gate-hatch" width="7" height="7" patternUnits="userSpaceOnUse" patternTransform="rotate(-45)">';
    s += '<rect class="hz-bg" width="7" height="7"/><line class="hz" x1="0" y1="0" x2="0" y2="7"/></pattern></defs>';

    // 格線：整 0.5，避開門檻與目標
    var named = [spec.low, spec.high, spec.goal], grid = [];
    for (var g = Math.ceil(lo * 2) / 2; g <= hi + 1e-9; g += 0.5) {
      var near = named.some(function (v) { return Math.abs(v - g) < 0.14; });
      if (!near && g > lo + 0.05) grid.push(Math.round(g * 10) / 10);
    }
    grid.forEach(function (v) { s += '<line class="g" x1="0" x2="' + pw + '" y1="' + r(Y(v)) + '" y2="' + r(Y(v)) + '"/>'; });
    s += '<line class="g" x1="0" x2="' + pw + '" y1="' + yb + '" y2="' + yb + '"/>';
    s += '<line class="goal" x1="0" x2="' + pw + '" y1="' + yGoal + '" y2="' + yGoal + '"/>';

    // 高於上門檻的時段：斜線。這是「判定為高」的區域，不是變動
    segs.forEach(function (seg) {
      if (seg.length < 2) return;
      var a = r(X(seg[0])), b = r(X(seg[seg.length - 1]));
      s += '<path class="area" clip-path="url(#gate-above)" d="M' + a + "," + yHigh + "L" + seg.map(pt).join("L") + "L" + b + "," + yHigh + 'Z"/>';
    });

    // 兩道門檻：最近的那一道加重，另一道退後
    [[spec.low, yLow], [spec.high, yHigh]].forEach(function (t) {
      var key = Math.abs(t[0] - spec.gate) < 1e-9;
      s += '<line class="thr' + (key ? "" : " thr2") + '" x1="0" x2="' + (key ? xb : pw) + '" y1="' + t[1] + '" y2="' + t[1] + '"/>';
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

    // 近三月年化：同一個月的另一個讀法，畫成空心圓
    s += '<g class="late">';
    if (spec.ann3 !== null && spec.ann3 > lo && spec.ann3 < hi) {
      var ya = r(Y(spec.ann3)), side = ya > ye ? 1 : -1;
      if (Math.abs(ya - ye) > 20) s += '<line class="conn" x1="' + xe + '" x2="' + xe + '" y1="' + (ye + 9 * side) + '" y2="' + (ya - 8 * side) + '"/>';
      s += '<circle class="m3" cx="' + xe + '" cy="' + ya + '" r="4.5"/>';
      var nearGoal = Math.abs(ya - yGoal) < 26;
      s += '<text class="lab" x="' + (xe - 12) + '" y="' + (ya + (nearGoal ? (mob ? 19 : 21) : -10)) + '" text-anchor="end">' + spec.trend + "</text>";
    }
    s += '<circle class="dot" cx="' + xe + '" cy="' + ye + '" r="5.5"/>';
    s += '<text class="endv" x="' + (xe + (mob ? 9 : 13)) + '" y="' + (ye - (mob ? 11 : 14)) + '">' + spec.last + "</text></g>";

    // 現在離最近那道門檻的距離
    if (Math.abs(ye - yGate) > 6) {
      s += '<g class="late2"><path class="br" d="M' + (xb - 5) + "," + (ye + 0.5) + "H" + xb + "V" + yGate + "H" + (xb - 5) + '"/>';
      s += '<text class="gapt" x="' + (xb + (mob ? 8 : 12)) + '" y="' + r((ye + yGate) / 2 + 5) + '">還差 <tspan class="num">' + spec.gap + "</tspan></text></g>";
    }
    s += "</svg>";
    plot.innerHTML = s;
    plot.style.minHeight = H + "px";
    Array.prototype.forEach.call(plot.querySelectorAll(".ln"), function (line) {
      try { line.style.setProperty("--len", Math.ceil(line.getTotalLength()) + 2); } catch (e) { /* 舊瀏覽器 */ }
    });

    // 刻度寫在頁邊，短橫線穿過直線——Y 軸就是版面那條線
    var labels = [
      { y: yGate, html: "門檻 <i>" + spec.gate.toFixed(1) + "</i>", key: true },
      { y: yGoal, html: "目標 <i>" + spec.goal.toFixed(1) + "</i>" }
    ];
    var other = Math.abs(spec.gate - spec.high) < 1e-9 ? spec.low : spec.high;
    labels.push({ y: r(Y(other)), html: "門檻 <i>" + other.toFixed(1) + "</i>" });
    grid.forEach(function (v) {
      var y = r(Y(v));
      if (labels.every(function (l) { return Math.abs(l.y - y) > 17; })) labels.push({ y: y, html: "<i>" + v.toFixed(1) + "</i>" });
    });
    yax.innerHTML = labels.map(function (l) {
      return '<span class="yl' + (l.key ? " key" : "") + '" style="top:' + l.y + 'px">' + l.html + "</span>";
    }).join("");
  }
  if (spec) {
    draw();
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(function () { lastW = 0; draw(); });
    var timer;
    window.addEventListener("resize", function () { clearTimeout(timer); timer = setTimeout(draw, 120); });
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
