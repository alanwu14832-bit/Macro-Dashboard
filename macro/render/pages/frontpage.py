"""頭版頭條：有事報事，沒事報判定。

「邊際」的首頁是一份日報的頭版，頭條只能有一則。規則寫死、順序固定，同一份資料
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

這裡只決定「說什麼」，不決定「長什麼樣」——回傳的是資料，排版在 front_blocks.py。
"""
from __future__ import annotations

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


def lede(events: dict | None, scenario: dict, bundle=None) -> dict:
    """今天的頭條。回傳 kind／eyebrow／headline／figure／deck／href／quiet。

    quiet 只在頭條退回情境判定時有值——那一行「今天沒有重大數據或政策決議」
    （或行事曆抓不到時的那句「沒有偵測到…可能漏列」）要跟著頭條一起出現。
    """
    today = [e for e in (events or {}).get("events") or [] if e.get("today")]
    policy = [e for e in today if e.get("kind") == "policy"]
    data = [e for e in today if e.get("kind") == "data" and e.get("id") in LEDE_GRADE]
    data.sort(key=lambda e: LEDE_GRADE.index(e["id"]))

    def from_policy(event: dict, kind: str) -> dict:
        headline, figure = _split_policy_title(event["title"])
        return {"kind": kind, "eyebrow": event["tag"], "headline": headline,
                "figure": figure, "deck": event.get("detail", ""), "href": event.get("href", "/")}

    missing = [e for e in policy if e.get("policy") == "遺漏"]
    if missing:
        return {**from_policy(missing[0], "gap"), "quiet": ""}

    announced = sorted((e for e in policy if e.get("policy") in POLICY_RANK),
                       key=lambda e: POLICY_RANK[e["policy"]])
    if announced:
        return {**from_policy(announced[0], "policy"), "quiet": ""}

    published = [e for e in data if "已公布" in e.get("tag", "")]
    if published:
        return {**data_lede(published[0], bundle), "quiet": ""}

    pending = [e for e in policy if e.get("policy") == "待公布"]
    if pending:
        return {**from_policy(pending[0], "pending"), "quiet": ""}

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
