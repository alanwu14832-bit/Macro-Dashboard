"""政府資料開放平臺：把資料集編號解析成當前的下載網址。

各機關重新上架檔案時，下載網址裡的版本號或 GUID 會換（主計總處的
relfile/11525/230555、國發會的 Download.ashx?u=...）。寫死的網址在那之後會
回退到過期快取，頁面看起來正常，只是停在舊月份。平臺的單一資料集查詢
不需要 API key，所以每次建置先問它當前網址，寫死的那條只當退路。
"""
from __future__ import annotations

import json

from ..http import get

API = "https://data.gov.tw/api/v2/rest/dataset/{nid}"


def download_url(nid: int, *, ext: str, fallback: str,
                 ttl: float = 24 * 3600) -> str:
    try:
        meta = json.loads(get(API.format(nid=nid), ttl=ttl,
                              namespace="datagov", timeout=40))
        for entry in meta["result"]["distribution"]:
            candidate = (entry.get("resourceDownloadUrl") or "").strip()
            if candidate.lower().endswith(ext):
                return candidate
    except Exception:
        pass
    return fallback
