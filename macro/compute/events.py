"""今天：重大數據與政策決議。

總覽最上面要能一眼回答「今天有沒有重大數據或政策轉向」。這裡把四條線收成
一份清單，全部是機構正式發布的事實，不放本站規則的判定（那在「自上次以來」）：

  政策  FOMC 決議（macro/fomc.py）、台灣央行理監事會（macro/cbc_board.py）
  數據  美國 13 項主要發布（compute/freshness.py 的 TRACKED）、
        台灣 7 項主要統計（sources/twcal.py 的 MAJOR）

「今天」一律是台北的今天。美東 8:30 的數據是台北當晚（冬令 21:30）；例會聲明
美東 14:00 是台北隔天凌晨——所以台北早上打開，凌晨的決議算今天。

會後一週內的決議即使不是今天，也列在「本週稍早」：幾天沒打開網站的人，
不能因為那天剛好沒看就錯過一次升息。決議遺漏則永遠置頂。行事曆抓不到時，
第一句不能說「今天沒有重大數據」——那是沒偵測到，不是沒有。
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

from .. import clock
from ..clock import NEW_YORK, TAIPEI
from ..sources import twcal

WEEKDAYS = "一二三四五六日"

# 美國主要發布的美東公布時刻。FRED 的更新時間常比實際發布晚好幾個小時
# （PPI 美東 8:30 發布，FRED 中午才更新，換成台北就跨到隔天），不能當公布時間。
RELEASE_TIMES = {"JTSJOL": time(10, 0), "INDPRO": time(9, 15), "DRTSCILM": time(14, 0)}
DEFAULT_RELEASE = time(8, 30)

POLICY_ORDER = {"遺漏": 0, "轉向": 1, "變動": 2, "調整": 3, "待公布": 4, "不變": 5}


def _states(value) -> list[dict]:
    if not value:
        return []
    return [value] if isinstance(value, dict) else list(value)


def _policy_kind(action: str, prev_action: str | None, change: bool) -> str:
    """轉向＝這次的動作跟上一次會議不同（維持→升息、升息→降息、升息→維持）。
    利率沒動但調了準備率或信用管制＝調整。上一次不可考時，有動作只能叫「變動」，
    不能冒稱轉向或調整。"""
    if prev_action is None:
        if action != "hold":
            return "變動"
        return "調整" if change else "不變"
    if action != prev_action:
        return "轉向"
    if action != "hold" or change:
        return "調整"
    return "不變"


def _built_note(now: datetime) -> str:
    return f"本頁建置於台北 {now:%H:%M}，公布後要等下一次建置才會更新。"


def _at(state: dict, fallback: datetime) -> datetime:
    try:
        return datetime.fromisoformat(state["at"]).astimezone(TAIPEI)
    except (KeyError, TypeError, ValueError):
        return fallback


def _pending(name: str, state: dict, at: datetime, now: datetime, href: str,
             official: str) -> dict:
    today = now.date()
    if state.get("overdue"):
        return {
            "kind": "policy", "policy": "待公布", "today": True, "sev": "high",
            "tag": f"{name}　公布時間已過",
            "title": f"{name}決議應已在台北 {at.month}/{at.day} {at:%H:%M} 公布，本站尚未取得",
            "detail": f"請先看官方公告（{official}）。{_built_note(now)}",
            "href": href, "at": at,
        }
    when = "今晚公布" if at.date() == today and at.hour >= 18 else f"台北 {at.month}/{at.day} {at:%H:%M} 公布"
    return {
        "kind": "policy", "policy": "待公布", "today": at.date() in (today, today + timedelta(days=1)),
        "sev": "medium", "tag": f"{name}　{when}", "title": f"{name}利率決議",
        "detail": _built_note(now), "href": href, "at": at,
    }


def _missing(name: str, state: dict, href: str) -> dict:
    meeting = date.fromisoformat(state["meeting"])
    return {
        "kind": "policy", "policy": "遺漏", "today": True, "sev": "high",
        "tag": f"{name}　決議遺漏",
        "title": f"{meeting.month}/{meeting.day} {name}決議本站沒有取得",
        "detail": f"{state['reason']}。利率可能仍是舊值，請以官方公告為準。",
        "href": href, "at": datetime.combine(meeting, time(0, 0), tzinfo=TAIPEI),
    }


def policy_events(fomc, cbc, now: datetime) -> list[dict]:
    today = now.date()
    out = []

    for state in _states(fomc):
        kind = state.get("state")
        if kind == "announced":
            fallback = datetime.combine(date.fromisoformat(state["date"]), time(14, 0),
                                        tzinfo=NEW_YORK).astimezone(TAIPEI)
            at = _at(state, fallback)
            policy = _policy_kind(state["action"], state.get("prev_action"),
                                  state["action"] != "hold")
            vote = f"，表決 {state['vote']}" if state.get("vote") else ""
            effective = "" if state["action"] == "hold" else f"；新利率 {state['effective']} 生效"
            out.append({
                "kind": "policy", "region": "美國", "policy": policy,
                "today": at.date() == today, "sev": "high" if policy != "不變" else "medium",
                "tag": f"FOMC　政策{policy}", "title": state["headline"],
                "detail": f"台北 {at.month}/{at.day} {at:%H:%M} 公布{vote}{effective}。",
                "href": "/fed/#statement", "at": at,
            })
        elif kind == "pending":
            fallback = datetime.combine(date.fromisoformat(state["meeting"]), time(14, 0),
                                        tzinfo=NEW_YORK).astimezone(TAIPEI)
            out.append({**_pending("FOMC", state, _at(state, fallback), now, "/fed/",
                                   "federalreserve.gov"), "region": "美國"})
        elif kind == "missing":
            out.append({**_missing("FOMC", state,
                                   "https://www.federalreserve.gov/newsevents/pressreleases.htm"),
                        "region": "美國"})

    for state in _states(cbc):
        kind = state.get("state")
        if kind == "announced":
            announced = date.fromisoformat(state["date"])
            policy = _policy_kind(state["rate"]["action"], state.get("prev_action"), state["change"])
            extra = "；".join(state.get("details") or [])
            out.append({
                "kind": "policy", "region": "台灣", "policy": policy,
                "today": announced == today, "sev": "high" if policy != "不變" else "medium",
                "tag": f"台灣央行　政策{policy}", "title": state["headline"],
                "detail": (f"{announced.month}/{announced.day} 理監事會決議"
                           + (f"：{extra}" if extra else "") + "。"),
                "href": "/taiwan/#money",
                "at": datetime.combine(announced, time(16, 30), tzinfo=TAIPEI),
            })
        elif kind == "pending":
            fallback = datetime.combine(date.fromisoformat(state["meeting"]), time(16, 30),
                                        tzinfo=TAIPEI)
            out.append({**_pending("台灣央行", state, _at(state, fallback), now,
                                   "/taiwan/#money", "cbc.gov.tw"), "region": "台灣"})
        elif kind == "missing":
            out.append({**_missing("台灣央行", state, "https://www.cbc.gov.tw/tw/lp-302-1.html"),
                        "region": "台灣"})
    return out


def us_data_events(freshness: dict, now: datetime) -> list[dict]:
    """美國 13 項主要發布：台北今天或昨天公布的，以及台北今天要公布的。"""
    today = now.date()
    out = []
    for row in freshness.get("rows") or []:
        if row.get("frequency") == "d":
            continue
        et = RELEASE_TIMES.get(row.get("id"), DEFAULT_RELEASE)

        updated = row.get("updated")
        if updated is not None:
            local_ny = updated.astimezone(NEW_YORK) if updated.tzinfo else updated.replace(tzinfo=NEW_YORK)
            released = datetime.combine(local_ny.date(), et, tzinfo=NEW_YORK)
            released = min(released, local_ny).astimezone(TAIPEI)
            if released.date() in (today, today - timedelta(days=1)):
                out.append({
                    "kind": "data", "region": "美國", "today": released.date() == today,
                    "sev": "medium", "tag": "美國數據　已公布", "title": row["name"],
                    "detail": f"台北 {released.month}/{released.day} {released:%H:%M} 公布。",
                    "href": "/freshness/", "at": released,
                })
                continue

        scheduled = row.get("next_release")
        if not scheduled:
            continue
        at = datetime.combine(scheduled, et, tzinfo=NEW_YORK).astimezone(TAIPEI)
        if at.date() != today:
            continue
        if now < at:
            tag = "美國數據　今晚公布" if at.hour >= 18 else f"美國數據　{at:%H:%M} 公布"
            detail = f"約台北 {at:%H:%M}。"
        else:
            tag = "美國數據　公布時間已過"
            detail = f"台北 {at:%H:%M} 應已公布，本站資料尚未更新。"
        out.append({"kind": "data", "region": "美國", "today": True, "sev": "medium",
                    "tag": tag, "title": row["name"], "detail": detail,
                    "href": "/freshness/", "at": at})
    return out


def taiwan_data_events(releases: list[dict], now: datetime) -> list[dict]:
    today = now.date()
    out, seen = [], set()
    for item in sorted(releases, key=lambda i: (i["date"], i.get("time") or time(0))):
        label = item.get("label")
        if not label or item["date"] not in (today, today - timedelta(days=1)):
            continue
        if (label, item["date"]) in seen:
            continue
        seen.add((label, item["date"]))
        at = datetime.combine(item["date"], item.get("time") or time(16, 0), tzinfo=TAIPEI)
        done = at <= now
        out.append({
            "kind": "data", "region": "台灣", "today": item["date"] == today, "sev": "medium",
            "tag": "台灣數據　" + ("已公布" if done else f"{at:%H:%M} 公布"),
            "title": label,
            "detail": f"{item['dept']}，資料期 {item['period']}。" if item.get("period") else item["dept"],
            "href": "/taiwan/", "at": at,
        })
    return out


def verdict(events: list[dict], *, us_ok: bool = True, tw_ok: bool = True) -> str:
    today_events = [e for e in events if e["today"]]
    count = lambda policy: sum(1 for e in today_events if e.get("policy") == policy)
    data = sum(1 for e in today_events if e["kind"] == "data")

    bits = []
    for policy, label in (("遺漏", "決議遺漏"), ("轉向", "政策轉向"), ("變動", "政策變動"),
                          ("調整", "政策調整"), ("不變", "政策決議（不變）"),
                          ("待公布", "待公布決議")):
        if count(policy):
            bits.append(f"{label} {count(policy)} 項")
    if data:
        bits.append(f"重大數據 {data} 項")

    failed = [name for name, ok in (("美國發布行事曆", us_ok), ("台灣統計發布看板", tw_ok)) if not ok]
    caveat = f"（{'與'.join(failed)}這一輪沒有取得，可能漏列）" if failed else ""
    if not bits:
        if failed:
            return f"今天沒有偵測到重大數據或政策決議{caveat}。"
        return "今天沒有重大數據或政策決議。"
    return "今天有" + "、".join(bits) + caveat + "。"


def build(fomc, cbc, freshness: dict, tw_releases: list[dict], now: datetime,
          *, tw_ok: bool | None = None) -> dict:
    events = policy_events(fomc, cbc, now)
    events += us_data_events(freshness, now)
    events += taiwan_data_events(tw_releases, now)
    events.sort(key=lambda e: (
        e.get("policy") != "遺漏", not e["today"], e["kind"] != "policy",
        POLICY_ORDER.get(e.get("policy"), 9), e["at"]))
    us_ok = not freshness.get("calendar_failed")
    tw_ok = bool(tw_releases) if tw_ok is None else tw_ok
    return {
        "date": now.date(), "weekday": WEEKDAYS[now.weekday()],
        "verdict": verdict(events, us_ok=us_ok, tw_ok=tw_ok),
        "events": events,
        "calendar_ok": tw_ok, "us_calendar_ok": us_ok,
        "us_calendar_failed": list(freshness.get("calendar_failed") or []),
    }


def compute(ctx: dict) -> dict:
    return build(ctx.get("fomc"), ctx.get("cbc"), ctx.get("freshness") or {},
                 twcal.releases(), clock.now())
