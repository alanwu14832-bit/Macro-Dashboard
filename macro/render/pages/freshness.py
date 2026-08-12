"""資料新鮮度頁：每個指標多新、下次什麼時候更新。"""
from __future__ import annotations

from ..html import callout, esc, fmt, section, table, zh_date


def _countdown(days: int | None) -> str:
    if days is None:
        return '<span class="muted">未公布時程</span>'
    if days == 0:
        return '<strong class="pos">今天</strong>'
    if days == 1:
        return '<strong class="pos">明天</strong>'
    if days <= 7:
        return f'<strong>{days} 天後</strong>'
    return f'{days} 天後'


def _age(days: int | None, frequency: str) -> str:
    """資料齡要對照它自己的頻率才有意義——季資料 90 天不算舊。"""
    if days is None:
        return "—"
    limit = {"d": 5, "w": 12, "m": 50, "q": 130, "a": 420}.get(frequency, 50)
    cls = "neg" if days > limit * 1.6 else ""
    return f'<span class="{cls}">{days} 天</span>'


def render(ctx: dict) -> str:
    d = ctx["freshness"]
    body = []

    # ---- 即將發布 ----
    imminent = d.get("imminent") or []
    if imminent:
        items = "".join(
            f'<div class="check {"alert" if r["days_away"] == 0 else "watch"}">'
            f'<div class="glyph">{"●" if r["days_away"] == 0 else "◆"}</div>'
            f'<div><div class="name">{esc(r["name"])}</div>'
            f'<div class="state">{esc(r["module"])}　目前是 {zh_date(r["data_date"])} 的資料</div></div>'
            f'<div class="reading">{_countdown(r["days_away"])}</div></div>'
            for r in imminent)
        body.append(section(
            "imminent", "七天內會更新的",
            f'<div class="checks">{items}</div>'
            + callout("這些指標即將發布新數字。發布後本站的下一次建置就會帶進來，"
                      "訊號與九宮格判定也可能跟著改變。", key=True),
            note=f'共 {len(imminent)} 項'))

    # ---- 完整表 ----
    rows = [[
        esc(r["name"]),
        esc(r["module"]),
        zh_date(r["data_date"], freq=r["frequency"]),
        _age(r["data_age"], r["frequency"]),
        (r["updated"].strftime("%Y-%m-%d %H:%M") if r["updated"] else "—"),
        (str(r["next_release"]) if r["next_release"] else "—"),
        _countdown(r["days_away"]),
    ] for r in d["rows"]]

    body.append(section(
        "schedule", "各指標的資料日期與下次發布",
        table(["指標", "模組", "最新資料", "資料齡", "FRED 上次更新", "下次發布", "倒數"], rows,
              foot="「資料齡」是相對於該指標自己的頻率評估——季資料 90 天不算舊，"
                   "日資料 30 天就有問題。標紅代表明顯超出正常延遲。"),
        note="發布日程取自 FRED 官方行事曆"))

    # ---- 為什麼沒有即時 ----
    body.append(section("why", "為什麼總經儀表板沒有「即時」", f'<div class="card">'
        + table(["頻率", "指標", "實際更新節奏"], [
            ["季", "GDP、生產力、放款標準調查、債務存量", "每季一次，且初值後還有兩次修正"],
            ["月", "非農、CPI、PCE、零售、工業生產、JOLTS", "每月一次，JOLTS 還額外延遲一個月"],
            ["週", "初領與續領失業金", "每週四"],
            ["日", "公債殖利率、匯率、股價、信用利差", "每個交易日收盤後更新一次"],
        ])
        + callout(
            "整站 196 檔序列裡，更新最快的就是日頻那一組，而 FRED 的日資料也是"
            "<strong>收盤後隔天才發布</strong>。所以就算每分鐘重建，九成的數字"
            "一個月才會動一次。<br><br>"
            "與其追求無意義的重整頻率，本站的做法是：<strong>把每個數字的新鮮度"
            "與下次發布時間攤開</strong>，讓你知道現在看到的是不是最新的，"
            "以及下一個轉折點什麼時候到。")
        + "</div>"))

    # ---- 非 FRED 來源 ----
    ext_rows = [[esc(name), esc(what), esc(cadence)] for name, what, cadence in d["external"]]
    body.append(section(
        "external", "非 FRED 來源",
        table(["來源", "提供什麼", "更新節奏"], ext_rows,
              foot="這些來源沒有公開的發布行事曆，本站以資料本身的日期為準。"),
        note="這些來源在各自頁面上都標有 as-of 日期"))

    body.append(callout(
        f'本頁產生於 {d["generated"].strftime("%Y-%m-%d %H:%M")}。'
        f'本站每天重建，發布密集的日子會多跑幾次。'))

    return "".join(body)
