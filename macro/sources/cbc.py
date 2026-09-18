"""台灣：中央銀行貼放利率。

央行沒有把政策利率放進任何開放資料檔，只有「央行貼放利率」這一頁的
HTML 表格（每頁 20 次調整，三頁回溯到 2000 年）。政策利率是階梯函數，
一年可能一次都不動，所以解析頁面比接一個會停更的代理指標可靠。

回傳兩種形狀：`changes` 是調整當天的點（每一點都是一次決策），
`monthly` 是把它展開成每月底的水準（畫成階梯，不會在兩次決策之間
畫出一條不存在的斜線）。
"""
from __future__ import annotations

import html as html_module
import re
from datetime import date

from ..clock import today as _today
from ..http import get
from ..series import Series

PAGES = [f"https://www.cbc.gov.tw/tw/lp-640-1-{n}-20.html" for n in (1, 2, 3)]

_ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
_CELL = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.S)
_TAG = re.compile(r"<[^>]+>")
_DATE = re.compile(r"^(\d{4})/(\d{1,2})/(\d{1,2})$")

EMPTY = {"changes": Series("TW_DISCOUNT", [], [], frequency="d"),
         "monthly": Series("TW_DISCOUNT_M", [], [], frequency="m")}


def _rows(html: str) -> list[list[str]]:
    out = []
    for block in _ROW.findall(html):
        cells = [_TAG.sub("", c).replace("&nbsp;", " ").strip()
                 for c in _CELL.findall(block)]
        if len(cells) >= 2:
            out.append(cells)
    return out


def discount_rate(*, ttl: float = 24 * 3600) -> dict[str, Series]:
    """重貼現率的完整調整史。抓不到就回空序列，不用前值假裝。"""
    points: dict[date, float] = {}
    for url in PAGES:
        try:
            html = get(url, ttl=ttl, namespace="cbc", timeout=40, retries=2)
        except Exception:
            continue
        for cells in _rows(html):
            match = _DATE.match(cells[0])
            if not match:
                continue
            try:
                value = float(cells[1])
            except (ValueError, IndexError):
                continue
            year, month, day = (int(g) for g in match.groups())
            try:
                points[date(year, month, day)] = value
            except ValueError:
                continue

    if not points:
        return dict(EMPTY)

    return rate_series(sorted(points.items()))


def rate_series(ordered: list[tuple[date, float]], *, meta: dict | None = None,
                today: date | None = None) -> dict[str, Series]:
    """調整紀錄 -> {changes, monthly}。

    月度展開取「當月底仍然有效的那個值」。政策利率在兩次決策之間就是不動，
    這是階梯，不是內插。
    """
    if not ordered:
        return dict(EMPTY)
    changes = Series.from_pairs(
        "TW_DISCOUNT", ordered, label="央行重貼現率", unit="%",
        frequency="d", source="中央銀行", meta=dict(meta or {}))

    monthly_pairs = []
    year, month = ordered[0][0].year, ordered[0][0].month
    today = today or _today()
    current = ordered[0][1]
    cursor = 0
    while (year, month) <= (today.year, today.month):
        month_end = date(year + (month == 12), month % 12 + 1, 1)
        while cursor < len(ordered) and ordered[cursor][0] < month_end:
            current = ordered[cursor][1]
            cursor += 1
        monthly_pairs.append((date(year, month, 1), current))
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)

    return {
        "changes": changes,
        "monthly": Series.from_pairs(
            "TW_DISCOUNT_M", monthly_pairs, label="央行重貼現率", unit="%",
            frequency="m", source="中央銀行", meta=dict(meta or {})),
    }


# ------------------------------------------------------------ 理監事會決議 --
# 2026-09-17 理監事會維持利率、放寬第 2 戶房貸成數，網站完全沒有顯示：
# 上面的貼放利率表只在利率「有變」時才多一列，利率不變、調準備率、調信用管制
# 都不會出現在那裡。決議的真相是決議新聞稿本身。

NEWS_RSS = "https://www.cbc.gov.tw/tw/rss-302-1.xml"
NEWS_TTL = 1800
PAGE_TTL = 7 * 24 * 3600
DECISION_TITLE = "中央銀行理監事聯席會議決議新聞稿"
SCHEDULE_TITLE = "理監事聯席會議預定日期"

_ITEM = re.compile(r"<item>(.*?)</item>", re.S)
_PUBLISHED = re.compile(r"發布日期[：:]\s*(\d{4})-(\d{2})-(\d{2})")
_EFFECTIVE = re.compile(r"自本年(\d{1,2})月(\d{1,2})日起實施")
_RATE_MOVE = re.compile(r"各調(升|降)([\d.]+)個百分點，?分別由年息([\d.]+)%.*?調整為(?:年息)?([\d.]+)%")
_RATE_HOLD = re.compile(r"分別維持年息([\d.]+)%")
# 兩種語序都有：「存款準備率各調升0.25個百分點」（2024）與
# 「另調升新台幣活期性及定期性存款準備率各0.25個百分點」（2022）
_RESERVE = [re.compile(r"存款準備率各?調(升|降)([\d.]+)個百分點"),
            re.compile(r"調(升|降)(?:新台幣)?(?:活期性及定期性)?存款準備率各?([\d.]+)個百分點")]
# 成數寫法很多：「由6成降為5成」「由6成降至5.5成」「降為5成」「上限為7成」
# 「調降…最高成數為6成」。一律錨定在「最高成數」之後，才不會讀到「保留1成動工款」。
_LTV = re.compile(r"最高成數(?:上限)?[^。；]{0,20}?(?:由([\d.]+)成[，,]?\s*)?"
                  r"(?:一律)?(?:調)?(?:[升降]|放寬|提高)?(?:為|至)([\d.]+)成")
_SECTION = re.compile(r"[一二三四五六七八九十]、")
_LTV_SUBJECTS = [
    ("第2戶", "第 2 戶購屋貸款"), ("第3戶", "第 3 戶以上購屋貸款"),
    ("高價住宅", "高價住宅貸款"), ("公司法人", "公司法人購置住宅貸款"),
    ("餘屋", "餘屋貸款"), ("購地", "購地貸款"), ("工業區閒置土地", "工業區閒置土地貸款"),
]


def _xml_field(item: str, tag: str) -> str:
    m = re.search(rf"<{tag}>(.*?)</{tag}>", item, re.S)
    if not m:
        return ""
    return html_module.unescape(re.sub(r"<!\[CDATA\[|\]\]>", "", m.group(1))).strip()


def news_items(*, ttl: float = NEWS_TTL) -> list[dict]:
    """央行新聞稿 RSS，新到舊。約兩年、500 則。"""
    try:
        xml = get(NEWS_RSS, ttl=ttl, namespace="cbc", timeout=60, retries=2)
    except Exception:
        return []
    return [{"title": _xml_field(item, "title"), "link": _xml_field(item, "link")}
            for item in _ITEM.findall(xml)]


def _notice_text(link: str) -> str:
    """新聞稿正文。沒有「發布日期」的回應（例如還沒上線時被 302 轉到首頁）不寫入
    一週的快取，下一輪建置會重抓。"""
    try:
        return page_text(get(link, ttl=PAGE_TTL, namespace="cbc", timeout=40, retries=2,
                             validate=lambda raw: bool(_PUBLISHED.search(page_text(raw)))))
    except Exception:
        return ""


def page_text(raw_html: str) -> str:
    body = re.sub(r"<script.*?</script>|<style.*?</style>", " ", raw_html, flags=re.S)
    return re.sub(r"\s+", " ", html_module.unescape(_TAG.sub(" ", body))).strip()


def _effective(sentence: str, year: int) -> str | None:
    m = _EFFECTIVE.search(sentence)
    if not m:
        return None
    try:
        return date(year, int(m.group(1)), int(m.group(2))).isoformat()
    except ValueError:
        return None


def _section_effective(body: str, sentence: str, year: int) -> str | None:
    """調息那句沒寫生效日時，往回找同一個「三、」大點的導言句——2016-03-24 寫成
    「本日本行理事會一致決議採行下列措施，並自本年3月25日起實施。(一) 本行重貼現率…」。"""
    at = body.find(sentence)
    if at < 0:
        return None
    starts = [m.start() for m in _SECTION.finditer(body) if m.start() <= at]
    start = starts[-1] if starts else 0
    return _effective(body[start:at], year)


def _ltv_changes(body: str) -> list[str]:
    """「由 X 成降為 Y 成」前面同一條款裡的貸款類別，全部列出。

    2024-09 那次一句話同時調降公司法人、高價住宅、第 3 戶三類——只取最近的
    一個，會讓讀者以為只動了第 3 戶。條款以句號、分號、「2.」或「(一)」切開。
    """
    out = []
    for m in _LTV.finditer(body):
        before = body[max(0, m.start() - 80):m.start()]
        cuts = [before.rfind("。"), before.rfind("；")]
        cuts += [x.end() - 1 for x in re.finditer(
            r"\d\.\s|\([一二三四五六七八九十]\)|\(\d\)", before)]
        clause = before[max(cuts) + 1:]
        found = sorted((clause.find(key), label) for key, label in _LTV_SUBJECTS if key in clause)
        label = "、".join(label for _pos, label in found) or "購屋貸款"
        new = float(m.group(2))
        if m.group(1):
            line = f"{label}成數上限 {float(m.group(1)):g} 成 → {new:g} 成"
        else:
            line = f"{label}成數上限調為 {new:g} 成"
        if line not in out:
            out.append(line)
    return out


def parse_board_decision(text: str, year: int) -> dict | None:
    """從決議新聞稿讀出三件事：政策利率、存款準備率、房貸信用管制。

    只看「業務聯繫單位」之前的正文——之後是附件對照表，會重複列出成數。
    信用管制只認「修正『…不動產抵押貸款業務規定』…自本年 M 月 D 日起實施」
    同一句：2024-12 以後每一份新聞稿都會用過去式提到「第七度調整選擇性信用
    管制措施」，只比對那幾個字會把每次會議都當成有調整。
    """
    # 2011 年的新聞稿用全形％；只換這一個字，不做整篇 NFKC（會把全形逗號與
    # 「(一)」也換掉，句型比對就跟著變了）
    body = text.split("業務聯繫單位")[0].replace("％", "%")
    rate = reserve = credit = None
    reserve_candidates = []
    for sentence in re.split(r"(?<=。)", body):
        if rate is None and "重貼現率" in sentence and "擔保放款融通利率" in sentence:
            if m := _RATE_MOVE.search(sentence):
                rate = {"action": "raise" if m.group(1) == "升" else "lower",
                        "step": float(m.group(2)), "from": float(m.group(3)),
                        "to": float(m.group(4)),
                        "effective": _effective(sentence, year) or _section_effective(body, sentence, year)}
            elif m := _RATE_HOLD.search(sentence):
                value = float(m.group(1))
                rate = {"action": "hold", "step": None, "from": value, "to": value,
                        "effective": None}
        for pattern in _RESERVE:
            if m := pattern.search(sentence):
                reserve_candidates.append({
                    "action": "raise" if m.group(1) == "升" else "lower",
                    "step": float(m.group(2)), "effective": _effective(sentence, year)})
                break
        if (credit is None and "不動產抵押貸款業務規定" in sentence and "修正" in sentence
                and (effective := _effective(sentence, year))):
            credit = {"effective": effective, "changes": _ltv_changes(body)}
    if reserve_candidates:
        # 導言句（「同意調升…存款準備率0.25個百分點」）沒有生效日，優先用有日期的那句
        reserve = next((r for r in reserve_candidates if r["effective"]), reserve_candidates[0])
    if rate is None:
        return None
    return {"rate": rate, "reserve": reserve, "credit": credit}


def latest_board_decision(*, ttl: float = NEWS_TTL,
                          items: list[dict] | None = None) -> dict:
    """最近一次理監事會決議。status 與 FOMC 同一套：ok／unparsed／unavailable。"""
    items = news_items(ttl=ttl) if items is None else items
    notices = [i for i in items if re.sub(r"\s+", "", i["title"]).endswith("理監事聯席會議決議新聞稿")]
    if not notices:
        return {"status": "unavailable", "reason": "抓不到央行新聞稿 RSS，或裡面沒有決議新聞稿"}

    parsed = []
    for notice in notices[:2]:
        text = _notice_text(notice["link"])
        published = _PUBLISHED.search(text)
        when = (date(int(published.group(1)), int(published.group(2)),
                     int(published.group(3))) if published else None)
        decision = parse_board_decision(text, when.year) if when else None
        parsed.append((notice["link"], when, decision))

    link, when, decision = parsed[0]
    if when is None:
        return {"status": "unavailable", "url": link,
                "reason": "決議新聞稿頁抓不到，或找不到發布日期"}
    base = {"date": when.isoformat(), "url": link}
    if decision is None:
        return {**base, "status": "unparsed",
                "reason": "決議新聞稿已發布，但讀不出重貼現率那一句"}

    rate = decision["rate"]
    consistent = {"raise": rate["to"] > rate["from"], "lower": rate["to"] < rate["from"],
                  "hold": rate["to"] == rate["from"]}[rate["action"]]
    previous = parsed[1][2] if len(parsed) > 1 else None
    if previous and previous["rate"]["to"] != rate["from"]:
        consistent = False
    if not consistent:
        return {**base, "status": "unparsed",
                "reason": "決議的動詞跟前後兩次的重貼現率對不上，不採用"}

    out = {**base, "status": "ok", **decision}
    if previous:
        out["prev_date"] = parsed[1][1].isoformat() if parsed[1][1] else None
        out["prev_action"] = previous["rate"]["action"]
    return out


def board_schedule(*, ttl: float = NEWS_TTL, items: list[dict] | None = None) -> list[date]:
    """「XXX年中央銀行理監事聯席會議預定日期」公告裡的會議日。每年 12 月公布隔年。"""
    items = news_items(ttl=ttl) if items is None else items
    dates: set[date] = set()
    for notice in items:
        title_year = re.match(r"(\d{3})年", notice["title"])
        if SCHEDULE_TITLE not in notice["title"] or not title_year:
            continue
        text = _notice_text(notice["link"])
        if text:
            dates.update(parse_schedule(text, int(title_year.group(1))))
    return sorted(dates)


def parse_schedule(text: str, roc_year: int) -> list[date]:
    out = []
    for roc, month, day in re.findall(r"(\d{3})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日", text):
        if int(roc) != roc_year:
            continue
        try:
            out.append(date(int(roc) + 1911, int(month), int(day)))
        except ValueError:
            continue
    return sorted(set(out))
