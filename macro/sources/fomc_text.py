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
    links = _statement_links(ttl)
    if len(links) < 2:
        return {}

    texts = []
    for date, href in links[:2]:
        try:
            # 已發布的聲明不會再改，快取一年
            body = _clean(get(href, ttl=365 * 24 * 3600, namespace="fomc",
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
