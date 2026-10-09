"""台灣：行政院主計總處（DGBAS）。

FRED 沒有台灣的 CPI，OECD 也沒有（台灣非會員），所以直接接主計總處的
開放資料 XML。檔案約 15 MB 且含全部基本分類，這裡只留「總指數」與
「核心指數」，其餘丟棄後再快取，避免每次建置都重新解析整份。

DGBAS 的伺服器（ws.dgbas.gov.tw）沒有送出中介憑證，OpenSSL 補不齊憑證鏈。
macro.http 會照憑證上的 AIA 網址把中介憑證補回來再驗——驗證沒有關。
（2026-10-10 以前這裡走 curl，以為 curl 會自己補；雲端建置的 curl 不會，
所以台灣 CPI 在 GitHub Actions 上一直是缺口，而且因為下面把例外吞掉，
建置紀錄裡看不出原因。現在失敗的原因留在 LAST_ERROR，build.py 會印。）
"""
from __future__ import annotations

import re

from ..http import get
from ..series import Series
from . import datagov

# 網址裡的 11525/230555 是上架版本號，主計總處重新上架就換。每次建置先經
# 政府資料開放平臺（資料集 6019）解析當前網址，這條寫死的只當退路。
CPI_DATASET = 6019
CPI_XML = ("https://ws.dgbas.gov.tw/001/Upload/461/relfile/11525/230555/"
           "pr0101a1m.xml")

# 最近一次 cpi() 失敗的原因；成功就是 None。頁面上只寫「抓不到」，原因印在建置紀錄。
LAST_ERROR: str | None = None

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
    global LAST_ERROR
    LAST_ERROR = None
    empty = {"index": Series("TW_CPI", [], [], frequency="m"),
             "yoy": Series("TW_CPI_YOY", [], [], frequency="m")}
    try:
        target = datagov.download_url(CPI_DATASET, ext=".xml",
                                      fallback=CPI_XML, ttl=ttl)
        raw = get(target, ttl=ttl, namespace="taiwan", timeout=90, retries=2)
    except Exception as exc:
        LAST_ERROR = f"下載失敗：{exc}"
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
        # 抓到了檔案卻讀不出「總指數」：多半是主計總處改了 XML 的欄位或項目名稱
        LAST_ERROR = f"下載到 {len(raw):,} 個字元，但讀不出「總指數」的原始值（XML 格式可能改了）"
        return empty
    return {
        "index": Series.from_pairs("TW_CPI", levels, label="台灣 CPI",
                                   unit="指數", frequency="m", source="主計總處"),
        "yoy": Series.from_pairs("TW_CPI_YOY", growth, label="台灣 CPI 年增率",
                                 unit="%", frequency="m", source="主計總處"),
    }
