"""FOMC 聲明全文與逐次比對。

來源是聯準會官網的貨幣政策新聞稿 RSS，免金鑰。抓最近兩次「FOMC
statement」的正文，做句子層級的比對——這正是分析師在會後做的事：
不是重讀整份聲明，而是看**哪一句改了**。措辭從 "solid" 換成
"moderated"，比任何評論都準確地說明委員會的看法變了。

刻意不做的事：不對聲明做語意評分或「AI 判讀」。這裡只呈現可驗證的
事實——新增哪句、刪除哪句、哪句改了哪幾個字，以及鷹鴿字彙的次數
變化。判讀留給讀者，跟本站其他部分的規則一致：同一份輸入永遠得到
同一個輸出。
"""
from __future__ import annotations

import difflib
import html as html_module
import re

from ..http import get

FEED = "https://www.federalreserve.gov/feeds/press_monetary.xml"

# RSS 只快取 30 分鐘。原本跟聲明一起快取 12 小時，結果 2026-09-16 升息之後，
# 每小時建置照樣跑，新聲明卻要半天後才進得來。聲明本身發布後不會再改，另外快取一年。
RSS_TTL = 1800
STATEMENT_TTL = 365 * 24 * 3600

_FRACTION = re.compile(r"^(\d+)/(\d+)$")
_MIXED = re.compile(r"^(\d+)(?:-(\d+)/(\d+))?$")
_DECISION = re.compile(
    r"decided to (raise|increase|lower|reduce|maintain|keep)\s+the target range for "
    r"the federal funds rate\s+(?:by\s+(\S+)\s+percentage points?\s+)?"
    r"(?:to|at)\s+(\S+)\s+to\s+(\S+)\s+percent", re.I)
_ACTIONS = {"raise": "raise", "increase": "raise", "lower": "lower",
            "reduce": "lower", "maintain": "hold", "keep": "hold"}


def _rate(token: str) -> float | None:
    """聲明裡的利率寫法：'4'、'3-3/4'、'1/4'。"""
    token = token.strip()
    if m := _FRACTION.match(token):
        return int(m.group(1)) / int(m.group(2))
    if m := _MIXED.match(token):
        whole = float(m.group(1))
        return whole + int(m.group(2)) / int(m.group(3)) if m.group(2) else whole
    return None


def parse_decision(text: str) -> dict | None:
    """從聲明全文讀出決議：動作、新的目標區間、調整幅度。讀不出來回 None。"""
    normal = re.sub(r"[‐‑‒–]", "-", text)
    m = _DECISION.search(normal)
    if not m:
        return None
    lower, upper = _rate(m.group(3)), _rate(m.group(4))
    if lower is None or upper is None or upper <= lower:
        return None
    return {"action": _ACTIONS[m.group(1).lower()], "lower": lower, "upper": upper,
            "step": _rate(m.group(2)) if m.group(2) else None}


def latest_decision(*, ttl: float = RSS_TTL) -> dict:
    """最近一次 FOMC 決議，來源是聯準會自己的聲明。

    status 三種，後兩種都必須在頁面上被看見，不能退回成「沒事」：
      ok           讀出決議，且動詞與前後兩次的利率區間一致
      unparsed     聲明在，但讀不出決議，或動詞跟數字對不上
      unavailable  RSS 或聲明頁抓不到
    """
    links = _statement_links(min(ttl, RSS_TTL))
    if not links:
        return {"status": "unavailable", "reason": "抓不到聯準會貨幣政策新聞稿的 RSS"}

    parsed = []
    for date, href in links[:2]:
        try:
            body = _clean(get(href, ttl=STATEMENT_TTL, namespace="fomc",
                              timeout=25, retries=2))
        except Exception:
            body = ""
        parsed.append((date, href, body, parse_decision(body) if body else None))

    date, href, body, decision = parsed[0]
    base = {"date": date, "url": href}
    if not body:
        return {**base, "status": "unavailable", "reason": "聲明頁抓不到，或版面改了"}
    if decision is None:
        return {**base, "status": "unparsed",
                "reason": "聲明已發布，但讀不出「decided to … the target range」這一句"}

    out = {**base, "status": "ok", **decision, "vote": _vote(body)}
    previous = parsed[1][3] if len(parsed) > 1 else None
    if previous:
        moved = decision["upper"] - previous["upper"]
        consistent = {"raise": moved > 0, "lower": moved < 0,
                      "hold": moved == 0}[decision["action"]]
        if not consistent:
            return {**base, "status": "unparsed",
                    "reason": "聲明的動詞跟前後兩次的利率區間對不上，不採用"}
        out.update(prev_date=parsed[1][0], prev_lower=previous["lower"],
                   prev_upper=previous["upper"], prev_action=previous["action"])
    return out

# 措辭光譜。挑的是聯準會實際會換掉的字，不是泛用的情緒詞。
HAWKISH_TERMS = [
    "elevated", "restrictive", "firm", "tight", "persistent", "elevated uncertainty",
    "additional firming", "resolute", "inflationary pressures", "upside risks",
]
DOVISH_TERMS = [
    "moderated", "easing", "slowed", "softened", "cooling", "downside risks",
    "declined", "moderating", "weakened", "accommodative",
]


def _clean(raw_html: str) -> str:
    body = re.search(r'<div class="col-xs-12 col-sm-8[^"]*"[^>]*>(.*?)</div>\s*</div>',
                     raw_html, re.S)
    if not body:
        return ""
    text = re.sub(r"<[^>]+>", " ", body.group(1))
    text = html_module.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _sentences(text: str) -> list[str]:
    """切句。兩個雷：句子裡有 "3-1/2 to 3-3/4 percent." 這種小數點，
    而投票段落全是 "Beth M. Hammack" 這種人名縮寫——在縮寫後面斷句
    會把異議委員的名字拆成兩「句」，那是聲明裡最重要的訊號之一。
    所以要求句點前不是單一大寫字母、也不是常見縮寫。"""
    # 句點前若是「空白 + 單一大寫字母」就是人名縮寫（Beth M. Hammack），
    # 常見敬稱同理。用負向 lookbehind 擋掉這兩類再斷句。
    # lookbehind 的位置在句點「之後」，所以樣式要把句點本身寫進去
    guard = (r"(?<![\s(][A-Z]\.)(?<!\bMr\.)(?<!\bMs\.)"
             r"(?<!\bJr\.)(?<!\bSr\.)(?<!\bSt\.)")
    parts = re.split(guard + r"(?<=[.;])\s+(?=[A-Z])", text)
    return [p.strip() for p in parts if len(p.strip()) > 25]


def _count_terms(text: str, terms: list[str]) -> dict[str, int]:
    lowered = text.lower()
    return {t: lowered.count(t) for t in terms if lowered.count(t)}


def _statement_links(ttl: float) -> list[tuple[str, str]]:
    """(標題日期, 網址)，新到舊。只取真正的 FOMC statement。"""
    try:
        xml = get(FEED, ttl=ttl, namespace="fomc", timeout=25, retries=2)
    except Exception:
        return []
    out = []
    for item in re.findall(r"<item>(.*?)</item>", xml, re.S):
        title = re.search(r"<title>(.*?)</title>", item, re.S)
        link = re.search(r"<link>(.*?)</link>", item, re.S)
        if not (title and link):
            continue
        name = html_module.unescape(re.sub(r"<!\[CDATA\[|\]\]>", "", title.group(1))).strip()
        href = re.sub(r"<!\[CDATA\[|\]\]>", "", link.group(1)).strip()
        if "FOMC statement" not in name:
            continue
        stamp = re.search(r"monetary(\d{8})", href)
        date = (f"{stamp.group(1)[:4]}-{stamp.group(1)[4:6]}-{stamp.group(1)[6:]}"
                if stamp else "")
        out.append((date, href))
    return out


def compare(*, ttl: float = 12 * 3600) -> dict:
    """最近一次聲明，以及它跟上一次的逐句差異。"""
    links = _statement_links(min(ttl, RSS_TTL))
    if len(links) < 2:
        return {}

    texts = []
    for date, href in links[:2]:
        try:
            body = _clean(get(href, ttl=STATEMENT_TTL, namespace="fomc",
                              timeout=25, retries=2))
        except Exception:
            return {}
        if not body:
            return {}
        texts.append((date, body))

    (new_date, new_text), (old_date, old_text) = texts
    new_sents, old_sents = _sentences(new_text), _sentences(old_text)

    matcher = difflib.SequenceMatcher(None, old_sents, new_sents)
    added, removed, changed = [], [], []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "insert":
            added.extend(new_sents[j1:j2])
        elif tag == "delete":
            removed.extend(old_sents[i1:i2])
        elif tag == "replace":
            # 一對一的替換視為「改寫」，才能標出改了哪幾個字
            for k in range(max(i2 - i1, j2 - j1)):
                before = old_sents[i1 + k] if i1 + k < i2 else ""
                after = new_sents[j1 + k] if j1 + k < j2 else ""
                if before and after:
                    changed.append({"before": before, "after": after,
                                    "words": _word_diff(before, after)})
                elif after:
                    added.append(after)
                elif before:
                    removed.append(before)

    same = len(added) == 0 and len(removed) == 0 and len(changed) == 0
    return {
        "date": new_date, "prev_date": old_date,
        "url": links[0][1], "prev_url": links[1][1],
        "text": new_text,
        "sentences": len(new_sents),
        "added": added, "removed": removed, "changed": changed,
        "same": same,
        "hawkish_now": _count_terms(new_text, HAWKISH_TERMS),
        "hawkish_prev": _count_terms(old_text, HAWKISH_TERMS),
        "dovish_now": _count_terms(new_text, DOVISH_TERMS),
        "dovish_prev": _count_terms(old_text, DOVISH_TERMS),
        "vote": _vote(new_text),
        "vote_prev": _vote(old_text),
    }


def _word_diff(before: str, after: str) -> list[dict]:
    """句內的字詞增刪，給前端標色用。"""
    a, b = before.split(), after.split()
    out = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b).get_opcodes():
        if tag == "equal":
            continue
        out.append({"kind": tag,
                    "before": " ".join(a[i1:i2]),
                    "after": " ".join(b[j1:j2])})
    return out


def _vote(text: str) -> str:
    """票數，例如 "9 – 3 vote" → "9–3"。異議票數本身就是訊號。"""
    m = re.search(r"(\d+)\s*[–-]\s*(\d+)\s*vote", text)
    return f"{m.group(1)}–{m.group(2)}" if m else ""
