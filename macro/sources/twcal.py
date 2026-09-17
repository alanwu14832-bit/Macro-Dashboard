"""台灣：跨部會統計發布看板（主計總處「近期統計發布」）。

各部會的統計都在這裡預告日期與時刻，涵蓋未來約一週，當天已發布的也還在。
頁面是 Vue 樣板，資料寫在 `var VueData = {...}` 裡，要用大括號配對切出來，
不能用貪婪正規表示式——JSON 字串裡也有大括號。

看板一週只有十來項，多數是小統計（國民年金、觀光旅館住用率）。總覽只挑
對台股判斷有分量的幾項，名單寫死在 MAJOR。
"""
from __future__ import annotations

import json
from datetime import date, time

from ..clock import today as _today
from ..http import get

FUTURE = "https://www.stat.gov.tw/News_NoticeCalendar_Future.aspx?n=3907"

# (發布機關, 名稱裡的任一關鍵字, 總覽上的名字)
MAJOR = [
    ("行政院主計總處", ("國民所得", "經濟成長"), "GDP 與經濟成長率"),
    ("行政院主計總處", ("消費者物價",), "消費者物價（CPI）"),
    ("行政院主計總處", ("失業率",), "失業率"),
    ("財政部", ("進出口貿易",), "海關進出口"),
    ("經濟部", ("外銷訂單",), "外銷訂單"),
    ("經濟部", ("工業生產",), "工業生產"),
    ("國家發展委員會", ("景氣",), "景氣對策信號"),
]


def vue_data(page: str) -> dict:
    start = page.find("{", page.find("var VueData"))
    if start < 0:
        raise ValueError("找不到 VueData")
    depth, in_string, escaped = 0, False, False
    for index in range(start, len(page)):
        char = page[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return json.loads(page[start:index + 1])
    raise ValueError("VueData 大括號沒有配對")


def _date(month_day: str, today: date) -> date | None:
    """看板只給 'MM/DD'，年份要從今天推：跨年時 12 月看得到 1 月的項目。"""
    try:
        month, day = (int(x) for x in month_day.split("/"))
        candidate = date(today.year, month, day)
    except (ValueError, TypeError):
        return None
    if (candidate - today).days < -180:
        candidate = candidate.replace(year=today.year + 1)
    elif (candidate - today).days > 180:
        candidate = candidate.replace(year=today.year - 1)
    return candidate


def _time(raw: str) -> time | None:
    try:
        hour, minute = (int(x) for x in raw.split(":"))
        return time(hour, minute)
    except (ValueError, TypeError, AttributeError):
        return None


def major_label(dept: str, name: str) -> str | None:
    for major_dept, keywords, label in MAJOR:
        if dept == major_dept and any(k in name for k in keywords):
            return label
    return None


def parse(page: str, today: date) -> list[dict]:
    out = []
    for item in vue_data(page).get("list") or []:
        slot = item.get("timedatas") or {}
        when = _date(slot.get("date", ""), today)
        if when is None:
            continue
        out.append({
            "dept": item.get("DeptName") or "", "name": item.get("name") or "",
            "label": major_label(item.get("DeptName") or "", item.get("name") or ""),
            "date": when, "time": _time(slot.get("time", "")),
            "period": (slot.get("notice") or "").strip("()"),
        })
    return out


def releases(*, ttl: float = 1800) -> list[dict]:
    """看板上的全部項目；抓不到回空清單（總覽會說「台灣發布行事曆沒有取得」）。"""
    try:
        return parse(get(FUTURE, ttl=ttl, namespace="twcal", timeout=40), _today())
    except Exception:
        return []
