"""資料新鮮度：每個指標多新、下次什麼時候更新。

這一頁存在的理由：使用者問「怎麼即時更新」，但總經資料本身沒有即時可言——
非農月頻、GDP 季頻、JOLTS 還延遲一個月。真正的需求是「我現在看到的數字是
不是最新的、下一個什麼時候來」。這個模組把那件事變成可見的。

FRED 的 series/release 端點給出序列屬於哪個發布，release/dates 給出未來的
發布日程，兩者合起來就是一份倒數計時表。
"""
from __future__ import annotations

from datetime import date, datetime

from ..data import Bundle
from ..http import build_url, get_json
from ..sources import fred

# 值得放上檯面的發布。順序＝呈現順序。
TRACKED = [
    ("PAYEMS", "非農就業", "勞動市場", 50),
    ("UNRATE", "失業率", "勞動市場", 50),
    ("ICSA", "初領失業金", "勞動市場", 180),
    ("JTSJOL", "JOLTS 職缺", "勞動市場", 192),
    ("CPIAUCSL", "CPI", "通膨", 10),
    ("PPIFIS", "PPI", "通膨", 46),
    ("PCEPILFE", "核心 PCE", "通膨", 54),
    ("GDPC1", "實質 GDP", "成長", 53),
    ("RSAFS", "零售銷售", "成長", 9),
    ("INDPRO", "工業生產", "成長", 13),
    ("HOUST", "新屋開工", "成長", 20),
    ("DGS10", "公債殖利率", "利率", 18),
    ("DRTSCILM", "放款標準調查", "信用", 34),
]

# 非 FRED 來源沒有發布行事曆，只能報告資料本身的日期。
EXTERNAL = [
    ("OECD SDMX", "各國 CPI", "每月，各國時程不一"),
    ("ECB Data Portal", "歐元區失業率、核心 HICP", "每月"),
    ("行政院主計總處", "台灣 CPI", "每月 5 日前後"),
    ("LBMA", "黃金、白銀定盤價", "每個交易日"),
    ("證交所 mis.twse.com.tw", "台股個股與 ETF 報價", "交易日 09:00–13:30 盤中更新"),
    ("Fincept Terminal", "美股、新興市場指數與個股報價", "各市場交易時段"),
]


def _release_dates(release_id: int, *, limit: int = 3) -> list[str]:
    """今天之後的發布日。"""
    params = {
        "release_id": release_id, "api_key": fred.api_key(), "file_type": "json",
        "sort_order": "asc", "include_release_dates_with_no_data": "true",
        "realtime_start": date.today().isoformat(), "limit": limit,
    }
    try:
        payload = get_json(build_url("https://api.stlouisfed.org/fred/release/dates", params),
                           ttl=12 * 3600, namespace="fred")
    except Exception:
        return []
    return [row["date"] for row in payload.get("release_dates", [])]


def _parse_updated(raw: str) -> datetime | None:
    """FRED 的 last_updated 形如 '2026-08-07 07:31:03-05'。"""
    if not raw:
        return None
    text = raw.strip()
    try:
        # 時區偏移只有小時，補足分鐘讓 fromisoformat 吃得下
        if len(text) > 6 and text[-3] in "+-":
            text = text + ":00"
        return datetime.fromisoformat(text.replace(" ", "T"))
    except Exception:
        return None


def compute(bundle: Bundle) -> dict:
    today = date.today()
    rows = []
    for series_id, label, module, release_id in TRACKED:
        series = bundle[series_id]
        if not series:
            continue
        # 一般載入為了省 API 呼叫略過 metadata，這裡只為這十幾檔補抓，
        # 因為「FRED 什麼時候更新的」正是這張表要回答的問題。
        meta = series.meta or {}
        if not meta.get("updated"):
            try:
                meta = fred.metadata(series_id, ttl=6 * 3600)
                meta = {"updated": meta.get("last_updated", "")}
            except Exception:
                meta = {}
        updated = _parse_updated(meta.get("updated", ""))
        upcoming = _release_dates(release_id)
        next_release = None
        days_away = None
        for candidate in upcoming:
            when = date.fromisoformat(candidate)
            if when >= today:
                next_release = when
                days_away = (when - today).days
                break

        rows.append({
            "id": series_id, "name": label, "module": module,
            "data_date": series.last_date,
            "data_age": (today - series.last_date).days if series.last_date else None,
            "updated": updated,
            "updated_days": (today - updated.date()).days if updated else None,
            "next_release": next_release,
            "days_away": days_away,
            "frequency": series.frequency,
        })

    rows.sort(key=lambda r: (r["days_away"] is None, r["days_away"]))
    imminent = [r for r in rows if r["days_away"] is not None and r["days_away"] <= 7]

    # 剛公布的數據：FRED 在今天或昨天更新過的序列。使用者打開網站時
    # 不會記得每個發布日，這個集合讓渲染層能在對應讀數旁掛「新」徽章。
    # 日頻排除——殖利率每個交易日都更新，天天掛「新」會把月度發布
    # 這種真正的事件淹沒。
    fresh = {r["id"]: {"name": r["name"],
                       "date": r["updated"].date().isoformat()}
             for r in rows
             if r["updated_days"] is not None and r["updated_days"] <= 1
             and r["frequency"] != "d"}

    return {
        "rows": rows,
        "imminent": imminent,
        "fresh": fresh,
        "external": EXTERNAL,
        "generated": datetime.now(),
        "next_up": rows[0] if rows else None,
    }
