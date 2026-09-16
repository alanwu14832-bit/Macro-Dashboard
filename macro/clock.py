"""全站唯一的時間來源。

建置在 GitHub Actions 上跑，runner 的時區是 UTC。用 naive 的 datetime.now()
或 date.today() 會產生兩種錯，而且都不會當場爆炸：

  1. 頁面上的「最後更新」標著台北時間，實際是 UTC，整整差 8 小時。
  2. 每日存檔用 UTC 日期歸檔——台北時間凌晨 0 到 8 點之間的建置會被歸到
     前一天，直接覆蓋掉前一天已經寫好的判斷快照。改成每小時建置之後，
     每天會有 8 個小時落在這個區間。

所以時間一律從這裡拿。台北不實施日光節約，+8 這個偏移永遠成立，寫死比讀
環境變數安全——runner 的 TZ 本來就不該影響產出。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

TAIPEI = timezone(timedelta(hours=8), "Asia/Taipei")
NEW_YORK = ZoneInfo("America/New_York")


def now() -> datetime:
    """帶時區的現在時間（台北）。"""
    return datetime.now(TAIPEI)


def today() -> date:
    """台北的今天。"""
    return now().date()


def us_today() -> date:
    """美東的今天。拿來跟美國事件的日期比：FOMC、公債標售、FRED 發布日、財報日。

    這些日期是美東日期。台北在美東中午前後就換日，拿台北的今天去比，14:00 的
    FOMC 決策還沒公布就會被當成已經過去；UTC 則在美東傍晚換日。美東的日期要到
    當天的事件都結束之後才換——寧可晚半天劃掉，不能在事件發生前就劃掉。
    美東有日光節約，偏移不能寫死，所以用標準庫的 zoneinfo。
    """
    return datetime.now(NEW_YORK).date()


def stamp(prefix: str = "最後更新 ") -> str:
    return prefix + now().strftime("%Y-%m-%d %H:%M")
