"""公布前的預期：克里夫蘭聯準銀行的通膨即時預估（Inflation Nowcasting）。

本站沒有市場共識——那是付費資料，而且 CPI、非農這類數據沒有以單次公布為標的、
又有公開報價的期貨可以推。能拿到的「公布前的預期」只有兩種：聯邦基金利率期貨
（利率決議，已在 sources/fedfunds.py）與聯準銀行自己公布的模型即時預估。
這裡接的是後者的通膨部分；GDP 的 GDPNow 走 FRED（序列 GDPNOW）。

它是**模型**，不是共識、也不是市場定價。頁面上一律寫「模型預估」並標來源。

資料形狀：兩個 JSON（月增、年增），各是一串圖表，一個目標月份一張。每張圖裡：
  categories  橫軸的日期標籤（"09/08"），中間夾著「CPI Aug」這類公布日的直線標記
  dataset     CPI／Core CPI／PCE／Core PCE 四條每日預估線，加上四條 Actual（只有
              公布那天有一個點）
直線標記不是資料點：資料陣列比標籤少了那幾格，對日期時要先把標記拿掉。
標籤沒有年份，由目標月份推：月份比目標月小的是隔年（12 月的預估會算到 1 月）。

檔案各 7 MB、每天更新。只留最近 KEEP_MONTHS 個月（算模型平常差多少用）。
解析一個檔要兩秒，所以把留下來的那一小份另外存起來（以原檔內容的雜湊為名）：
原檔沒變就不重新解析——每小時的建置與排程的摘要都會用到它。
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import date

from ..http import get
from ..paths import CACHE_DIR

BASE = "https://www.clevelandfed.org/-/media/files/webcharts/inflationnowcasting"
FILES = {"mom": f"{BASE}/nowcast_month.json", "yoy": f"{BASE}/nowcast_year.json"}
SOURCE = "克里夫蘭聯準銀行 Inflation Nowcasting"
PAGE = "https://www.clevelandfed.org/indicators-and-data/inflation-nowcasting"

# 圖上的線名 -> 本站的代號
MEASURES = {
    "CPI Inflation": "cpi", "Core CPI Inflation": "core_cpi",
    "PCE Inflation": "pce", "Core PCE Inflation": "core_pce",
}
KEEP_MONTHS = 40
TTL = 6 * 3600

# 最近一次抓取或解析失敗的原因；成功是 None。build.py 會印。
LAST_ERROR: str | None = None


def _number(raw) -> float | None:
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _label_date(label: str, year: int, month: int) -> date | None:
    """"09/08" + 目標月份 -> 日期。預估從目標月的月初算到隔月（或再隔月）的公布日。"""
    try:
        mm, dd = (int(part) for part in label.split("/"))
    except ValueError:
        return None
    try:
        return date(year + 1 if mm < month else year, mm, dd)
    except ValueError:
        return None


def parse(raw: str, *, keep: int = KEEP_MONTHS) -> dict:
    """一個檔 -> {(年, 月): {代號: {"path": [(日期, 預估)…], "actual": (日期, 實際) 或 None}}}。

    格式不對就丟例外，由呼叫端決定怎麼降級——不回一個看起來正常的空結果。
    """
    charts = json.loads(raw)
    if not isinstance(charts, list) or not charts:
        raise ValueError("不是一串圖表")
    out: dict = {}
    for chart in charts[-keep:]:
        year, month = (int(part) for part in chart["chart"]["subcaption"].split("-"))
        labels = [c["label"] for c in chart["categories"][0]["category"] if not c.get("vline")]
        days = [_label_date(label, year, month) for label in labels]
        measures: dict = {}
        for line in chart["dataset"]:
            name = line.get("seriesname") or ""
            actual = name.startswith("Actual ")
            key = MEASURES.get(name[len("Actual "):] if actual else name)
            if key is None:
                continue
            points = [(days[i], _number(point.get("value")))
                      for i, point in enumerate(line.get("data") or []) if i < len(days)]
            points = [(d, v) for d, v in points if d is not None and v is not None]
            slot = measures.setdefault(key, {"path": [], "actual": None})
            if actual:
                slot["actual"] = points[-1] if points else None
            else:
                slot["path"] = points
        if measures:
            out[(year, month)] = measures
    if not out:
        raise ValueError("讀不出任何一個月份的預估")
    return out


def _looks_right(raw: str) -> bool:
    """不合格的回應不寫進快取：網站改版或擋爬時會回 HTML。"""
    return raw.lstrip().startswith("[") and '"seriesname"' in raw and "Core PCE Inflation" in raw


def _pack(parsed: dict) -> str:
    return json.dumps({
        f"{year}-{month}": {key: {"path": [[d.isoformat(), v] for d, v in slot["path"]],
                                  "actual": ([slot["actual"][0].isoformat(), slot["actual"][1]]
                                             if slot["actual"] else None)}
                            for key, slot in measures.items()}
        for (year, month), measures in parsed.items()})


def _unpack(text: str) -> dict:
    out = {}
    for label, measures in json.loads(text).items():
        year, month = (int(part) for part in label.split("-"))
        out[(year, month)] = {
            key: {"path": [(date.fromisoformat(d), v) for d, v in slot["path"]],
                  "actual": ((date.fromisoformat(slot["actual"][0]), slot["actual"][1])
                             if slot["actual"] else None)}
            for key, slot in measures.items()}
    return out


def _parsed(raw: str, kind: str) -> dict:
    """parse(raw)，原檔沒變就讀上次存的那一小份。"""
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]
    directory = os.path.join(CACHE_DIR, "nowcast")
    prefix = f"parsed-{kind}-"
    path = os.path.join(directory, f"{prefix}{digest}-{KEEP_MONTHS}.json")
    try:
        with open(path, encoding="utf-8") as fh:
            return _unpack(fh.read())
    except Exception:
        pass
    parsed = parse(raw)
    try:
        os.makedirs(directory, exist_ok=True)
        for name in os.listdir(directory):          # 舊的一份不留，一天一個檔會越積越多
            if name.startswith(prefix):
                os.remove(os.path.join(directory, name))
        with open(path + ".tmp", "w", encoding="utf-8") as fh:
            fh.write(_pack(parsed))
        os.replace(path + ".tmp", path)
    except OSError:
        pass                                        # 存不了只是下次再解析一次
    return parsed


def fetch(*, ttl: float = TTL) -> dict | None:
    """{"mom": {...}, "yoy": {...}}（parse 的結果）；任何一個檔拿不到或讀不懂就回 None。"""
    global LAST_ERROR
    LAST_ERROR = None
    out = {}
    for kind, url in FILES.items():
        try:
            out[kind] = _parsed(get(url, ttl=ttl, namespace="nowcast", timeout=90, retries=2,
                                    validate=_looks_right), kind)
        except Exception as exc:
            LAST_ERROR = f"{SOURCE}（{kind}）拿不到或讀不懂：{exc}"
            return None
    return out
