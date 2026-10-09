"""頭版頭條：有事報事，沒事報判定。

首頁是一份日報的頭版，頭條只能有一則。規則寫死、順序固定，同一份資料
每次得到同一則頭條：

  1. 央行決議遺漏      本站該拿到卻沒拿到——這比任何新聞都該先被看見
  2. 今天公布的決議    FOMC、台灣央行（轉向 > 變動 > 調整 > 不變）
  3. 今天公布的頭條級數據
  4. 今天稍晚要公布的決議
  5. 今天稍晚要公布的頭條級數據
  6. 以上皆無          頭條退回「目前情境」那句判定，「今天沒事」縮成一行

「頭條級」是編輯判斷，不是資料屬性，所以明列在 LEDE_GRADE：只有會直接移動九宮格
或市場整體定價的發布才上頭版。初領失業金每週四都公布，讓它每週搶走頭版等於把雜訊
當新聞；它仍然列在「今天」的清單裡，只是不當頭條。

頭版分成美國版與台灣版，兩版各跑一次同一套順序，各自只看自己那一邊的事件
（events.for_region）。差別只在第 6 條：美國版退回九宮格的判定；台灣沒有九宮格，
退回的是國發會的燈號——那是機構的事實，不是本站的判定，所以台灣版的頭條永遠
不會出現本站下的結論句。

這裡只決定「說什麼」，不決定「長什麼樣」——回傳的是資料，排版在 front_blocks.py。
"""
from __future__ import annotations

import re

from ..html import zh_date
from .release import SPECS, _reading

# 會上頭版的數據，順序＝同一天有多項時的優先序。
LEDE_GRADE = ["PAYEMS", "CPIAUCSL", "PCEPILFE", "GDPC1", "UNRATE"]

POLICY_RANK = {"轉向": 0, "變動": 1, "調整": 2, "不變": 3}

# 情境判定當頭條時的後半句。前半句是九宮格的格名（通膨未解、軟著陸邊緣…）。
# 每一句拆成兩段：頭條的字很大，中文沒有空格，斷行點只能自己給。
REGIME_PHRASES = {
    "inflation_first": ("聯準會的重心", "仍在物價"),
    "employment_first": ("聯準會的重心", "已轉向就業"),
    "balanced": ("兩個目標", "互相牽制"),
}
REGIME_CLAUSE = {key: "".join(parts) for key, parts in REGIME_PHRASES.items()}

MODE_LABEL = {"yoy": "年增", "diff": "月增", "level": ""}

QUIET = "今天沒有重大數據或政策決議。"


def _split_policy_title(title: str) -> tuple[str, str]:
    """'聯準會升息 1 碼　3.50%–3.75% → 3.75%–4.00%' -> (標題, 數字行)。"""
    head, _, figure = title.partition("　")
    return head.strip(), figure.strip()


def _figure(value: float | None, spec: dict, series_id: str) -> str:
    if value is None:
        return "—"
    if series_id == "PAYEMS":          # 千人 → 萬人，月增要帶正負號
        return f"{value / 10:+.1f} 萬人"
    unit = spec["unit"].strip()
    sign = "+" if spec["mode"] == "diff" else ""
    text = f"{value:{sign},.{spec['digits']}f}"
    return f"{text}{unit}" if unit == "%" else f"{text} {unit}"


def _change_phrase(reading: dict, spec: dict, series_id: str) -> str:
    prior, change = reading.get("prior"), reading.get("change")
    if prior is None or change is None:
        return "沒有可比較的前值。"
    before = _figure(prior, spec, series_id)
    if abs(change) < 10 ** -(spec["digits"] + 1):
        return f"前值 {before}，持平。"
    word = "上升" if change > 0 else "下降"
    if series_id == "PAYEMS":
        size = f"{abs(change) / 10:.1f} 萬人"
    elif spec["unit"].strip() == "%":
        size = f"{abs(change):.{spec['digits']}f} 個百分點"
    else:
        size = f"{abs(change):,.{spec['digits']}f} {spec['unit'].strip()}"
    return f"前值 {before}，{word} {size}。"


def data_lede(event: dict, bundle) -> dict:
    """已公布的頭條級數據：標題是指標名，數字行是讀數，副題跟前值比。"""
    series_id = event.get("id")
    spec = SPECS.get(series_id) or {}
    reading = _reading(bundle[series_id], spec) if (bundle is not None and spec) else None
    label = MODE_LABEL.get(spec.get("mode", ""), "")
    headline = f"{event['title']}{label}" if label else event["title"]
    if not reading:
        return {"kind": "data", "eyebrow": event["tag"], "headline": headline,
                "figure": "", "deck": event.get("detail", ""),
                "href": f"/release/{series_id}/" if series_id else "/freshness/"}
    feeds = spec.get("feeds")
    return {
        "kind": "data", "eyebrow": event["tag"], "headline": headline,
        "figure": _figure(reading["value"], spec, series_id),
        "deck": _change_phrase(reading, spec, series_id) + (f"它餵的是：{feeds}。" if feeds else ""),
        "href": f"/release/{series_id}/",
    }


def verdict_lede(scenario: dict) -> dict:
    clause = REGIME_CLAUSE.get(scenario.get("regime"), "")
    name = scenario.get("name") or ""
    headline = f"{name}，{clause}。" if clause else f"{name}。"
    parts = REGIME_PHRASES.get(scenario.get("regime"))
    phrases = [f"{name}，", parts[0], f"{parts[1]}。"] if parts else [headline]
    return {"kind": "verdict", "eyebrow": "目前情境", "headline": headline, "figure": "",
            "phrases": phrases,
            "deck": (scenario.get("regime_explain") or "") + "。", "href": "/scenario/"}


# ------------------------------------------------------------- 台灣版 ----

# 台灣版會上頭條的發布（名字是 sources/twcal.MAJOR 的），順序＝同一天多項時的優先序。
# 失業率與工業生產不上：台灣失業率一個月動 0.01 到 0.03 個百分點，當頭條是把雜訊當新聞。
TW_LEDE_GRADE = ["GDP 與經濟成長率", "消費者物價（CPI）", "景氣對策信號", "海關進出口", "外銷訂單"]

TW_QUIET = "今天台灣沒有重大數據或政策決議。"


def _held(taiwan: dict, label: str):
    """本站手上這個指標的最新讀數：(文字, 資料日期, 頻率)。沒有就回 None。"""
    cycle, ext = taiwan.get("cycle") or {}, taiwan.get("external") or {}
    labour, output = taiwan.get("labour") or {}, taiwan.get("output") or {}
    if label == "景氣對策信號" and cycle.get("score") is not None:
        light = f"　{cycle['light']}燈" if cycle.get("light") else ""
        return f"{cycle['score']:.0f} 分{light}", cycle.get("score_date"), "m"
    if label == "消費者物價（CPI）" and labour.get("cpi_yoy") is not None:
        return f"年增 {labour['cpi_yoy']:.2f}%", labour.get("cpi_date"), "m"
    if label == "GDP 與經濟成長率" and output.get("gdp_growth") is not None:
        return f"年增 {output['gdp_growth']:.2f}%", output.get("gdp_date"), "q"
    if label == "海關進出口" and ext.get("customs_yoy") is not None:
        return f"出口年增 {ext['customs_yoy']:+.1f}%", ext.get("customs_date"), "m"
    if label == "外銷訂單" and ext.get("orders_amount_yoy") is not None:
        return f"金額年增 {ext['orders_amount_yoy']:+.1f}%", ext.get("orders_amount_date"), "m"
    return None


def _roc_month(period: str) -> tuple[int, int] | None:
    """發布看板的資料期「11509」→ (2026, 9)。季資料與其他寫法認不得就回 None。"""
    match = re.fullmatch(r"(\d{3})(\d{2})", (period or "").strip())
    if not match or not 1 <= int(match.group(2)) <= 12:
        return None
    return int(match.group(1)) + 1911, int(match.group(2))


def tw_data_lede(event: dict, taiwan: dict) -> dict:
    """台灣的頭條級數據。

    看板說「已公布」不代表本站已經抓到那一期——各部會的資料庫常常晚看板幾個小時。
    所以數字行只在本站手上那一筆的月份對得上看板的資料期時才出現；對不上就在副題
    講明本站手上是哪一個月的，不把舊數字印成今天的頭條。
    """
    published = "已公布" in event.get("tag", "")
    held = _held(taiwan or {}, event["title"])
    period = _roc_month(event.get("period", ""))
    figure, deck = "", event.get("detail", "")
    if held and held[1] is not None:
        text, when, freq = held
        stamp = zh_date(when, freq=freq)
        if not published:
            deck = f"上一期（{stamp}）{text}。" + deck
        elif period and (when.year, when.month) == period:
            figure = text
        elif period:
            deck += f"本站手上最新的是 {stamp} 的 {text}，這一期還沒有進來。"
        else:
            deck += f"本站手上最新的是 {stamp} 的 {text}。"
    return {"kind": "data" if published else "pending", "eyebrow": event["tag"],
            "headline": event["title"], "figure": figure, "deck": deck,
            "href": event.get("href") or "/taiwan/"}


def state_lede(taiwan: dict) -> dict:
    """台灣版沒事的日子：報國發會的燈號。kind 是 state（機構事實），不是 verdict。"""
    cycle, money = (taiwan or {}).get("cycle") or {}, (taiwan or {}).get("money") or {}
    light, score = cycle.get("light"), cycle.get("score")
    if light is None or score is None:
        return {"kind": "gap", "eyebrow": "台灣　資料缺口",
                "headline": "景氣對策信號這一輪沒有取得。",
                "phrases": ["景氣對策信號", "這一輪", "沒有取得。"], "figure": "",
                "deck": "國發會景氣指標整包抓不到，台灣的循環位置留白；其餘各段各自標明資料日期。",
                "href": "/taiwan/#notes"}
    streak = cycle.get("light_streak") or 0
    tail = f"已連續 {streak} 個月。" if streak > 1 else "本期剛換燈。"
    up, down = cycle.get("leading_up") or 0, cycle.get("leading_down") or 0
    if down >= 3:
        trend = f"領先指標已連續 {down} 個月下滑"
    elif up >= 3:
        trend = f"領先指標連續 {up} 個月走高"
    else:
        trend = "領先指標連續同向不足三個月"
    deck = (f"國發會綜合分數 {score:.0f} 分（{zh_date(cycle.get('score_date'))}），"
            f"屬{cycle.get('light_meaning') or ''}；{trend}。")
    months = money.get("policy_unchanged_months")
    if money.get("policy") is not None:
        deck += f"央行重貼現率 {money['policy']:g}%"
        deck += f"，已 {months} 個月未調整。" if months else "。"
    return {"kind": "state", "eyebrow": "目前位置",
            "headline": f"景氣{light}燈，{tail}",
            "phrases": [f"景氣{light}燈，", tail], "figure": "", "deck": deck,
            "href": "/taiwan/#cycle"}


def lede_tw(events: dict | None, taiwan: dict | None) -> dict:
    """台灣版今天的頭條。events 要先用 events.for_region(…, "台灣") 濾過。"""
    today = [e for e in (events or {}).get("events") or [] if e.get("today")]
    policy = [e for e in today if e.get("kind") == "policy"]
    data = [e for e in today if e.get("kind") == "data" and e.get("title") in TW_LEDE_GRADE]
    data.sort(key=lambda e: TW_LEDE_GRADE.index(e["title"]))

    decided = _decided(policy)
    if decided:
        return decided
    published = [e for e in data if "已公布" in e.get("tag", "")]
    if published:
        return {**tw_data_lede(published[0], taiwan or {}), "quiet": ""}
    pending = _pending(policy)
    if pending:
        return pending
    upcoming = [e for e in data if "已公布" not in e.get("tag", "")]
    if upcoming:
        return {**tw_data_lede(upcoming[0], taiwan or {}), "quiet": ""}
    # fallback＝今天沒事、退回燈號。排版用它決定頭條底下要不要再放一格「目前位置」。
    return {**state_lede(taiwan or {}), "fallback": True,
            "quiet": (events or {}).get("verdict") or TW_QUIET}


# ------------------------------------------------------------- 共用 ------

def _from_policy(event: dict, kind: str) -> dict:
    headline, figure = _split_policy_title(event["title"])
    return {"kind": kind, "eyebrow": event["tag"], "headline": headline,
            "figure": figure, "deck": event.get("detail", ""), "href": event.get("href", "/"),
            "quiet": ""}


def _decided(policy: list[dict]) -> dict | None:
    """決議遺漏，否則今天公布的決議（轉向 > 變動 > 調整 > 不變）。"""
    missing = [e for e in policy if e.get("policy") == "遺漏"]
    if missing:
        return _from_policy(missing[0], "gap")
    announced = sorted((e for e in policy if e.get("policy") in POLICY_RANK),
                       key=lambda e: POLICY_RANK[e["policy"]])
    return _from_policy(announced[0], "policy") if announced else None


def _pending(policy: list[dict]) -> dict | None:
    pending = [e for e in policy if e.get("policy") == "待公布"]
    return _from_policy(pending[0], "pending") if pending else None


def lede(events: dict | None, scenario: dict, bundle=None) -> dict:
    """今天的頭條。回傳 kind／eyebrow／headline／figure／deck／href／quiet。

    quiet 只在頭條退回情境判定時有值——那一行「今天沒有重大數據或政策決議」
    （或行事曆抓不到時的那句「沒有偵測到…可能漏列」）要跟著頭條一起出現。
    """
    today = [e for e in (events or {}).get("events") or [] if e.get("today")]
    policy = [e for e in today if e.get("kind") == "policy"]
    data = [e for e in today if e.get("kind") == "data" and e.get("id") in LEDE_GRADE]
    data.sort(key=lambda e: LEDE_GRADE.index(e["id"]))

    decided = _decided(policy)
    if decided:
        return decided

    published = [e for e in data if "已公布" in e.get("tag", "")]
    if published:
        return {**data_lede(published[0], bundle), "quiet": ""}

    pending = _pending(policy)
    if pending:
        return pending

    upcoming = [e for e in data if "已公布" not in e.get("tag", "")]
    if upcoming:
        event = upcoming[0]
        spec = SPECS.get(event["id"]) or {}
        reading = _reading(bundle[event["id"]], spec) if (bundle is not None and spec) else None
        before = (f"上一期 {_figure(reading['value'], spec, event['id'])}。" if reading else "")
        return {"kind": "pending", "eyebrow": event["tag"], "headline": event["title"],
                "figure": "", "deck": before + event.get("detail", ""),
                "href": f"/release/{event['id']}/", "quiet": ""}

    quiet = (events or {}).get("verdict") or QUIET
    return {**verdict_lede(scenario), "quiet": quiet}
