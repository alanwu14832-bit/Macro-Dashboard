#!/usr/bin/env python3
"""發布守候——公布時間到了就盯著 FRED，新數字一登出就觸發建置。

    python3 tools/release_watch.py          # 守候（.github/workflows/release-watch.yml 跑的就是這個）
    python3 tools/release_watch.py --plan   # 只印出接下來要等哪幾項、現在各是什麼狀態，不等也不觸發

為什麼需要它：GitHub 對公開 repo 的排程只是 best-effort，每小時的建置實際上 2–10 小時
才跑一次。2026-11-10 的 CPI 公布後，第一次建置比 FRED 登出早了五分鐘，下一次是兩個半
小時以後。這支腳本提早幾個小時啟動，用專案自己的行事曆（compute/due.py，跟建置同一份）
看接下來有沒有追蹤的發布：

  沒有   → 立刻結束。
  有     → 等到公布時間，每分鐘向 FRED 問一次那幾檔的最新資料日期（跟建置抓的是同一個
           網址）；比 main 上 data/series_dates.json 記的新，就等同一份發布的其他序列
           到齊，再用 GITHUB_TOKEN 觸發 build.yml 的 workflow_dispatch，然後看著它提交。
  沒等到 → 公布後 180 分鐘 FRED 的資料日期還是沒有往前，結束並在紀錄裡講明。

同一次公布只觸發一次：觸發之後那幾檔不再看；站上已經跟上（別的建置帶上去的）就不觸發。
守候自己被 GitHub 延後到公布之後才啟動時，第一輪就直接比對，落後就觸發。

它不碰 site/、不提交任何東西——搶推的問題不存在；建置照舊在 build.yml 的並行群組裡排隊。
時間上限：一個 job 最多 6 小時，所以跑滿 5 小時而事情還沒完時，它觸發自己接力再結束。

BLS 探針（只記錄，不改網站、不影響觸發）：CPI、PPI、非農、JOLTS 是勞工統計局發的，FRED
要晚 10–133 分鐘才登出。守候在這幾項公布之後順便問幾次 BLS 自己的 API，把「BLS 幾點有、
FRED 幾點有」寫在這一次執行的註記裡——用來決定值不值得改成直接讀 BLS。見 BlsProbe。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from macro import catalogue, clock  # noqa: E402
from macro.compute import due  # noqa: E402
from macro.sources import fred  # noqa: E402

# 往後看多遠：排程實測會被延後 3–6 小時，所以要夠早就開始等。
LOOKAHEAD = timedelta(hours=8)
# 往回看多遠：守候被延後到公布之後才啟動時，站上還沒跟上的那幾項要直接比對。
LOOKBACK = timedelta(hours=24)
# 公布後等 FRED 多久。實測 FRED 比公布時間晚 4–133 分鐘（初領失業金 4、CPI 42、
# PPI 110、非農 133），90 分鐘會等不到非農與 PPI。
FRED_TIMEOUT = timedelta(minutes=180)
POLL = 60                 # 公布時間過了之後，每幾秒問一次 FRED
# 看到第一檔之後等幾秒再觸發：FRED 一份發布分批登出（CPI 前後 88 秒、就業報告 157 秒）。
SETTLE = 180
LAND_TIMEOUT = timedelta(minutes=20)   # 觸發之後等建置提交多久
LAND_POLL = 30
BUDGET = timedelta(hours=5)            # 一個 job 跑多久就交棒（GitHub 的上限是 6 小時）
IDLE_NAP = 300                         # 公布時間還沒到時一次睡多久（醒來檢查要不要交棒）
MAX_DISPATCH_FAILURES = 3
HANDOFF_MARK = "接力"                  # release-watch.yml 的 run-name 裡標記接力的那個詞
WORKFLOW = "release-watch.yml"

# BLS 探針。免金鑰的 API v1：每個 IP 一天 25 次查詢、一次最多 25 檔——所以不能像 FRED 那樣
# 每分鐘問，一次公布最多問 12 次，同一個時刻的幾檔併成一次查詢。
BLS_API = "https://api.bls.gov/publicAPI/v1/timeseries/data/"
# 追蹤的序列裡 BLS 發的那幾檔：FRED 代號 → BLS 代號（2026-11-10 逐檔比對過，數值相同）。
BLS_IDS = {"CPIAUCSL": "CUSR0000SA0", "PAYEMS": "CES0000000001", "UNRATE": "LNS14000000",
           "PPIFIS": "WPSFD4", "JTSJOL": "JTS000000000000000JOL"}
# 公布後第幾分鐘問：前十分鐘密、之後疏——要量的是「公布那一刻就有」還是「晚很久」。
BLS_ASK_AT = (0, 2, 4, 6, 8, 10, 15, 20, 30, 45, 60, 90)
BLS_MAX_FAILURES = 3                   # 連續幾次問不到就不再問（被擋、額度用完）


# ------------------------------------------------------------------ 判斷（不連網）--

def plan(now: datetime, calendar: dict, state: dict) -> list[dict]:
    """要守候的發布，按公布時刻排：[{"at": 時刻, "series": [(序列, 名稱), ...]}]。

    接下來 LOOKAHEAD 之內要公布的，加上 LOOKBACK 之內已經公布、站上還沒跟上的。
    同一個時刻公布的幾項（非農與失業率、PPI 與零售銷售）併成一筆。
    """
    slots: dict[datetime, list[tuple[str, str]]] = {}
    for series_id, label, release_id in due.tracked():
        for day in calendar.get(release_id) or []:
            at = due.release_at(series_id, day)
            if not now - LOOKBACK <= at <= now + LOOKAHEAD:
                continue
            if at <= now and due.landed(state.get(series_id), at):
                continue
            slots.setdefault(at, []).append((series_id, label))
    return [{"at": at, "series": slots[at]} for at in sorted(slots)]


def is_ahead(fred_date: str | None, entry: dict | None) -> bool:
    """FRED 的最新資料日期是不是比站上記的新。任一邊不知道＝不算——不猜。"""
    have = (entry or {}).get("date")
    return bool(fred_date and have and fred_date > have)


def open_ids(item: dict, state: dict, fired: set[str]) -> list[str]:
    """這一筆裡還要看的序列：沒觸發過、站上也還沒跟上的。"""
    return [series_id for series_id, _label in item["series"]
            if series_id not in fired and not due.landed(state.get(series_id), item["at"])]


def verdict(item: dict, now: datetime, fred_dates: dict, state: dict,
            fired: set[str]) -> tuple[str, list[str]]:
    """這一筆現在該做什麼，以及是哪幾檔。

    wait     公布時間還沒到
    done     每一檔都處理完了（站上跟上了，或已經觸發過）
    trigger  FRED 的資料日期比站上的新——觸發建置
    timeout  公布後超過 FRED_TIMEOUT，FRED 還是沒有新的一期
    poll     公布時間已過、FRED 還沒登出——繼續問
    """
    if now < item["at"]:
        return "wait", []
    remaining = open_ids(item, state, fired)
    if not remaining:
        return "done", []
    ahead = [sid for sid in remaining if is_ahead(fred_dates.get(sid), state.get(sid))]
    if ahead:
        return "trigger", ahead
    if now > item["at"] + FRED_TIMEOUT:
        return "timeout", remaining
    return "poll", remaining


def should_yield(runs: list[dict], my_id: int | None, successor: bool) -> bool:
    """已經有別的守候在跑，這一支就讓。接力的那一支不讓——它就是來接手的。

    兩支同時啟動時讓給比較早的（編號小的）；看到接力的那一支一律讓。
    """
    if successor or my_id is None:
        return False
    for run in runs:
        if run.get("id") == my_id or run.get("status") == "completed":
            continue
        if run.get("id", my_id) < my_id or HANDOFF_MARK in (run.get("display_title") or ""):
            return True
    return False


def _names(item: dict, ids: list[str] | None = None) -> str:
    return "、".join(label for series_id, label in item["series"]
                    if ids is None or series_id in ids)


def _minutes(delta: timedelta) -> int:
    return round(delta.total_seconds() / 60)


def _taipei(at: datetime) -> str:
    return f"台北 {at.astimezone(clock.TAIPEI):%m/%d %H:%M}"


# ------------------------------------------------------------------ BLS 探針 ----

def bls_latest(payload: dict) -> dict[str, str]:
    """BLS API 的回應 → {BLS 代號: 最新一期 "YYYY-MM-01"}。

    沒被受理（額度用完時 status 是 REQUEST_NOT_PROCESSED）就丟例外——那不是「沒有新的一期」。
    M13 是年平均，不是月份。
    """
    if payload.get("status") != "REQUEST_SUCCEEDED":
        reason = "；".join(str(m) for m in payload.get("message") or [])
        raise RuntimeError(f"{payload.get('status')}：{reason[:160]}")
    out: dict[str, str] = {}
    for series in (payload.get("Results") or {}).get("series") or []:
        months = [f"{row['year']}-{row['period'][1:]}-01" for row in series.get("data") or []
                  if str(row.get("period", ""))[:1] == "M" and row["period"] != "M13"]
        if months:
            out[series["seriesID"]] = max(months)
    return out


def bls_next_ask(elapsed_minutes: float) -> int | None:
    """問過之後，下一次是公布後第幾分鐘。排完了＝None。"""
    return next((minute for minute in BLS_ASK_AT if minute > elapsed_minutes), None)


class BlsProbe:
    """公布之後問 BLS API 幾次，記下它幾點有新的一期。只記錄：不觸發建置、不改任何資料，
    自己出什麼錯都不影響守候。結果寫成 ::notice::，在那一次執行的頁面上看得到。"""

    def __init__(self) -> None:
        self.slots: dict[datetime, dict] = {}

    def ask(self, io, item: dict, now: datetime, state: dict) -> None:
        try:
            self._ask(io, item, now, state)
        except Exception as exc:
            io.log(f"BLS 探針出錯（{type(exc).__name__}：{exc}），不影響守候")

    def _ask(self, io, item: dict, now: datetime, state: dict) -> None:
        at = item["at"]
        slot = self.slots.get(at)
        if slot is None:
            # 比的是第一次看到這一筆時站上的資料日期——之後站上跟上了，基準也不跟著動
            base = {sid: state[sid]["date"] for sid in open_ids(item, state, set())
                    if sid in BLS_IDS and (state.get(sid) or {}).get("date")}
            slot = self.slots[at] = {"base": base, "have": {}, "asks": 0, "failures": 0,
                                     "next": 0, "miss": None, "found": None,
                                     "closed": not base, "compared": False}
        if slot["closed"] or now < at + timedelta(minutes=slot["next"]):
            return
        elapsed = _minutes(now - at)
        left = sorted(set(slot["base"]) - set(slot["have"]))
        slot["asks"] += 1
        upcoming = bls_next_ask((now - at).total_seconds() / 60)
        try:
            dates = io.bls_dates(left)
        except Exception as exc:
            slot["failures"] += 1
            io.log(f"BLS 探針：公布後 {elapsed} 分鐘第 {slot['asks']} 次問，沒有問到"
                   f"（{type(exc).__name__}：{exc}）")
            if slot["failures"] >= BLS_MAX_FAILURES:
                slot["closed"] = True
                io.log(f"::notice title=BLS 探針::{_names(item, left)}：連續 {slot['failures']} 次"
                       f"問不到 BLS API（最後一次：{type(exc).__name__}：{exc}）——從這裡用不了，不再問")
                return
        else:
            slot["failures"] = 0
            fresh = {sid: dates[sid] for sid in left
                     if dates.get(sid) and dates[sid] > slot["base"][sid]}
            slot["have"].update(fresh)
            if fresh and len(slot["have"]) == len(slot["base"]):
                slot["closed"], slot["found"], slot["exact"] = True, elapsed, slot["miss"] is not None
                before = (f"上一次問是公布後 {slot['miss']} 分鐘、還沒有" if slot["miss"] is not None
                          else "這是第一次問到，只知道不晚於這個時間")
                io.log(f"::notice title=BLS 探針::BLS API 有新的一期了："
                       f"{_names(item, list(slot['base']))}（{max(slot['have'].values())[:7]}），"
                       f"公布後 {elapsed} 分鐘問到；{before}")
                return
            slot["miss"] = elapsed
            got = f"；{_names(item, list(fresh))}先到" if fresh else ""
            io.log(f"BLS 探針：公布後 {elapsed} 分鐘第 {slot['asks']} 次問，"
                   f"{_names(item, sorted(set(left) - set(fresh)))} 還沒有新的一期{got}")
        if upcoming is None:
            slot["closed"] = True
            io.log(f"::notice title=BLS 探針::{_names(item, left)}：問了 {slot['asks']} 次、"
                   f"到公布後 {elapsed} 分鐘，BLS API 仍沒有新的一期——不再問")
        else:
            slot["next"] = upcoming

    def fred_seen(self, io, item: dict, now: datetime) -> None:
        """FRED 登出的那一刻，把兩邊的時間並排寫下來（一次公布只寫一次）。"""
        slot = self.slots.get(item["at"])
        if not slot or not slot["base"] or slot["compared"]:
            return
        slot["compared"] = True
        fred = _minutes(now - item["at"])
        names = _names(item, list(slot["base"]))
        if slot["found"] is not None:
            # 第一次問就有的，BLS 實際可能更早——差距只能說「至少」
            gap = max(0, fred - slot["found"])
            gain = (f"直讀 BLS 可以早約 {gap} 分鐘" if slot["exact"]
                    else f"直讀 BLS 至少早 {gap} 分鐘" if gap
                    else "守候啟動時兩邊都已經有了，這一次量不出差距")
            io.log(f"::notice title=BLS 探針::{names}：BLS API 公布後 {slot['found']} 分鐘問到，"
                   f"FRED 公布後 {fred} 分鐘——{gain}")
        elif slot["miss"] is not None:
            slot["closed"] = True
            io.log(f"::notice title=BLS 探針::{names}：FRED 公布後 {fred} 分鐘先有了；BLS API 到"
                   f"公布後 {slot['miss']} 分鐘（問了 {slot['asks']} 次）還沒有——直讀沒有比較快")
        else:
            io.log(f"::notice title=BLS 探針::{names}：FRED 公布後 {fred} 分鐘有了，"
                   f"BLS API 這一次沒有量到（問了 {slot['asks']} 次，都沒有問到）")


# ------------------------------------------------------------------ 流程 --------

def trigger(io, item: dict, ahead: list[str]) -> bool:
    """等到齊、再確認一次、觸發、看著它提交。回傳 False＝觸發失敗（下一輪再試）。"""
    at, names = item["at"], _names(item, ahead)
    seen = io.now()
    io.log(f"FRED 有新的一期了：{names}（公布後 {_minutes(seen - at)} 分鐘看到）。"
           f"等 {SETTLE} 秒讓同一份發布的其他序列到齊")
    io.sleep(SETTLE)
    state = io.state()
    if all(due.landed(state.get(sid), at) for sid in ahead):
        io.log(f"{names}：這段時間已經有別的建置帶上站，不另外觸發")
        return True
    try:
        io.dispatch_build()
    except Exception as exc:
        io.log(f"::error title=發布守候::觸發建置失敗：{exc}")
        return False
    io.log("已觸發 build.yml（workflow_dispatch）")
    deadline = io.now() + LAND_TIMEOUT
    while io.now() < deadline:
        io.sleep(LAND_POLL)
        state = io.state()
        if all(due.landed(state.get(sid), at) for sid in ahead):
            done = io.now()
            io.log(f"上站了：{names} 在公布後 {_minutes(done - at)} 分鐘、守候看到 FRED 有新數字後 "
                   f"{_minutes(done - seen)} 分鐘提交到 main（Vercel 部署另需約一分鐘）")
            return True
    io.log(f"::warning title=發布守候::已觸發建置，但 {_minutes(LAND_TIMEOUT)} 分鐘內沒有看到 "
           f"{names} 提交到 main——請看 build.yml 那一次的紀錄。不重複觸發；"
           f"下一次建置會繞過快取重抓")
    return True


def run(io, *, budget: timedelta = BUDGET) -> str:
    """守候到沒有事情可等為止。回傳 idle（本來就沒事）、done、handoff（時間到，要接力）、
    blind（行事曆抓不到，不知道有沒有事）。"""
    started = io.now()
    calendar = io.calendar()
    blind = sorted(release_id for release_id, days in calendar.items() if days is None)
    if blind and len(blind) == len(calendar):
        # 沒偵測到，不是沒有：整份行事曆都抓不到（金鑰、限流）時不能說「沒有發布」
        io.log("::error title=發布守候::FRED 的發布行事曆整份抓不到，不知道接下來有沒有發布"
               "——這一支沒有在守候")
        return "blind"
    if blind:
        io.log(f"::warning title=發布守候::發布行事曆有 {len(blind)} 份抓不到"
               f"（發布編號 {'、'.join(map(str, blind))}），那幾份這一支看不到")
    items = plan(started, calendar, io.state())
    if not items:
        io.log(f"接下來 {_minutes(LOOKAHEAD) // 60} 小時沒有追蹤的發布，"
               f"過去 {_minutes(LOOKBACK) // 60} 小時公布的也都上站了——結束")
        return "idle"
    for item in items:
        io.log(f"守候：{_names(item)}（{_taipei(item['at'])}，美東 {item['at']:%H:%M}）")

    fired: set[str] = set()
    asking: set[datetime] = set()
    failures = 0
    probe = BlsProbe()
    while True:
        now = io.now()
        state = None
        for item in list(items):
            if item["at"] > now:
                continue
            if state is None:
                state = io.state()
            probe.ask(io, item, now, state)
            fred_dates = {sid: io.fred_date(sid) for sid in open_ids(item, state, fired)}
            what, ids = verdict(item, now, fred_dates, state, fired)
            if what == "trigger":
                probe.fred_seen(io, item, now)
                if trigger(io, item, ids):
                    fired.update(ids)
                else:
                    failures += 1
                    if failures >= MAX_DISPATCH_FAILURES:
                        io.log(f"::error title=發布守候::觸發建置連續失敗 {failures} 次，"
                               f"不再試：{_names(item, ids)} 等下一次排程建置")
                        fired.update(ids)
                state = None            # 觸發之後 main 變了，下一筆重新讀
            elif what == "timeout":
                io.log(f"::warning title=發布守候::沒等到：{_names(item, ids)} 公布後已超過 "
                       f"{_minutes(FRED_TIMEOUT)} 分鐘，FRED 的資料日期沒有往前（只修正舊值、"
                       f"沒有新的一期時也會這樣）。不觸發；之後的建置三天內仍會繞過快取重抓")
                items.remove(item)
            elif what == "done":
                if not any(sid in fired for sid, _label in item["series"]):
                    io.log(f"{_names(item)}：站上已經跟上，不用觸發")
                items.remove(item)
            elif item["at"] not in asking:
                asking.add(item["at"])
                io.log(f"{_names(item, ids)}：公布時間已過，FRED 還沒有新的一期——每 {POLL} 秒問一次，"
                       f"最多等到公布後 {_minutes(FRED_TIMEOUT)} 分鐘")
        if not items:
            io.log("沒有要等的了——結束")
            return "done"
        now = io.now()
        if now - started > budget:
            return "handoff"
        upcoming = min(item["at"] for item in items)
        io.sleep(POLL if upcoming <= now
                 else max(1.0, min((upcoming - now).total_seconds(), IDLE_NAP)))


# ------------------------------------------------------------------ 連網的那一半 --

class Live:
    """真的時鐘、真的 FRED、真的 GitHub。測試用另一個同形狀的假物件。"""

    def __init__(self) -> None:
        self.repo = os.environ.get("GITHUB_REPOSITORY", "")
        self.token = os.environ.get("GITHUB_TOKEN", "")
        run_id = os.environ.get("GITHUB_RUN_ID", "")
        self.run_id = int(run_id) if run_id.isdigit() else None
        self._state: dict = {}
        self._specs: dict = {}
        for group in catalogue.ALL_GROUPS.values():
            self._specs.update(group)

    def now(self) -> datetime:
        return clock.us_now()

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)

    def log(self, message: str) -> None:
        # ::error:: 與 ::warning:: 要在行首，Actions 才會標記
        stamp = f"[{clock.now():%m-%d %H:%M:%S} 台北] "
        print(message if message.startswith("::") else stamp + message, flush=True)

    def calendar(self) -> dict:
        return due.calendar()

    def state(self) -> dict:
        """main 上現在的 data/series_dates.json。讀不到就沿用上一次讀到的。"""
        fetch = ["git", "fetch", "--quiet", "origin", "main"]
        if os.environ.get("GITHUB_ACTIONS"):
            fetch.insert(2, "--depth=1")    # 只在 runner 的淺層 checkout 用；本機的完整 clone 不能截短
        try:
            subprocess.run(fetch, cwd=ROOT, check=True, capture_output=True, timeout=120)
            shown = subprocess.run(["git", "show", "FETCH_HEAD:data/series_dates.json"],
                                   cwd=ROOT, check=True, capture_output=True, timeout=60)
            self._state = json.loads(shown.stdout.decode("utf-8"))
        except Exception as exc:
            self.log(f"讀不到 main 上的 series_dates.json（{type(exc).__name__}），沿用上一次讀到的")
        return self._state

    def fred_date(self, series_id: str) -> str | None:
        """FRED 上這檔序列的最新資料日期。跟建置抓同一個網址，不讀快取。"""
        start = (self._specs.get(series_id) or ("", "", "", catalogue.DEFAULT_START))[3]
        try:
            rows = fred.observations(series_id, start=start, ttl=0)
        except Exception as exc:
            self.log(f"FRED 這一次沒有回應（{series_id}：{type(exc).__name__}），下一輪再問")
            return None
        return rows[-1][0] if rows else None

    def bls_dates(self, series_ids: list[str]) -> dict[str, str]:
        """BLS API v1（免金鑰）上這幾檔的最新一期：{FRED 代號: "YYYY-MM-01"}。一次查詢問完。
        問不到就丟例外，由探針記下來。"""
        year = self.now().year          # 一月公布的是去年 12 月，所以連去年一起問
        body = {"seriesid": [BLS_IDS[sid] for sid in series_ids],
                "startyear": str(year - 1), "endyear": str(year)}
        request = urllib.request.Request(
            BLS_API, method="POST", data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json",
                     "User-Agent": "macro-dashboard-release-watch"})
        with urllib.request.urlopen(request, timeout=20) as response:
            latest = bls_latest(json.loads(response.read()))
        return {sid: latest[BLS_IDS[sid]] for sid in series_ids if BLS_IDS[sid] in latest}

    def _api(self, method: str, path: str, body: dict | None = None):
        if not (self.token and self.repo):
            raise RuntimeError("沒有 GITHUB_TOKEN 或 GITHUB_REPOSITORY（本機執行不觸發）")
        request = urllib.request.Request(
            f"https://api.github.com/repos/{self.repo}{path}", method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Authorization": f"Bearer {self.token}",
                     "Accept": "application/vnd.github+json",
                     "X-GitHub-Api-Version": "2022-11-28",
                     "User-Agent": "macro-dashboard-release-watch"})
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read()
        return json.loads(raw) if raw else None

    def dispatch_build(self) -> None:
        self._api("POST", "/actions/workflows/build.yml/dispatches", {"ref": "main"})

    def handoff(self) -> None:
        self._api("POST", f"/actions/workflows/{WORKFLOW}/dispatches",
                  {"ref": "main", "inputs": {"successor": "true"}})

    def runs(self) -> list[dict]:
        payload = self._api("GET", f"/actions/workflows/{WORKFLOW}/runs?per_page=30")
        return (payload or {}).get("workflow_runs") or []


def main() -> int:
    parser = argparse.ArgumentParser(description="發布守候")
    parser.add_argument("--plan", action="store_true",
                        help="只印出要等哪幾項與現在的狀態，不等也不觸發")
    args = parser.parse_args()
    io = Live()

    if args.plan:
        now, state = io.now(), io.state()
        items = plan(now, io.calendar(), state)
        if not items:
            print("沒有要守候的發布")
        for item in items:
            ids = open_ids(item, state, set()) if item["at"] <= now else []
            what, _ids = verdict(item, now, {sid: io.fred_date(sid) for sid in ids}, state, set())
            print(f"{_taipei(item['at'])}　{_names(item)}　→ {what}")
        return 0

    successor = os.environ.get("SUCCESSOR", "").strip().lower() == "true"
    if io.run_id is not None and not successor:
        try:
            others = io.runs()
        except Exception as exc:
            io.log(f"查不到有沒有別的守候在跑（{type(exc).__name__}），照常執行")
            others = []
        if should_yield(others, io.run_id, successor):
            io.log("已經有一支守候在跑，這一支結束")
            return 0

    outcome = run(io)
    if outcome == "handoff":
        try:
            io.handoff()
            io.log(f"這一支已經跑了 {_minutes(BUDGET) // 60} 小時，交給下一支接力")
        except Exception as exc:
            io.log(f"::warning title=發布守候::接力失敗（{exc}）：等下一個排程啟動守候")
    return 1 if outcome == "blind" else 0


if __name__ == "__main__":
    sys.exit(main())
