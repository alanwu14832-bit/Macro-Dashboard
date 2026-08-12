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
        # 收盤後或無成交時 z 是 '-'，退而用最佳買價／賣價
        price = (_tw_num((row.get("b") or "").split("_")[0])
                 or _tw_num((row.get("a") or "").split("_")[0]))

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


def taiwan_quotes(tickers: list[str], *, ttl: float = 900) -> list[dict]:
    """證交所官方報價。上市與上櫃兩個 channel 都送，MIS 只回存在的那個。"""
    codes = [str(t).strip().upper().split(".")[0] for t in tickers if str(t).strip()]
    if not codes:
        return []
    channels = "|".join(f"{market}_{code}.tw"
                        for code in codes for market in ("tse", "otc"))
    url = build_url(MIS_URL, {"ex_ch": channels, "json": "1", "delay": "0"})
    try:
        payload = get_json(url, ttl=ttl, namespace="twse", timeout=30, retries=2)
    except Exception:
        return []
    if payload.get("rtcode") != "0000":
        return []

    found = {row.get("c"): row for row in payload.get("msgArray") or [] if row.get("c")}
    return [_shape_taiwan(found[code]) for code in codes if code in found]


# -------------------------------------------------------------- 其他市場 ---

def index_quotes(symbols: list[str], *, timeout: int = 90) -> list[dict]:
    """Fincept Terminal 的 yfinance_data.py batch_quotes。"""
    if not available() or not symbols:
        return []
    script = os.path.join(FINCEPT_SCRIPTS, "yfinance_data.py")
    if not os.path.exists(script):
        return []
    try:
        result = subprocess.run(
            [FINCEPT_PYTHON, script, "batch_quotes", *symbols],
            capture_output=True, timeout=timeout, cwd=FINCEPT_SCRIPTS)
    except Exception:
        return []
    if result.returncode != 0:
        return []
    try:
        payload = json.loads(result.stdout.decode("utf-8", "replace"))
    except Exception:
        return []
    if isinstance(payload, dict):
        payload = payload.get("data") or []
    return [row for row in payload if isinstance(row, dict) and row.get("price") is not None]


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
