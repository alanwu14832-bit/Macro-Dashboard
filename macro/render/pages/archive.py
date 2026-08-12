"""存檔頁：回看每天的判斷與關鍵讀數。"""
from __future__ import annotations

from ..common import line_chart
from ..html import accordion, callout, delta_span, esc, fmt, section, table, tag
from ...series import Series


def _series_from_archive(snapshots: list[dict], key: str) -> Series:
    pairs = []
    for snap in snapshots:
        value = (snap.get("readings") or {}).get(key)
        if value is not None:
            pairs.append((snap["date"], value))
    return Series.from_pairs(key, pairs, frequency="d")


def render(snapshots: list[dict]) -> str:
    body = []

    if not snapshots:
        return ('<div class="card"><p class="muted">還沒有存檔。'
                '每次執行 build.py 都會存下當天的判斷，明天再回來就會看到比較。</p></div>')

    latest = snapshots[-1]
    body.append(section(
        "current", "目前判斷",
        f'<div class="card">'
        f'<div class="card-title">{esc(latest["scenario"]["name"])}'
        f'（{esc(latest["scenario"]["regime"])}）</div>'
        f'<p class="dim">就業{esc(latest["scenario"]["employment"])}　·　'
        f'通膨{esc(latest["scenario"]["inflation"])}　·　'
        f'{tag(latest["scenario"]["lean"])}　·　'
        f'訊號 {latest["summary"]["total"]} 條（{esc(latest["summary"]["tilt"])}）</p>'
        f'<p class="muted">產生於 {esc(latest.get("generated_at", latest["date"]))}</p>'
        f'</div>'))

    # ---- 判斷歷史 ----
    rows = []
    for snap in reversed(snapshots):
        scenario = snap.get("scenario") or {}
        summary = snap.get("summary") or {}
        rows.append([
            esc(snap["date"]),
            esc(scenario.get("name", "—")),
            f'{esc(scenario.get("employment", "—"))} × {esc(scenario.get("inflation", "—"))}',
            esc(scenario.get("regime", "—")),
            tag(scenario.get("lean", "neutral")),
            f'{summary.get("total", 0)} 條（{esc(summary.get("tilt", "—"))}）',
        ])
    body.append(section(
        "history", "判斷歷史",
        table(["日期", "情境", "九宮格位置", "政策重心", "傾向", "訊號"], rows),
        note=f"共 {len(snapshots)} 筆存檔"))

    # ---- 讀數走勢 ----
    if len(snapshots) >= 3:
        charts = [
            line_chart("核心 PCE 與核心 CPI（存檔序列）",
                       [(_series_from_archive(snapshots, "core_pce"), "核心 PCE", "series-1"),
                        (_series_from_archive(snapshots, "core_cpi"), "核心 CPI", "series-2")],
                       years=None, default_years=0, suffix="%", digits=2, freq="d",
                       sub="每次產生時的當下讀數"),
            line_chart("10 年期與實質利率（存檔序列）",
                       [(_series_from_archive(snapshots, "ten_year"), "10 年名目", "series-1"),
                        (_series_from_archive(snapshots, "real_ten_year"), "10 年實質", "series-3")],
                       years=None, default_years=0, suffix="%", digits=2, freq="d"),
        ]
        body.append(section("readings", "關鍵讀數走勢",
                            f'<div class="grid grid-2">{"".join(c for c in charts if c)}</div>'))

    # ---- 每日訊號 ----
    items = []
    for snap in reversed(snapshots[-30:]):
        signal_rows = "".join(
            f'<div class="signal"><div class="sev {esc(s["severity"])}">'
            f'{"■" if s["severity"] == "high" else "▲" if s["severity"] == "medium" else "●"}</div>'
            f'<div><div class="headline">{esc(s["headline"])}</div>'
            f'<div class="evidence">{esc(s.get("evidence", ""))}</div></div>'
            f'<div class="side">{tag(s["direction"])}</div></div>'
            for s in (snap.get("signals") or []))
        items.append(accordion(
            f'{snap["date"]}　{snap.get("scenario", {}).get("name", "")}　'
            f'（{len(snap.get("signals") or [])} 條訊號）',
            f'<div class="signal-list">{signal_rows}</div>' if signal_rows
            else '<p class="muted">無訊號。</p>'))
    body.append(section("daily", "每日訊號明細", "".join(items),
                        note="最近 30 筆"))

    body.append(callout(
        "存檔存的是「判斷」而不是原始資料：訊號清單、九宮格位置與關鍵讀數。"
        "原始資料本來就在 data/cache 裡，不需要重複存。"))

    return "".join(body)
