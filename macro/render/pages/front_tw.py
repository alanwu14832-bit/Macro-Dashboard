"""頭版的台灣版。

段落跟美國版一一對應（頭條、圖、四個數字、本站的判定、今天、接下來、今日價格、
別人怎麼說），錨點都以 tw- 開頭；排版的零件與三條規矩都沿用 front_blocks。

有一件事跟美國版不一樣，而且不能假裝一樣：本站沒有為台灣訂情境規則，沒有九宮格。
所以——

  頭條        沒事的日子報的是國發會的燈號。那是機構的事實（印「實」），
              不是本站的判定；台灣版的頭條永遠不會出現本站下的結論句。
  圖與尺      燈號的分界是國發會訂的，圖上用灰底、不用斜線——斜線在這一頁專指
              「本站規則判定的區域」。出口、物價、利率本站沒有寫死的門檻，
              一律畫區間尺（虛線）。
  本站的判定  只列觸發的規則，不下結論句、不標升降息方向（紅與藍專指聯準會）。

台灣各項統計的月份本來就不一致（財政部出口最快，景氣燈號慢一個多月），
每一列都帶自己的資料期，不對齊到同一個月。
"""
from __future__ import annotations

from datetime import date, timedelta

from ... import cbc_board, clock
from ...compute import taiwan as rules
from ...sources import ndc
from ..html import SEV_TEXT, accordion, attr_json, esc, fmt, zh_date
from . import front_blocks as fb
from . import frontpage
from .front_blocks import MINUS, _signed, note, row, sec_open

# 各燈號的下緣（國發會的定義）：藍 9、黃藍 17、綠 23、黃紅 32、紅 38。
LIGHTS = [name for _top, name in ndc.LIGHT_BANDS]
FLOORS = dict(zip(LIGHTS, [9] + [top + 1 for top, _name in ndc.LIGHT_BANDS[:-1]]))
SCORE_MIN, SCORE_MAX = 9, ndc.LIGHT_BANDS[-1][0]


def _rate(value: float) -> str:
    """重貼現率是八分之一碼一跳（1.875%），但整數的時候不要寫成 2.000%。"""
    text = f"{value:.3f}".rstrip("0")
    whole, _, frac = text.partition(".")
    return f"{whole}.{frac.ljust(2, '0')}%"


def _md(day: date) -> str:
    return f"{day.month}/{day.day}"


def next_meeting(taiwan: dict) -> dict | None:
    """下一次央行理監事會。日程用央行公告的，公告抓不到時退回寫死的那一份。"""
    today = clock.today()
    for meeting in cbc_board.meetings((taiwan or {}).get("cbc_schedule") or []):
        if meeting >= today:
            return {"date": meeting, "days": (meeting - today).days}
    return None


def light_gate(score: float | None, light: str | None) -> dict | None:
    """離最近一次換燈多遠。

    往下：分數低於這個燈的下緣才換燈，所以寫「高出下緣幾分」，圖上那條線畫在下緣。
    往上：達到下一個燈的下緣就換燈，寫「還差幾分」。兩邊一樣近時報往下的那一邊。
    """
    if score is None or light not in LIGHTS:
        return None
    index = LIGHTS.index(light)
    down = up = None
    if index:
        down = {"dir": "down", "word": "高出", "value": score - FLOORS[light],
                "line": FLOORS[light], "to": LIGHTS[index - 1],
                "rule": f"低於 {FLOORS[light]} 分轉為{LIGHTS[index - 1]}燈"}
    if index < len(LIGHTS) - 1:
        floor = FLOORS[LIGHTS[index + 1]]
        up = {"dir": "up", "word": "還差", "value": floor - score, "line": floor,
              "to": LIGHTS[index + 1], "rule": f"達到 {floor} 分轉為{LIGHTS[index + 1]}燈"}
    if down and (up is None or down["value"] + 1 <= up["value"]):
        return down
    return up


# -------------------------------------------------- 頁邊：自上一期以來 ----

def since_items(diff: dict, changes: list[dict] | None) -> list[dict]:
    """跟上一期比，台灣變了什麼。順序：換燈 > 新訊號 > 讀數 > 訊號退場。"""
    items: list[dict] = []
    for change in changes or []:
        if change.get("text"):
            items.append({"big": change["text"], "text": True, "name": change["name"],
                          "ft": "國發會的燈號改變"})
    added = diff.get("added") or []
    if added:
        more = f"等 {len(added)} 條" if len(added) > 1 else ""
        items.append({"big": f"+{len(added)}", "name": "新增訊號", "long": True,
                      "ft": esc(added[0].get("headline") or "") + more})
    for change in changes or []:
        if change.get("text"):
            continue
        digits = change.get("digits", 2)
        unit = change.get("unit") or ""
        unit = unit if unit == "%" else f" {unit}"
        items.append({"big": _signed(change["change"], digits), "name": change["name"],
                      "ft": f'{fmt(change["was"], digits)} → '
                            f'<em>{fmt(change["now"], digits)}{esc(unit)}</em>'})
    removed = diff.get("removed") or []
    if removed:
        more = f"等 {len(removed)} 條" if len(removed) > 1 else ""
        items.append({"big": f"{MINUS}{len(removed)}", "name": "不再觸發", "long": True,
                      "ft": esc(removed[0].get("headline") or "") + more})
    return items


# ------------------------------------------------------------------ 頭條 ----

def gist_blocks(taiwan: dict, signals: list[dict], equities: dict, standing: dict | None,
                story: str = "") -> str:
    """頭條底下的三句：央行（或目前位置）、本站規則、市場。責任不同，所以分欄。"""
    money = taiwan.get("money") or {}
    blocks = []
    if standing:
        blocks.append(("目前位置", f'<a href="/taiwan/#cycle">{esc(standing["headline"])}</a>'))
    elif money.get("policy") is not None:
        text = f'重貼現率 {_rate(money["policy"])}'
        if money.get("policy_unchanged_months"):
            text += f'，已 {money["policy_unchanged_months"]} 個月未調整'
        meeting = next_meeting(taiwan)
        if meeting:
            text += (f'<span class="dash">——</span>下次理監事會 <strong>{_md(meeting["date"])}</strong>'
                     f'（{fb._when(meeting["days"])}）')
        blocks.append(("央行", text + "。"))

    high = sum(1 for s in signals if s.get("severity") == "high")
    if signals:
        rule = (f'台灣規則觸發 <strong>{len(signals)} 條</strong>'
                + (f'，其中 {high} 條嚴重' if high else "") + "。")
    else:
        rule = "台灣規則目前沒有觸發。"
    blocks.append(("本站規則", rule + "台灣沒有九宮格，這一版不下結論句。"))

    market = []
    index = next((r for r in equities.get("index") or [] if str(r.get("symbol")) == "^TWII"), None)
    if index and index.get("price") is not None:
        text = f'加權指數 {fmt(index["price"], 2)}'
        if index.get("change_percent") is not None:
            text += f'（{_signed(index["change_percent"], 2)}%）'
        market.append(text)
    foreign = (equities.get("institutional") or {}).get("foreign")
    if foreign is not None:
        market.append(f'外資 {_signed(foreign, 1)} 億')
    if market:
        blocks.append(("市場", "；".join(market) + "。"))
    return fb.lead_note("".join(f'<div class="gist"><h2>{esc(name)}</h2><p>{text}</p></div>'
                                for name, text in blocks), story)


def hero(ctx: dict, signals: list[dict], diff: dict, changes: list[dict] | None,
         prior: dict | None, events: dict | None, *, story: dict | None = None) -> tuple[str, bool]:
    """台灣版的頭條＋頁邊的變動欄。回傳 (HTML, 有沒有變動)。

    changes 是 None 代表上一期的存檔沒有記台灣讀數——比不了，要明講。
    """
    taiwan = ctx.get("taiwan") or {}
    lede = frontpage.lede_tw(events, taiwan)
    items = since_items(diff, changes)
    base = (prior or {}).get("date") or "上一期"
    if changes is None:
        none_text = "上一期沒有記台灣的讀數，下一期開始比對。"
    else:
        none_text = f"台灣的規則訊號與關鍵讀數與 {base} 相同。"
    standing = None
    if not lede.get("fallback"):
        state = frontpage.state_lede(taiwan)
        standing = state if state["kind"] == "state" else None
    body = fb.hero_shell(
        lede,
        fb.since_block(items, prior, bool(diff.get("first_run")), prefix="tw-",
                       none_text=none_text),
        gist_blocks(taiwan, signals, (ctx.get("equities") or {}).get("tw") or {}, standing,
                    fb.story_block(story, events)),
        prefix="tw-", nav="台灣｜頭條")
    return body, bool(items)


# ------------------------------------------------- 圖：景氣對策信號 ----

def signal_chart(ctx: dict) -> str:
    """景氣對策信號綜合分數對國發會的燈號分界。跟美國版那張同一個畫法：
    Y 軸就是版面那條直線，分界寫在頁邊。差別是這裡的分界是官方的，所以紅燈的
    時段塗灰底，不打斜線。"""
    cycle = (ctx.get("taiwan") or {}).get("cycle") or {}
    score, light, series = cycle.get("score"), cycle.get("light"), cycle.get("score_series")
    gate = light_gate(score, light)
    if gate is None or not series:
        return ""
    recent = series.tail(36)
    if len(recent.values) < 6:
        return ""
    values = [round(v, 1) for v in recent.values]
    lo = max(SCORE_MIN - 1, min(values + [gate["line"]]) - 3)
    hi = min(SCORE_MAX + 1, max(values + [gate["line"]]) + 3)
    red, yellow_blue = FLOORS["紅"], FLOORS["黃藍"]
    zones = []
    if max(values) >= red:
        zones.append({"dir": "above", "v": red, "style": "tint"})
    if min(values) < yellow_blue:
        zones.append({"dir": "below", "v": yellow_blue, "style": "tint"})
    spec = {
        "dates": [d.isoformat() for d in recent.dates], "values": values,
        "lo": lo, "hi": hi, "grid": 5, "digits": 0,
        # short：手機的頁邊只有 70px，「黃藍燈 17」放不下
        "thr": [{"v": floor, "name": f"{name}燈", "short": name}
                for name, floor in FLOORS.items() if lo < floor < hi],
        "gate": gate["line"], "goal": None, "zones": zones,
        "gap": f'{gate["value"]:.0f}', "gapWord": gate["word"],
        "last": f"{score:.0f} 分", "ann3": None, "trend": "",
    }
    if gate["dir"] == "down":
        title = (f'景氣分數高出{light}燈下緣 {gate["value"]:.0f} 分。' if gate["value"] > 0
                 else f'景氣分數正好在{light}燈下緣。')
    else:
        title = f'景氣分數離{gate["to"]}燈還差 {gate["value"]:.0f} 分。'
    period = zh_date(recent.dates[-1], freq="m")
    shaded = []
    if any(z["dir"] == "above" for z in zones):
        shaded.append(f"紅燈（{red} 分以上）")
    if any(z["dir"] == "below" for z in zones):
        shaded.append(f"藍燈（低於 {yellow_blue} 分）")
    shade_note = f'灰底是{"與".join(shaded)}的時段；' if shaded else ""
    label = (f"景氣對策信號綜合分數折線圖。最新值 {score:.0f} 分，{light}燈；"
             f"{gate['rule']}。分界由國發會定義。")
    return (
        '<div class="sec gate">'
        + row(f'<h2>{esc(title)}</h2>'
              f'<p>國發會景氣對策信號綜合分數，{SCORE_MIN} 到 {SCORE_MAX} 分。'
              f'分界是國發會訂的：{esc(gate["rule"])}。</p>', cls="sh rv", tag="header")
        + f'<figure class="row gchart rv" role="img" aria-label="{esc(label)}" '
          f'data-gate="{attr_json(spec)}">'
          '<div class="b"><div class="plot"></div></div>'
          '<div class="m yax" aria-hidden="true"></div></figure>'
        + row(f'<p class="fig-src">資料：國家發展委員會，至 {esc(period)}。{shade_note}'
              '分界是官方定義，不是本站的門檻，所以不打斜線。'
              '<a href="/taiwan/#cycle">看台灣景氣循環 →</a></p>')
        + '</div>')


# -------------------------------------------------------------- 四個數字 ----

def _year_range(series, now: float | None, *, points: int = 12) -> tuple[float, float]:
    values = list(series.tail(points).values) if series is not None and len(series) else []
    if now is not None:
        values.append(now)
    return (min(values), max(values)) if values else (0.0, 1.0)


def _range_ruler(now, prev, lo, hi, *, digits: int, span: str, name: str, show=None) -> dict:
    """區間尺：沒有寫死的門檻，只標一段期間的高低點。show 是數字的寫法（預設固定小數位）。"""
    show = show or (lambda value: f"{value:.{digits}f}")
    pad = (hi - lo) * 0.04 or 0.5
    return dict(lo=lo - pad, hi=hi + pad, now=now, prev=prev, kind="range", flag=show(now),
                ticks=[(lo, f"{show(lo)} {span}低點"), (hi, f"{show(hi)} {span}高點")],
                label=f"{name} {show(now)}；{span}區間 {show(lo)} 到 {show(hi)}。這是區間，不是門檻")


def figure_rows(ctx: dict, changes: list[dict] | None) -> list[dict]:
    """台灣版的四個數字：循環、外需、物價、利率——台灣總經頁由上往下的那條傳導鏈。"""
    taiwan = ctx.get("taiwan") or {}
    cycle, external = taiwan.get("cycle") or {}, taiwan.get("external") or {}
    labour, money = taiwan.get("labour") or {}, taiwan.get("money") or {}
    changed = {c["name"]: c for c in changes or [] if not c.get("text")}

    def prev_of(name: str, now):
        return changed[name]["was"] if name in changed else now

    empty = dict(lo=0, hi=1, now=None)
    rows = []

    # 1. 景氣對策信號：五個燈號的分界是國發會訂的
    score, light = cycle.get("score"), cycle.get("light")
    gate = light_gate(score, light)
    streak = cycle.get("light_streak") or 0
    rows.append({
        "name": "景氣對策信號", "href": "/taiwan/#cycle", "unit": "分",
        "value": fmt(score, 0, dash="—"), "missing": score is None,
        "read": f"{light}燈" if light else "",
        "sub": (f'{cycle.get("light_meaning") or ""}，同色連續 {streak} 個月。'
                f'資料期 {zh_date(cycle.get("score_date"))}；分界是國發會訂的'
                if score is not None else "國發會景氣指標這一輪沒有取得"),
        "change": changed.get("景氣對策信號"),
        "ruler": (dict(lo=SCORE_MIN, hi=SCORE_MAX, now=score,
                       prev=prev_of("景氣對策信號", score), kind="threshold", step=1,
                       flag=fmt(score, 0), dense=True,
                       ticks=[(floor, str(floor)) for name, floor in FLOORS.items() if name != "藍"],
                       zones=[(FLOORS[name], FLOORS[LIGHTS[i + 1]] if i + 1 < len(LIGHTS)
                               else SCORE_MAX + 1, name) for i, name in enumerate(LIGHTS)],
                       label=f"景氣對策信號 {fmt(score, 0)} 分，{light}燈；"
                             "國發會分界：17 黃藍、23 綠、32 黃紅、38 紅")
                  if score is not None else empty),
        "gap": ({"word": gate["word"], "value": f'{gate["value"]:.0f}',
                 "what": f'{light}燈下緣' if gate["dir"] == "down" else f'離{gate["to"]}燈',
                 "unit": "分"} if gate else None),
    })

    # 2. 出口年增：財政部按美元計；抓不到時退回國發會轉載、按新台幣計的那一檔
    yoy, when, series = (external.get("customs_yoy"), external.get("customs_date"),
                         external.get("customs_yoy_series"))
    basis = "財政部，美元計"
    if yoy is None:
        yoy, when, series = (external.get("exports_yoy"), external.get("exports_date"),
                             external.get("exports_yoy_series"))
        basis = "國發會轉載，新台幣計"
    orders = external.get("orders_amount_yoy")
    lo, hi = _year_range(series, yoy)
    rows.append({
        "name": "出口年增", "href": "/taiwan/#external",
        "value": fmt(yoy, 1, suffix="%", signed=True, dash="—"), "missing": yoy is None,
        "read": f"外銷訂單 {_signed(orders, 1)}%" if orders is not None else "",
        "sub": ((f'（{zh_date(external.get("orders_amount_date"))}），領先出口一到三個月。'
                 if orders is not None else "")
                + f'出口資料期 {zh_date(when)}，{basis}。沒有寫死的門檻，只標近一年區間'
                if yoy is not None else "財政部與國發會的出口統計這一輪都沒有取得"),
        "change": changed.get("出口年增"),
        "ruler": (_range_ruler(yoy, prev_of("出口年增", yoy), lo, hi, digits=1,
                               span="一年", name="出口年增率") if yoy is not None else empty),
        "gap": None,
    })

    # 3. CPI 年增：本站沒有台灣的物價門檻
    cpi = labour.get("cpi_yoy")
    lo, hi = _year_range(labour.get("cpi_series"), cpi)
    rows.append({
        "name": "CPI 年增", "href": "/taiwan/#labour",
        "value": fmt(cpi, 2, suffix="%", dash="—"), "missing": cpi is None,
        "read": "",
        "sub": (f'主計總處總指數，資料期 {zh_date(labour.get("cpi_date"))}。'
                "沒有寫死的門檻，只標近一年區間"
                if cpi is not None else "主計總處消費者物價指數這一輪沒有取得，這一格留白，不補前值"),
        "change": changed.get("CPI 年增"),
        "ruler": (_range_ruler(cpi, prev_of("CPI 年增", cpi), lo, hi, digits=2,
                               span="一年", name="CPI 年增率") if cpi is not None else empty),
        "gap": None,
    })

    # 4. 重貼現率：階梯，一年可能一次都不動，所以區間看十年
    policy = money.get("policy")
    lo, hi = _year_range(money.get("policy_series"), policy, points=120)
    months = money.get("policy_unchanged_months")
    spread, fed = money.get("spread_vs_fed"), money.get("fed_upper")
    sub = ""
    if money.get("policy_source"):
        sub += "依理監事會決議，貼放利率表尚未更新。"
    if spread is not None:
        sub += f'台美政策利差 {_signed(spread, 2)} pp（聯準會上緣 {fed:.2f}%）。'
    sub += "沒有寫死的門檻，只標近十年區間"
    rows.append({
        "name": "重貼現率", "href": "/taiwan/#money",
        "value": _rate(policy) if policy is not None else "—", "missing": policy is None,
        "read": f"{months} 個月未調整" if months else "",
        "sub": sub if policy is not None else "中央銀行貼放利率頁這一輪沒有取得",
        "change": changed.get("重貼現率"),
        "ruler": (_range_ruler(policy, prev_of("重貼現率", policy), lo, hi, digits=3,
                               span="十年", name="重貼現率", show=lambda v: _rate(v)[:-1])
                  if policy is not None else empty),
        "gap": None,
    })
    return rows


def facts(ctx: dict, changes: list[dict] | None, prior: dict | None) -> str:
    return fb.fact_section(
        figure_rows(ctx, changes), (prior or {}).get("date"),
        anchor="tw-facts", title="四個數字", nav="台灣｜四個數字",
        sub="機構發布的數字，各標各的資料期。燈號的分界是國發會訂的；"
            "其餘三個本站沒有寫死的門檻，只畫區間。",
        comparable=changes is not None)


# ------------------------------------------------------------ 本站的判定 ----

def calls(signals: list[dict]) -> str:
    """台灣只有一個輸出：觸發了幾條規則。沒有情境傾向——本站沒有訂那條規則。"""
    count = {key: sum(1 for s in signals if s.get("severity") == key)
             for key in ("high", "medium", "low")}
    split = "".join(f'<span><i>{count[key]}</i>條{SEV_TEXT[key]}</span>'
                    for key in ("high", "medium", "low") if count[key])
    return row(
        '<div class="calls calls-1"><div class="call">'
        f'<h3>台灣規則訊號 <i>{len(signals)}</i> 條</h3>'
        + (f'<p class="split">{split}</p>' if split else '<p class="big">沒有觸發</p>')
        + '<p class="call-s">本站沒有為台灣訂情境規則，沒有九宮格——所以這裡只有訊號條數，'
          '沒有「情境傾向」那一格。景氣燈號是國發會的，在上面的「四個數字」。</p>'
        '</div></div>', cls="rv")


def verdict(signals: list[dict], diff: dict) -> str:
    """台灣版的判定：觸發的規則，最重的幾條列出來。不標升降息方向。"""
    from ..common import signals_block
    new_keys = {s.get("key") for s in diff.get("added") or []}
    high = [s for s in signals if s.get("severity") == "high"]
    rest = [s for s in signals if s.get("severity") != "high"]
    out = [sec_open("tw-verdict", "本站的判定", kind="判", nav="台灣｜本站的判定",
                    sub="固定規則的輸出，不是機構的數字。台灣的規則一律不標升降息方向"
                        "——紅與藍在本站專指聯準會。"),
           calls(signals)]
    if high:
        out.append(row(f'<h3 class="sub-h">最重的 {len(high)} 條規則訊號</h3>', cls="rv"))
        out.extend(fb._signal_row(signal, new_keys, direction=False) for signal in high)
    tail = ""
    if rest:
        tail += accordion(f"其餘 {len(rest)} 條訊號",
                          signals_block(rest, grid=True, direction=False))
    tail += '<p class="more"><a href="/taiwan/#signals">台灣的規則與門檻寫在哪裡　→</a></p>'
    out.append(row(tail, cls="rv"))
    out.append("</section>")
    return "".join(out)


# ------------------------------------------------------------------ 今天 ----

def today(ctx: dict, events: dict | None) -> str:
    """台灣版的今天：央行決議與台灣主要統計。沒有「今天更新的序列」那份清單
    （那是 FRED 的更新紀錄），改成把這一輪沒抓到的台灣來源逐條講出來。"""
    taiwan = ctx.get("taiwan") or {}
    gaps = list(taiwan.get("gaps") or []) if taiwan else ["台灣總經模組這一輪沒有計算成功"]
    hint = ""
    upcoming = (events or {}).get("tw_upcoming") or []
    meeting = next_meeting(taiwan)
    if upcoming:
        first = upcoming[0]
        hint = f'下一個：{first["label"]}（{_md(first["date"])}，{fb._when(first["days"])}）。'
    elif meeting:
        hint = f'下一個：央行理監事會（{_md(meeting["date"])}，{fb._when(meeting["days"])}）。'
    return fb.today(ctx, events=events or {}, anchor="tw-today", nav="台灣｜今天",
                    updates=False, gaps=gaps, hint=hint)


# ---------------------------------------------------------------- 接下來 ----

def _next_settlement() -> dict | None:
    """下一個台指期與選擇權月結算日（每月第三個星期三）。"""
    today_ = clock.today()
    for offset in (0, 1):
        year = today_.year + (today_.month + offset - 1) // 12
        month = (today_.month + offset - 1) % 12 + 1
        first = date(year, month, 1)
        third = first + timedelta(days=(2 - first.weekday()) % 7 + 14)
        if third >= today_:
            return {"date": third, "days": (third - today_).days}
    return None


def upcoming(ctx: dict, events: dict | None) -> list[dict]:
    """台灣未來會來的事：央行理監事會、看板上排定的主要統計、期貨結算。"""
    items: list[dict] = []
    meeting = next_meeting(ctx.get("taiwan") or {})
    if meeting:
        items.append({"days": meeting["days"], "kind": "央行", "date": meeting["date"],
                      "what": "理監事會利率決議"})
    for release in (events or {}).get("tw_upcoming") or []:
        items.append({"days": release["days"], "kind": "數據", "date": release["date"],
                      "what": release["label"]})
    settle = _next_settlement()
    if settle:
        items.append({"days": settle["days"], "kind": "期權", "date": settle["date"],
                      "what": "台指期與選擇權月結算"})
    return items


def gates(ctx: dict) -> list[dict]:
    """離換燈、離規則觸發還差多少。第一條是國發會的分界，第二條才是本站的門檻。"""
    taiwan = ctx.get("taiwan") or {}
    cycle, labour = taiwan.get("cycle") or {}, taiwan.get("labour") or {}
    out = []
    gate = light_gate(cycle.get("score"), cycle.get("light"))
    if gate:
        out.append({"kind": "官方分界", "name": f'景氣燈號轉為{gate["to"]}燈',
                    "need": f'綜合分數{gate["rule"].split("轉為")[0]}（國發會的定義）。'
                            f'現在 {cycle["score"]:.0f} 分',
                    "word": gate["word"], "value": f'{gate["value"]:.0f}', "unit": "分"})
    low, rate = labour.get("unemployment_low_12m"), labour.get("unemployment")
    if low is not None and rate is not None:
        weak_at = low + rules.UNEMPLOYMENT_RISE_PP
        if rate < weak_at:
            out.append({"kind": "門檻", "name": "台灣失業率轉弱",
                        "need": f'失業率升到 {weak_at:.2f}% 以上（近 12 個月低點 {low:.2f}% '
                                f'加 {rules.UNEMPLOYMENT_RISE_PP} 個百分點，本站規則）。現在 {rate:.2f}%',
                        "word": "還差", "value": f"{weak_at - rate:.2f}", "unit": "個百分點"})
    return out


def next_up(ctx: dict, events: dict | None, *, horizon: int = 30) -> str:
    """台灣版的接下來。排版跟美國版同一套：直線是今天，橫條越長離得越遠。"""
    out = [sec_open("tw-next", "接下來", kind="", nav="台灣｜接下來",
                    sub="直線是今天，線拉得越長離得越遠。"
                        "統計發布看板只排到一兩週後，更遠的發布日這裡看不到。")]
    for gate in gates(ctx):
        body = (f'<p class="kind"><b>{esc(gate["kind"])}</b></p>'
                f'<div><h3>{esc(gate["name"])}</h3>'
                f'<p class="det">{esc(gate["need"])}</p></div>')
        out.append(row(body, note(f'{esc(gate["word"])} <i>{gate["value"]}</i>', esc(gate["unit"])),
                       cls="nx ln rv", tag="article"))

    items = upcoming(ctx, events)
    dated: dict[int, list[dict]] = {}
    for item in items:
        if item["days"] is not None and 0 <= item["days"] <= horizon:
            dated.setdefault(item["days"], []).append(item)
    if dated:
        span = max(max(dated), 7)
        out.append(row('<span>今天</span><span>一格一天</span>', cls="axis rv",
                       attrs=f' style="--span:{span}"'))
        for days in sorted(dated):
            group = dated[days]
            kinds = "、".join(dict.fromkeys(item["kind"] for item in group))
            names = "、".join(item["what"] for item in group) + f'（{_md(group[0]["date"])}）'
            margin = (note("今天") if days == 0 else note("明天") if days == 1
                      else note(f'<i>{days}</i> 天後'))
            out.append(row(
                '<div class="run"><span class="bar" aria-hidden="true"></span>'
                f'<div class="txt"><p class="kind"><b>{esc(kinds)}</b></p>'
                f'<h3>{esc(names)}</h3></div></div>',
                margin, cls="when rv", tag="article",
                attrs=f' style="--days:{days};--span:{span}"'))
    later = [item for item in items if item["days"] is not None and item["days"] > horizon]
    if later:
        extra = "；".join(f'{esc(item["kind"])}　{esc(item["what"])}'
                         f'（{_md(item["date"])}，{item["days"]} 天後）' for item in later)
        out.append(row(f'<p class="quiet">另外：{extra}。</p>', cls="rv"))
    out.append("</section>")
    return "".join(out)


# -------------------------------------------------------------- 今日價格 ----

def price_rows(ctx: dict) -> list[dict]:
    """台灣版的價格：加權、櫃買、台積電、匯率。沒有變動資料就是 None，不補值。"""
    tw = (ctx.get("equities") or {}).get("tw") or {}
    rows: list[dict] = []
    names = {"^TWII": ("加權指數", "集中市場"), "^TWOII": ("櫃買指數", "中小型股")}
    for item in tw.get("index") or []:
        name, cap = names.get(str(item.get("symbol")), (None, None))
        if not name or item.get("price") is None:
            continue
        rows.append({"name": name, "href": "/tw/", "level": fmt(item["price"], 2), "cap": cap,
                     "chg": (item.get("change_percent"), 2, "%", "")})
    tsmc = next((s for s in tw.get("stocks") or [] if str(s.get("symbol")) == "2330"), None)
    if tsmc and tsmc.get("price") is not None:
        rows.append({"name": "台積電", "href": "/tw/", "level": fmt(tsmc["price"], 0),
                     "cap": "權值最大的一檔", "chg": (tsmc.get("change_percent"), 2, "%", "")})
    fx = tw.get("usdtwd") or {}
    if fx.get("value") is not None:
        stamp = str(fx.get("as_of") or "")[5:].replace("-", "/")
        rows.append({"name": "美元兌新台幣", "href": "/taiwan/#money", "level": fmt(fx["value"], 2),
                     "cap": f"{stamp} 收盤，數字變大＝台幣貶值" if stamp else "數字變大＝台幣貶值",
                     "plain": True, "chg": (fx.get("chg_3m"), 2, "%", "近三月")})
    return rows


def prices(ctx: dict) -> str:
    tw = (ctx.get("equities") or {}).get("tw") or {}
    lines = []
    inst = tw.get("institutional") or {}
    if inst.get("foreign") is not None:
        parts = [f'外資 {_signed(inst["foreign"], 1)} 億']
        for key, name in (("trust", "投信"), ("dealer", "自營")):
            if inst.get(key) is not None:
                parts.append(f'{name} {_signed(inst[key], 1)} 億')
        lines.append(("三大法人", "、".join(parts) + f'（{esc(str(inst.get("date", ""))[5:].replace("-", "/"))}）'))
    margin = tw.get("margin") or {}
    if margin.get("financing_yi") is not None:
        text = f'{fmt(margin["financing_yi"], 1)} 億'
        if margin.get("financing_chg_yi") is not None:
            text += f'，較前一日 {_signed(margin["financing_chg_yi"], 1)} 億'
        lines.append(("融資餘額", text))
    breadth = tw.get("wide_breadth") or {}
    if breadth.get("up") is not None:
        total = breadth["up"] + breadth.get("down", 0) + breadth.get("flat", 0)
        lines.append((f"本站追蹤的 {total} 檔",
                      f'上漲 {breadth["up"]}、下跌 {breadth.get("down", 0)}、持平 {breadth.get("flat", 0)}'))
    groups = [g for g in tw.get("group_avgs") or [] if g.get("value") is not None]
    if len(groups) >= 2:
        best, worst = groups[0], groups[-1]
        lines.append(("類股", f'最強 {esc(best["name"])} {_signed(best["value"], 2)}%，'
                              f'最弱 {esc(worst["name"])} {_signed(worst["value"], 2)}%'))
    status = tw.get("status") or ""
    sub = "頁邊是漲跌。" + (f"台股：{status}。" if status else "") + "匯率取自 FRED，會晚幾個交易日。"
    return fb.price_section(price_rows(ctx), lines, anchor="tw-prices", sub=sub,
                            nav="台灣｜今日價格")
