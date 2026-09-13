"""市場反應：一個數字公布之後，期貨動了多少。

這份程式原本住在 tools/send_push.py 裡，只有推播用得到。問題是頁面也要顯示
同一件事——兩份各自抓、各自算，遲早會在同一個時刻給出兩個不同的數字，而
使用者是先看到推播、再點進頁面的，那個矛盾百分之百會被看見。

所以搬到這裡，推播與頁面共用同一個函式。兩邊的時間戳仍然會差：推播是發布
後不久量的，頁面是下一次建置時重算的，最多差一小時。那不是 bug，是兩次
不同時間的量測——所以兩邊都標明自己量於何時，而不是假裝是同一個瞬間。

刻意不做的事：不歸因（「因為 CPI 低於預期所以漲」是敘事，不是量測）、
不做第二次量測（公布後 30 分與收盤各一個數字會讓人以為有因果）、
基準是前一交易日收盤，不是公布前一刻——後者需要分鐘級資料，本站沒有。
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request

from .. import clock

# 觀察標的：美股與債市對總經數據的第一反應。三檔就夠——再多只是把同一件事
# 說三遍，而且每多一檔就多一個可能抓不到的來源。
FUTURES = [
    ("ES=F", "S&P 期貨", "美股大盤"),
    ("NQ=F", "那斯達克期貨", "科技股／長天期資產"),
    ("ZN=F", "10 年債期貨", "殖利率反向"),
]

CHART = "https://query1.finance.yahoo.com/v8/finance/chart/"


def _quote(symbol: str, *, timeout: int = 12) -> dict | None:
    """單檔期貨的現價與前收。抓不到就回 None——這一檔略過，不影響其他檔。"""
    request = urllib.request.Request(
        CHART + urllib.parse.quote(symbol) + "?range=1d&interval=15m",
        headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            meta = json.load(response)["chart"]["result"][0]["meta"]
        price = meta["regularMarketPrice"]
        prior = meta["chartPreviousClose"]
    except Exception:
        return None
    if not prior:
        return None
    return {"price": price, "prior": prior,
            "change_pct": (price - prior) / prior * 100}


def snapshot() -> dict:
    """三檔期貨的當下讀數，附量測時間。

    量測時間要跟著數字一起走：這一頁下次建置才會重算，中間使用者看到的
    是一個小時前的市場。標出來，讀者自己判斷還算不算數。
    """
    rows = []
    for symbol, label, meaning in FUTURES:
        quote = _quote(symbol)
        if not quote:
            continue
        rows.append({"symbol": symbol, "label": label, "meaning": meaning,
                     "price": quote["price"], "change_pct": quote["change_pct"]})
    return {
        "measured_at": clock.now().isoformat(timespec="minutes"),
        "rows": rows,
        # 基準寫進資料裡，免得呈現層各自寫一套說法
        "baseline": "前一交易日收盤",
    }


def summary_line(snap: dict) -> str:
    """一行文字版——推播的內文用這個。"""
    return "、".join(f'{r["label"]} {r["change_pct"]:+.2f}%'
                     for r in (snap or {}).get("rows") or [])
