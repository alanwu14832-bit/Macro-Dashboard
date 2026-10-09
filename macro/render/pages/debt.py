"""長端與債務頁。"""
from __future__ import annotations

from ..common import (checks_block, legend_note, line_chart,
                      signals_block)
from ..html import (accordion, callout, esc, fmt, kv, pct, section, stat,
                    table, zh_date)

def render(ctx: dict, signals: list[dict]) -> str:
    d = ctx["debt"]
    dynamics = d["dynamics"]
    fiscal = d["fiscal"]
    holders = d["holders"]
    supply = d["supply"]
    body = []

    body.append(section("signals", "本期關鍵訊號",
                        signals_block(signals, module="債務") + legend_note(),
                        terms=["signal_engine", "hawkish_dovish"]))

    tiles = [
        stat("聯邦債務佔 GDP", fmt(dynamics["debt_gdp"], 0, suffix="%"),
             delta=f'五年前 {fmt(dynamics["debt_gdp_5y_ago"], 0, suffix="%")}',
             asof=f'{zh_date(d["as_of"], freq="q")} 資料'),
        stat("r − g", fmt(dynamics["r_minus_g"], 2, suffix=" pp", signed=True),
             delta=f'實質利率 {pct(dynamics["real_rate"], 2)} vs 實質成長 {pct(dynamics["real_growth"], 2)}',
             asof="正值＝債務比自動累積"),
        stat("財政赤字佔 GDP", fmt(abs(fiscal["deficit_gdp"] or 0), 1, suffix="%"),
             delta=f'滾動 12 月赤字 {fmt((fiscal["annual_deficit"] or 0) / 1_000_000, 2, suffix=" 兆美元")}'),
        stat("聯邦利息支出", fmt((fiscal["interest"] or 0) / 1000, 2, suffix=" 兆美元"),
             delta=f'年增 {fmt(fiscal["interest_yoy"], 0, suffix="%", signed=True)}',
             asof=f'佔 GDP {fmt(fiscal["interest_gdp"], 1, suffix="%")}'),
    ]
    body.append(section("numbers", "關鍵數字",
                        f'<div class="grid grid-4">{"".join(tiles)}</div>',
                        terms=["debt_to_gdp", "r_minus_g", "interest_burden"]))

    # ---- 長端為什麼在這裡 ----
    reasons = "".join(f"<li>{esc(r)}</li>" for r in supply["reasons"])
    body.append(section(
        "why", "長端利率為什麼在這裡",
        f'<div class="card">'
        f'<div class="hero-figure">供給壓力：{esc(supply["level"])}'
        f'<span style="font-size:.35em;color:var(--ink-muted)"> '
        f'{supply["score"]}/{supply["max"]} 項成立</span></div>'
        + (f'<ul style="color:var(--ink-2);margin:8px 0 0">{reasons}</ul>' if reasons
           else '<p class="muted">四項供給壓力條件都不成立。</p>')
        + callout(
            "長端利率不只由聯準會決定。降息可以壓低短端，但長端還要看發債量、"
            "買盤結構與財政可持續性——這也是降息後長端反而上行的常見原因。")
        + "</div>",
        terms=["term_premium"]))

    # ---- 債務動態 ----
    body.append(section("dynamics", "債務動態：r − g 框架", f'<div class="card">' + kv([
        ("聯邦債務佔 GDP", fmt(dynamics["debt_gdp"], 1, suffix="%")),
        ("10 年實質利率 r", pct(dynamics["real_rate"], 2)),
        ("實質 GDP 年增 g", pct(dynamics["real_growth"], 2)),
        ("r − g", fmt(dynamics["r_minus_g"], 2, suffix=" pp", signed=True)),
        ("穩定債務比所需的基本盈餘", fmt(dynamics["required_primary"], 2, suffix="% of GDP")),
    ]) + callout(f'判定：<strong>{esc(dynamics["verdict"])}</strong>。'
                 f'r 大於 g 時，就算基本收支平衡，債務佔 GDP 仍會上升——'
                 f'這意味著長端供給只會增加，不會減少。', key=True)
        + "</div>", note="決定債務是否可持續的基本恆等式",
                        terms=["r_minus_g", "primary_balance"]))

    body.append(section("debt-trend", "債務與利息負擔走勢",
                        f'<div class="grid grid-2">' + "".join([
                            line_chart("聯邦債務佔 GDP",
                                       [(dynamics["debt_gdp_series"], "債務佔 GDP", "series-1")],
                                       years=40, default_years=10, suffix="%", digits=0,
                                       freq="q", sub="季資料"),
                            line_chart("聯邦利息支出",
                                       [(fiscal["interest_series"], "利息支出（十億美元）", "series-2")],
                                       years=40, default_years=10, digits=0, freq="q",
                                       sub="舊債以更高利率換新債，這條線會持續上行"),
                        ]) + "</div>",
                        terms=["debt_to_gdp", "interest_burden"]))

    # ---- 買盤 ----
    def quarter(when):
        return zh_date(when, freq="q") if when else "—"

    share, prior = holders["foreign_share"], holders["foreign_share_5y_ago"]
    if share is None:
        # 佔比算不出來（分子分母沒有同一季）：不留一個 0.0% 讓下面那段話照講
        reading = callout("外國持有與債務總額這一輪沒有同一季的資料，佔比不計算，"
                          "也不對買盤結構下判斷。", key=True)
    else:
        move = ""
        if prior is not None:
            move = (f'五年前同一季是 {fmt(prior, 1, suffix="%")}，'
                    f'{"下降" if share < prior else "上升"} {fmt(abs(share - prior), 1)} 個百分點。')
        reading = callout(
            f'{quarter(holders["foreign_share_as_of"])}外國持有佔債務總額 '
            f'<strong>{fmt(share, 1, suffix="%")}</strong>。{move}'
            "佔比下降代表同樣的發債量有更大的比例要由其他買方吸收；"
            "這是買盤結構的描述，本站沒有資料可以判斷其他買方對價格有多敏感。")
    body.append(section("holders", "誰持有這些債", f'<div class="card">' + kv([
        (f'債務總額（{quarter(holders["total_as_of"])}）',
         fmt(holders["total"], 2, suffix=" 兆美元")),
        (f'民間持有（{quarter(holders["private_as_of"])}）',
         fmt(holders["private"], 2, suffix=" 兆美元")),
        (f'外國持有（{quarter(holders["foreign_as_of"])}）',
         fmt(holders["foreign"], 2, suffix=" 兆美元")),
        ("外國持有年增", fmt(holders["foreign_yoy"], 1, suffix="%", signed=True)),
        (f'外國持有佔債務總額（{quarter(holders["foreign_share_as_of"])}）',
         fmt(share, 1, suffix="%")),
        ("五年前同一季的佔比", fmt(prior, 1, suffix="%")),
    ]) + reading
        + '<p class="muted" style="font-size:.83rem;margin-top:8px">'
          "三個金額不是互斥的分類，不能相加：債務總額＝公眾持有＋政府內部持有（社安基金等）；"
          "民間持有＝公眾持有扣掉聯準會；外國持有是民間持有的一部分。"
          "各檔的最新一季不同，括號裡是各自的資料期；佔比只用分子分母都有的那一季。</p>"
        + "</div>",
                        terms=["foreign_holdings"]))

    body.append(section("checks", "關鍵指標檢核", checks_block(d["checks"]),
                        terms=["check_lights"]))

    return "".join(body)
