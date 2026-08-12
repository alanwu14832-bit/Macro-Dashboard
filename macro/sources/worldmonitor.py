"""WorldMonitor 的新聞來源目錄（koala73/worldmonitor）。

WorldMonitor 是一個開源的全球情勢儀表板，它最耐用的資產不是那些看板，
而是一份維護良好的新聞來源清單：500 多個 RSS feed，依主題分類，
壞掉的來源會被上游換掉。

它的 REST API（api.worldmonitor.app）與 MCP server（worldmonitor.app/mcp）
都需要 API key——tools/list 是公開的，tools/call 一律回 401/403。
但來源目錄本身就寫在原始碼裡（src/config/feeds.ts），是公開可讀的，
所以這裡不接它的服務，而是讀它的目錄，再自己去抓各家的 RSS。

這樣做不需要金鑰、不需要 Node、不需要在本機跑它那套 5,500 檔的前端，
而且來源清單會跟著上游一起更新——它換掉死掉的 feed，我們下次建置就跟著換。

授權：WorldMonitor 是 AGPL-3.0。這裡取用的是 feed 網址與分類名稱這類事實
資料，不是它的程式碼；本專案沒有內含、連結或改作它的原始碼。
"""
from __future__ import annotations

import re

from .. import http

RAW_BASE = "https://raw.githubusercontent.com/koala73/worldmonitor/main/"
FEEDS_URL = RAW_BASE + "src/config/feeds.ts"

# 目錄一天內不會變太多，而且它只是一份清單，不是行情。
CATALOGUE_TTL = 24 * 3600

# 完整版（world 變體）的新聞目錄。其他 export 是各站變體的子集，
# 我們要的是母集合，再自己挑分類。CANONICAL_FEEDS 是用函式合出來的，
# 靜態讀不到，也不需要——它是 FULL_FEEDS 的重組。
RECORD_NAME = "FULL_FEEDS"

# 另一份平鋪的清單：國防、國際關係、情勢分析類的來源，上游單獨維護。
# 併成一個 intel 分類，因為對總經判讀來說它跟新聞分類是同一種東西。
INTEL_NAME = "INTEL_SOURCES"

_ENTRY_BLOCK = re.compile(r"\{[^{}]*\}")
_NAME = re.compile(r"\bname:\s*'((?:[^'\\]|\\.)*)'")
_URL = re.compile(r"\burl:\s*(?:rss|railwayRss)\(\s*'([^']+)'\s*\)")
_LANG = re.compile(r"\blang:\s*'([A-Za-z-]+)'")
_CATEGORY_KEY = re.compile(r"(\w+)\s*:\s*\[")


class CatalogueError(RuntimeError):
    pass


def _match_bracket(text: str, start: int, opener: str, closer: str) -> int:
    """回傳與 text[start] 這個括號配對的收尾位置。

    feeds.ts 的字串裡有 `{` 也有 `[`（Google News 查詢字串），所以掃描時
    必須跳過字串內容，否則會在 `q=(...)` 這種地方數錯層。
    """
    depth = 0
    i = start
    while i < len(text):
        ch = text[i]
        if ch in "'\"`":
            quote = ch
            i += 1
            while i < len(text) and text[i] != quote:
                i += 2 if text[i] == "\\" else 1
        elif ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                return i
        i += 1
    raise CatalogueError(f"{opener} 從第 {start} 字未配對")


def _unquote(value: str) -> str:
    return value.replace("\\'", "'").replace("\\\\", "\\")


def _feeds_in(text: str) -> list[dict]:
    """從一段 `[...]` 內容抽出 feed 條目。

    只認 http(s) 的 feed：目錄裡有少數指向 WorldMonitor 自家路由的相對網址
    （例如 '/api/fwdstart'），那些要有它的後端才抓得到，對我們沒有用。
    """
    feeds = []
    for block in _ENTRY_BLOCK.finditer(text):
        chunk = block.group(0)
        name, url = _NAME.search(chunk), _URL.search(chunk)
        if not (name and url):
            continue
        address = url.group(1)
        if not address.startswith(("http://", "https://")):
            continue
        lang = _LANG.search(chunk)
        feeds.append({"name": _unquote(name.group(1)), "url": address,
                      "lang": lang.group(1) if lang else "en"})
    return feeds


def parse(source: str) -> dict[str, list[dict]]:
    """把 feeds.ts 解析成 {分類: [{name, url, lang}, ...]}。"""
    anchor = source.find(f"const {RECORD_NAME}")
    if anchor < 0:
        raise CatalogueError(f"feeds.ts 裡找不到 {RECORD_NAME}，上游結構可能改了")

    open_brace = source.index("{", anchor)
    record = source[open_brace:_match_bracket(source, open_brace, "{", "}") + 1]

    catalogue: dict[str, list[dict]] = {}
    cursor = 0
    while True:
        found = _CATEGORY_KEY.search(record, cursor)
        if not found:
            break
        bracket = record.index("[", found.start())
        end = _match_bracket(record, bracket, "[", "]")
        feeds = _feeds_in(record[bracket:end])
        if feeds:
            catalogue[found.group(1)] = feeds
        cursor = end + 1

    # 從 `= [` 開始找，不要從宣告開始找第一個 `[`——型別註記 `Feed[]` 的
    # 那對空括號會先被抓到，配對到的是空內容。
    intel = re.search(rf"const\s+{INTEL_NAME}\b[^=]*=\s*(\[)", source)
    if intel:
        bracket = intel.start(1)
        end = _match_bracket(source, bracket, "[", "]")
        feeds = _feeds_in(source[bracket:end])
        if feeds:
            catalogue["intel"] = feeds

    if not catalogue:
        raise CatalogueError("解析到 0 個分類，feeds.ts 的格式可能改了")
    return catalogue


def load(*, ttl: float = CATALOGUE_TTL) -> dict[str, list[dict]]:
    """抓下上游的 feeds.ts 並解析。"""
    source = http.get(FEEDS_URL, ttl=ttl, namespace="worldmonitor", timeout=45)
    return parse(source)
