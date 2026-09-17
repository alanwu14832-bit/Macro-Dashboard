"""今天：重大數據與政策決議。

總覽最上面要能一眼回答「今天有沒有重大數據或政策轉向」。這裡把四條線收成
一份清單，全部是機構正式發布的事實，不放本站規則的判定（那在「自上次以來」）：

  政策  FOMC 決議（macro/fomc.py）、台灣央行理監事會（macro/cbc_board.py）
  數據  美國 13 項主要發布（compute/freshness.py 的 TRACKED）、
        台灣 7 項主要統計（sources/twcal.py 的 MAJOR）

「今天」一律是台北的今天。美東早上 8:30 的發布是台北當天晚上；FOMC 美東
14:00 的聲明是台北隔天凌晨——所以台北早上打開，凌晨的決議算今天。

會後一週內的決議即使不是今天，也列在「本週稍早」：幾天沒打開網站的人，
不能因為那天剛好沒看就錯過一次升息。決議遺漏則永遠置頂。
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

from .. import clock
from ..clock import NEW_YORK, TAIPEI
from ..sources import twcal

WEEKDAYS = "一二三四五六日"


def _fomc_announced_at(day: str) -> datetime:
    return datetime.combine(date.fromisoformat(day), time(14, 0),
                            tzinfo=NEW_YORK).astimezone(TAIPEI)


def _policy_kind(action: str, prev_action: str | None, change: bool) -> str:
    """轉向＝這次的動作跟上一次會議不同（維持→升息、升息→降息、升息→維持）。
    利率沒動但調了準備率或信用管制＝調整。都沒有＝不變。"""
    if prev_action is not None and action != prev_action:
        return "轉向"
    if action != "hold" or change:
        return "調整"
    return "不變"


def policy_events(fomc: dict | None, cbc: dict | None, now: datetime) -> list[dict]:
    today = now.date()
    out = []

    if fomc and fomc.get("state") == "announced":
        at = _fomc_announced_at(fomc["date"])
        kind = _policy_kind(fomc["action"], fomc.get("prev_action"), fomc["action"] != "hold")
        vote = f"，表決 {fomc['vote']}" if fomc.get("vote") else ""
        out.append({
            "kind": "policy", "region": "美國", "policy": kind,
            "today": at.date() == today, "sev": "high" if kind != "不變" else "medium",
            "tag": f"FOMC　政策{kind}", "title": fomc["headline"],
            "detail": (f"台北 {at.month}/{at.day} {at:%H:%M} 公布{vote}；"
                       f"新利率 {fomc['effective']} 生效。"),
            "href": "/fed/#statement", "at": at,
        })
    elif fomc and fomc.get("state") == "pending":
        at = _fomc_announced_at(fomc["meeting"])
        out.append({
            "kind": "policy", "region": "美國", "policy": "待公布",
            "today": at.date() == today or at.date() == today + timedelta(days=1),
            "sev": "medium", "tag": "FOMC　今晚公布",
            "title": f"FOMC 利率決議，台北 {at.month}/{at.day} {at:%H:%M} 公布",
            "detail": "聲明發布後本站最慢一小時內更新。", "href": "/fed/", "at": at,
        })
    elif fomc and fomc.get("state") == "missing":
        out.append(_missing("美國", "FOMC", fomc, "https://www.federalreserve.gov/newsevents/pressreleases.htm"))

    if cbc and cbc.get("state") == "announced":
        kind = _policy_kind(cbc["rate"]["action"], cbc.get("prev_action"), cbc["change"])
        announced = date.fromisoformat(cbc["date"])
        extra = "；".join(cbc.get("details") or [])
        out.append({
            "kind": "policy", "region": "台灣", "policy": kind,
            "today": announced == today, "sev": "high" if kind != "不變" else "medium",
            "tag": f"台灣央行　政策{kind}", "title": cbc["headline"],
            "detail": (f"{announced.month}/{announced.day} 理監事會決議" + (f"：{extra}" if extra else "") + "。"),
            "href": "/taiwan/#money",
            "at": datetime.combine(announced, time(16, 30), tzinfo=TAIPEI),
        })
    elif cbc and cbc.get("state") == "pending":
        meeting = date.fromisoformat(cbc["meeting"])
        out.append({
            "kind": "policy", "region": "台灣", "policy": "待公布", "today": meeting == today,
            "sev": "medium", "tag": "台灣央行　今天公布",
            "title": "台灣央行理監事會，約 16:30 公布決議",
            "detail": "決議新聞稿上線後本站最慢一小時內更新。", "href": "/taiwan/#money",
            "at": datetime.combine(meeting, time(16, 30), tzinfo=TAIPEI),
        })
    elif cbc and cbc.get("state") == "missing":
        out.append(_missing("台灣", "台灣央行", cbc, "https://www.cbc.gov.tw/tw/lp-302-1.html"))

    return out


def _missing(region: str, name: str, state: dict, href: str) -> dict:
    meeting = date.fromisoformat(state["meeting"])
    return {
        "kind": "policy", "region": region, "policy": "遺漏", "today": True, "sev": "high",
        "tag": f"{name}　決議遺漏",
        "title": f"{meeting.month}/{meeting.day} {name}決議本站沒有取得",
        "detail": f"{state['reason']}。利率可能仍是舊值，請以官方公告為準。",
        "href": href, "at": datetime.combine(meeting, time(0, 0), tzinfo=TAIPEI),
    }


def us_data_events(freshness: dict, now: datetime) -> list[dict]:
    """美國 13 項主要發布：台北今天或昨天公布的，以及台北今晚要公布的。"""
    today = now.date()
    out = []
    for row in freshness.get("rows") or []:
        if row.get("frequency") == "d":
            continue
        updated = row.get("updated")
        if updated is not None:
            local = updated.astimezone(TAIPEI) if updated.tzinfo else updated
            if local.date() in (today, today - timedelta(days=1)):
                out.append({
                    "kind": "data", "region": "美國", "today": local.date() == today,
                    "sev": "medium", "tag": "美國數據　已公布", "title": row["name"],
                    "detail": f"台北 {local.month}/{local.day} {local:%H:%M} 公布。",
                    "href": "/freshness/", "at": local,
                })
                continue
        if row.get("next_release") == today:
            out.append({
                "kind": "data", "region": "美國", "today": True, "sev": "medium",
                "tag": "美國數據　今晚公布", "title": row["name"],
                "detail": "約台北 20:30。",
                "href": "/freshness/",
                "at": datetime.combine(today, time(20, 30), tzinfo=TAIPEI),
            })
    return out


def taiwan_data_events(releases: list[dict], now: datetime) -> list[dict]:
    today = now.date()
    out = []
    for item in releases:
        if not item.get("label") or item["date"] not in (today, today - timedelta(days=1)):
            continue
        at = datetime.combine(item["date"], item["time"] or time(16, 0), tzinfo=TAIPEI)
        done = at <= now
        out.append({
            "kind": "data", "region": "台灣", "today": item["date"] == today, "sev": "medium",
            "tag": "台灣數據　" + ("已公布" if done else f"{at:%H:%M} 公布"),
            "title": item["label"],
            "detail": f"{item['dept']}，資料期 {item['period']}。" if item.get("period") else item["dept"],
            "href": "/taiwan/", "at": at,
        })
    return out


def verdict(events: list[dict], now: datetime) -> str:
    today_events = [e for e in events if e["today"]]
    missing = [e for e in events if e.get("policy") == "遺漏"]
    turns = [e for e in today_events if e.get("policy") == "轉向"]
    adjusts = [e for e in today_events if e.get("policy") == "調整"]
    holds = [e for e in today_events if e.get("policy") == "不變"]
    pending = [e for e in today_events if e.get("policy") == "待公布"]
    data = [e for e in today_events if e["kind"] == "data"]

    bits = []
    if missing:
        bits.append(f"決議遺漏 {len(missing)} 項")
    if turns:
        bits.append(f"政策轉向 {len(turns)} 項")
    if adjusts:
        bits.append(f"政策調整 {len(adjusts)} 項")
    if holds:
        bits.append(f"政策決議（不變）{len(holds)} 項")
    if pending:
        bits.append(f"待公布決議 {len(pending)} 項")
    if data:
        bits.append(f"重大數據 {len(data)} 項")
    if not bits:
        return "今天沒有重大數據或政策決議。"
    return "今天有" + "、".join(bits) + "。"


def build(fomc: dict | None, cbc: dict | None, freshness: dict,
          tw_releases: list[dict], now: datetime) -> dict:
    events = policy_events(fomc, cbc, now)
    events += us_data_events(freshness, now)
    events += taiwan_data_events(tw_releases, now)
    order = {"遺漏": 0, "轉向": 1, "調整": 2, "待公布": 3, "不變": 4}
    events.sort(key=lambda e: (
        e.get("policy") != "遺漏", not e["today"], e["kind"] != "policy",
        order.get(e.get("policy"), 5), e["at"]))
    return {
        "date": now.date(), "weekday": WEEKDAYS[now.weekday()],
        "verdict": verdict(events, now),
        "events": events,
        "calendar_ok": bool(tw_releases),
    }


def compute(ctx: dict) -> dict:
    return build(ctx.get("fomc"), ctx.get("cbc"), ctx.get("freshness") or {},
                 twcal.releases(), clock.now())
