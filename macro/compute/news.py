"""國際新聞。

來源目錄取自 WorldMonitor（見 macro/sources/worldmonitor.py），RSS 由這裡
自己抓、自己解析。整條流程仍然是純標準函式庫，沒有多一個相依套件。

這一頁想回答的不是「今天有什麼新聞」——那種東西任何一個入口網站都有——
而是「今天有哪幾件事大到多家獨立媒體同時report」。所以核心動作是聚合：
把標題斷詞後兩兩比對，同一件事的報導收成一束，再用「幾家報」而不是
「誰先報」來排序。單一家媒體的獨家會沉下去，這是刻意的：對總經判讀來說，
一件事的重要性比較接近它被多少人同時認為重要。

另外挑出一組與本站指標直接相關的關鍵字（聯準會、通膨、關稅、公債……），
獨立成一區，讓新聞跟儀表板上的數字能對得起來。

只取英文來源。目錄裡有匈牙利文、克羅埃西亞文、西班牙文等在地媒體，
對上游的多語系介面有意義，但混進這裡只會變成讀不懂的雜訊。
"""
from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from .. import http
from ..data import Bundle
from ..sources import worldmonitor

# (目錄分類, 顯示名稱, 取幾個來源)。上游是按重要性宣告的——它自己的
# 免費版來源上限就是照宣告順序填的——所以直接取前幾個。
CATEGORIES = [
    ("politics", "國際政治", 6),
    ("us", "美國", 8),
    ("gov", "官方與央行", 8),
    ("finance", "財經", 5),
    ("energy", "能源", 4),
    ("intel", "國防與情勢", 8),
    ("crisis", "危機與衝突", 4),
    ("middleeast", "中東", 5),
    ("asia", "亞洲", 6),
    ("europe", "歐洲", 5),
    ("thinktanks", "智庫", 5),
]

WINDOW_HOURS = 36        # 一天兩次建置，抓 36 小時才不會在時區交界漏掉
RSS_TTL = 30 * 60        # 開發時反覆跑不會一直打人家的伺服器
FEED_TIMEOUT = 15
FEED_RETRIES = 2

# build.py 在 --fresh／--offline 時設這個值。新聞的預設 TTL 比其他資料短
# 很多，所以不能直接沿用全站的 ttl，只在使用者明確要求時才覆蓋。
TTL_OVERRIDE: float | None = None

# 同一件事的判定：實詞至少共用這麼多個，而且要佔兩邊詞集的一定比例。
# 只看共用數會把長標題誤併，只看比例會把短標題誤併，兩個都要過。
CLUSTER_MIN_SHARED = 3
CLUSTER_MIN_JACCARD = 0.34
FOCUS_MIN_SOURCES = 2    # 「今日焦點」至少要幾家報
PER_CATEGORY_ITEMS = 8

# 與本站指標直接相關的字。命中就進「與總經相關」那一區。
MACRO_TERMS = {
    "fed", "federal reserve", "fomc", "powell", "rate cut", "rate hike",
    "interest rate", "inflation", "cpi", "pce", "deflation", "disinflation",
    "tariff", "trade war", "sanction", "treasury", "yield", "bond",
    "payroll", "jobless", "unemployment", "labor market", "recession",
    "gdp", "ecb", "bank of japan", "boj", "pboc", "imf", "opec",
    "crude", "oil price", "dollar", "yuan", "yen", "debt ceiling",
    "budget deficit", "credit", "default", "stimulus", "central bank",
}

STOPWORDS = {
    "the", "and", "for", "with", "from", "that", "this", "have", "has",
    "was", "were", "will", "would", "could", "should", "says", "say", "said",
    "after", "over", "into", "amid", "its", "his", "her", "their", "our",
    "new", "more", "than", "but", "not", "how", "why", "what", "who",
    "you", "are", "been", "about", "against", "under", "between", "during",
    "first", "last", "next", "one", "two", "may", "can", "out", "off",
    "day", "days", "week", "year", "years", "news", "report", "reports",
    "update", "updates", "live", "video", "watch", "read", "full",
}

_TAGS = re.compile(r"<[^>]+>")
_WORD = re.compile(r"[a-z0-9']+")
# Google News 會在標題尾巴接「 - 媒體名」，那是來源不是內容。
_SOURCE_SUFFIX = re.compile(r"\s+[-–—]\s+[^-–—]{2,40}$")


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _text(element) -> str:
    if element is None:
        return ""
    raw = "".join(element.itertext())
    return html.unescape(_TAGS.sub(" ", raw)).strip()


def _when(value: str):
    """RSS 用 RFC 822，Atom 用 ISO 8601，兩種都要吃。"""
    value = value.strip()
    if not value:
        return None
    try:
        moment = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        try:
            moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if moment is None:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def _link(entry) -> str:
    """RSS 的 link 是文字，Atom 的是 href 屬性。"""
    fallback = ""
    for child in entry:
        if _local(child.tag) != "link":
            continue
        href = child.attrib.get("href")
        if href:
            if child.attrib.get("rel", "alternate") == "alternate":
                return href
            fallback = fallback or href
        elif (child.text or "").strip():
            return child.text.strip()
    return fallback


def parse_feed(body: str, source: str) -> list[dict]:
    """把一份 RSS/Atom 解析成條目。壞掉的 XML 直接回空陣列。"""
    try:
        root = ET.fromstring(body.strip())
    except ET.ParseError:
        return []

    items = []
    for entry in root.iter():
        if _local(entry.tag) not in ("item", "entry"):
            continue
        fields = {}
        for child in entry:
            fields.setdefault(_local(child.tag), child)
        title = _text(fields.get("title"))
        if not title:
            continue
        published = None
        for key in ("pubDate", "published", "updated", "date"):
            published = _when(_text(fields.get(key)))
            if published:
                break
        items.append({"title": title, "link": _link(entry),
                      "published": published, "source": source})
    return items


def _headline(title: str) -> str:
    """去掉 Google News 接在標題尾巴的媒體名。"""
    stripped = _SOURCE_SUFFIX.sub("", title).strip()
    # 整個標題就是「A - B」時不要砍到只剩一半。
    return stripped if len(stripped) >= 20 else title


def _tokens(title: str) -> set[str]:
    words = _WORD.findall(title.lower())
    return {w for w in words if len(w) >= 3 and w not in STOPWORDS}


def _same_story(a: set[str], b: set[str]) -> bool:
    shared = len(a & b)
    if shared < CLUSTER_MIN_SHARED:
        return False
    union = len(a | b)
    return bool(union) and shared / union >= CLUSTER_MIN_JACCARD


def cluster(items: list[dict]) -> list[dict]:
    """把講同一件事的條目收成一束。

    貪婪比對，新條目跟每束的「代表標題」比。代表標題固定是第一則，
    不把後續成員的詞併進去——併進去的話詞集會越長越大，比對門檻等於
    越來越鬆，最後一束會像磁鐵一樣把整天的新聞都吸進去（第一版就是
    這樣，跑出「39 家報導同一則」這種明顯不對的數字）。

    條目數量是幾百，不是幾萬，O(n·k) 夠用，換來的是不用引進分群套件。
    """
    clusters: list[dict] = []
    for item in items:
        tokens = _tokens(_headline(item["title"]))
        if not tokens:
            continue
        for group in clusters:
            if _same_story(tokens, group["tokens"]):
                group["items"].append(item)
                break
        else:
            clusters.append({"tokens": tokens, "items": [item]})

    packed = []
    for group in clusters:
        members = group["items"]
        sources = sorted({m["source"] for m in members})
        latest = max((m["published"] for m in members if m["published"]),
                     default=None)
        lead = members[0]
        packed.append({
            "headline": _headline(lead["title"]),
            "link": lead["link"],
            "sources": sources,
            "count": len(sources),
            "latest": latest,
            "others": [_headline(m["title"]) for m in members[1:6]],
        })
    packed.sort(key=lambda c: (c["count"],
                               c["latest"] or datetime.min.replace(tzinfo=timezone.utc)),
                reverse=True)
    return packed


def _is_macro(title: str) -> bool:
    lowered = title.lower()
    return any(term in lowered for term in MACRO_TERMS)


def _select(catalogue: dict[str, list[dict]]) -> list[tuple[str, str, dict]]:
    """挑出要抓的來源：(分類 key, 分類名稱, feed)。"""
    chosen = []
    for key, label, cap in CATEGORIES:
        feeds = [f for f in catalogue.get(key, []) if f.get("lang", "en") == "en"]
        for feed in feeds[:cap]:
            chosen.append((key, label, feed))
    return chosen


def compute(bundle: Bundle) -> dict:
    """bundle 用不到——這一頁不吃 FRED，但保持跟其他 compute 模組同一個介面。"""
    feed_ttl = RSS_TTL if TTL_OVERRIDE is None else TTL_OVERRIDE
    try:
        catalogue = worldmonitor.load(
            ttl=worldmonitor.CATALOGUE_TTL if TTL_OVERRIDE is None else TTL_OVERRIDE)
    except Exception as exc:
        return {"available": False, "error": str(exc)[:200], "clusters": [],
                "categories": [], "macro": [], "stats": {}}

    selected = _select(catalogue)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=WINDOW_HOURS)

    items: list[dict] = []
    failed: list[str] = []
    by_category: dict[str, list[dict]] = {}

    for key, label, feed in selected:
        try:
            body = http.get(feed["url"], ttl=feed_ttl, namespace="news",
                            retries=FEED_RETRIES, timeout=FEED_TIMEOUT)
        except Exception:
            failed.append(feed["name"])
            continue
        fresh = [i for i in parse_feed(body, feed["name"])
                 if i["published"] and i["published"] >= cutoff]
        for item in fresh:
            item["category"] = key
            item["category_label"] = label
        items.extend(fresh)
        by_category.setdefault(key, []).extend(fresh)

    # 同一則被兩個分類的來源同時收到時，只留一份。
    seen: set[str] = set()
    unique: list[dict] = []
    for item in sorted(items, key=lambda i: i["published"], reverse=True):
        fingerprint = " ".join(sorted(_tokens(_headline(item["title"]))))
        if not fingerprint or fingerprint in seen:
            continue
        seen.add(fingerprint)
        unique.append(item)

    groups = cluster(unique)
    focus = [g for g in groups if g["count"] >= FOCUS_MIN_SOURCES]

    macro = [i for i in unique if _is_macro(i["title"])][:20]

    categories = []
    for key, label, _cap in CATEGORIES:
        rows = sorted(by_category.get(key, []),
                      key=lambda i: i["published"], reverse=True)
        trimmed, taken = [], set()
        for row in rows:
            fingerprint = " ".join(sorted(_tokens(_headline(row["title"]))))
            if fingerprint in taken:
                continue
            taken.add(fingerprint)
            trimmed.append(row)
            if len(trimmed) >= PER_CATEGORY_ITEMS:
                break
        if trimmed:
            categories.append({"key": key, "label": label, "items": trimmed})

    return {
        "available": True,
        "clusters": focus,
        "categories": categories,
        "macro": macro,
        "stats": {
            "feeds_tried": len(selected),
            "feeds_failed": len(failed),
            "failed_names": failed[:12],
            "items": len(unique),
            "clusters": len(focus),
            "window_hours": WINDOW_HOURS,
            "catalogue_feeds": sum(len(v) for v in catalogue.values()),
            "catalogue_categories": len(catalogue),
        },
    }
