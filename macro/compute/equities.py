"""三個股市報價區塊：美股、台股、其他新興市場。

刻意不做技術分析。這一頁在總經儀表板裡的角色是「總經判斷有沒有反映在
股市定價上」，所以每一組後面都接一句從當下數字算出來的解讀，而不是
單純列一張報價表。
"""
from __future__ import annotations

import json
import os
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
# 大盤 ETF。原始指數（^GSPC 等）在多數報價 API 的免費層不開放，這些 ETF
# 追蹤同樣的標的且開放，所以它們是「能即時更新」的那一組。
US_PROXIES = [
    ("SPY", "SPDR 標普 500"), ("QQQ", "Invesco 那斯達克 100"),
    ("DIA", "SPDR 道瓊"), ("IWM", "iShares 羅素 2000"),
    ("VXX", "波動率期貨 ETN"),
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
]
TW_ETFS = [
    ("0050", "元大台灣50"), ("0056", "元大高股息"), ("00878", "國泰永續高股息"),
    ("006208", "富邦台50"), ("009816", "凱基台灣TOP50"),
]

# ---- 台股族群熱力圖 -------------------------------------------------------
# 每個族群挑市值與成交量具代表性的個股，上市優先、必要時含上櫃
# （MIS 對兩個 board 都能報價）。熱力圖看的是「族群內一致還是分歧」，
# 不是選股清單，所以每組 4–6 檔就夠說話。
TW_GROUPS = [
    ("金融", [("2881", "富邦金"), ("2882", "國泰金"), ("2884", "玉山金"),
              ("2885", "元大金"), ("2891", "中信金"), ("2886", "兆豐金")]),
    ("電子代工與 AI 伺服器", [("2317", "鴻海"), ("2382", "廣達"), ("3231", "緯創"),
                              ("2356", "英業達"), ("2376", "技嘉"), ("2357", "華碩")]),
    ("航運", [("2603", "長榮"), ("2609", "陽明"), ("2615", "萬海"),
              ("2610", "華航"), ("2618", "長榮航")]),
    ("重電與電力設備", [("1519", "華城"), ("1513", "中興電"), ("1503", "士電"),
                        ("2308", "台達電")]),
    ("塑化", [("1301", "台塑"), ("1303", "南亞"), ("1326", "台化"),
              ("6505", "台塑化")]),
    ("鋼鐵", [("2002", "中鋼"), ("2027", "大成鋼"), ("9958", "世紀鋼")]),
    ("光電與鏡頭", [("3008", "大立光"), ("3406", "玉晶光"), ("2409", "友達"),
                    ("3481", "群創")]),
    ("通信網路", [("2412", "中華電"), ("3045", "台灣大"), ("4904", "遠傳"),
                  ("2345", "智邦")]),
]

# ---- 半導體產業鏈熱力圖 ---------------------------------------------------
# 依製程順序排：設計 → 製造 → 記憶體 → 封測 → 設備 → 材料 → 載板 → 通路。
# 同一天各環節的分歧（例如設計漲、封測跌）比大盤漲跌本身更有資訊量。
TW_SEMI_CHAIN = [
    ("IC 設計", [("2454", "聯發科"), ("3034", "聯詠"), ("2379", "瑞昱"),
                 ("3443", "創意"), ("3529", "力旺"), ("5269", "祥碩")]),
    ("晶圓代工", [("2330", "台積電"), ("2303", "聯電"), ("5347", "世界先進"),
                  ("6770", "力積電")]),
    ("記憶體", [("2408", "南亞科"), ("2344", "華邦電"), ("3006", "晶豪科"),
                ("8299", "群聯"), ("2451", "創見")]),
    ("封測", [("3711", "日月光投控"), ("6239", "力成"), ("2449", "京元電子"),
              ("6147", "頎邦"), ("3374", "精材")]),
    ("設備", [("3680", "家登"), ("3131", "弘塑"), ("3583", "辛耘"),
              ("2360", "致茂"), ("6196", "帆宣")]),
    ("材料與矽晶圓", [("6488", "環球晶"), ("3532", "台勝科"), ("1560", "中砂"),
                      ("5434", "崇越")]),
    ("IC 載板與 PCB", [("3037", "欣興"), ("8046", "南電"), ("2368", "金像電"),
                       ("2383", "台光電"), ("3044", "健鼎"), ("4958", "臻鼎-KY")]),
    ("IC 通路", [("3702", "大聯大"), ("3036", "文曄")]),
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


def _fetch_taiwan(pairs: list[tuple[str, str]], region: str,
                  fetcher=None) -> list[dict]:
    names = dict(pairs)
    fetch = fetcher or quotes.taiwan_quotes
    rows = fetch([symbol for symbol, _ in pairs])
    out = [quotes.normalise(r, name=names.get(str(r.get("symbol", "")), ""), region=region)
           for r in rows]
    order = {symbol: i for i, (symbol, _) in enumerate(pairs)}
    out.sort(key=lambda r: order.get(str(r["symbol"]), 999))
    return out


def _group_rows(defs: list[tuple[str, list]], rows: list[dict]) -> list[dict]:
    """把攤平抓回來的報價分回各族群，保持定義裡的順序。"""
    by_symbol = {str(r["symbol"]): r for r in rows}
    return [{"name": name,
             "rows": [by_symbol[s] for s, _ in pairs if s in by_symbol]}
            for name, pairs in defs]


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


def _snapshot_path() -> str:
    from .. import paths
    return os.path.join(paths.DATA_DIR, "quotes_snapshot.json")


def _load_snapshot() -> dict:
    try:
        with open(_snapshot_path(), encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def _save_snapshot(groups: list[list[dict]]) -> None:
    """記住每檔最後一次成功的報價。

    來源會暫時掛掉（Finnhub 額度、證交所維護、CI 上沒有 Fincept），
    那時留白會讓整個區塊消失。留下上次的值並標明它的原始時間，
    比假裝沒有這個市場要誠實，也比拿舊值假裝是現況要誠實。
    """
    snapshot = _load_snapshot()
    for rows in groups:
        for row in rows:
            if row.get("price") is None:
                continue
            snapshot[str(row["symbol"])] = {
                "name": row.get("name"), "price": row.get("price"),
                "change": row.get("change"), "change_percent": row.get("change_percent"),
                "open": row.get("open"), "high": row.get("high"), "low": row.get("low"),
                "previous_close": row.get("previous_close"),
                "limit_up": row.get("limit_up"), "limit_down": row.get("limit_down"),
                "market_status": row.get("market_status"),
                "quoted_at": row["quoted_at"].isoformat() if row.get("quoted_at") else None,
                "saved_at": datetime.now().isoformat(timespec="seconds"),
                "source": row.get("source"),
            }
    try:
        with open(_snapshot_path(), "w", encoding="utf-8") as fh:
            json.dump(snapshot, fh, ensure_ascii=False, indent=1, sort_keys=True)
    except Exception:
        pass


def _fill_gaps(rows: list[dict], pairs: list[tuple[str, str]],
               region: str, snapshot: dict) -> list[dict]:
    """這次沒取到的代號，用存檔補上並標為 stale。"""
    # 有列但沒價格，跟完全沒抓到一樣是洞
    rows = [r for r in rows if r.get("price") is not None]
    have = {str(r["symbol"]) for r in rows}
    for symbol, name in pairs:
        if symbol in have:
            continue
        saved = snapshot.get(symbol)
        if not saved or saved.get("price") is None:
            continue
        when = None
        if saved.get("quoted_at"):
            try:
                when = datetime.fromisoformat(saved["quoted_at"])
            except Exception:
                when = None
        rows.append({
            "symbol": symbol, "name": name or saved.get("name") or symbol,
            "region": region,
            "price": saved.get("price"), "change": saved.get("change"),
            "change_percent": saved.get("change_percent"),
            "open": saved.get("open"), "high": saved.get("high"),
            "low": saved.get("low"), "previous_close": saved.get("previous_close"),
            "limit_up": saved.get("limit_up"), "limit_down": saved.get("limit_down"),
            "volume": None, "trade_time": None,
            "quoted_at": when,
            "market_status": saved.get("market_status") or "",
            "is_intraday": False,
            "source": saved.get("source") or "存檔",
            "stale": True,
            "saved_at": saved.get("saved_at"),
        })
    order = {symbol: i for i, (symbol, _) in enumerate(pairs)}
    rows.sort(key=lambda r: order.get(str(r["symbol"]), 999))
    return rows


def compute(bundle=None) -> dict:
    snapshot = _load_snapshot()

    us_indices = _fetch(US_INDICES, "美股")
    us_stocks = _fetch(US_STOCKS, "美股")
    us_proxies = _fetch(US_PROXIES, "美股")
    us_sectors = _fetch(US_SECTORS, "美股")

    # 加權指數與個股都走證交所官方（指數是 MIS 的 t00 channel），
    # 這樣建置快照與部署後的即時更新是同一個來源、同一套數字。
    tw_index = _fetch_taiwan(TW_INDICES, "台股", fetcher=quotes.taiwan_index_quotes)
    tw_stocks = _fetch_taiwan(TW_TICKERS, "台股")
    tw_etfs = _fetch_taiwan(TW_ETFS, "台股")

    # 熱力圖的代號跨族群會重複（台積電同時在權值股與晶圓代工），
    # 抓一次攤平的清單，再分回各族群。
    heat_pairs = list({symbol: (symbol, name)
                       for _, pairs in TW_GROUPS + TW_SEMI_CHAIN
                       for symbol, name in pairs}.values())
    tw_heat = _fetch_taiwan(heat_pairs, "台股")

    em_indices = _fetch(EM_INDICES, "新興市場")
    em_etfs = _fetch(EM_ETFS, "新興市場")

    # 先把這次成功的存起來，再用存檔補這次沒取到的——順序不能反，
    # 否則會拿這次剛補進去的舊值去覆蓋存檔。
    _save_snapshot([us_indices, us_proxies, us_stocks, us_sectors,
                    tw_index, tw_stocks, tw_etfs, tw_heat,
                    em_indices, em_etfs])

    us_indices = _fill_gaps(us_indices, US_INDICES, "美股", snapshot)
    us_proxies = _fill_gaps(us_proxies, US_PROXIES, "美股", snapshot)
    us_stocks = _fill_gaps(us_stocks, US_STOCKS, "美股", snapshot)
    us_sectors = _fill_gaps(us_sectors, US_SECTORS, "美股", snapshot)
    tw_index = _fill_gaps(tw_index, TW_INDICES, "台股", snapshot)
    tw_stocks = _fill_gaps(tw_stocks, TW_TICKERS, "台股", snapshot)
    tw_etfs = _fill_gaps(tw_etfs, TW_ETFS, "台股", snapshot)
    tw_heat = _fill_gaps(tw_heat, heat_pairs, "台股", snapshot)
    em_indices = _fill_gaps(em_indices, EM_INDICES, "新興市場", snapshot)
    em_etfs = _fill_gaps(em_etfs, EM_ETFS, "新興市場", snapshot)

    everything = (us_indices + us_proxies + us_stocks + us_sectors
                  + tw_index + tw_stocks + tw_etfs + em_indices + em_etfs)

    return {
        "available": bool(everything),
        "stale_count": sum(1 for r in everything if r.get("stale")),
        "source_note": ("Fincept Terminal" if quotes.available()
                        else "Finnhub" if quotes.finnhub_key() else "存檔"),
        "fetched_at": datetime.now(),
        "us": {
            "indices": us_indices, "proxies": us_proxies,
            "stocks": us_stocks, "sectors": us_sectors,
            "breadth": _breadth(us_stocks),
            "sector_breadth": _breadth(us_sectors),
            "status": _market_note(us_indices),
        },
        "tw": {
            "index": tw_index, "stocks": tw_stocks, "etfs": tw_etfs,
            "groups": _group_rows(TW_GROUPS, tw_heat),
            "semi": _group_rows(TW_SEMI_CHAIN, tw_heat),
            "breadth": _breadth(tw_stocks),
            "status": _market_note(tw_stocks or tw_index),
        },
        "em": {
            "indices": em_indices, "etfs": em_etfs,
            "breadth": _breadth(em_indices),
            "status": _market_note(em_indices),
        },
    }
