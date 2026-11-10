"""公布時間到了，資料跟上了沒。

2026-11-10 的 10 月 CPI：美東 8:30 公布，FRED 到 9:12（14:12 UTC）才登出。當天公布後
第一次建置在 13:59 UTC 開跑、14:07 提交——早了五分鐘，抓回來的還是 9 月；之後兩個半
小時 GitHub 的排程一次都沒有跑。就算那段時間有建置，50 分鐘的快取也可能讓它重用
公布前抓的那一份。

所以建置在載入資料之前先問這一題：追蹤的發布裡，哪幾份的公布時間已經過了、而上一輪
建置記下的資料日期還沒往前推？那幾份發布的每一檔序列這一輪繞過快取重新抓，其餘照舊
讀快取。抓回來仍是舊的就照舊——不補值、不猜，下一輪再問一次。

「跟上了沒」看的是 data/series_dates.json 的 `seen`（那個資料日期第一次被建置看到的
台北日期）：seen 不早於公布那一刻的台北日期，就是這次公布之後才到的。

發布守候（tools/release_watch.py）用同一套時刻與同一個判斷，兩邊不會各說各話。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from .. import catalogue
from ..clock import NEW_YORK, TAIPEI
from . import freshness
from .events import DEFAULT_RELEASE, RELEASE_TIMES

# 公布後幾天內還沒跟上的才繞過快取。超過就交還給一般的快取：行事曆上有日期、實際沒有
# 發布的月份（2025-10 政府關門）不能讓那幾檔永遠每輪重抓。
WINDOW = timedelta(days=freshness.CALENDAR_LOOKBACK_DAYS)


def tracked() -> list[tuple[str, str, int]]:
    """(序列, 名稱, 發布編號)。日頻的不算——殖利率沒有「公布那一刻」，50 分鐘的快取就夠。"""
    specs: dict = {}
    for group in catalogue.ALL_GROUPS.values():
        specs.update(group)
    return [(series_id, label, release_id)
            for series_id, label, _module, release_id in freshness.TRACKED
            if (specs.get(series_id) or ("", "", "m", ""))[2] != "d"]


def release_at(series_id: str, day: date) -> datetime:
    """那一天的公布時刻（美東，帶時區——夏令冬令由 zoneinfo 決定，不寫死 UTC）。"""
    return datetime.combine(day, RELEASE_TIMES.get(series_id, DEFAULT_RELEASE),
                            tzinfo=NEW_YORK)


def landed(entry: dict | None, at: datetime) -> bool:
    """這檔序列的資料日期，是不是在這次公布之後才往前推的。沒有紀錄＝還沒。"""
    try:
        seen = date.fromisoformat((entry or {}).get("seen") or "")
    except ValueError:
        return False
    return seen >= at.astimezone(TAIPEI).date()


def calendar() -> dict[int, list[date] | None]:
    """{發布編號: 發布日}，取自 FRED 的發布行事曆（12 小時快取，跟新鮮度頁共用同一份）。
    抓不到的那一份是 None：不知道就不繞過快取，不猜今天有沒有發布。"""
    out: dict[int, list[date] | None] = {}
    for _series_id, _label, release_id in tracked():
        if release_id in out:
            continue
        try:
            raw = freshness._release_dates(release_id)
        except Exception:
            raw = None
        out[release_id] = None if raw is None else [date.fromisoformat(d) for d in raw]
    return out


def latest_release(series_id: str, days: list[date] | None, now: datetime) -> datetime | None:
    """行事曆上最近一次「時間已過」的公布時刻；早於 WINDOW 的不算。"""
    passed = [at for at in (release_at(series_id, day) for day in days or [])
              if now - WINDOW <= at <= now]
    return max(passed) if passed else None


def waiting(now: datetime, cal: dict[int, list[date] | None], state: dict) -> dict[str, datetime]:
    """{追蹤序列: 公布時刻}：公布時間已過、資料日期卻還沒往前推的。"""
    out: dict[str, datetime] = {}
    for series_id, _label, release_id in tracked():
        at = latest_release(series_id, cal.get(release_id), now)
        if at is not None and not landed(state.get(series_id), at):
            out[series_id] = at
    return out


def refresh_ids(now: datetime, cal: dict[int, list[date] | None], state: dict) -> set[str]:
    """這一輪要繞過快取的序列：公布時間已過的那幾份發布裡，還沒跟上的每一檔。

    逐檔判斷，不是「追蹤的那一檔到了就整份放行」：FRED 一份發布是分批登出的
    （2026-11-10 的 CPI 前後差 88 秒、11-06 的就業報告差 157 秒），建置剛好落在中間時，
    總指數是新的、分項還是舊的；晚到的那幾檔下一輪要繼續重抓。
    """
    ids: set[str] = set()
    for series_id, _label, release_id in tracked():
        at = latest_release(series_id, cal.get(release_id), now)
        if at is None:
            continue
        for member in {series_id, *catalogue.RELEASE_FAMILY.get(release_id, ())}:
            if not landed(state.get(member), at):
                ids.add(member)
    return ids
