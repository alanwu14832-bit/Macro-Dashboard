"""證交所公開統計：三大法人買賣金額、融資融券餘額。

走 www.twse.com.tw 的 rwd JSON 端點，免金鑰、每個交易日收盤後更新。
只在建置時抓（日頻資料沒有盤中即時的意義），走 http 層的快取與節流。

融資「維持率」刻意不在這裡：大盤整戶擔保維持率需要擔保品市值，
證交所沒有公開，市面上看到的都是券商或資料商自己算的。這裡放的是
公開資料裡最接近的原料——融資餘額與其增減。
"""
from __future__ import annotations

from datetime import date

from ..http import build_url, get_json
from ..series import Series

BFI82U = "https://www.twse.com.tw/rwd/zh/fund/BFI82U"
MI_MARGN = "https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN"
FMTQIK = "https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK"


def _num(text) -> float | None:
    try:
        return float(str(text).replace(",", ""))
    except (ValueError, TypeError):
        return None


def _date(raw: str) -> str:
    """20260812 → 2026-08-12"""
    raw = str(raw or "")
    return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}" if len(raw) == 8 else raw


def institutional(*, ttl: float = 6 * 3600) -> dict:
    """三大法人買賣金額（整體市場、單日）。單位換成億元。"""
    try:
        payload = get_json(build_url(BFI82U, {"response": "json"}),
                           ttl=ttl, namespace="twse_open", timeout=30, retries=2)
    except Exception:
        return {}
    if payload.get("stat") != "OK":
        return {}

    rows = {row[0]: _num(row[3]) for row in payload.get("data", []) if len(row) >= 4}
    yi = 100_000_000.0
    dealer_self = rows.get("自營商(自行買賣)") or 0
    dealer_hedge = rows.get("自營商(避險)") or 0
    foreign = (rows.get("外資及陸資(不含外資自營商)") or 0) + (rows.get("外資自營商") or 0)
    return {
        "date": _date(payload.get("date")),
        "foreign": foreign / yi,
        "trust": (rows.get("投信") or 0) / yi,
        "dealer": (dealer_self + dealer_hedge) / yi,
        "total": (rows.get("合計") or 0) / yi,
    }


def margin(*, ttl: float = 6 * 3600) -> dict:
    """融資融券彙總。融資金額換成億元，融券以張數呈現。"""
    try:
        payload = get_json(build_url(MI_MARGN, {"selectType": "MS", "response": "json"}),
                           ttl=ttl, namespace="twse_open", timeout=30, retries=2)
    except Exception:
        return {}
    if payload.get("stat") != "OK":
        return {}

    rows: dict[str, tuple[float | None, float | None]] = {}
    for tbl in payload.get("tables", []):
        for row in tbl.get("data", []):
            if len(row) >= 6:
                rows[row[0]] = (_num(row[4]), _num(row[5]))     # (前日, 今日)

    fin_prev, fin_now = rows.get("融資金額(仟元)", (None, None))
    short_prev, short_now = rows.get("融券(交易單位)", (None, None))
    if fin_now is None:
        return {}
    wan_yi = 100_000.0                       # 仟元 → 億元
    return {
        "date": _date(payload.get("date")),
        "financing_yi": fin_now / wan_yi,
        "financing_chg_yi": (fin_now - fin_prev) / wan_yi if fin_prev else None,
        "short_units": short_now,
        "short_chg_units": (short_now - short_prev) if (short_now and short_prev) else None,
    }


def _roc_date(raw: str) -> str | None:
    """民國年日期：115/08/12 → 2026-08-12。"""
    try:
        y, m, d = str(raw).split("/")
        return f"{int(y) + 1911}-{m}-{d}"
    except (ValueError, AttributeError):
        return None


def daily_market(*, months: int = 6, ttl: float = 6 * 3600) -> dict:
    """大盤指數收盤與成交金額的日線，FMTQIK 一個月一批往回抓。

    已經走完的月份內容不會再變，快取放 30 天；只有當月需要照一般
    TTL 更新——一天實際上只多一次上游呼叫。
    """
    today = date.today()
    wanted = []
    y, m = today.year, today.month
    for _ in range(months):
        wanted.append((y, m))
        m -= 1
        if m == 0:
            y, m = y - 1, 12

    idx_pairs, turn_pairs = [], []
    for yy, mm in reversed(wanted):
        month_ttl = ttl if (yy, mm) == (today.year, today.month) else 30 * 24 * 3600
        try:
            payload = get_json(
                build_url(FMTQIK, {"response": "json", "date": f"{yy}{mm:02d}01"}),
                ttl=month_ttl, namespace="twse_open", timeout=30, retries=2)
        except Exception:
            continue
        if payload.get("stat") != "OK":
            continue
        for row in payload.get("data", []):
            if len(row) < 5:
                continue
            iso = _roc_date(row[0])
            close, turnover = _num(row[4]), _num(row[2])
            if iso and close:
                idx_pairs.append((iso, close))
            if iso and turnover:
                turn_pairs.append((iso, turnover / 1e8))     # 元 → 億元

    if not idx_pairs:
        return {}
    return {
        "index": Series.from_pairs("TWII.D", idx_pairs, label="加權指數",
                                   unit="點", frequency="d"),
        "turnover": Series.from_pairs("TW.TURNOVER", turn_pairs, label="成交金額",
                                      unit="億元", frequency="d"),
    }
