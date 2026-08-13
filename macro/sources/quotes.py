"""即時報價：指數走 Fincept Terminal，台股走證交所。

分工照使用者指定：
  指數（美股、台股、新興市場）→ Fincept Terminal 的 yfinance_data.py
  台股個股與台股指數        → 證交所官方 mis.twse.com.tw（fincept 的 twse_source）

兩者都在**建置時**取得，因為 twse.com.tw 與 Yahoo 都沒有送
Access-Control-Allow-Origin，靜態網頁沒辦法自己去抓。所以頁面上呈現的是
「建置當下的快照」，每一筆都會標明報價時間與當時的市場狀態，不會假裝是
串流即時價。

Fincept 不在時整個模組會安靜降級（回傳空清單），不會讓建置失敗——
這個專案的其他部分不該因為一個外部相依而壞掉。
"""
from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, time as dtime, timezone
from zoneinfo import ZoneInfo

from ..http import build_url, get_json

FINCEPT_ROOT = os.path.expanduser(
    os.environ.get("FINCEPT_ROOT", "~/Desktop/fincept-mcp"))
FINCEPT_PYTHON = os.path.join(FINCEPT_ROOT, ".venv", "bin", "python")
FINCEPT_SCRIPTS = os.path.join(FINCEPT_ROOT, "FinceptTerminal", "fincept-qt", "scripts")

def available() -> bool:
    return os.path.exists(FINCEPT_PYTHON) and os.path.isdir(FINCEPT_SCRIPTS)


# ------------------------------------------------------------------ 台股 ---
# 直接打證交所，不透過 fincept：它的 twse_source 需要 requests，而本專案
# 刻意維持零第三方套件。欄位處理與市場狀態判斷沿用同一套邏輯。

MIS_URL = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp"
TAIPEI = ZoneInfo("Asia/Taipei")
MARKET_OPEN = dtime(9, 0)
MARKET_CLOSE = dtime(13, 30)


def _tw_num(value) -> float | None:
    """TWSE 的數字帶千分位逗號，停牌或無成交時是 '-' 或空字串。"""
    if value is None:
        return None
    text = str(value).replace(",", "").replace("+", "").strip()
    if text in ("", "-", "--", "X"):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _market_status(quoted: datetime | None) -> str:
    """這筆報價是盤中還是收盤價。

    用「報價日期 vs 今天」判斷而不是只看時鐘，才能正確處理週末與國定假日
    ——休市時 MIS 回的是最後一個交易日的資料，看時鐘會誤判成盤前。
    """
    now = datetime.now(TAIPEI)
    if quoted is None:
        return "未知"
    if quoted.date() < now.date():
        return f"已收盤（{quoted.date().isoformat()} 最後交易日資料）"
    if quoted.timetz().replace(tzinfo=None) >= MARKET_CLOSE:
        return "已收盤（本日收盤價）"
    if now.time() < MARKET_OPEN:
        return "盤前"
    return "盤中"


def _shape_taiwan(row: dict) -> dict:
    price = _tw_num(row.get("z"))                 # 最近成交價
    prev = _tw_num(row.get("y"))                  # 昨收
    if price is None:
        # 無成交時 z 是 '-'，退而用最佳買價／賣價
        price = (_tw_num((row.get("b") or "").split("_")[0])
                 or _tw_num((row.get("a") or "").split("_")[0]))
    if price is None:
        # 盤前連掛單都還沒有，這時該顯示昨收而不是空白——市場狀態欄位
        # 已經標明「盤前」，不會有人把它讀成成交價。
        price = prev

    change = round(price - prev, 4) if (price is not None and prev) else None
    pct = round(change / prev * 100, 4) if (change is not None and prev) else None

    quoted = None
    if row.get("tlong"):
        try:
            quoted = datetime.fromtimestamp(int(row["tlong"]) / 1000, tz=TAIPEI)
        except (ValueError, OSError, TypeError):
            quoted = None

    status = _market_status(quoted)
    return {
        "symbol": row.get("c"), "name": row.get("n"),
        "price": price, "change": change, "change_percent": pct,
        "volume": _tw_num(row.get("v")),
        "high": _tw_num(row.get("h")), "low": _tw_num(row.get("l")),
        "open": _tw_num(row.get("o")), "previous_close": prev,
        "limit_up": _tw_num(row.get("u")), "limit_down": _tw_num(row.get("w")),
        "trade_time": row.get("t"),
        "timestamp": quoted.isoformat() if quoted else None,
        "market_status": status,
        "price_is_intraday": status == "盤中",
        "market": {"tse": "上市", "otc": "上櫃"}.get(row.get("ex"), row.get("ex")),
        "source": "mis.twse.com.tw",
    }


def _mis_fetch(channels: str, ttl: float) -> dict[str, dict]:
    """打 MIS 並依代號建索引。

    證交所限流時回的是 HTTP 200 加上非 0000 的 rtcode。HTTP 層只看狀態碼，
    會把這種「成功的錯誤」寫進快取，接下來整個 TTL 都拿不到報價。
    所以這裡驗過內容才算數，內容不對就繞過快取重抓一次——成功的回應會
    順帶把壞的快取覆蓋掉。
    """
    url = build_url(MIS_URL, {"ex_ch": channels, "json": "1", "delay": "0"})
    for attempt, cache_ttl in enumerate((ttl, 0)):
        try:
            payload = get_json(url, ttl=cache_ttl, namespace="twse",
                               timeout=30, retries=2)
        except Exception:
            return {}
        if payload.get("rtcode") == "0000":
            break
        if attempt == 1:
            return {}
    else:
        return {}
    return {row.get("c"): row
            for row in payload.get("msgArray") or [] if row.get("c")}


def taiwan_quotes(tickers: list[str], *, ttl: float = 900) -> list[dict]:
    """證交所官方報價。上市與上櫃兩個 channel 都送，MIS 只回存在的那個。"""
    codes = [str(t).strip().upper().split(".")[0] for t in tickers if str(t).strip()]
    if not codes:
        return []
    channels = "|".join(f"{market}_{code}.tw"
                        for code in codes for market in ("tse", "otc"))
    found = _mis_fetch(channels, ttl)
    return [_shape_taiwan(found[code]) for code in codes if code in found]


# MIS 也提供大盤指數，channel 是保留代號而不是股票代號。
# t00 = 發行量加權股價指數（也就是 ^TWII），o00 = 櫃買指數。
TW_INDEX_CHANNELS = {"^TWII": ("tse_t00.tw", "t00")}


def taiwan_index_quotes(symbols: list[str], *, ttl: float = 900) -> list[dict]:
    """加權指數走證交所官方，跟個股同一個 MIS 端點。

    對外的代號維持 ^TWII——快照存檔、頁面上的 data-quote 與即時更新腳本
    都用它當 key，來源換掉不該讓 key 跟著換。
    """
    wanted = [(s, TW_INDEX_CHANNELS[s]) for s in symbols if s in TW_INDEX_CHANNELS]
    if not wanted:
        return []
    channels = "|".join(channel for _, (channel, _) in wanted)
    found = _mis_fetch(channels, ttl)
    out = []
    for symbol, (_, code) in wanted:
        row = found.get(code)
        if not row:
            continue
        shaped = _shape_taiwan(row)
        shaped["symbol"] = symbol            # t00 → ^TWII
        out.append(shaped)
    return out


# -------------------------------------------------------------- 其他市場 ---
# 兩條路徑：本機有 Fincept 就用它（涵蓋指數）；沒有就走 Finnhub（stdlib，
# 但免費層不含指數）。雲端建置（GitHub Actions）走的是後者。

FINNHUB_QUOTE = "https://finnhub.io/api/v1/quote"


def finnhub_key() -> str:
    return (os.environ.get("FINNHUB_API_KEY")
            or os.environ.get("MARKETDATA_API_KEY") or "").strip()


def finnhub_quotes(symbols: list[str], *, ttl: float = 900) -> list[dict]:
    """Finnhub 逐檔報價。免費層不含指數，^ 開頭的直接略過不浪費額度。"""
    token = finnhub_key()
    if not token or not symbols:
        return []
    out = []
    for symbol in symbols:
        if symbol.startswith("^"):
            continue
        url = build_url(FINNHUB_QUOTE, {"symbol": symbol, "token": token})
        try:
            q = get_json(url, ttl=ttl, namespace="finnhub", timeout=25, retries=2)
        except Exception:
            continue
        price = q.get("c")
        if not price:
            continue
        out.append({
            "symbol": symbol, "price": price,
            "change": q.get("d"), "change_percent": q.get("dp"),
            "open": q.get("o"), "high": q.get("h"), "low": q.get("l"),
            "previous_close": q.get("pc"),
            "timestamp": q.get("t"),
            "source": "finnhub.io",
        })
    return out


def index_quotes(symbols: list[str], *, timeout: int = 90) -> list[dict]:
    """優先用 Fincept Terminal；本機沒有它時退回 Finnhub。"""
    if not symbols:
        return []
    if not available():
        return finnhub_quotes(symbols)
    script = os.path.join(FINCEPT_SCRIPTS, "yfinance_data.py")
    if not os.path.exists(script):
        return finnhub_quotes(symbols)
    try:
        result = subprocess.run(
            [FINCEPT_PYTHON, script, "batch_quotes", *symbols],
            capture_output=True, timeout=timeout, cwd=FINCEPT_SCRIPTS)
    except Exception:
        return finnhub_quotes(symbols)
    if result.returncode != 0:
        return finnhub_quotes(symbols)
    try:
        payload = json.loads(result.stdout.decode("utf-8", "replace"))
    except Exception:
        return finnhub_quotes(symbols)
    if isinstance(payload, dict):
        payload = payload.get("data") or []
    rows = [row for row in payload
            if isinstance(row, dict) and row.get("price") is not None]
    return rows or finnhub_quotes(symbols)


# ---------------------------------------------------------------- 正規化 ---

def normalise(row: dict, *, name: str = "", region: str = "") -> dict:
    """把兩種來源的欄位統一成同一個形狀。"""
    stamp = row.get("timestamp")
    when = None
    if isinstance(stamp, (int, float)):
        when = datetime.fromtimestamp(stamp, tz=timezone.utc).astimezone()
    elif isinstance(stamp, str):
        try:
            when = datetime.fromisoformat(stamp)
        except Exception:
            when = None

    return {
        "symbol": row.get("symbol", ""),
        "name": name or row.get("name") or row.get("symbol", ""),
        "region": region,
        "price": row.get("price"),
        "change": row.get("change"),
        "change_percent": row.get("change_percent"),
        "open": row.get("open"),
        "high": row.get("high"),
        "low": row.get("low"),
        "previous_close": row.get("previous_close"),
        "volume": row.get("volume"),
        "quoted_at": when,
        "market_status": row.get("market_status") or "",
        "is_intraday": bool(row.get("price_is_intraday")),
        "source": row.get("source") or "Fincept / yfinance",
        # 台股專屬
        "limit_up": row.get("limit_up"),
        "limit_down": row.get("limit_down"),
        "trade_time": row.get("trade_time"),
    }
