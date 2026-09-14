"""台灣：中央銀行貼放利率。

央行沒有把政策利率放進任何開放資料檔，只有「央行貼放利率」這一頁的
HTML 表格（每頁 20 次調整，三頁回溯到 2000 年）。政策利率是階梯函數，
一年可能一次都不動，所以解析頁面比接一個會停更的代理指標可靠。

回傳兩種形狀：`changes` 是調整當天的點（每一點都是一次決策），
`monthly` 是把它展開成每月底的水準（畫成階梯，不會在兩次決策之間
畫出一條不存在的斜線）。
"""
from __future__ import annotations

import re
from datetime import date

from ..clock import today as _today
from ..http import get
from ..series import Series

PAGES = [f"https://www.cbc.gov.tw/tw/lp-640-1-{n}-20.html" for n in (1, 2, 3)]

_ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
_CELL = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.S)
_TAG = re.compile(r"<[^>]+>")
_DATE = re.compile(r"^(\d{4})/(\d{1,2})/(\d{1,2})$")

EMPTY = {"changes": Series("TW_DISCOUNT", [], [], frequency="d"),
         "monthly": Series("TW_DISCOUNT_M", [], [], frequency="m")}


def _rows(html: str) -> list[list[str]]:
    out = []
    for block in _ROW.findall(html):
        cells = [_TAG.sub("", c).replace("&nbsp;", " ").strip()
                 for c in _CELL.findall(block)]
        if len(cells) >= 2:
            out.append(cells)
    return out


def discount_rate(*, ttl: float = 24 * 3600) -> dict[str, Series]:
    """重貼現率的完整調整史。抓不到就回空序列，不用前值假裝。"""
    points: dict[date, float] = {}
    for url in PAGES:
        try:
            html = get(url, ttl=ttl, namespace="cbc", timeout=40, retries=2)
        except Exception:
            continue
        for cells in _rows(html):
            match = _DATE.match(cells[0])
            if not match:
                continue
            try:
                value = float(cells[1])
            except (ValueError, IndexError):
                continue
            year, month, day = (int(g) for g in match.groups())
            try:
                points[date(year, month, day)] = value
            except ValueError:
                continue

    if not points:
        return dict(EMPTY)

    ordered = sorted(points.items())
    changes = Series.from_pairs(
        "TW_DISCOUNT", ordered, label="央行重貼現率", unit="%",
        frequency="d", source="中央銀行")

    # 展開成月底水準：政策利率在兩次決策之間就是不動，所以每個月都取
    # 「當月底仍然有效的那個值」。這是階梯，不是內插。
    monthly_pairs = []
    year, month = ordered[0][0].year, ordered[0][0].month
    today = _today()
    current = ordered[0][1]
    cursor = 0
    while (year, month) <= (today.year, today.month):
        month_end = date(year + (month == 12), month % 12 + 1, 1)
        while cursor < len(ordered) and ordered[cursor][0] < month_end:
            current = ordered[cursor][1]
            cursor += 1
        monthly_pairs.append((date(year, month, 1), current))
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)

    return {
        "changes": changes,
        "monthly": Series.from_pairs(
            "TW_DISCOUNT_M", monthly_pairs, label="央行重貼現率", unit="%",
            frequency="m", source="中央銀行"),
    }
