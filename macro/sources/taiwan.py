"""台灣：行政院主計總處（DGBAS）。

FRED 沒有台灣的 CPI，OECD 也沒有（台灣非會員），所以直接接主計總處的
開放資料 XML。檔案約 15 MB 且含全部基本分類，這裡只留「總指數」與
「核心指數」，其餘丟棄後再快取，避免每次建置都重新解析整份。

DGBAS 的伺服器沒有送出中介憑證，OpenSSL 補不齊憑證鏈，因此走
macro.http 的 curl 路徑 — 驗證仍由系統信任庫完整執行。
"""
from __future__ import annotations

import re

from ..http import get
from ..series import Series

CPI_XML = ("https://ws.dgbas.gov.tw/001/Upload/461/relfile/11525/230555/"
           "pr0101a1m.xml")

# 民國年 + 月 -> 西元 ISO 日期
_PERIOD = re.compile(r"^(\d{4})M(\d{2})$")
_OBS = re.compile(
    r"<Obs><Item>(?P<item>[^<]*)</Item>"
    r"<TIME_PERIOD>(?P<period>[^<]*)</TIME_PERIOD>"
    r"<FREQ>(?P<freq>[^<]*)</FREQ>"
    r"<TYPE>(?P<type>[^<]*)</TYPE>\s*"
    r"<Item_VALUE>(?P<value>[^<]*)</Item_VALUE></Obs>")


def _iso(period: str) -> str | None:
    m = _PERIOD.match(period.strip())
    if not m:
        return None
    year, month = int(m.group(1)), int(m.group(2))
    if not 1 <= month <= 12:
        return None
    return f"{year:04d}-{month:02d}-01"


def cpi(*, ttl: float = 24 * 3600) -> dict[str, Series]:
    """回傳 {'index': 總指數, 'yoy': 年增率}。取不到就回空 Series。"""
    empty = {"index": Series("TW_CPI", [], [], frequency="m"),
             "yoy": Series("TW_CPI_YOY", [], [], frequency="m")}
    try:
        raw = get(CPI_XML, ttl=ttl, namespace="taiwan", timeout=90, retries=2)
    except Exception:
        return empty

    levels: list[tuple[str, float]] = []
    growth: list[tuple[str, float]] = []
    for match in _OBS.finditer(raw):
        item = match.group("item")
        if not item.startswith("總指數"):
            continue
        value = match.group("value").strip()
        if not value:
            continue
        date = _iso(match.group("period"))
        if not date:
            continue
        try:
            number = float(value)
        except ValueError:
            continue
        if match.group("type") == "原始值":
            levels.append((date, number))
        elif match.group("type").startswith("年增率"):
            growth.append((date, number))

    if not levels:
        return empty
    return {
        "index": Series.from_pairs("TW_CPI", levels, label="台灣 CPI",
                                   unit="指數", frequency="m", source="主計總處"),
        "yoy": Series.from_pairs("TW_CPI_YOY", growth, label="台灣 CPI 年增率",
                                 unit="%", frequency="m", source="主計總處"),
    }
