"""公布前的預期。

本站一直寫「沒有市場共識預期——那是付費資料」。這句話仍然成立，但有三種公布前的預期
是公開、免費、而且有出處的，各自的性質不同，頁面上不能混成一個「預期」：

  利率決議   聯邦基金利率期貨隱含的機率——**市場定價**（compute/fedfunds.py，這裡不重算）
  通膨       克里夫蘭聯準銀行的即時預估——**模型**，每天更新
  GDP        亞特蘭大聯準銀行的 GDPNow——**模型**

非農、失業率、零售銷售這些沒有公開的預期來源，就寫沒有；不拿前值充數。

模型會錯，所以每個預估都帶著它的成績單：過去 TRACK 期「最後一次預估」跟「實際公布」
平均差多少。公布之後的「意外」也拿這個平均差當尺——差 0.05 個百分點算不算意外，
要看這個模型平常就差多少。

通膨的成績單有一個已知的坑：年增率的實際值會受歷史修正影響（2026-09 的年度修正讓
核心 PCE 年增一次差了 0.39 個百分點），月增率比較乾淨。兩個都列。
"""
from __future__ import annotations

from datetime import date

from .. import clock
from ..data import Bundle
from ..sources import nowcast

TRACK = 24                    # 成績單看最近幾期
STALE_DAYS = 10               # 最新的預估超過這麼多天沒更新就不登
INFLATION_NAMES = {"cpi": "CPI", "core_cpi": "核心 CPI", "pce": "PCE", "core_pce": "核心 PCE"}
# 哪一項發布（release 頁的代號）對應哪幾個預估。CPI 那一天同時公布總體與核心。
RELEASES = {
    "CPIAUCSL": ["cpi", "core_cpi"],
    "PCEPILFE": ["core_pce", "pce"],
    "GDPC1": ["gdp"],
}
# 沒有公開預期來源的主要發布：頁面上要明講「沒有」，不是漏了
NO_SOURCE = "這一項沒有公開的預期來源（市場共識是付費資料），本站不拿前值充數"


def _final_before(path: list, cutoff: date) -> tuple | None:
    """公布日之前的最後一次預估。公布當天的那一筆不算——它可能已經看過答案。"""
    earlier = [point for point in path if point[0] < cutoff]
    return earlier[-1] if earlier else None


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def inflation_measure(data: dict, key: str, today: date) -> dict | None:
    """一個通膨指標的預期：下一次公布的預估、上一次的預估對實際、以及成績單。"""
    months = sorted(set(data["yoy"]) & set(data["mom"]))
    slot = lambda kind, month: (data[kind].get(month) or {}).get(key) or {"path": [], "actual": None}
    released = [m for m in months if slot("yoy", m)["actual"] and slot("mom", m)["actual"]]
    # 下一期＝最後一個已公布月份之後、第一個有預估的月份。不能只找「有預估、沒有實際值」：
    # 2025-10 的 CPI 因政府關門從未公布，它永遠停在「沒有實際值」。
    after_last = [m for m in months if not released or m > released[-1]]
    pending = [m for m in after_last if slot("yoy", m)["path"] and not slot("yoy", m)["actual"]]

    def scored(month) -> dict | None:
        out = {"target": month}
        for kind in ("yoy", "mom"):
            s = slot(kind, month)
            when, actual = s["actual"]
            final = _final_before(s["path"], when)
            if final is None:
                return None
            out.update({f"{kind}_nowcast": final[1], f"{kind}_actual": actual,
                        f"{kind}_error": actual - final[1], "released": when,
                        "nowcast_date": final[0]})
        return out

    history = [row for row in (scored(m) for m in released) if row][-TRACK:]
    track = None
    if history:
        track = {"n": len(history)}
        for kind in ("yoy", "mom"):
            errors = [row[f"{kind}_error"] for row in history]
            track[f"{kind}_mae"] = _mean([abs(e) for e in errors])
            track[f"{kind}_bias"] = _mean(errors)
            track[f"{kind}_worst"] = max(errors, key=abs)

    upcoming = None
    if pending:
        month = pending[0]
        yoy, mom = slot("yoy", month)["path"], slot("mom", month)["path"]
        if yoy and mom and (today - yoy[-1][0]).days <= STALE_DAYS:
            upcoming = {"target": month, "yoy": yoy[-1][1], "mom": mom[-1][1], "as_of": yoy[-1][0]}

    if not history and not upcoming:
        return None
    return {"key": key, "name": INFLATION_NAMES[key], "kind": "model",
            "source": nowcast.SOURCE, "source_url": nowcast.PAGE,
            "next": upcoming, "last": history[-1] if history else None,
            "history": history, "track": track}


def gdp(bundle: Bundle) -> dict | None:
    """GDPNow：亞特蘭大聯準銀行對「這一季實質 GDP 年化季增率」的即時預估。

    FRED 的 GDPNOW 一季一個值：還沒公布的那一季是最新的預估，已經公布的那幾季是
    公布前的最後一次預估。實際值用 A191RL1Q225SBEA——它是現在的數字，包含初值之後
    的修正，所以成績單量的是「預估對現在的數字」，不是對當時的初值。
    """
    model, actual = bundle["GDPNOW"], bundle["A191RL1Q225SBEA"]
    if not model or model.last is None:
        return None
    actual_by = {(d.year, d.month): v for d, v in zip(actual.dates, actual.values)} if actual else {}
    history = []
    for d, v in zip(model.dates, model.values):
        real = actual_by.get((d.year, d.month))
        if real is not None:
            history.append({"target": (d.year, d.month), "nowcast": v, "actual": real,
                            "error": real - v})
    history = history[-TRACK:]
    track = None
    if history:
        errors = [row["error"] for row in history]
        track = {"n": len(history), "mae": _mean([abs(e) for e in errors]),
                 "bias": _mean(errors), "worst": max(errors, key=abs)}
    last_quarter = (model.last_date.year, model.last_date.month)
    upcoming = None
    if last_quarter not in actual_by:
        upcoming = {"target": last_quarter, "value": model.last}
    return {"key": "gdp", "name": "實質 GDP 年化季增", "kind": "model",
            "source": "亞特蘭大聯準銀行 GDPNow", "source_url": "https://www.atlantafed.org/cqer/research/gdpnow",
            "next": upcoming, "last": history[-1] if history else None,
            "history": history, "track": track}


def compute(bundle: Bundle) -> dict:
    today = clock.us_today()
    data = nowcast.fetch()
    items: dict[str, dict] = {}
    if data:
        for key in INFLATION_NAMES:
            try:
                item = inflation_measure(data, key, today)
            except Exception:
                item = None           # 一個指標的格式出問題不拖累其他的
            if item:
                items[key] = item
    growth = gdp(bundle)
    if growth:
        items["gdp"] = growth
    return {"items": items, "error": nowcast.LAST_ERROR, "as_of": today}


# ------------------------------------------------------------ 給頁面用的話 ----

def quarter_label(target: tuple[int, int]) -> str:
    return f"{target[0]} 年 Q{(target[1] - 1) // 3 + 1}"


def month_label(target: tuple[int, int]) -> str:
    return f"{target[1]} 月"


def for_release(expectations: dict | None, series_id: str) -> list[dict]:
    """某一項發布對應的預估（可能不只一個）。沒有來源的發布回空清單。"""
    items = (expectations or {}).get("items") or {}
    return [items[key] for key in RELEASES.get(series_id, []) if key in items]


def has_source(series_id: str) -> bool:
    return series_id in RELEASES


def before(item: dict) -> str:
    """公布前的一句話：模型預估多少、是哪一天的估計。沒有下一期的預估就回空字串。"""
    nxt = item.get("next")
    if not nxt:
        return ""
    if item["key"] == "gdp":
        return f'{quarter_label(nxt["target"])} 年化季增 {nxt["value"]:.1f}%'
    return f'{item["name"]} 年增 {nxt["yoy"]:.2f}%、月增 {nxt["mom"]:.2f}%'


def after(item: dict) -> str:
    """公布後的一句話：實際比預估高還是低多少，以及這個差距算不算大。"""
    last = item.get("last")
    track = item.get("track") or {}
    if not last:
        return ""
    if item["key"] == "gdp":
        # GDP 的數字只到小數一位，差距也只寫到一位——「1.5% 對 2.2%，高 0.66」像是兩套數字
        error, mae, digits = last["error"], track.get("mae"), 1
        head = (f'{quarter_label(last["target"])} 預估 {last["nowcast"]:.1f}%、'
                f'現在的數字 {last["actual"]:.1f}%')
    else:
        error, mae, digits = last["mom_error"], track.get("mom_mae"), 2
        head = (f'{month_label(last["target"])} {item["name"]} 月增：預估 {last["mom_nowcast"]:.2f}%、'
                f'實際 {last["mom_actual"]:.2f}%')
    if abs(error) < 0.5 * 10 ** -digits:
        gap = "，跟預估一樣"
    else:
        gap = f'，{"高" if error > 0 else "低"} {abs(error):.{digits}f} 個百分點'
    scale = ""
    if mae:
        ratio = abs(error) / mae
        scale = (f'（這個模型近 {track["n"]} 期平均差 {mae:.{digits}f}；'
                 + ("這次在平常的誤差內" if ratio <= 1.0 else
                    f"這次是平常的 {ratio:.1f} 倍") + "）")
    return head + gap + scale
