"""台灣各部會的統計資料庫。

主計總處、勞動部、財政部、內政部的統計查詢系統是同一套引擎（webMain.aspx），
參數與輸出格式完全相同，所以一支解析器涵蓋四個部會。各部會自己的網頁多半是
AJAX 殼或舊版 .xls，這個引擎才是背後真正出數字的地方。

`sys=220` 取資料、`outmode=900` 要 XML：期別已經是西元（2026M07、2026Q2），
數值沒有千分位，省掉民國年換算與 Big5 解碼。欄位與分類用「起點,個數」成對的
區段選取，位置要先查 `sys=212` 的表定義。**位置選錯不會報錯，只會拿到隔壁那一欄**，
所以呼叫端一律用回傳的標籤取序列，不用位置——標籤對不上就是空序列。

會靜默給錯答案的地方：
  - 功能代號或參數寫錯時回 HTTP 200 加一行純文字（「功能代號不存在」），
    不是 4xx。這裡把「不是 XML」當成失敗。
  - 財政部的標籤被 HTML 跳脫兩層（`&amp;lt;b&amp;gt;總計`），要還原並去掉標籤。
  - 缺格寫成 '-'、'...'、'－'，不是空白；當成 0 會讓年增率變成 -100%。
  - 資料上限 `ymt` 要填遠未來值，伺服器會截到現有最新期。填今天的話，
    跨月之後就永遠少抓最新那一期。
"""
from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
from datetime import date

from ..clock import today as _today
from ..http import get
from ..series import Series

HOSTS = {
    "dgbas": "https://nstatdb.dgbas.gov.tw/dgbasAll/webMain.aspx",
    "mol": "https://statdb.mol.gov.tw/statiscla/webMain.aspx",
    "mof": "https://web02.mof.gov.tw/njswww/WebMain.aspx",
    "moi": "https://statis.moi.gov.tw/micst/webMain.aspx",
}
AGENCY = {"dgbas": "主計總處", "mol": "勞動部", "mof": "財政部", "moi": "內政部"}

CYCLE = {"m": 1, "q": 2, "a": 4}
_FREQ = {"M": "m", "Q": "q", "A": "a", "Y": "a"}

_TAG = re.compile(r"<[^>]+>")
_MONTH = re.compile(r"^(\d{4})M(\d{2})$")
_QUARTER = re.compile(r"^(\d{4})Q([1-4])$")
_YEAR = re.compile(r"^(\d{4})$")


class StatdbError(RuntimeError):
    pass


def spans(indexes) -> str:
    """[0, 3, 4, 13] -> '0,1,3,2,13,1'：相鄰的位置併成一段。"""
    runs: list[list[int]] = []
    for i in sorted(set(indexes)):
        if runs and runs[-1][0] + runs[-1][1] == i:
            runs[-1][1] += 1
        else:
            runs.append([i, 1])
    return ",".join(f"{start},{count}" for start, count in runs)


def label(raw: str) -> str:
    """還原多層 HTML 跳脫並去掉標籤：'&lt;b&gt;總計&lt;/b&gt;' -> '總計'。"""
    text = raw
    for _ in range(3):
        unescaped = html.unescape(text)
        if unescaped == text:
            break
        text = unescaped
    return _TAG.sub("", text).strip()


def period(raw: str) -> date | None:
    raw = raw.strip()
    if m := _MONTH.match(raw):
        month = int(m.group(2))
        return date(int(m.group(1)), month, 1) if 1 <= month <= 12 else None
    if m := _QUARTER.match(raw):
        return date(int(m.group(1)), (int(m.group(2)) - 1) * 3 + 1, 1)
    if m := _YEAR.match(raw):
        return date(int(m.group(1)), 1, 1)
    return None


def parse(text: str) -> dict[str, dict]:
    """XML -> {標籤: {"freq", "unit", "points"}}。不是 XML 就拋 StatdbError。"""
    body = text.lstrip("﻿").strip()
    if not body.startswith("<"):
        raise StatdbError(body[:60] or "空回應")
    try:
        root = ET.fromstring(body)
    except ET.ParseError as exc:
        raise StatdbError(f"XML 解析失敗：{exc}") from exc

    out: dict[str, dict] = {}
    for node in root.iter("Series"):
        points = []
        for obs in node.iter("Obs"):
            when = period(obs.findtext("period") or "")
            raw = (obs.findtext("value") or "").strip().replace(",", "")
            if when is None:
                continue
            try:
                points.append((when, float(raw)))
            except ValueError:
                continue
        out[label(node.get("item", ""))] = {
            "freq": _FREQ.get((node.get("freq") or "").upper(), ""),
            "unit": label(node.get("unit", "")).removeprefix("單位：").strip(),
            "points": points,
        }
    return out


def url(agency: str, funid: str, *, fields, codes0=(), codes1=(),
        freq: str = "m", start_year: int = 1990) -> str:
    roc_end = _today().year - 1911 + 5
    params = [
        ("sys", "220"), ("funid", funid), ("outmode", "900"), ("outkind", "1"),
        ("cycle", str(CYCLE[freq])),
        ("ymf", f"{start_year - 1911}01"), ("ymt", f"{roc_end}12"),
        ("fldspc", spans(fields)),
        ("codspc0", spans(codes0) if codes0 else ""),
        ("codspc1", spans(codes1) if codes1 else ""),
        ("cmp0", "1"), ("cmp1", "0"), ("cmp2", "0"), ("compmode", "0"),
    ]
    # 參數值全是 ASCII；逗號不做百分比編碼，跟各部會自己網頁產生的網址一致。
    return HOSTS[agency] + "?" + "&".join(f"{k}={v}" for k, v in params)


def build(parsed: dict[str, dict], agency: str, funid: str, freq: str,
          today: date) -> dict[str, Series]:
    """解析結果 -> {標籤: Series}。

    頻率與請求不符的序列丟掉：cycle 用錯時伺服器會把年列與月列混排，
    年值會被當成某一個月。未來日期的點也丟掉——有些表以 0 預填尚未公布的期別。
    """
    out: dict[str, Series] = {}
    for name, block in parsed.items():
        if block["freq"] and block["freq"] != freq:
            continue
        points = [(d, v) for d, v in block["points"] if d <= today]
        out[name] = Series.from_pairs(
            f"{agency}:{funid}:{name}", points, label=name, unit=block["unit"],
            frequency=freq, source=AGENCY[agency])
    return out


def table(agency: str, funid: str, *, fields, codes0=(), codes1=(),
          freq: str = "m", start_year: int = 1990,
          ttl: float = 24 * 3600) -> dict[str, Series]:
    """一張表 -> {標籤: Series}。抓不到或回應不是 XML 時回傳空 dict。"""
    try:
        text = get(url(agency, funid, fields=fields, codes0=codes0,
                       codes1=codes1, freq=freq, start_year=start_year),
                   ttl=ttl, namespace="statdb", timeout=60, retries=3)
        return build(parse(text), agency, funid, freq, _today())
    except Exception:
        return {}
