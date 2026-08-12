"""三個股市報價區塊：美股、台股、其他新興市場。

刻意不做技術分析。這一頁在總經儀表板裡的角色是「總經判斷有沒有反映在
股市定價上」，所以每一組後面都接一句從當下數字算出來的解讀，而不是
單純列一張報價表。
"""
from __future__ import annotations

from datetime import datetime

from ..sources import quotes

# ---- 美股：指數 + 權值股 -------------------------------------------------
US_INDICES = [
    ("^GSPC", "標普 500"), ("^IXIC", "那斯達克綜合"), ("^DJI", "道瓊工業"),
    ("^RUT", "羅素 2000"), ("^NDX", "那斯達克 100"), ("^VIX", "VIX 波動率"),
]
US_STOCKS = [
    ("NVDA", "輝達"), ("AAPL", "蘋果"), ("MSFT", "微軟"), ("GOOGL", "Alphabet"),
    ("AMZN", "亞馬遜"), ("META", "Meta"), ("TSLA", "特斯拉"), ("AVGO", "博通"),
    ("JPM", "摩根大通"), ("XOM", "埃克森美孚"),
]
US_SECTORS = [
    ("XLK", "科技"), ("XLF", "金融"), ("XLE", "能源"), ("XLV", "醫療"),
    ("XLI", "工業"), ("XLY", "非必需消費"), ("XLP", "必需消費"), ("XLU", "公用事業"),
]

# ---- 台股：指數 + 權值股（走證交所）--------------------------------------
TW_INDICES = [("^TWII", "台股加權指數")]
TW_TICKERS = [
    ("2330", "台積電"), ("2317", "鴻海"), ("2454", "聯發科"), ("2308", "台達電"),
    ("2382", "廣達"), ("2412", "中華電"), ("2881", "富邦金"), ("2882", "國泰金"),
    ("1301", "台塑"), ("2603", "長榮"),
]
TW_ETFS = [
    ("0050", "元大台灣50"), ("0056", "元大高股息"), ("00878", "國泰永續高股息"),
    ("006208", "富邦台50"),
]

# ---- 其他新興市場 --------------------------------------------------------
# 中國 A 股指數（000001.SS 等）這條路徑取不到，改以 ASHR／FXI 兩檔 ETF 代表。
EM_INDICES = [
    ("^KS11", "南韓 KOSPI"), ("^HSI", "香港恆生"),
    ("^BSESN", "印度 SENSEX"), ("^JKSE", "印尼綜合"), ("^BVSP", "巴西 BOVESPA"),
    ("^MXX", "墨西哥 IPC"), ("^N225", "日經 225"),
]
EM_ETFS = [
    ("EEM", "新興市場 ETF"), ("EWY", "南韓 ETF"), ("EWT", "台灣 ETF"),
    ("INDA", "印度 ETF"), ("FXI", "中國大型股 ETF"), ("ASHR", "中國 A 股 ETF"),
    ("EWZ", "巴西 ETF"),
]


def _fetch(pairs: list[tuple[str, str]], region: str) -> list[dict]:
    names = dict(pairs)
    rows = quotes.index_quotes([symbol for symbol, _ in pairs])
    out = [quotes.normalise(r, name=names.get(r.get("symbol", ""), ""), region=region)
           for r in rows]
    order = {symbol: i for i, (symbol, _) in enumerate(pairs)}
    out.sort(key=lambda r: order.get(r["symbol"], 999))
    return out


def _fetch_taiwan(pairs: list[tuple[str, str]], region: str) -> list[dict]:
    names = dict(pairs)
    rows = quotes.taiwan_quotes([symbol for symbol, _ in pairs])
    out = [quotes.normalise(r, name=names.get(str(r.get("symbol", "")), ""), region=region)
           for r in rows]
    order = {symbol: i for i, (symbol, _) in enumerate(pairs)}
    out.sort(key=lambda r: order.get(str(r["symbol"]), 999))
    return out


def _breadth(rows: list[dict]) -> dict:
    """漲跌家數與平均漲跌幅 — 一組報價唯一值得算的統計。"""
    moves = [r["change_percent"] for r in rows if r.get("change_percent") is not None]
    if not moves:
        return {}
    up = sum(1 for m in moves if m > 0)
    down = sum(1 for m in moves if m < 0)
    return {
        "up": up, "down": down, "flat": len(moves) - up - down,
        "average": sum(moves) / len(moves),
        "best": max(rows, key=lambda r: r.get("change_percent") or -999),
        "worst": min(rows, key=lambda r: r.get("change_percent") or 999),
        "n": len(moves),
    }


def _market_note(rows: list[dict]) -> str:
    """從報價本身描述市場狀態，不假裝是即時串流。"""
    if not rows:
        return ""
    intraday = [r for r in rows if r.get("is_intraday")]
    statuses = {r["market_status"] for r in rows if r.get("market_status")}
    if intraday:
        return "盤中報價"
    if statuses:
        return sorted(statuses)[0]
    return "最近收盤價"


def compute(bundle=None) -> dict:
    if not quotes.available():
        return {"available": False, "groups": [], "fetched_at": datetime.now()}

    us_indices = _fetch(US_INDICES, "美股")
    us_stocks = _fetch(US_STOCKS, "美股")
    us_sectors = _fetch(US_SECTORS, "美股")

    tw_index = _fetch(TW_INDICES, "台股")          # 加權指數走 yfinance
    tw_stocks = _fetch_taiwan(TW_TICKERS, "台股")   # 個股走證交所官方
    tw_etfs = _fetch_taiwan(TW_ETFS, "台股")

    em_indices = _fetch(EM_INDICES, "新興市場")
    em_etfs = _fetch(EM_ETFS, "新興市場")

    return {
        "available": True,
        "fetched_at": datetime.now(),
        "us": {
            "indices": us_indices, "stocks": us_stocks, "sectors": us_sectors,
            "breadth": _breadth(us_stocks),
            "sector_breadth": _breadth(us_sectors),
            "status": _market_note(us_indices),
        },
        "tw": {
            "index": tw_index, "stocks": tw_stocks, "etfs": tw_etfs,
            "breadth": _breadth(tw_stocks),
            "status": _market_note(tw_stocks or tw_index),
        },
        "em": {
            "indices": em_indices, "etfs": em_etfs,
            "breadth": _breadth(em_indices),
            "status": _market_note(em_indices),
        },
    }
