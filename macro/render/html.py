"""HTML component helpers.

A component library rather than a template language: every helper returns an
HTML string, everything user- or API-derived goes through `esc`, and chart
specs are serialised into a `data-chart` attribute for chart.js to pick up.
Numbers are formatted here (server side) so the page reads correctly with
scripting disabled.
"""
from __future__ import annotations

import html
import json
from datetime import date

# ------------------------------------------------------------------ escaping -


def esc(value) -> str:
    if value is None:
        return ""
    return html.escape(str(value), quote=True)


def attr_json(payload) -> str:
    """JSON for an HTML attribute — compact, and safe inside single quotes."""
    text = json.dumps(payload, separators=(",", ":"), ensure_ascii=False, default=_json_default)
    return html.escape(text, quote=True)


def _json_default(obj):
    if isinstance(obj, date):
        return obj.isoformat()
    raise TypeError(f"not serialisable: {type(obj)}")


# ---------------------------------------------------------------- formatting -

def fmt(value, digits: int = 1, *, prefix: str = "", suffix: str = "",
        signed: bool = False, dash: str = "—") -> str:
    if value is None:
        return dash
    try:
        number = float(value)
    except (TypeError, ValueError):
        return dash
    if number != number:  # NaN
        return dash
    text = f"{number:,.{digits}f}"
    if signed and number > 0:
        text = "+" + text
    return f"{prefix}{text}{suffix}"


def pct(value, digits: int = 1, *, signed: bool = False) -> str:
    return fmt(value, digits, suffix="%", signed=signed)


def pp(value, digits: int = 2, *, signed: bool = True) -> str:
    """Percentage points — the unit for a gap between two rates."""
    return fmt(value, digits, suffix=" 個百分點", signed=signed)


def thousands_to_wan(value, digits: int = 1, *, signed: bool = True) -> str:
    """FRED reports payrolls in thousands; Taiwanese readers count in 萬人."""
    if value is None:
        return "—"
    return fmt(value / 10.0, digits, suffix=" 萬人", signed=signed)


def zh_date(value: date | str | None, *, freq: str = "m") -> str:
    if value is None:
        return "—"
    d = value if isinstance(value, date) else date.fromisoformat(str(value))
    if freq == "a":
        return f"{d.year}"
    if freq == "q":
        return f"{d.year} 年 Q{(d.month - 1) // 3 + 1}"
    if freq == "m":
        return f"{d.year}-{d.month:02d}"
    return d.isoformat()


def direction_label(direction: str) -> str:
    return {"hawkish": "利升息", "dovish": "利降息", "neutral": "中性"}.get(direction, "中性")


def direction_class(direction: str) -> str:
    return direction if direction in ("hawkish", "dovish") else "neutral"


# ---------------------------------------------------------------- components -

def tag(direction: str, text: str | None = None) -> str:
    """A small polarity pill. Colour is the diverging pair; the label carries
    the meaning so hue is never the only channel."""
    return (f'<span class="tag {direction_class(direction)}">'
            f'{esc(text or direction_label(direction))}</span>')


def stat(label: str, value: str, *, delta: str = "", asof: str = "",
         direction: str | None = None, spark: list | None = None,
         spark_color: str = "series-1") -> str:
    parts = [f'<div class="stat"><div class="label">{esc(label)}</div>',
             f'<div class="value">{value}</div>']
    if delta or direction:
        chunk = f'<div class="delta">{delta}'
        if direction:
            chunk += " " + tag(direction)
        parts.append(chunk + "</div>")
    if spark:
        payload = attr_json([[d, v] for d, v in spark])
        parts.append(f'<div class="spark" data-spark="{payload}" '
                     f'data-spark-color="{esc(spark_color)}"></div>')
    if asof:
        parts.append(f'<div class="asof">{esc(asof)}</div>')
    return "".join(parts) + "</div>"


SEV_GLYPH = {"high": "■", "medium": "▲", "low": "●"}
SEV_TEXT = {"high": "嚴重", "medium": "留意", "low": "參考"}


def signal_row(signal: dict) -> str:
    """One rule-engine finding. Severity is glyph + text; direction is colour +
    text — neither leans on hue alone."""
    sev = signal.get("severity", "low")
    return (
        '<div class="signal">'
        f'<div class="sev {esc(sev)}" title="{esc(SEV_TEXT.get(sev, ""))}">'
        f'{SEV_GLYPH.get(sev, "●")}<span class="sr-only">{esc(SEV_TEXT.get(sev, ""))}</span></div>'
        '<div>'
        f'<div class="headline">{esc(signal["headline"])}</div>'
        f'<div class="why">{esc(signal.get("why", ""))}</div>'
        + (f'<div class="evidence">{esc(signal["evidence"])}</div>' if signal.get("evidence") else "")
        + '</div>'
        f'<div class="side">{tag(signal.get("direction", "neutral"))}'
        f'<div class="evidence">{esc(signal.get("module", ""))}</div></div>'
        '</div>'
    )


CHECK_GLYPH = {"alert": "▲", "watch": "◆", "normal": "●"}
CHECK_TEXT = {"alert": "警戒", "watch": "留意", "normal": "正常"}


def check_row(check: dict) -> str:
    state = check.get("state", "normal")
    return (
        f'<div class="check {esc(state)}">'
        f'<div class="glyph">{CHECK_GLYPH.get(state, "●")}</div>'
        f'<div><div class="name">{esc(check["name"])}</div>'
        f'<div class="state">{esc(CHECK_TEXT.get(state, ""))}　{esc(check.get("note", ""))}</div></div>'
        f'<div class="reading">{check.get("reading", "—")}</div>'
        '</div>'
    )


RANGES = [("1Y", 1), ("3Y", 3), ("5Y", 5), ("10Y", 10), ("全期", 0)]


def _span_years(spec: dict) -> float | None:
    """spec 裡所有序列涵蓋的年數。抓不到日期就回 None（不做過濾）。"""
    firsts, lasts = [], []
    for s in spec.get("series") or []:
        pts = s.get("data") or []
        if pts:
            firsts.append(pts[0][0])
            lasts.append(pts[-1][0])
    if not firsts:
        return None
    try:
        start = date.fromisoformat(str(min(firsts))[:10])
        end = date.fromisoformat(str(max(lasts))[:10])
    except ValueError:
        return None
    return (end - start).days / 365.25


def chart(spec: dict, *, title: str = "", sub: str = "", ranges: bool = True,
          table_rows: list | None = None, table_head: list | None = None) -> str:
    """A chart card. `spec` is consumed by chart.js; `table_rows` is the
    table view — the documented relief for low-contrast hues in light mode,
    and the no-JavaScript fallback."""
    spec = dict(spec)
    spec.setdefault("title", title)

    tools = ""
    if ranges:
        default = spec.get("defaultYears", 0)
        # 只列資料真的涵蓋得到的區間。序列只有半年時把 1Y/3Y/10Y 全列出來，
        # 按了畫面完全不變——那不是「沒反應的按鈕」，是騙人的按鈕。
        span = _span_years(spec)
        usable = [(n, y) for n, y in RANGES if y == 0 or (span is None or y < span)]
        if len(usable) <= 1:
            tools = ""                      # 只剩「全期」就不必給選擇
        else:
            if default and all(y != default for _, y in usable):
                default = 0                 # 預設值被濾掉了 → 退回全期
                spec["defaultYears"] = 0
            buttons = "".join(
                f'<button type="button" data-years="{years}" '
                f'aria-pressed="{"true" if years == default else "false"}">{esc(name)}</button>'
                for name, years in usable)
            tools += (f'<div class="range-group" role="group" '
                      f'aria-label="時間區間">{buttons}</div>')
    if table_rows:
        tools += ('<button type="button" class="icon-btn" data-toggle-table '
                  'aria-expanded="false">表格</button>')

    legend = ""
    series = spec.get("series") or []
    if len(series) >= 2:
        items = "".join(
            '<span class="legend-item">'
            f'<span class="legend-key{" rect" if spec.get("type") in ("bar", "hbar") else ""}" '
            f'style="background:var(--{s.get("color") or f"series-{i + 1}"})"></span>'
            f'{esc(s.get("name", ""))}</span>'
            for i, s in enumerate(series))
        legend = f'<div class="legend">{items}</div>'

    table = ""
    if table_rows:
        head = "".join(f"<th>{esc(h)}</th>" for h in (table_head or []))
        body = "".join(
            "<tr>" + "".join(f'<td class="num">{cell}</td>' for cell in row) + "</tr>"
            for row in table_rows)
        table = (f'<div class="chart-table table-wrap"><table><thead><tr>{head}</tr></thead>'
                 f'<tbody>{body}</tbody></table></div>')

    return (
        f'<figure class="chart-card" data-chart="{attr_json(spec)}" style="margin:0">'
        '<div class="chart-head"><div>'
        f'<figcaption class="chart-title">{esc(title)}</figcaption>'
        + (f'<div class="chart-sub">{esc(sub)}</div>' if sub else "")
        + f'</div><div class="chart-tools">{tools}</div></div>'
        f'<div class="chart-wrap"></div>{legend}{table}'
        '</figure>'
    )


def card(title: str, body: str, *, sub: str = "") -> str:
    head = f'<div class="card-title">{esc(title)}</div>' if title else ""
    if sub:
        head += f'<div class="card-sub">{esc(sub)}</div>'
    return f'<div class="card">{head}{body}</div>'


FIELD_LABELS = [
    ("what", "是什麼"),
    ("how", "怎麼算"),
    ("why", "為什麼重要"),
    ("read", "怎麼讀"),
]


def terms_block(keys: list[str], *, title: str = "這一段的名詞與意義") -> str:
    """區塊底部的名詞解釋。

    收合起來，讓已經懂的人不會被擋路；展開後每個詞都給「是什麼／怎麼算／
    為什麼重要／怎麼讀」，因為只給定義的名詞表沒有教育意義——讀者真正卡住的
    地方是「知道它的定義，但不知道看到這個數字該想什麼」。
    """
    from .. import glossary

    entries = [glossary.get(k) for k in keys]
    entries = [e for e in entries if e]
    if not entries:
        return ""

    items = []
    for entry in entries:
        rows = "".join(
            f'<div class="term-row"><span class="term-tag">{esc(label)}</span>'
            f'<span class="term-text">{entry[field]}</span></div>'
            for field, label in FIELD_LABELS if entry.get(field))
        items.append(f'<div class="term"><div class="term-name">{esc(entry["term"])}</div>'
                     f'{rows}</div>')

    return (f'<details class="acc terms"><summary>{esc(title)}'
            f'<span class="term-count">{len(entries)} 個</span></summary>'
            f'<div class="acc-body">{"".join(items)}</div></details>')


def section(anchor: str, title: str, body: str, *, note: str = "",
            terms: list[str] | None = None, sub: bool = False) -> str:
    """sub=True 的區塊在側欄目錄裡是「小小標」，縮排列在前一個小標下。

    頁面本身的呈現不變——這個旗標只影響側欄大綱的層級，讓區塊很多的
    頁（如股市報價）不會把側欄撐成一長串同級項目。
    """
    note_html = f'<p class="note">{esc(note)}</p>' if note else ""
    cls = ' class="sub-section"' if sub else ""
    return (f'<section id="{esc(anchor)}"{cls}>'
            f'<div class="section-head"><h2>{esc(title)}</h2>{note_html}</div>'
            f'{body}{terms_block(terms) if terms else ""}</section>')


def table(headers: list[str], rows: list[list[str]], *, foot: str = "",
          align_first_left: bool = True) -> str:
    head = "".join(f"<th>{esc(h)}</th>" for h in headers)
    body = "".join(
        "<tr>" + "".join(
            f'<td class="{"" if i == 0 and align_first_left else "num"}">{cell}</td>'
            for i, cell in enumerate(row)) + "</tr>"
        for row in rows)
    tfoot = (f'<tfoot><tr><td colspan="{len(headers)}">{foot}</td></tr></tfoot>'
             if foot else "")
    return (f'<div class="table-wrap"><table><thead><tr>{head}</tr></thead>'
            f'<tbody>{body}</tbody>{tfoot}</table></div>')


def accordion(summary: str, body: str, *, open_: bool = False) -> str:
    return (f'<details class="acc"{" open" if open_ else ""}>'
            f'<summary>{esc(summary)}</summary>'
            f'<div class="acc-body">{body}</div></details>')


def callout(text: str, *, key: bool = False) -> str:
    return f'<div class="callout{" key" if key else ""}">{text}</div>'


def kv(pairs: list[tuple[str, str]]) -> str:
    body = "".join(f"<dt>{esc(k)}</dt><dd>{v}</dd>" for k, v in pairs)
    return f'<dl class="kv">{body}</dl>'


def delta_span(value, digits: int = 1, *, suffix: str = "", good_is_up: bool = True) -> str:
    """A signed change wearing the direction colour, not a series colour."""
    if value is None:
        return '<span class="muted">—</span>'
    good = (value > 0) if good_is_up else (value < 0)
    cls = "pos" if good else ("neg" if value else "muted")
    return f'<span class="{cls} num">{esc(fmt(value, digits, suffix=suffix, signed=True))}</span>'
