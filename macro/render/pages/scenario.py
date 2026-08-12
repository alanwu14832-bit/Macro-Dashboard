"""情境與部位頁：九宮格、政策重心、轉換門檻、部位對照。"""
from __future__ import annotations

from ..html import (accordion, callout, direction_class, direction_label, esc,
                    fmt, kv, section, table, tag)

LEAN_COLOR = {"hawkish": "var(--hawkish)", "dovish": "var(--dovish)",
              "neutral": "var(--neutral)"}
LEAN_WASH = {"hawkish": "var(--hawkish-wash)", "dovish": "var(--dovish-wash)",
             "neutral": "var(--neutral-wash)"}

def nine_grid(scenario: dict) -> str:
    lean = scenario["lean"]
    cells = ['<div class="corner"></div>',
             '<div class="colhead">通膨低</div>',
             '<div class="colhead">通膨中</div>',
             '<div class="colhead">通膨高</div>']
    for row in scenario["grid"]:
        cells.append(f'<div class="rowhead">就業{esc(row["label"])}</div>')
        for cell in row["cells"]:
            style = ""
            if cell["active"]:
                style = (f' style="--regime-color:{LEAN_COLOR[cell["lean"]]};'
                         f'--regime-wash:{LEAN_WASH[cell["lean"]]}"')
            cells.append(
                f'<div class="cell{" active" if cell["active"] else ""}"{style}>'
                f'<div class="name">{esc(cell["name"])}</div>'
                f'<div class="lean">{esc(direction_label(cell["lean"]))}</div></div>')
    return (f'<div class="ninegrid" style="--regime-color:{LEAN_COLOR[lean]};'
            f'--regime-wash:{LEAN_WASH[lean]}">{"".join(cells)}</div>')

def render(ctx: dict, scenario: dict, summary: dict) -> str:
    lean = scenario["lean"]
    body = []

    # ---- 目前定位 ----
    body.append(
        f'<div class="verdict" style="--regime-color:{LEAN_COLOR[lean]}">'
        f'<div class="eyebrow">目前定位</div>'
        f'<div class="hero-figure">{esc(scenario["name"])}</div>'
        f'<div class="chips">'
        f'<span class="chip">就業{esc(scenario["employment_label"])}</span>'
        f'<span class="chip">通膨{esc(scenario["inflation_label"])}</span>'
        f'<span class="chip">重心：{esc(scenario["regime_label"])}</span>'
        f'<span class="chip {direction_class(lean)}"><span class="dot"></span>'
        f'{esc(direction_label(lean))}</span></div>'
        f'<p class="summary">{esc(scenario["regime_explain"])}</p></div>')

    # ---- 九宮格 ----
    body.append(section(
        "positioning", "九宮格定位", nine_grid(scenario),
        note=f'格內文字是該情境在「{scenario["regime_label"]}」重心下的政策傾向',
        terms=["nine_grid", "policy_regime"]))

    # ---- 判定依據 ----
    detail = scenario.get("employment_detail") or {}
    parts = detail.get("parts") or {}
    weights = scenario["bands"]["employment"]["weights"]
    part_names = {"payrolls": "三月均非農 vs 損益兩平", "unrate": "失業率距一年低點",
                  "prime_epop": "黃金年齡就業率 12 個月變動"}
    score_rows = [[esc(part_names.get(k, k)), fmt(weights.get(k, 0) * 100, 0, suffix="%"),
                   fmt(v, 2, signed=True) if v is not None else "—",
                   fmt((v or 0) * weights.get(k, 0), 2, signed=True) if v is not None else "—"]
                  for k, v in parts.items()]

    body.append(section("why", "這個判斷怎麼來的", "".join([
        f'<div class="card"><div class="card-title">就業：{esc(scenario["employment_label"])}</div>',
        f'<ul style="color:var(--ink-2);margin:0 0 10px">'
        + "".join(f"<li>{esc(r)}</li>" for r in scenario["employment_reasons"]) + "</ul>",
        table(["分項", "權重", "分數 (−1 弱 ~ +1 強)", "加權"], score_rows) if score_rows else "",
        f'<p class="muted" style="font-size:.83rem">加權總分 '
        f'{fmt(detail.get("score"), 2, signed=True)}；'
        f'≤ {scenario["bands"]["employment"]["weak_score"]} 為弱、'
        f'≥ {scenario["bands"]["employment"]["strong_score"]} 為強。'
        f'用加權分數而非投票，是因為投票制會讓「失業率在低點」抵銷掉'
        f'「聘僱遠低於損益兩平」——而失業率下降有可能只是勞動力在萎縮。</p></div>',

        f'<div class="card"><div class="card-title">通膨：{esc(scenario["inflation_label"])}</div>',
        f'<ul style="color:var(--ink-2);margin:0">'
        + "".join(f"<li>{esc(r)}</li>" for r in scenario["inflation_reasons"]) + "</ul>",
        f'<p class="muted" style="font-size:.83rem">門檻：核心 PCE '
        f'≤ {scenario["bands"]["inflation"]["low"]}% 為低、'
        f'≥ {scenario["bands"]["inflation"]["high"]}% 為高。</p></div>',

        f'<div class="card"><div class="card-title">重心：{esc(scenario["regime_label"])}</div>',
        f'<ul style="color:var(--ink-2);margin:0">'
        + "".join(f"<li>{esc(r)}</li>" for r in scenario["regime_reasons"]) + "</ul>",
        f'<p class="muted" style="font-size:.83rem">規則：長期通膨預期超過 '
        f'{scenario["bands"]["regime"]["expectations_threshold"]}% 時必為通膨優先；'
        f'否則核心 PCE 距目標超過 {scenario["bands"]["regime"]["inflation_first_gap"]} '
        f'個百分點為通膨優先，小於 0.2 個百分點為就業優先，其餘為兩邊並重。</p></div>',
    ]),
                        terms=["breakeven_payrolls", "prime_epop", "core_pce", "five_y_five_y"]))

    # ---- 三種重心 ----
    rows = [[esc(a["label"]) + ("（目前）" if a["active"] else ""),
             tag(a["lean"]), esc(a["explain"])]
            for a in scenario["alternatives"]]
    body.append(section(
        "regimes", "同一格，三種重心下會變成什麼",
        table(["政策重心", "政策傾向", "說明"], rows)
        + callout("聯準會的兩個使命在停滯性通膨情境下互相衝突。"
                  "同樣的數據，把哪一個使命排在前面，會導出相反的結論——"
                  "所以判斷重心比判斷數據本身更重要。"),
        terms=["policy_regime"]))

    # ---- 轉換門檻 ----
    transitions = scenario.get("transitions") or []
    if transitions:
        rows = [[esc(t["name"]), esc(t["need"]),
                 (f'<span class="num">{fmt(abs(t["gap"]), 2)} {esc(t["unit"])}</span>'
                  if t.get("gap") is not None else '<span class="muted">—</span>')]
                for t in transitions]
        body.append(section("transitions", "情境轉換門檻",
                            table(["要換到哪一格", "需要什麼", "還差"], rows),
                            note="這些就是接下來每次數據發布時該盯的數字",
                        terms=["transition_threshold"]))

    # ---- 部位對照 ----
    rows = [[esc(name), f'<strong>{esc(direction)}</strong>', esc(reason)]
            for name, direction, reason in scenario["positioning"]]
    body.append(section(
        "portfolio", "部位對照",
        table(["部位類別", "方向", "原因"], rows)
        + callout(f'以上對應「{esc(scenario["name"])}／{esc(scenario["regime_label"])}」'
                  f'情境下政策傾向{esc(direction_label(lean))}的組合。'
                  f'情境一變，整張表就會改寫。')
        + '<p class="muted" style="font-size:.82rem">'
          '這是情境到部位方向的機械對照，不是投資建議，也未考慮任何個人的'
          '風險承受度、稅務與既有部位。</p>',
        terms=["bull_bear_steepener", "duration", "tips"]))

    # ---- 交叉檢查 ----
    body.append(section("cross-check", "跟其他證據對得起來嗎", f'<div class="card">' + kv([
        ("規則引擎合計", esc(summary.get("tilt", "—"))),
        ("市場定價隱含", esc(scenario.get("market_check", "—"))),
        ("長端供給壓力", esc(scenario.get("supply_pressure", "—"))),
        ("衰退風險刻度", esc(scenario.get("recession_gauge", "—"))),
    ]) + callout("九宮格是對「聯準會會怎麼想」的判斷；市場定價是對「市場已經信了多少」的判斷。"
                 "兩者背離時，才有交易價值。") + "</div>",
                        terms=["signal_engine"]))

    return "".join(body)
