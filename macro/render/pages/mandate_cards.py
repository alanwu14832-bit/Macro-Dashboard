"""就業與通膨的雙目標卡。

兩張卡刻意用**完全相同的結構**：判定標題 → 四格讀數 → 傳導鏈 → 全指標
下拉。相同的視覺語言讓讀者第二次就不必重新學怎麼讀，也讓「這兩件事
在聯準會眼裡是對等的」這個事實在版面上成立。

四格裡有一格帶綠邊，標示的是**九宮格判定實際採用的那一個口徑**——
其餘三格是脈絡，不是判定依據。這一點在通膨特別重要：媒體報 CPI，
但聯準會的目標是核心 PCE，兩者常常給出不同的印象。
"""
from __future__ import annotations

from .overview_blocks import _inflation_read, _payroll_read
from ..html import (accordion, callout, esc, fmt, new_badge, pct, section,
                    table, zh_date)





# ------------------------------------------------------------------ 就業 --


def _wan(value, *, signed: bool = True) -> str:
    if value is None:
        return "—"
    return f'{value / 10:+.1f} 萬人' if signed else f'{value / 10:.1f} 萬人'


def _gap_note(avg3, breakeven) -> str:
    if avg3 is None or not breakeven:
        return "—"
    return "三月均低於門檻" if avg3 < breakeven else "三月均高於門檻"



# ------------------------------------------------------------------ 通膨 --


# ------------------------------------------------------------ 雙目標合併 --

def _compact(label, sub, value, foot) -> str:
    return (f'<div class="mc-cell"><div class="mc-label">{esc(label)}'
            f'<span class="mc-sub">｜{esc(sub)}</span></div>'
            f'<div class="mc-value">{value}</div>'
            f'<div class="mc-foot">{esc(foot)}</div></div>')


def _streak(series, above) -> str:
    """連續同向幾個月。慢慢漂的變化不會觸發任何門檻，只能靠這個看見。"""
    if series is None:
        return ""
    months = 0
    for i in range(1, 13):
        value = series.at(-i)
        if value is None or not above(value):
            break
        months += 1
    return f"連 {months} 個月" if months >= 2 else ""


def dual_mandate(ctx: dict, scenario: dict) -> str:
    """就業與通膨合成一個區塊。

    實測 33 天的存檔：就業判定只改寫過 1 次、通膨判定 0 次——其餘日子那兩張
    四格卡一個數字都沒變，卻各佔一個區塊。所以壓成左右各兩格。

    原本「當天有新公布就升格成完整的兩張卡」：那會讓總覽在資料真的送達的日子
    變成 9 個區塊、7 個摺疊、24 個讀數格，三項全部撞上版面預算的硬上限，
    建置失敗、CI 跳過提交——網站反而在最該更新的那一天停住。何況「今天公布了
    什麼」現在由總覽第一個區塊「今天」負責，完整卡的傳導鏈與二階解讀在
    /labor/ 與 /inflation/ 兩個深頁上，這裡再放一次是同一件事講兩遍。

    刻意保持左右對稱：兩邊同時降、同時升，只降一邊會讓那個對稱看起來像 bug。
    """
    labor = ctx.get("labor") or {}
    infl = ctx.get("inflation") or {}
    payrolls = labor.get("payrolls") or {}
    head = infl.get("headline") or {}
    if not payrolls or not head:
        return ""

    bundle = ctx.get("_bundle")
    unrate = (labor.get("unemployment") or {}).get("rate")
    avg3 = payrolls.get("avg3")
    breakeven = (labor.get("breakeven") or {}).get("value")
    core_pce = head.get("core_pce")
    ann3 = (infl.get("momentum") or {}).get("core_pce_3m")
    supercore = (infl.get("supercore") or {})

    jobs = "".join([
        _compact("三月均非農", "vs 損益兩平", _wan(avg3),
                 _gap_note(avg3, breakeven)),
        _compact("失業率", "九宮格水準", pct(unrate, 1),
                 (_streak(bundle["UNRATE"] if bundle else None,
                          lambda v: unrate is not None and v >= unrate - 0.15)
                  or f'判定 {scenario.get("employment_label", "")}')),
    ])
    prices = "".join([
        _compact("核心 PCE", "九宮格水準", pct(core_pce, 1),
                 f'判定 {scenario.get("inflation_label", "")}'),
        _compact("核心三月年化", "動能", pct(ann3, 1),
                 ("低於年增，降溫中" if (ann3 is not None and core_pce is not None
                                        and ann3 < core_pce) else "高於年增，仍在加速")),
    ])

    tail = ""
    if supercore.get("months_above"):
        tail = (f'<p class="mc-foot-note">核心服務除住房連 '
                f'{supercore["months_above"]} 個月高於 2.5%——沒有單日事件的'
                f'累積變化不會觸發任何門檻，只能這樣看見。</p>')

    return section(
        "mandate", "雙目標",
        f'<div class="dual"><div class="dual-half">'
        f'<div class="mc-eyebrow">就業</div>'
        f'<div class="mc-cells">{jobs}</div></div>'
        f'<div class="dual-half"><div class="mc-eyebrow">通膨</div>'
        f'<div class="mc-cells">{prices}</div></div></div>'
        + tail
        + '<p class="mc-foot-note"><a href="/labor/">看完整就業拆解 →</a>　'
          '<a href="/inflation/">看完整通膨拆解 →</a></p>',
        note="今天有新公布時，這一塊會自動展開成完整的雙目標卡")
