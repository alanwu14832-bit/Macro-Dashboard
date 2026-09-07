"""30 天聯邦基金期貨（CME ZQ）報價。

FedWatch 的原料就是這批合約：價格 = 100 − 該合約月的平均有效聯邦資金利率。
CME 網站禁止程式抓取（真的會封 IP），所以報價走公開行情：本機有 Fincept
Terminal 就用它的 yfinance，沒有就直接打 Yahoo 的 chart 端點（純 urllib）。
兩條路都不通時退回上次成功的快照並標 stale——跟股市報價同一套原則：
舊值要說是舊值，不留白也不假裝是現況。
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime, timezone

from .. import http, paths
from . import quotes

MONTH_CODES = "FGHJKMNQUVXZ"          # CME 月份代碼：1 月 F … 12 月 Z
YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
# Yahoo 對非瀏覽器的 UA 直接回 429，這裡得裝成瀏覽器
BROWSER_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"),
    "Accept": "application/json",
}
SNAPSHOT = os.path.join(paths.DATA_DIR, "fedfunds_snapshot.json")


def symbol_for(year: int, month: int) -> str:
    return f"ZQ{MONTH_CODES[month - 1]}{year % 100:02d}.CBT"


def contract_months(start: date, months: int = 12) -> list[tuple[str, str]]:
    """(YYYY-MM, 代號)，從 start 當月起連續 months 個月。"""
    out = []
    year, month = start.year, start.month
    for _ in range(months):
        out.append((f"{year}-{month:02d}", symbol_for(year, month)))
        month += 1
        if month > 12:
            month, year = 1, year + 1
    return out


def _when(stamp) -> str | None:
    if isinstance(stamp, (int, float)):
        return (datetime.fromtimestamp(stamp, tz=timezone.utc).astimezone()
                .isoformat(timespec="minutes"))
    if isinstance(stamp, str) and stamp:
        return stamp
    return None


def _fincept(symbols: list[str]) -> dict[str, dict]:
    # 沒有 Fincept 時 index_quotes 會退到 Finnhub，免費層沒有期貨，
    # 只會白白燒額度，所以先擋。
    if not quotes.available():
        return {}
    rows = quotes.index_quotes(symbols)
    return {r["symbol"]: {"price": float(r["price"]), "quoted_at": _when(r.get("timestamp")),
                          "source": "Fincept / yfinance"}
            for r in rows if r.get("price") is not None and r.get("symbol")}


def _yahoo(symbol: str, ttl: float) -> dict | None:
    url = http.build_url(YAHOO_CHART.format(symbol=symbol),
                         {"range": "5d", "interval": "1d"})
    try:
        payload = http.get_json(url, ttl=ttl, namespace="yahoo", retries=1,
                                timeout=20, headers=BROWSER_HEADERS)
        meta = payload["chart"]["result"][0]["meta"]
    except Exception:
        return None
    price = meta.get("regularMarketPrice")
    if price is None:
        return None
    return {"price": float(price), "quoted_at": _when(meta.get("regularMarketTime")),
            "source": "Yahoo Finance"}


def _load_snapshot() -> dict:
    try:
        with open(SNAPSHOT, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def _save_snapshot(found: dict[str, dict]) -> None:
    """記住每個合約最後一次成功的報價。沒有新東西也照寫——雲端建置的
    commit 步驟會 git add 這個檔，檔案不存在會讓整個步驟失敗。"""
    snapshot = _load_snapshot()
    now = datetime.now().isoformat(timespec="seconds")
    for symbol, row in found.items():
        snapshot[symbol] = {"price": row["price"], "quoted_at": row.get("quoted_at"),
                            "source": row.get("source"), "saved_at": now}
    try:
        with open(SNAPSHOT, "w", encoding="utf-8") as fh:
            json.dump(snapshot, fh, ensure_ascii=False, indent=1, sort_keys=True)
    except Exception:
        pass


def fetch(symbols: list[str], *, ttl: float = 3000) -> dict[str, dict]:
    """代號 → {price, quoted_at, source, stale}。拿不到的用快照補並標 stale。"""
    found = _fincept(symbols)
    for symbol in symbols:
        if symbol in found:
            continue
        row = _yahoo(symbol, ttl)
        if row:
            found[symbol] = row
    for row in found.values():
        row["stale"] = False
    _save_snapshot(found)

    snapshot = _load_snapshot()
    for symbol in symbols:
        if symbol in found:
            continue
        saved = snapshot.get(symbol)
        if saved and saved.get("price") is not None:
            found[symbol] = {"price": saved["price"], "quoted_at": saved.get("quoted_at"),
                             "source": saved.get("source") or "存檔", "stale": True}
    return found
