"""台灣：國家發展委員會景氣指標。

一個 ZIP 幾乎涵蓋整套台灣月頻總經：景氣對策信號分數與燈號、領先／同時／
落後指標，以及三組指標的全部構成項目——外銷訂單、M1B、工業生產、海關出口、
失業率、五大銀行放款利率、金融機構放款與投資都在裡面。台灣不在 FRED 也不在
OECD，這是唯一能一次拿齊的免費官方來源。

下載網址走政府資料開放平臺的 dataset API 轉一手：國發會每月重新上傳，檔案
路徑裡的 GUID 會換，寫死會在某次更新後靜默失效（回退到過期快取，頁面看起來
正常但停在舊月份）。轉一手之後，失效會是 dataset API 掛掉，那是看得見的錯誤。
"""
from __future__ import annotations

import csv
import io
import zipfile

from ..http import get_bytes
from ..series import Series
from . import datagov

DATASET_ID = 6099

# dataset API 掛掉時的退路。這個路徑會過期，所以它只是退路，不是主要來源。
FALLBACK_ZIP = (
    "https://ws.ndc.gov.tw/Download.ashx?u=LzAwMS9hZG1pbmlzdHJhdG9yLzEwL3JlbG"
    "ZpbGUvNTc4MS82MzkyL2VhMjM1YmQ5LWQwNTItNGE2OS1hYmZjLWQ1Yzc4NWQzZDBlMi56aX"
    "A%3d&n=5pmv5rCj5oyH5qiZ5Y%2bK54eI6JmfLnppcA%3d%3d&icon=.zip")

# 國發會官方的綜合分數分界（不是本站訂的）：
# 9–16 藍、17–22 黃藍、23–31 綠、32–37 黃紅、38–45 紅。
LIGHT_BANDS = [(16, "藍"), (22, "黃藍"), (31, "綠"), (37, "黃紅"), (45, "紅")]
LIGHT_MEANING = {
    "藍": "景氣低迷", "黃藍": "景氣轉向", "綠": "景氣穩定",
    "黃紅": "景氣轉向", "紅": "景氣熱絡",
}

# 檔名 -> {本站代號: (CSV 欄名, 中文名, 單位)}
# 欄名含單位且國發會偶爾會改寫，抓不到的欄位留空序列，不用鄰近欄位替代。
LAYOUT: dict[str, dict[str, tuple[str, str, str]]] = {
    "景氣指標與燈號.csv": {
        "signal_score": ("景氣對策信號綜合分數", "景氣對策信號綜合分數", "分"),
        "leading": ("領先指標不含趨勢指數", "領先指標（不含趨勢）", "指數"),
        "leading_raw": ("領先指標綜合指數", "領先指標綜合指數", "指數"),
        "coincident": ("同時指標不含趨勢指數", "同時指標（不含趨勢）", "指數"),
        "lagging": ("落後指標不含趨勢指數", "落後指標（不含趨勢）", "指數"),
    },
    "領先指標構成項目.csv": {
        "export_orders": ("外銷訂單動向指數(以家數計)", "外銷訂單動向指數", "指數"),
        "m1b": ("貨幣總計數M1B(百萬元)", "貨幣總計數 M1B", "百萬元"),
        "twse_index": ("股價指數(Index1966=100)", "股價指數", "指數"),
        "net_entry": ("工業及服務業受僱員工淨進入率(%)", "受僱員工淨進入率", "%"),
        "floor_area": (
            "建築物開工樓地板面積(住宅類住宅、商業辦公、工業倉儲)(千平方公尺)",
            "建築物開工樓地板面積", "千平方公尺"),
        "semi_equip": ("名目半導體設備進口(新臺幣百萬元)", "半導體設備進口", "百萬元"),
    },
    "同時指標構成項目.csv": {
        "industrial": ("工業生產指數(Index2021=100)", "工業生產指數", "指數"),
        "power": ("電力(企業)總用電量(十億度)", "企業總用電量", "十億度"),
        "mfg_sales": ("製造業銷售量指數(Index2021=100)", "製造業銷售量指數", "指數"),
        "retail": ("批發、零售及餐飲業營業額(十億元)", "批發零售餐飲營業額", "十億元"),
        "overtime": ("工業及服務業加班工時(小時)", "加班工時", "小時"),
        "exports": ("海關出口值(十億元)", "海關出口值", "十億元"),
        "capex_imports": ("機械及電機設備進口值(十億元)", "機電設備進口值", "十億元"),
    },
    "落後指標構成項目.csv": {
        "unemployment": ("失業率(%)", "失業率", "%"),
        "unit_labour_cost": (
            "製造業單位產出勞動成本指數(2021=100)", "單位產出勞動成本", "指數"),
        "loan_rate": (
            "五大銀行新承做放款平均利率(年息百分比)", "五大銀行新承做放款利率", "%"),
        "credit": ("全體金融機構放款與投資(10億元)", "金融機構放款與投資", "十億元"),
        "inventory": ("製造業存貨價值(千元)", "製造業存貨價值", "千元"),
    },
}


def light_for(score) -> str | None:
    """綜合分數落在哪一個官方燈號區間。"""
    if score is None:
        return None
    for ceiling, name in LIGHT_BANDS:
        if score <= ceiling:
            return name
    return LIGHT_BANDS[-1][1]


def _iso(period: str) -> str | None:
    """'202607' -> '2026-07-01'。"""
    period = period.strip()
    if len(period) != 6 or not period.isdigit():
        return None
    month = int(period[4:])
    if not 1 <= month <= 12:
        return None
    return f"{period[:4]}-{period[4:]}-01"


def zip_url(*, ttl: float = 24 * 3600) -> str:
    return datagov.download_url(DATASET_ID, ext=".zip", fallback=FALLBACK_ZIP,
                                ttl=ttl)


def _empty() -> dict[str, Series]:
    return {code: Series(f"TW_{code.upper()}", [], [], frequency="m")
            for block in LAYOUT.values() for code in block}


def _parse_archive(archive: zipfile.ZipFile) -> dict[str, Series]:
    """把 ZIP 裡的五個 CSV 攤成序列。

    欄名對不上就留空，不用鄰近欄位頂替——國發會改寫過欄名，位置型解析
    會讓失業率那條線畫的是單位產出勞動成本，而且不會報錯。
    """
    out = _empty()
    for filename, columns in LAYOUT.items():
        try:
            text = archive.read(filename).decode("utf-8-sig")
        except Exception:
            continue
        rows = list(csv.DictReader(io.StringIO(text)))
        for code, (column, label, unit) in columns.items():
            pairs = []
            for row in rows:
                raw = (row.get(column) or "").strip()
                date = _iso(row.get("Date") or "")
                if not raw or raw == "-" or not date:
                    continue
                try:
                    pairs.append((date, float(raw)))
                except ValueError:
                    continue
            if pairs:
                out[code] = Series.from_pairs(
                    f"TW_{code.upper()}", pairs, label=label, unit=unit,
                    frequency="m", source="國發會")
    return out


def indicators(*, ttl: float = 24 * 3600) -> dict[str, Series]:
    """景氣指標全套。整包取不到就回空序列，讓頁面就地說明缺口。"""
    try:
        blob = get_bytes(zip_url(ttl=ttl), ttl=ttl, namespace="ndc", timeout=120)
        return _parse_archive(zipfile.ZipFile(io.BytesIO(blob)))
    except Exception:
        return _empty()
