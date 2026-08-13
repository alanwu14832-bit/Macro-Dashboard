"""Shared bits every page uses: chart-spec builders and small blocks."""
from __future__ import annotations

from ..series import Series
from .html import (SEV_GLYPH, attr_json, callout, check_row, chart, esc, fmt,
                   signal_row, table, tag)

MAX_POINTS = 900          # 圖表點數上限，避免 HTML 過胖


def _stride(pairs: list, step: int) -> list:
    """每 step 取一點，但一定保留最後一點。

    單純的 pairs[::step] 會在長度不是 step 倍數時丟掉序列尾端，
    讓圖表末端標籤與同頁的數字卡對不起來。
    """
    if step <= 1 or len(pairs) <= 1:
        return pairs
    out = pairs[::step]
    if out[-1] is not pairs[-1]:
        out.append(pairs[-1])
    return out


def points(series: Series, years: float | None = None, *, every: int = 1) -> list:
    """Series -> [[iso date, value], ...]，必要時抽樣。"""
    if not series:
        return []
    s = series.last_years(years) if years else series
    pairs = s.pairs()
    if every > 1:
        pairs = _stride(pairs, every)
    if len(pairs) > MAX_POINTS:
        pairs = _stride(pairs, len(pairs) // MAX_POINTS + 1)
    return [[d.isoformat(), round(v, 4)] for d, v in pairs]


def line_chart(title: str, series_specs: list[tuple[Series, str, str | None]], *,
               sub: str = "", years: float | None = 10, default_years: int = 5,
               suffix: str = "", prefix: str = "", digits: int | None = None,
               chart_type: str = "line", target: float | None = None,
               band: list | None = None, height: int = 260,
               include_zero: bool = False, freq: str = "m",
               with_table: bool = True,
               sign_colors: tuple[str, str] | None = None) -> str:
    """Build a chart card from Series objects.

    `series_specs` is [(series, display name, colour token or None)].
    `sign_colors`（bar 圖用）：(正值色token, 負值色token)，例如買賣超
    這種正負有意義的量，每根柱依正負著色而不是同一色。
    """
    data, legend = [], []
    for s, name, color in series_specs:
        pts = points(s, years)
        if not pts:
            continue
        entry = {"name": name, "color": color, "data": pts}
        if sign_colors:
            entry["signColor"] = list(sign_colors)
        data.append(entry)
        legend.append((name, s))

    if not data:
        return ""

    spec = {
        "type": chart_type, "series": data, "defaultYears": default_years,
        "suffix": suffix, "prefix": prefix, "freq": freq,
        "includeZero": include_zero, "height": height,
    }
    if digits is not None:
        spec["digits"] = digits
    if target is not None:
        spec["target"] = target
    if band:
        spec["band"] = band

    rows = head = None
    if with_table:
        head = ["日期"] + [name for name, _ in legend]
        lookup = [dict(zip(s.dates, s.values)) for _, s in legend]
        dates = sorted({d for _, s in legend for d in s.last_years(2).dates},
                       reverse=True)[:24]
        rows = [[d.isoformat()] + [fmt(t.get(d), digits if digits is not None else 2,
                                       suffix=suffix, prefix=prefix)
                                   for t in lookup] for d in dates]

    return chart(spec, title=title, sub=sub, table_rows=rows, table_head=head)


def bar_chart(title: str, series: Series, *, sub: str = "", years: float = 5,
              default_years: int = 3, suffix: str = "", digits: int | None = None,
              sign_color: tuple[str, str] | None = ("series-1", "series-8"),
              name: str = "", height: int = 240, freq: str = "m") -> str:
    pts = points(series, years)
    if not pts:
        return ""
    entry = {"name": name or title, "data": pts}
    if sign_color:
        entry["signColor"] = list(sign_color)
    spec = {"type": "bar", "series": [entry], "defaultYears": default_years,
            "suffix": suffix, "freq": freq, "includeZero": True, "height": height}
    if digits is not None:
        spec["digits"] = digits
    rows = [[d, fmt(v, digits if digits is not None else 1, suffix=suffix, signed=True)]
            for d, v in reversed(pts[-24:])]
    return chart(spec, title=title, sub=sub, table_rows=rows,
                 table_head=["日期", name or title])


def hbar_chart(title: str, rows: list[dict], *, sub: str = "", suffix: str = "",
               digits: int = 1, label_width: int = 150,
               sign_color: tuple[str, str] | None = ("series-1", "series-8"),
               name: str = "") -> str:
    """rows: [{"name": ..., "value": ..., "sub": ...}]"""
    clean = [r for r in rows if r.get("value") is not None]
    if not clean:
        return ""
    spec = {
        "type": "hbar", "rows": clean, "series": [{"name": name or title}],
        "suffix": suffix, "digits": digits, "labelWidth": label_width,
        "rowHeight": 26,
    }
    if sign_color:
        spec["signColor"] = list(sign_color)
    return chart(spec, title=title, sub=sub, ranges=False)


def curve_chart(title: str, rows: list[dict], *, sub: str = "") -> str:
    """殖利率曲線：現在 vs 三個月前，用啞鈴圖比兩條線更好讀。"""
    clean = [{"name": r["name"], "a": r["m3"], "b": r["value"]}
             for r in rows if r.get("value") is not None and r.get("m3") is not None]
    if not clean:
        return ""
    spec = {
        "type": "dumbbell", "rows": clean,
        "series": [{"name": "三個月前", "color": "neutral"},
                   {"name": "現在", "color": "series-1"}],
        "suffix": "%", "digits": 2, "labelWidth": 70, "rowHeight": 26,
    }
    return chart(spec, title=title, sub=sub, ranges=False)


def signals_block(signals: list[dict], *, limit: int | None = None,
                  module: str | None = None) -> str:
    rows = [s for s in signals if module is None or s.get("module") == module]
    if limit:
        rows = rows[:limit]
    if not rows:
        return '<p class="muted">本期沒有觸發訊號。</p>'
    return '<div class="signal-list">' + "".join(signal_row(s) for s in rows) + "</div>"


def checks_block(checks: list[dict]) -> str:
    if not checks:
        return '<p class="muted">資料不足，無法產生檢核。</p>'
    return '<div class="checks">' + "".join(check_row(c) for c in checks) + "</div>"


def legend_note() -> str:
    return (f'<p class="muted" style="font-size:.8rem">'
            f'嚴重度：{SEV_GLYPH["high"]} 嚴重　{SEV_GLYPH["medium"]} 留意　'
            f'{SEV_GLYPH["low"]} 參考。'
            f'方向：{tag("hawkish")} 表示這件事讓升息更可能或降息更遠，'
            f'{tag("dovish")} 反之。</p>')


def glossary(items: list[tuple[str, str]]) -> str:
    rows = "".join(f"<dt>{esc(term)}</dt><dd style='text-align:left'>{esc(text)}</dd>"
                   for term, text in items)
    return f'<dl class="kv" style="grid-template-columns:auto 1fr">{rows}</dl>'


def as_of_note(*pairs: tuple[str, object]) -> str:
    parts = [f"{name}：{value}" for name, value in pairs if value]
    return "　·　".join(parts)
