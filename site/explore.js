/* ============================================================================
 * explore.js — 自選指標瀏覽器。
 *
 * 從目錄挑最多 4 檔序列，選轉換方式與時間區間，即時比較。
 * 序列資料向 /api/series 取（serverless function 代理 FRED），所以看到的
 * 永遠是 FRED 上的最新版，不是建置當下的快照。
 *
 * 一個刻意的限制：單位不同的序列不會被畫在同一條 Y 軸上。混合單位時
 * 會自動切到「指數化」並說明原因——雙軸圖是最容易誤導人的圖表形式，
 * 兩條線的交叉點完全由縮放決定，沒有任何意義。
 * ========================================================================== */
(() => {
  "use strict";

  const root = document.getElementById("explore");
  if (!root) return;

  const MAX_SERIES = 4;
  const TRANSFORMS = {
    level: { label: "原始值", needsBase: false },
    yoy: { label: "年增率 %", needsBase: true, suffix: "%" },
    ann3: { label: "近三月年化 %", needsBase: true, suffix: "%" },
    index: { label: "指數化（起點=100）", needsBase: true },
    zscore: { label: "z 分數", needsBase: true },
  };
  const RANGES = [["1Y", 1], ["3Y", 3], ["5Y", 5], ["10Y", 10], ["全期", 0]];
  const PER_YEAR = { d: 252, w: 52, m: 12, q: 4, a: 1 };

  const state = {
    catalogue: [],
    selected: [],          // [{id, name, unit, freq, group_label}]
    data: new Map(),       // id -> {dates, values}
    transform: "level",
    years: 10,
    query: "",
    group: "",
  };

  const $ = (sel) => root.querySelector(sel);

  /* ------------------------------------------------------------- 轉換 ---- */
  function transform(series, meta, mode) {
    const { dates, values } = series;
    const per = PER_YEAR[meta.freq] || 12;

    if (mode === "level") return { dates, values };

    if (mode === "yoy" || mode === "ann3") {
      const periods = mode === "yoy" ? per : Math.max(1, Math.round(per / 4));
      const power = mode === "yoy" ? 1 : per / periods;
      const d = [], v = [];
      for (let i = periods; i < values.length; i++) {
        const base = values[i - periods];
        if (!base) continue;
        const ratio = values[i] / base;
        if (ratio <= 0) continue;
        d.push(dates[i]);
        v.push((Math.pow(ratio, power) - 1) * 100);
      }
      return { dates: d, values: v };
    }

    if (mode === "index") {
      const base = values.find((x) => x);
      if (!base) return { dates, values };
      return { dates, values: values.map((x) => (x / base) * 100) };
    }

    if (mode === "zscore") {
      const n = values.length;
      if (n < 3) return { dates, values };
      const mean = values.reduce((a, b) => a + b, 0) / n;
      const sd = Math.sqrt(values.reduce((a, b) => a + (b - mean) ** 2, 0) / (n - 1));
      if (!sd) return { dates, values };
      return { dates, values: values.map((x) => (x - mean) / sd) };
    }
    return { dates, values };
  }

  function clip(series, years) {
    if (!years || !series.dates.length) return series;
    const last = new Date(series.dates[series.dates.length - 1]);
    last.setFullYear(last.getFullYear() - years);
    const cut = last.toISOString().slice(0, 10);
    const from = series.dates.findIndex((d) => d >= cut);
    if (from <= 0) return series;
    return { dates: series.dates.slice(from), values: series.values.slice(from) };
  }

  /* ------------------------------------------------------------- 取值 ---- */
  async function load(id) {
    if (state.data.has(id)) return state.data.get(id);
    const response = await fetch(`/api/series?id=${encodeURIComponent(id)}`);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();
    if (payload.error) throw new Error(payload.error);
    const value = { dates: payload.dates, values: payload.values };
    state.data.set(id, value);
    return value;
  }

  /* ------------------------------------------------------------- 統計 ---- */
  function stats(values) {
    if (!values.length) return null;
    const last = values[values.length - 1];
    const n = values.length;
    const mean = values.reduce((a, b) => a + b, 0) / n;
    const sd = n > 1
      ? Math.sqrt(values.reduce((a, b) => a + (b - mean) ** 2, 0) / (n - 1)) : 0;
    const sorted = [...values].sort((a, b) => a - b);
    const below = sorted.filter((x) => x <= last).length;
    return {
      last, min: sorted[0], max: sorted[n - 1], mean,
      z: sd ? (last - mean) / sd : null,
      pct: (below / n) * 100,
    };
  }

  const fmt = (value, digits = 2) =>
    value === null || value === undefined || !Number.isFinite(value) ? "—"
      : value.toLocaleString("en-US", { minimumFractionDigits: digits,
                                        maximumFractionDigits: digits });

  /* ------------------------------------------------------------- 渲染 ---- */
  function renderPicker() {
    const list = $("#ex-list");
    const query = state.query.toLowerCase();
    const matches = state.catalogue.filter((s) => {
      if (state.group && s.group !== state.group) return false;
      if (!query) return true;
      return s.name.toLowerCase().includes(query) || s.id.toLowerCase().includes(query);
    }).slice(0, 60);

    list.textContent = "";
    if (!matches.length) {
      const empty = document.createElement("p");
      empty.className = "muted";
      empty.textContent = "沒有符合的序列。";
      list.appendChild(empty);
      return;
    }
    for (const item of matches) {
      const chosen = state.selected.some((s) => s.id === item.id);
      const button = document.createElement("button");
      button.type = "button";
      button.className = "ex-item" + (chosen ? " is-on" : "");
      button.dataset.id = item.id;
      button.disabled = !chosen && state.selected.length >= MAX_SERIES;

      const name = document.createElement("span");
      name.className = "ex-name";
      name.textContent = item.name;
      const meta = document.createElement("span");
      meta.className = "ex-meta";
      meta.textContent = `${item.group_label}　${item.unit || "—"}　${item.last || ""}`;
      button.append(name, meta);
      list.appendChild(button);
    }
  }

  function renderChosen() {
    const box = $("#ex-chosen");
    box.textContent = "";
    if (!state.selected.length) {
      const hint = document.createElement("p");
      hint.className = "muted";
      hint.textContent = "還沒有選任何指標。從下方清單挑，最多 4 個。";
      box.appendChild(hint);
      return;
    }
    state.selected.forEach((item, index) => {
      const chip = document.createElement("span");
      chip.className = "ex-chip";
      const dot = document.createElement("span");
      dot.className = "ex-dot";
      dot.style.background = `var(--series-${index + 1})`;
      const label = document.createElement("span");
      label.textContent = item.name;
      const drop = document.createElement("button");
      drop.type = "button";
      drop.className = "ex-drop";
      drop.dataset.drop = item.id;
      drop.setAttribute("aria-label", `移除 ${item.name}`);
      drop.textContent = "×";
      chip.append(dot, label, drop);
      box.appendChild(chip);
    });
  }

  function unitsDiffer() {
    const units = new Set(state.selected.map((s) => s.unit || ""));
    return units.size > 1;
  }

  function renderChart() {
    const host = $("#ex-chart");
    const note = $("#ex-note");
    host.textContent = "";
    note.textContent = "";

    if (!state.selected.length) return;

    // 單位不同就不能共用一條 Y 軸——自動切到指數化並說明。
    let mode = state.transform;
    if (unitsDiffer() && (mode === "level")) {
      mode = "index";
      note.textContent =
        "選到的指標單位不同，已自動切換為指數化。單位不同的序列畫在同一條 "
        + "Y 軸上，交叉點只反映縮放比例，不代表任何事實。";
    }

    const series = [];
    for (const [index, item] of state.selected.entries()) {
      const raw = state.data.get(item.id);
      if (!raw) continue;
      const shaped = clip(transform(raw, item, mode), state.years);
      if (!shaped.dates.length) continue;
      series.push({
        name: item.name + (mode === "level" && item.unit ? `（${item.unit}）` : ""),
        color: `series-${index + 1}`,
        data: shaped.dates.map((d, i) => [d, Math.round(shaped.values[i] * 10000) / 10000]),
      });
    }
    if (!series.length) return;

    const spec = {
      type: "line", series, defaultYears: 0,
      suffix: TRANSFORMS[mode].suffix || "",
      freq: state.selected[0].freq || "m",
      height: 320, digits: mode === "level" ? undefined : 2,
    };

    const card = document.createElement("figure");
    card.className = "chart-card";
    card.style.margin = "0";
    card.dataset.chart = JSON.stringify(spec);
    const head = document.createElement("div");
    head.className = "chart-head";
    const title = document.createElement("figcaption");
    title.className = "chart-title";
    title.textContent = TRANSFORMS[mode].label;
    head.appendChild(title);
    const wrap = document.createElement("div");
    wrap.className = "chart-wrap";
    card.append(head, wrap);
    host.appendChild(card);

    document.dispatchEvent(new CustomEvent("chartadded", { detail: { card } }));
    renderStats(mode);
  }

  function renderStats(mode) {
    const host = $("#ex-stats");
    host.textContent = "";
    if (!state.selected.length) return;

    const table = document.createElement("table");
    const thead = document.createElement("thead");
    thead.innerHTML = "";
    const headRow = document.createElement("tr");
    for (const label of ["指標", "最新", "區間最低", "區間最高", "平均", "z 分數", "區間百分位"]) {
      const th = document.createElement("th");
      th.textContent = label;
      headRow.appendChild(th);
    }
    thead.appendChild(headRow);
    const tbody = document.createElement("tbody");

    for (const item of state.selected) {
      const raw = state.data.get(item.id);
      if (!raw) continue;
      const shaped = clip(transform(raw, item, mode), state.years);
      const s = stats(shaped.values);
      if (!s) continue;
      const row = document.createElement("tr");
      const cells = [
        item.name,
        fmt(s.last), fmt(s.min), fmt(s.max), fmt(s.mean),
        s.z === null ? "—" : fmt(s.z), fmt(s.pct, 0) + "%",
      ];
      cells.forEach((text, i) => {
        const td = document.createElement("td");
        if (i) td.className = "num";
        td.textContent = text;
        row.appendChild(td);
      });
      tbody.appendChild(row);
    }
    table.append(thead, tbody);
    const wrap = document.createElement("div");
    wrap.className = "table-wrap";
    wrap.appendChild(table);
    host.appendChild(wrap);
  }

  /* --------------------------------------------------------- 網址狀態 ---- */
  function syncUrl() {
    const params = new URLSearchParams();
    if (state.selected.length) params.set("s", state.selected.map((x) => x.id).join(","));
    if (state.transform !== "level") params.set("t", state.transform);
    if (state.years !== 10) params.set("y", String(state.years));
    const query = params.toString();
    history.replaceState(null, "", query ? `?${query}` : location.pathname);
  }

  async function refresh() {
    $("#ex-status").textContent = state.selected.length ? "載入中…" : "";
    try {
      await Promise.all(state.selected.map((s) => load(s.id)));
      $("#ex-status").textContent = "";
    } catch (error) {
      $("#ex-status").textContent =
        "取不到序列資料。此環境可能沒有 /api/series 代理（本機預覽會如此）。";
    }
    renderChosen();
    renderPicker();
    renderChart();
    syncUrl();
  }

  /* --------------------------------------------------------------- 事件 -- */
  root.addEventListener("click", (event) => {
    const add = event.target.closest(".ex-item");
    if (add) {
      const item = state.catalogue.find((s) => s.id === add.dataset.id);
      if (!item) return;
      const at = state.selected.findIndex((s) => s.id === item.id);
      if (at >= 0) state.selected.splice(at, 1);
      else if (state.selected.length < MAX_SERIES) state.selected.push(item);
      refresh();
      return;
    }
    const drop = event.target.closest("[data-drop]");
    if (drop) {
      state.selected = state.selected.filter((s) => s.id !== drop.dataset.drop);
      refresh();
      return;
    }
    const range = event.target.closest("[data-years]");
    if (range) {
      state.years = Number(range.dataset.years);
      root.querySelectorAll("[data-years]").forEach((b) =>
        b.setAttribute("aria-pressed", String(b === range)));
      renderChart();
      syncUrl();
    }
  });

  root.addEventListener("input", (event) => {
    if (event.target.id === "ex-search") {
      state.query = event.target.value;
      renderPicker();
    }
  });

  root.addEventListener("change", (event) => {
    if (event.target.id === "ex-transform") {
      state.transform = event.target.value;
      renderChart();
      syncUrl();
    }
    if (event.target.id === "ex-group") {
      state.group = event.target.value;
      renderPicker();
    }
  });

  /* ---------------------------------------------------------------- 啟動 - */
  (async () => {
    let payload;
    try {
      payload = await (await fetch("/data/catalogue.json")).json();
    } catch {
      $("#ex-status").textContent = "載入指標目錄失敗。";
      return;
    }
    state.catalogue = payload.series || [];

    const groupSelect = $("#ex-group");
    for (const group of payload.groups || []) {
      const option = document.createElement("option");
      option.value = group.key;
      option.textContent = group.label;
      groupSelect.appendChild(option);
    }

    const transformSelect = $("#ex-transform");
    for (const [key, meta] of Object.entries(TRANSFORMS)) {
      const option = document.createElement("option");
      option.value = key;
      option.textContent = meta.label;
      transformSelect.appendChild(option);
    }

    // 從網址還原，沒有就給一組有意思的預設
    const params = new URLSearchParams(location.search);
    const ids = (params.get("s") || "UNRATE,CPILFESL").split(",").filter(Boolean);
    state.transform = params.get("t") || "level";
    state.years = params.has("y") ? Number(params.get("y")) : 10;
    transformSelect.value = state.transform;
    root.querySelectorAll("[data-years]").forEach((b) =>
      b.setAttribute("aria-pressed", String(Number(b.dataset.years) === state.years)));

    state.selected = ids
      .map((id) => state.catalogue.find((s) => s.id === id))
      .filter(Boolean).slice(0, MAX_SERIES);

    refresh();
  })();
})();
