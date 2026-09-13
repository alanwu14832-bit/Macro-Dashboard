"""發布與反應：一個數字公布之後只需要看一次的那一頁。

推播的落點。它刻意是一條真路由（/release/<序列代號>/）而不是一張 sheet 或
總覽上的一個錨點——你會想從通知直接打開、會想留著網址、會想離線再看一次的
東西，就不該是 sheet。

整頁伺服器端渲染：第一次繪製就是完整內容，沒有骨架屏、沒有 spinner，離線
打開一樣為真，因為數字是烘進 HTML 的，不是載入後才抓的。

刻意不做的三件事，全部寫在頁尾而不是藏起來：
  · 不補市場共識預期——本站沒有那份付費資料，所以只能跟前值與自己的節奏比
  · 不做因果歸因——「因為 CPI 低於預期所以期貨漲」是敘事，不是量測
  · 市場反應只有一次量測，基準是前一交易日收盤，不是公布前一刻
"""
from __future__ import annotations

from ..common import line_chart
from ..html import (callout, esc, fmt, pct, section, table, zh_date)

# 每個可以當落點的指標怎麼呈現。mode 決定「這個數字本身」是什麼：
#   level 讀數就是水準值（失業率、殖利率）
#   yoy   讀數是年增率（物價指數、產出指數這類 index）
#   diff  讀數是較前期的變動（非農月增）
SPECS = {
    "PAYEMS":   {"mode": "diff",  "unit": " 千人", "digits": 0, "page": "/labor/",
                 "feeds": "三月均非農 vs 損益兩平（就業分項之一）",
                 "note": "月增單月雜訊極大且會被修正兩次，判斷看三月均。"},
    "UNRATE":   {"mode": "level", "unit": "%", "digits": 1, "page": "/labor/",
                 "feeds": "失業率距一年低點（就業分項之一）"},
    "ICSA":     {"mode": "level", "unit": " 件", "digits": 0, "page": "/labor/",
                 "feeds": "勞動市場的高頻溫度計（不直接進九宮格）",
                 "note": "週頻雜訊大，本站判斷用四週均。"},
    "JTSJOL":   {"mode": "level", "unit": " 千個", "digits": 0, "page": "/labor/",
                 "feeds": "職缺與 V/U（需求端，不直接進九宮格）"},
    "CPIAUCSL": {"mode": "yoy",   "unit": "%", "digits": 1, "page": "/inflation/",
                 "feeds": "消費端趨勢（九宮格採用的是核心 PCE，不是 CPI）"},
    "PPIFIS":   {"mode": "yoy",   "unit": "%", "digits": 1, "page": "/inflation/",
                 "feeds": "上游成本壓力（只判斷壓力，不移動九宮格）"},
    "PCEPILFE": {"mode": "yoy",   "unit": "%", "digits": 1, "page": "/inflation/",
                 "feeds": "九宮格的通膨格位", "band": "inflation"},
    "GDPC1":    {"mode": "yoy",   "unit": "%", "digits": 1, "page": "/growth/",
                 "feeds": "成長（季頻，初值後還有兩次修正）"},
    "RSAFS":    {"mode": "yoy",   "unit": "%", "digits": 1, "page": "/growth/",
                 "feeds": "消費動能"},
    "INDPRO":   {"mode": "yoy",   "unit": "%", "digits": 1, "page": "/growth/",
                 "feeds": "工業生產"},
    "HOUST":    {"mode": "level", "unit": " 千戶", "digits": 0, "page": "/growth/",
                 "feeds": "住宅循環（對利率最敏感的一環）"},
    "DGS10":    {"mode": "level", "unit": "%", "digits": 2, "page": "/fed/",
                 "feeds": "長端利率與估值分母"},
    "DRTSCILM": {"mode": "level", "unit": "%", "digits": 1, "page": "/growth/",
                 "feeds": "放款標準（季頻，信用循環的領先訊號）"},
}

NO_CONSENSUS = ("本站沒有市場共識預期（那是付費資料），所以這一頁只跟前值與"
                "這個數字自己的近期節奏比，不說「優於／低於預期」。")


def _reading(series, spec: dict) -> dict | None:
    """把一檔序列換成這一頁要顯示的三個數字：本期、前期、變動。"""
    if series is None or series.last is None:
        return None
    mode = spec["mode"]
    if mode == "yoy":
        yoy = series.yoy()
        value, prior = yoy.last, yoy.at(-2)
        chart_series, chart_label = yoy, "年增率"
    elif mode == "diff":
        now, before, older = series.last, series.at(-2), series.at(-3)
        value = None if now is None or before is None else now - before
        prior = None if before is None or older is None else before - older
        chart_series, chart_label = series.diff_months(1), "月增"
    else:
        value, prior = series.last, series.at(-2)
        chart_series, chart_label = series, "水準值"
    change = None if value is None or prior is None else value - prior
    return {"value": value, "prior": prior, "change": change,
            "as_of": series.last_date, "frequency": series.frequency,
            "chart": chart_series, "chart_label": chart_label}


def _verdict_band(ctx: dict, scenario: dict, prior_snapshot: dict | None) -> str:
    """判定換檔帶。沒換就是一行字，不留空殼。"""
    was = (prior_snapshot or {}).get("scenario") or {}
    moved = [(label, was.get(key), scenario.get(cur))
             for key, cur, label in (("employment", "employment_label", "就業"),
                                     ("inflation", "inflation_label", "通膨"),
                                     ("regime", "regime_label", "政策重心"))
             if was.get(key) and scenario.get(cur) and was.get(key) != scenario.get(cur)]
    if not moved:
        return (f'<p class="rel-hold">判定未變：'
                f'<strong>{esc(scenario.get("name", ""))}：'
                f'{esc(scenario.get("regime_label", ""))}</strong></p>')
    rows = "　".join(f'{esc(label)} {esc(old)} → {esc(new)}' for label, old, new in moved)
    return callout(
        f'<strong>判定換檔</strong>　{rows}<br>'
        f'<span class="muted">與上一次建置相比。這一頁的數字是判定的其中一項'
        f'輸入，不是唯一原因——完整依據見 '
        f'<a href="/scenario/">判定頁的 30 條規則</a>。</span>', key=True)


def _threshold_rows(sid: str, spec: dict, reading: dict, scenario: dict) -> str:
    """離門檻還差多少。只有真的對應到寫死級距的指標才畫。"""
    if spec.get("band") != "inflation" or reading["value"] is None:
        return ""
    bands = (scenario.get("bands") or {}).get("inflation") or {}
    low, high = bands.get("low"), bands.get("high")
    if low is None or high is None:
        return ""
    value = reading["value"]
    rows = [
        ["低於此為「低」", pct(low, 1), fmt(value - low, 2, suffix=" pp", signed=True)],
        ["高於此為「高」", pct(high, 1), fmt(value - high, 2, suffix=" pp", signed=True)],
    ]
    return ('<h3 class="fd-h">離門檻還差多少</h3>'
            + table(["寫死的級距", "門檻", "現值減門檻"], rows,
                    foot="門檻是固定規則，不隨行情調整；同一份資料每次執行都會"
                         "得到同一個格位。"))


def _reaction_card(snap: dict | None) -> str:
    if not snap or not snap.get("rows"):
        return ('<p class="muted">這次建置沒有取到期貨報價——'
                '不是零變動，是沒量到。</p>')
    rows = []
    for row in snap["rows"]:
        change = row["change_pct"]
        cls = "delta-up" if change > 0 else "critical" if change < 0 else ""
        rows.append([esc(row["label"]),
                     f'<span class="{cls}">{change:+.2f}%</span>',
                     esc(row["meaning"])])
    measured = (snap.get("measured_at") or "").replace("T", " ")[:16]
    flat = all(abs(r["change_pct"]) < 0.005 for r in snap["rows"])
    closed = ('<p class="muted">三檔同時完全持平，通常代表美股期貨休市中，'
              '不是市場對這個數字沒有反應。</p>' if flat else "")
    return (table(["合約", "較前一交易日收盤", "它在反映什麼"], rows)
            + closed
            + f'<p class="mc-foot-note">量測於 {esc(measured)}（台北），'
              f'基準是{esc(snap.get("baseline", "前一交易日收盤"))}。'
              f'只有這一次量測：推播當下與這一頁的數字會差最多一小時，'
              f'因為兩者在不同時間量。不做因果歸因。</p>')


def render_one(ctx: dict, sid: str, *, scenario: dict,
               prior_snapshot: dict | None = None) -> str:
    from ...compute import freshness

    spec = SPECS[sid]
    name = next((label for series_id, label, _m, _r in freshness.TRACKED
                 if series_id == sid), sid)
    bundle = ctx.get("_bundle")
    series = bundle[sid] if bundle else None
    reading = _reading(series, spec)
    body = []

    body.append(_verdict_band(ctx, scenario, prior_snapshot))

    if not reading:
        body.append(section(
            "print", name,
            f'<p class="muted">{esc(name)}（<code>{esc(sid)}</code>）這一期沒有值'
            f'——不是載入中，是來源沒有。'
            f'<a href="/freshness/">看資料新鮮度頁的說明</a>。</p>'))
        return "".join(body)

    digits = spec["digits"]
    unit = spec["unit"]
    label = {"yoy": "年增率", "diff": "較前期變動", "level": "最新讀數"}[spec["mode"]]

    body.append(section(
        "print", name,
        f'<div class="verdict">'
        f'<div class="eyebrow">{esc(label)}　{esc(zh_date(reading["as_of"], freq=reading["frequency"]))}</div>'
        f'<div class="hero-figure">{fmt(reading["value"], digits, suffix=unit)}</div>'
        f'<div class="chips">'
        f'<span class="chip">前期 {fmt(reading["prior"], digits, suffix=unit)}</span>'
        f'<span class="chip">變動 {fmt(reading["change"], digits + 1, suffix=unit, signed=True)}</span>'
        f'</div>'
        f'<p class="summary">這個數字用在哪裡：{esc(spec["feeds"])}。</p>'
        + (f'<p class="muted" style="margin:6px 0 0">{esc(spec["note"])}</p>'
           if spec.get("note") else "")
        + '</div>'
        + f'<p class="chg-scope">{esc(NO_CONSENSUS)}</p>'
        + _threshold_rows(sid, spec, reading, scenario)))

    if reading["chart"] is not None:
        target = None
        if spec.get("band") == "inflation":
            target = ((scenario.get("bands") or {}).get("inflation") or {}).get("high")
        body.append(section(
            "history", "自己的近期節奏",
            line_chart(f'{name}　{reading["chart_label"]}',
                       [(reading["chart"], name, "series-1")],
                       years=15, default_years=5,
                       suffix=unit.strip() or "", digits=digits,
                       target=target,
                       sub="虛線是寫死的級距門檻" if target else
                           "看這一點是噪音還是趨勢"),
            note="門檻畫成線，「跨越」就變成一個看得見的交點"))

    body.append(section(
        "reaction", "市場反應", _reaction_card(ctx.get("reaction")),
        note="數字與規則先於價格：這一段刻意排在讀數與門檻之後"))

    body.append(section(
        "exits", "接下來看哪裡",
        f'<p class="mc-foot-note">'
        f'<a href="{esc(spec["page"])}">看 {esc(name)} 所屬模組的完整拆解 →</a>　'
        f'<a href="/scenario/">看這個數字影響的判定規則 →</a>　'
        f'<a href="/freshness/">看下一次什麼時候公布 →</a>　'
        f'<a href="/explore/?id={esc(sid)}">在自選比較裡疊圖 →</a></p>'))

    return "".join(body)


def render_index(ctx: dict) -> str:
    """沒有指定指標時的落點：最近的發布索引。"""
    from ...compute import freshness

    rows = []
    for row in sorted((ctx.get("freshness") or {}).get("rows") or [],
                      key=lambda r: (r["data_date"] is None, r["data_date"]),
                      reverse=True):
        if row["id"] not in SPECS:
            continue
        rows.append([
            f'<a href="/release/{esc(row["id"])}/">{esc(row["name"])}</a>',
            esc(row["module"]),
            zh_date(row["data_date"], freq=row["frequency"]),
            (row["updated"].strftime("%Y-%m-%d") if row["updated"] else "—"),
        ])

    return "".join([
        section("index", "最近的發布",
                table(["指標", "模組", "最新資料期間", "FRED 上次更新"], rows,
                      foot="點指標名稱看那一次公布的完整落點：讀數、門檻距離、"
                           "市場反應。"),
                note="推播會直接打開對應的那一頁"),
        # 設計裡寫的是 /release/?id=CPIAUCSL；那個形式導到對應的靜態路由，
        # 兩種網址都會到同一個地方。
        '<script>(function(){var m=/[?&]id=([A-Z0-9_]+)/i.exec(location.search);'
        'if(m)location.replace("/release/"+m[1].toUpperCase()+"/");})();</script>',
    ])
