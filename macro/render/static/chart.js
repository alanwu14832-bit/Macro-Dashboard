/* ============================================================================
 * chart.js — dependency-free SVG charts for the macro dashboard.
 *
 * Every chart is a <div class="chart-card" data-chart='{...}'> whose JSON spec
 * the build writes. Rendering happens client-side so range switching, the
 * crosshair and the table view all work without a round trip, and so the page
 * still degrades to readable numbers if scripting is off (the table markup is
 * emitted server-side).
 *
 * Forms: line, area, bar, hbar, dumbbell, scatter, heat-strip.
 * Interaction contract (dataviz skill): crosshair snaps X on line/area, marks
 * are their own hit targets on bar/scatter, one tooltip lists every series,
 * labels inserted with textContent, hit targets larger than marks.
 * ========================================================================== */
(() => {
  "use strict";

  const NS = "http://www.w3.org/2000/svg";
  const SERIES_VARS = ["--series-1", "--series-2", "--series-3", "--series-4",
                       "--series-5", "--series-6", "--series-7", "--series-8"];

  const cssVar = (name) =>
    getComputedStyle(document.documentElement).getPropertyValue(name).trim();

  /** Resolve a spec color: a token name ("dovish") or a slot index. */
  function seriesColor(token, index) {
    if (token) {
      const named = cssVar("--" + token);
      if (named) return named;
      if (token.startsWith("#")) return token;
    }
    return cssVar(SERIES_VARS[index % SERIES_VARS.length]);
  }

  const el = (tag, attrs = {}, parent = null) => {
    const node = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (v !== null && v !== undefined) node.setAttribute(k, String(v));
    }
    if (parent) parent.appendChild(node);
    return node;
  };

  // ---------------------------------------------------------------- format --
  function fmtNum(v, digits) {
    if (v === null || v === undefined || Number.isNaN(v)) return "—";
    const d = digits ?? (Math.abs(v) >= 100 ? 0 : Math.abs(v) >= 10 ? 1 : 2);
    return v.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
  }
  const fmtVal = (v, spec) =>
    v === null || v === undefined ? "—"
      : (spec.prefix || "") + fmtNum(v, spec.digits) + (spec.suffix || "");

  function fmtDate(iso, freq) {
    if (!iso) return "";
    const [y, m, d] = iso.split("-");
    if (freq === "a") return y;
    if (freq === "q") return `${y} Q${Math.floor((+m - 1) / 3) + 1}`;
    if (freq === "m") return `${y}-${m}`;
    return `${y}-${m}-${d}`;
  }

  /** Axis ticks at 1/2/2.5/5 × 10^n, always including zero when in range. */
  function niceTicks(lo, hi, count = 5) {
    if (!(hi > lo)) { hi = lo + 1; lo -= 1; }
    const raw = (hi - lo) / count;
    const mag = Math.pow(10, Math.floor(Math.log10(raw)));
    const norm = raw / mag;
    const step = (norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 2.5 ? 2.5 : norm <= 5 ? 5 : 10) * mag;
    const out = [];
    for (let t = Math.ceil(lo / step) * step; t <= hi + step * 1e-9; t += step) {
      out.push(Math.abs(t) < step * 1e-9 ? 0 : t);
    }
    return out;
  }

  // ------------------------------------------------------------ tooltip UI --
  let tip = null;
  function tooltip() {
    if (!tip) {
      tip = document.createElement("div");
      tip.className = "tooltip";
      tip.setAttribute("role", "status");
      document.body.appendChild(tip);
    }
    return tip;
  }

  function showTip(host, x, y, dateLabel, rows) {
    const t = tooltip();
    t.textContent = "";
    if (dateLabel) {
      const head = document.createElement("div");
      head.className = "tt-date";
      head.textContent = dateLabel;            // untrusted text → textContent
      t.appendChild(head);
    }
    for (const r of rows) {
      const row = document.createElement("div");
      row.className = "tt-row";
      const key = document.createElement("span");
      key.className = "tt-key";
      key.style.background = r.color;
      const name = document.createElement("span");
      name.className = "tt-name";
      name.textContent = r.name;
      const val = document.createElement("span");
      val.className = "tt-val";
      val.textContent = r.value;
      row.append(key, name, val);
      t.appendChild(row);
    }
    t.dataset.open = "true";
    const box = t.getBoundingClientRect();
    const pad = 12;
    let left = x + pad, top = y - box.height - pad;
    if (left + box.width > window.innerWidth - 8) left = x - box.width - pad;
    if (top < 8) top = y + pad;
    t.style.left = `${Math.max(8, left + window.scrollX)}px`;
    t.style.top = `${Math.max(8, top + window.scrollY)}px`;
  }
  const hideTip = () => { if (tip) tip.dataset.open = "false"; };

  // ----------------------------------------------------------- data slicing -
  /** Keep the trailing `years` of the union date axis. */
  function sliceSpec(spec, years) {
    if (!years || years <= 0) return spec.series.map((s) => s.data);
    const last = spec.series.reduce((acc, s) => {
      const d = s.data.length ? s.data[s.data.length - 1][0] : null;
      return d && (!acc || d > acc) ? d : acc;
    }, null);
    if (!last) return spec.series.map((s) => s.data);
    const cut = new Date(last);
    cut.setFullYear(cut.getFullYear() - years);
    const iso = cut.toISOString().slice(0, 10);
    return spec.series.map((s) => s.data.filter((p) => p[0] >= iso));
  }

  // ================================================================ render ==
  function renderChart(card) {
    let spec;
    try { spec = JSON.parse(card.dataset.chart); }
    catch { return; }
    const wrap = card.querySelector(".chart-wrap");
    if (!wrap) return;

    const state = { years: spec.defaultYears ?? 0 };

    const draw = () => {
      wrap.querySelectorAll("svg").forEach((n) => n.remove());
      const data = sliceSpec(spec, state.years);
      const svg = (spec.type === "hbar" || spec.type === "dumbbell")
        ? drawCategorical(spec, data)
        : drawTimeSeries(spec, data);
      wrap.insertBefore(svg, wrap.firstChild);
    };

    // range control
    const tools = card.querySelector(".chart-tools .range-group");
    if (tools) {
      tools.addEventListener("click", (e) => {
        const btn = e.target.closest("button");
        if (!btn) return;
        state.years = Number(btn.dataset.years);
        tools.querySelectorAll("button").forEach((b) =>
          b.setAttribute("aria-pressed", String(b === btn)));
        draw();
      });
    }
    // table view toggle (the relief for low-contrast light-mode hues)
    const tableBtn = card.querySelector("[data-toggle-table]");
    const table = card.querySelector(".chart-table");
    if (tableBtn && table) {
      tableBtn.addEventListener("click", () => {
        const open = table.dataset.open === "true";
        table.dataset.open = String(!open);
        tableBtn.setAttribute("aria-expanded", String(!open));
        tableBtn.textContent = open ? "表格" : "收合表格";
      });
    }

    draw();
    card._redraw = draw;

    // 進場動畫：已經在視窗內的直接播，其餘等捲到才播。
    // 不完全依賴 IntersectionObserver——某些環境（背景分頁、部分嵌入式
    // 瀏覽器）它不會觸發，那時圖表仍要正常顯示，只是不播動畫。
    queueAnimation(card);

    // 響應式：容器寬度跨過斷點時重繪，讓刻度數量跟著改
    if ("ResizeObserver" in window) {
      let bucket = widthBucket(wrap.clientWidth);
      const ro = new ResizeObserver(() => {
        if (document.documentElement.classList.contains("rail-animating")) return;
        const next = widthBucket(wrap.clientWidth);
        if (next === bucket) return;
        bucket = next;
        draw();
      });
      ro.observe(wrap);
    }
  }

  /** 只在跨過這幾個級距時重繪，避免每一像素都重畫。 */
  function widthBucket(width) {
    return width < 380 ? 0 : width < 560 ? 1 : width < 820 ? 2 : 3;
  }

  // ------------------------------------------------------ time-series form --
  function drawTimeSeries(spec, data) {
    const W = 720, H = spec.height || 260;
    const m = { t: 14, r: spec.endLabels === false ? 16 : 54, b: 22, l: 46 };
    const iw = W - m.l - m.r, ih = H - m.t - m.b;

    const svg = el("svg", {
      class: "chart-svg", viewBox: `0 0 ${W} ${H}`,
      preserveAspectRatio: "xMidYMid meet", role: "img",
      "aria-label": spec.title || "chart",
    });

    // union X axis, ordinal positions so irregular calendars space evenly
    const dateSet = new Set();
    data.forEach((d) => d.forEach((p) => dateSet.add(p[0])));
    const dates = [...dateSet].sort();
    if (!dates.length) return svg;
    const xi = new Map(dates.map((d, i) => [d, i]));
    const X = (d) => m.l + (dates.length === 1 ? iw / 2 : (xi.get(d) / (dates.length - 1)) * iw);

    // 量價合圖：標了 axis:"right" 的序列（通常是成交量）走自己的刻度，
    // 而且壓在下方三成，不跟價格線爭畫面。左軸只由左軸序列決定範圍，
    // 否則成交量的量級會把價格線壓成一條平線。
    const isRight = (si) => spec.series[si]?.axis === "right";
    const hasRight = spec.series.some((s) => s.axis === "right");

    let lo = Infinity, hi = -Infinity;
    data.forEach((d, si) => {
      if (isRight(si)) return;
      d.forEach(([, v]) => {
        if (v === null) return;
        if (v < lo) lo = v; if (v > hi) hi = v;
      });
    });
    if (!Number.isFinite(lo)) return svg;
    if (spec.zeroBased && lo > 0) lo = 0;
    if (spec.includeZero && lo > 0) lo = 0;
    if (spec.includeZero && hi < 0) hi = 0;
    if (lo === hi) { lo -= 1; hi += 1; }
    const pad = (hi - lo) * 0.08;
    lo -= pad; hi += pad;
    const Y = (v) => m.t + ih - ((v - lo) / (hi - lo)) * ih;

    // 右軸：0 起算，最大值放大到只佔畫面下方 RIGHT_SHARE 的高度
    const RIGHT_SHARE = 0.32;
    let rhi = 0;
    if (hasRight) {
      data.forEach((d, si) => {
        if (!isRight(si)) return;
        d.forEach(([, v]) => { if (v !== null && v > rhi) rhi = v; });
      });
      if (rhi <= 0) rhi = 1;
    }
    const rightTop = rhi / RIGHT_SHARE;
    const YR = (v) => m.t + ih - (v / rightTop) * ih;

    // grid + y ticks
    for (const t of niceTicks(lo + pad, hi - pad, spec.yTicks || 4)) {
      if (t < lo || t > hi) continue;
      const y = Y(t);
      el("line", { class: t === 0 ? "zero-line" : "grid-line", x1: m.l, x2: m.l + iw, y1: y, y2: y }, svg);
      el("text", { class: "tick", x: m.l - 7, y: y + 3.5, "text-anchor": "end" }, svg)
        .textContent = fmtVal(t, spec);
    }

    // shaded reference band (e.g. the Fed's 2% target zone)
    if (spec.band) {
      const y1 = Y(spec.band[1]), y2 = Y(spec.band[0]);
      el("rect", { class: "band", x: m.l, y: Math.min(y1, y2), width: iw, height: Math.abs(y2 - y1) }, svg);
    }
    if (spec.target !== undefined && spec.target !== null) {
      el("line", { class: "zero-line", x1: m.l, x2: m.l + iw, y1: Y(spec.target), y2: Y(spec.target),
                   "stroke-dasharray": "0" }, svg);
    }

    // x ticks — first, last and evenly spaced interior.
    // 窄容器放不下六個日期標籤，硬塞會互相重疊。
    const rendered = svg.parentElement?.clientWidth || 720;
    const maxTicks = rendered < 380 ? 2 : rendered < 560 ? 3 : rendered < 820 ? 4 : 6;
    const nTicks = Math.min(maxTicks, dates.length);
    const seen = new Set();
    for (let i = 0; i < nTicks; i++) {
      const idx = Math.round((i / (nTicks - 1 || 1)) * (dates.length - 1));
      if (seen.has(idx)) continue;
      seen.add(idx);
      const d = dates[idx];
      el("text", {
        class: "tick", x: X(d), y: H - 6,
        "text-anchor": i === 0 ? "start" : i === nTicks - 1 ? "end" : "middle",
      }, svg).textContent = fmtDate(d, spec.freq);
    }
    el("line", { class: "axis-line", x1: m.l, x2: m.l + iw, y1: m.t + ih, y2: m.t + ih }, svg);

    // 右軸刻度（只標最大值一格，避免跟左軸的格線打架）
    if (hasRight) {
      for (const t of niceTicks(0, rhi, 2)) {
        if (t <= 0) continue;
        el("text", { class: "tick", x: m.l + iw + 6, y: YR(t) + 3.5,
                     "text-anchor": "start", opacity: 0.75 }, svg)
          .textContent = fmtVal(t, { digits: 0, suffix: spec.rightSuffix || "" });
      }
    }

    // marks — bar 可以是整張圖的型別，也可以是單一序列的 kind
    const isBar = spec.type === "bar";
    const anyBar = isBar || spec.series.some((s) => s.kind === "bar");
    const barW = anyBar ? Math.max(1, Math.min(24, (iw / dates.length) * 0.68)) : 0;

    // 柱子先畫，折線壓在上面
    const order = spec.series
      .map((s, si) => si)
      .sort((a, b) => (spec.series[b].kind === "bar" ? 0 : 1)
                    - (spec.series[a].kind === "bar" ? 0 : 1));

    order.forEach((si) => {
      const s = spec.series[si];
      const color = seriesColor(s.color, si);
      const pts = data[si].filter((p) => p[1] !== null);
      if (!pts.length) return;
      const useRight = isRight(si);
      const Yv = useRight ? YR : Y;

      if (isBar || s.kind === "bar") {
        const zero = useRight ? (m.t + ih) : Y(Math.max(lo, Math.min(hi, 0)));
        for (const [d, v] of pts) {
          const y = Yv(v), x = X(d) - barW / 2;
          const h = Math.abs(y - zero);
          const up = v >= 0;
          const fill = s.signColor
            ? cssVar(v >= 0 ? "--" + s.signColor[0] : "--" + s.signColor[1])
            : color;
          // 4px rounded data-end, square at the baseline
          const r = Math.min(4, barW / 2, h);
          const top = up ? y : zero;
          const path = up
            ? `M${x} ${top + h} L${x} ${top + r} Q${x} ${top} ${x + r} ${top} L${x + barW - r} ${top} Q${x + barW} ${top} ${x + barW} ${top + r} L${x + barW} ${top + h} Z`
            : `M${x} ${top} L${x} ${top + h - r} Q${x} ${top + h} ${x + r} ${top + h} L${x + barW - r} ${top + h} Q${x + barW} ${top + h} ${x + barW} ${top + h - r} L${x + barW} ${top} Z`;
          el("path", { d: path, fill, "shape-rendering": "crispEdges",
                       "data-bar": up ? "up" : "down" }, svg);
        }
      } else {
        const line = pts.map(([d, v], i) => `${i ? "L" : "M"}${X(d).toFixed(2)} ${Yv(v).toFixed(2)}`).join(" ");
        if (spec.type === "area") {
          const base = Yv(Math.max(lo, Math.min(hi, 0)));
          el("path", {
            d: `${line} L${X(pts[pts.length - 1][0]).toFixed(2)} ${base} L${X(pts[0][0]).toFixed(2)} ${base} Z`,
            fill: color, "fill-opacity": 0.1, "data-fade": "",
          }, svg);
        }
        el("path", {
          d: line, fill: "none", stroke: color, "stroke-width": 2,
          "stroke-linejoin": "round", "stroke-linecap": "round",
          "stroke-dasharray": s.dashed ? "5 4" : null,
          "data-line": s.dashed ? null : "",
        }, svg);

        // end marker with a 2px surface ring, plus a direct end-label
        const [ld, lv] = pts[pts.length - 1];
        el("circle", {
          cx: X(ld), cy: Yv(lv), r: 4, fill: color,
          stroke: cssVar("--surface"), "stroke-width": 2, "data-fade": "",
        }, svg);
        if (spec.endLabels !== false) {
          el("text", { class: "end-label", x: X(ld) + 9, y: Yv(lv) + 4,
                       "data-fade": "" }, svg)
            .textContent = fmtVal(lv, spec);
        }
      }
    });

    attachCrosshair(svg, spec, data, dates, X, m, ih, iw, isBar, barW,
                    (v, si) => (isRight(si) ? YR(v) : Y(v)));
    return svg;
  }

  /** Crosshair finds the X; one tooltip lists every series at that X. */
  function attachCrosshair(svg, spec, data, dates, X, m, ih, iw, isBar, barW, Yof) {
    const cross = el("line", { class: "crosshair", y1: m.t, y2: m.t + ih, x1: -99, x2: -99,
                               opacity: 0 }, svg);
    const dots = dates.length ? spec.series.map((s, si) =>
      el("circle", { r: 4, fill: seriesColor(s.color, si), stroke: cssVar("--surface"),
                     "stroke-width": 2, opacity: 0 }, svg)) : [];
    const hit = el("rect", { x: m.l, y: m.t, width: iw, height: ih, fill: "transparent",
                             style: "cursor:crosshair" }, svg);

    // Forward-fill each series onto the union axis, but only inside its own
    // range. Two daily series rarely share every trading day, and without this
    // the tooltip silently drops a series whenever its calendar has a hole —
    // the contract is one tooltip listing every series.
    const lookup = data.map((series) => {
      const own = new Map(series);
      if (!series.length) return own;
      const first = series[0][0], last = series[series.length - 1][0];
      const filled = new Map();
      let carried = null;
      for (const d of dates) {
        if (d < first || d > last) continue;
        const v = own.get(d);
        if (v !== undefined && v !== null) carried = v;
        if (carried !== null) filled.set(d, carried);
      }
      return filled;
    });

    const move = (evt) => {
      const rect = svg.getBoundingClientRect();
      const cx = evt.clientX ?? (evt.touches && evt.touches[0].clientX);
      if (cx === undefined) return;
      const vx = ((cx - rect.left) / rect.width) * 720;
      const frac = Math.max(0, Math.min(1, (vx - m.l) / iw));
      const idx = Math.round(frac * (dates.length - 1));
      const d = dates[idx];
      const px = X(d);
      cross.setAttribute("x1", px); cross.setAttribute("x2", px);
      cross.setAttribute("opacity", isBar ? 0 : 1);

      const rows = [];
      spec.series.forEach((s, si) => {
        const v = lookup[si].get(d);
        const dot = dots[si];
        if (v === undefined || v === null) { if (dot) dot.setAttribute("opacity", 0); return; }
        // 柱狀序列不放圓點，折線序列才放
        if (dot && !isBar && s.kind !== "bar") {
          dot.setAttribute("cx", px); dot.setAttribute("cy", Yof(v, si));
          dot.setAttribute("opacity", 1);
        }
        rows.push({ name: s.name, color: seriesColor(s.color, si),
                    value: s.axis === "right"
                      ? fmtVal(v, { digits: 0, suffix: spec.rightSuffix || "" })
                      : fmtVal(v, spec) });
      });
      if (rows.length) {
        showTip(svg, cx, rect.top + (evt.clientY ? 0 : 0) + rect.height * 0.35, fmtDate(d, spec.freq), rows);
      } else hideTip();
    };

    hit.addEventListener("pointermove", move);
    hit.addEventListener("pointerdown", move);
    hit.addEventListener("pointerleave", () => {
      cross.setAttribute("opacity", 0);
      dots.forEach((d) => d.setAttribute("opacity", 0));
      hideTip();
    });
  }

  // ------------------------------------------------------ categorical form --
  function drawCategorical(spec, data) {
    const rows = spec.rows || [];
    const W = 720;
    const rowH = spec.rowHeight || 26;
    const m = { t: 8, r: 58, b: 24, l: spec.labelWidth || 150 };
    const H = m.t + m.b + rows.length * rowH;
    const iw = W - m.l - m.r;

    const svg = el("svg", { class: "chart-svg", viewBox: `0 0 ${W} ${H}`,
                            preserveAspectRatio: "xMidYMid meet", role: "img",
                            "aria-label": spec.title || "chart" });
    if (!rows.length) return svg;

    let lo = 0, hi = 0;
    for (const r of rows) for (const v of (spec.type === "dumbbell" ? [r.a, r.b] : [r.value])) {
      if (v === null || v === undefined) continue;
      lo = Math.min(lo, v); hi = Math.max(hi, v);
    }
    if (lo === hi) hi = lo + 1;
    const span = hi - lo, padv = span * 0.06;
    lo -= padv; hi += padv;
    const X = (v) => m.l + ((v - lo) / (hi - lo)) * iw;

    for (const t of niceTicks(lo + padv, hi - padv, 4)) {
      const x = X(t);
      el("line", { class: t === 0 ? "zero-line" : "grid-line", x1: x, x2: x, y1: m.t, y2: m.t + rows.length * rowH }, svg);
      el("text", { class: "tick", x, y: H - 8, "text-anchor": "middle" }, svg).textContent = fmtVal(t, spec);
    }

    rows.forEach((r, i) => {
      const cy = m.t + i * rowH + rowH / 2;
      const label = el("text", { class: "tick", x: m.l - 9, y: cy + 3.5, "text-anchor": "end" }, svg);
      label.textContent = r.name;

      if (spec.type === "dumbbell") {
        const xa = X(r.a), xb = X(r.b);
        el("line", { x1: xa, x2: xb, y1: cy, y2: cy, stroke: cssVar("--axis"), "stroke-width": 2,
                     "stroke-linecap": "round" }, svg);
        el("circle", { cx: xa, cy, r: 4.5, fill: seriesColor(spec.series[0].color, 0),
                       stroke: cssVar("--surface"), "stroke-width": 2,
                       "data-fade": "" }, svg);
        el("circle", { cx: xb, cy, r: 4.5, fill: seriesColor(spec.series[1].color, 1),
                       stroke: cssVar("--surface"), "stroke-width": 2,
                       "data-fade": "" }, svg);
      } else {
        const zero = X(Math.max(lo, Math.min(hi, 0)));
        const x = X(r.value);
        const barH = Math.min(18, rowH - 8);
        const fill = r.color ? seriesColor(r.color, 0)
          : (spec.signColor ? cssVar(r.value >= 0 ? "--" + spec.signColor[0] : "--" + spec.signColor[1])
                            : seriesColor(spec.series?.[0]?.color, 0));
        const w = Math.abs(x - zero), left = Math.min(x, zero);
        const rr = Math.min(4, w, barH / 2);
        const path = r.value >= 0
          ? `M${left} ${cy - barH / 2} L${left + w - rr} ${cy - barH / 2} Q${left + w} ${cy - barH / 2} ${left + w} ${cy - barH / 2 + rr} L${left + w} ${cy + barH / 2 - rr} Q${left + w} ${cy + barH / 2} ${left + w - rr} ${cy + barH / 2} L${left} ${cy + barH / 2} Z`
          : `M${left + w} ${cy - barH / 2} L${left + rr} ${cy - barH / 2} Q${left} ${cy - barH / 2} ${left} ${cy - barH / 2 + rr} L${left} ${cy + barH / 2 - rr} Q${left} ${cy + barH / 2} ${left + rr} ${cy + barH / 2} L${left + w} ${cy + barH / 2} Z`;
        el("path", { d: path, fill,
                     "data-bar": r.value >= 0 ? "left" : "right" }, svg);
        // Positive bars label past their right end; negative bars label just
        // right of the baseline. Labelling a negative bar past its LEFT end
        // walks into the category-name gutter and collides with it — and a
        // label must never be clipped or overlapped to make it fit.
        el("text", { class: "end-label",
                     x: (r.value >= 0 ? x : zero) + 7, y: cy + 4,
                     "text-anchor": "start", "data-fade": "" }, svg)
          .textContent = fmtVal(r.value, spec);
      }

      // hit target spans the full row — bigger than the mark, per the spec
      const hit = el("rect", { x: 0, y: m.t + i * rowH, width: W, height: rowH,
                               fill: "transparent" }, svg);
      const rowsOut = spec.type === "dumbbell"
        ? [{ name: spec.series[0].name, color: seriesColor(spec.series[0].color, 0), value: fmtVal(r.a, spec) },
           { name: spec.series[1].name, color: seriesColor(spec.series[1].color, 1), value: fmtVal(r.b, spec) }]
        : [{ name: r.name, color: r.color ? seriesColor(r.color, 0) : seriesColor(spec.series?.[0]?.color, 0),
             value: fmtVal(r.value, spec) }];
      const enter = (e) => showTip(svg, e.clientX, e.clientY, r.sub || "", rowsOut);
      hit.addEventListener("pointermove", enter);
      hit.addEventListener("pointerleave", hideTip);
    });
    return svg;
  }

  // ------------------------------------------------------------- sparkline --
  function renderSpark(node) {
    let pts;
    try { pts = JSON.parse(node.dataset.spark); } catch { return; }
    if (!pts || pts.length < 2) return;
    const W = 96, H = 24;
    const vals = pts.map((p) => p[1]);
    const lo = Math.min(...vals), hi = Math.max(...vals);
    const span = hi - lo || 1;
    const X = (i) => (i / (pts.length - 1)) * (W - 4) + 2;
    const Y = (v) => H - 3 - ((v - lo) / span) * (H - 6);
    const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H,
                            class: "chart-svg", "aria-hidden": "true" });
    const color = seriesColor(node.dataset.sparkColor, 0);
    el("path", {
      d: pts.map((p, i) => `${i ? "L" : "M"}${X(i).toFixed(1)} ${Y(p[1]).toFixed(1)}`).join(" "),
      fill: "none", stroke: cssVar("--ink-muted"), "stroke-width": 1.5,
      "stroke-linejoin": "round", "stroke-linecap": "round", opacity: 0.55,
    }, svg);
    el("circle", { cx: X(pts.length - 1), cy: Y(vals[vals.length - 1]), r: 2.5, fill: color }, svg);
    node.textContent = "";
    node.appendChild(svg);
  }

  // ------------------------------------------------------- entrance animation
  const REDUCED = window.matchMedia("(prefers-reduced-motion: reduce)");

  /**
   * 進場動畫。原則是「動的是墨水，不是資料」——
   * 線圖用描邊長度把線畫出來、長條從基線長出來，任何時刻看到的位置
   * 都是最終位置，不會出現值被誇大或縮小的中間狀態。
   */
  function animateIn(svg, spec) {
    if (REDUCED.matches) return;
    const bars = [...svg.querySelectorAll("[data-bar]")];
    const lines = [...svg.querySelectorAll("[data-line]")];
    const fades = [...svg.querySelectorAll("[data-fade]")];

    lines.forEach((path, index) => {
      let length;
      try { length = path.getTotalLength(); } catch { return; }
      if (!length || !Number.isFinite(length)) return;
      path.style.strokeDasharray = `${length}`;
      path.style.strokeDashoffset = `${length}`;
      path.style.transition = `stroke-dashoffset 820ms cubic-bezier(.4,0,.2,1) ${index * 110}ms`;
      requestAnimationFrame(() => { path.style.strokeDashoffset = "0"; });
      // 動畫結束後把 dash 屬性拿掉，否則虛線樣式的序列會被蓋掉
      setTimeout(() => {
        path.style.strokeDasharray = "";
        path.style.transition = "";
      }, 900 + index * 110);
    });

    bars.forEach((bar, index) => {
      bar.style.transformBox = "fill-box";
      bar.style.transformOrigin = bar.dataset.bar === "up" ? "50% 100%"
        : bar.dataset.bar === "down" ? "50% 0%"
        : bar.dataset.bar === "left" ? "0% 50%" : "100% 50%";
      const axis = (bar.dataset.bar === "up" || bar.dataset.bar === "down")
        ? "scaleY" : "scaleX";
      bar.style.transform = `${axis}(0)`;
      bar.style.transition =
        `transform 560ms cubic-bezier(.34,1.2,.64,1) ${Math.min(index * 26, 420)}ms`;
      requestAnimationFrame(() => { bar.style.transform = ""; });
    });

    const settle = lines.length ? 700 : 240;
    fades.forEach((node) => {
      node.style.opacity = "0";
      node.style.transition = `opacity 320ms ease ${settle}ms`;
      requestAnimationFrame(() => { node.style.opacity = ""; });
    });
  }

  /** 一張圖只播一次。 */
  const seen = new WeakSet();

  function playOnce(card) {
    if (seen.has(card)) return;
    seen.add(card);
    const svg = card.querySelector("svg");
    if (svg) animateIn(svg, null);
  }

  function inViewport(node) {
    const rect = node.getBoundingClientRect();
    return rect.top < window.innerHeight && rect.bottom > 0;
  }

  /* 待播清單。IntersectionObserver 是效率較好的路徑，但實測有些環境
     （背景分頁、部分嵌入式瀏覽器）它一次都不觸發，圖表就永遠不會播。
     所以再掛一條 rAF 節流的捲動備援；playOnce 本身冪等，兩條路徑
     同時命中也只會播一次。清單清空後兩個監聽都會拆掉。 */
  const pending = new Set();
  let draining = false;

  function drain() {
    draining = false;
    for (const card of [...pending]) {
      if (!inViewport(card)) continue;
      pending.delete(card);
      watcher?.unobserve(card);
      playOnce(card);
    }
    if (!pending.size) {
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onScroll);
    }
  }

  function onScroll() {
    if (draining) return;
    draining = true;
    requestAnimationFrame(drain);
  }

  function queueAnimation(card) {
    if (REDUCED.matches) return;
    if (inViewport(card)) { playOnce(card); return; }
    pending.add(card);
    watcher?.observe(card);
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll, { passive: true });
  }
  const watcher = ("IntersectionObserver" in window)
    ? new IntersectionObserver((entries) => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue;
          watcher.unobserve(entry.target);
          pending.delete(entry.target);
          playOnce(entry.target);
        }
      }, { rootMargin: "0px 0px -8% 0px", threshold: 0.12 })
    : null;

  // ------------------------------------------------------------------ init --
  function init() {
    document.querySelectorAll("[data-chart]").forEach(renderChart);
    document.querySelectorAll("[data-spark]").forEach(renderSpark);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else init();

  // Re-render on theme change so marks pick up the mode's own steps.
  const repaint = () => {
    document.querySelectorAll(".chart-card").forEach((c) => c._redraw && c._redraw());
    document.querySelectorAll("[data-spark]").forEach(renderSpark);
  };
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", repaint);
  document.addEventListener("themechange", repaint);
  document.addEventListener("layoutchange", repaint);
  window.addEventListener("scroll", hideTip, { passive: true });

  // 動態插入的圖表（例如 /explore/ 每次重畫）也要被接手
  document.addEventListener("chartadded", (event) => {
    const card = event.detail?.card;
    if (card) renderChart(card);
  });
})();
