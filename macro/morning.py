"""每日晨報（data/morning/YYYY-MM-DD.json）。

晨報由 GitHub Actions 每天台北 07:00 前後用 Claude API 寫一篇（tools/morning_brief.py），
一天一篇、提交進 repo，網站在 /morning/ 登最新一期、每期有自己的網址、可以往回翻。
它跟頭版的「今日導讀」一樣是語言模型寫的、蓋「摘」的印，但篇幅長得多，而且新聞那一半
用網頁搜尋找了實際來源。

程式判斷不了文章寫得好不好，這裡只做機械的檢查——每一條都是「壞了不會報錯、只會讓
頁面說謊」的那一類，所以寧可不出刊：

  形狀  三到五則要聞、每則兩三段、每則至少一個實際來源；四個固定欄目都要有
  長度  全文（不含標題與來源）800–2,000 字，說明書寫的是 1,000–1,500
  數字  「昨夜美國市場」「台股美股」「今天要看什麼」「本站判定」四欄裡的每個阿拉伯數字，
        都要能在寫稿時餵給模型的素材（tools/daily_digest.py 的輸出）裡找到——可以照常
        四捨五入，不能換算、不能自己加減。這一關只在寫稿時跑（要有素材），通過的才會存檔
  用語  不准寫「優於／不如預期」「市場共識」這類字；固定欄目不准寫「市場預期」
  休市  上一個美股交易日不是「昨夜」時（週末、假日），標題與美股兩欄不准寫「昨夜」

數字檢查比的是絕對值：中文的漲跌寫在字上（「跌 0.35%」），正負號比不了。這是已知的缺口，
寫在說明書裡讓模型照抄素材的寫法，不是靠這裡擋。
"""
from __future__ import annotations

import json
import os
import re
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal, InvalidOperation

from . import clock, paths

MORNING_DIR = os.path.join(paths.DATA_DIR, "morning")
FILENAME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.json$")
FAILED_RE = re.compile(r"^failed-(\d{4}-\d{2}-\d{2})\.json$")

WEEKDAYS = "一二三四五六日"

# 固定欄目：鍵、標題。美股那一欄的標題看有沒有「昨夜」，寫稿時決定、存在檔案裡。
SECTIONS = [
    ("us", "昨夜美國市場"),
    ("markets", "台股美股"),
    ("watch", "今天要看什麼"),
    ("verdict", "本站判定"),
]
CHECKED_SECTIONS = ("us", "markets", "watch", "verdict")   # 數字要對得上素材的欄目

STORIES_MIN, STORIES_MAX = 3, 5
STORY_PARAGRAPHS = (1, 3)
SECTION_PARAGRAPHS = (1, 3)
SOURCES_MAX = 3
LENGTH_TARGET = (1000, 1500)      # 說明書上寫的
LENGTH_HARD = (800, 2000)         # 超出就不出刊

# 全文都不准出現：本站不替任何人說「預期」是什麼，也不給操作建議
BANNED = ["優於預期", "不如預期", "符合預期", "高於預期", "低於預期", "好於預期", "差於預期",
          "預期之內", "市場共識", "共識預期", "投資建議", "建議買", "建議賣", "建議加碼",
          "建議減碼", "逢低布局", "逢低買", "逢高賣", "值得布局", "進場時機"]
# 固定欄目不准出現：新聞段可以轉述「路透報導，市場預期……」，本站自己的欄目不行
SECTION_BANNED = ["市場預期", "共識"]
OVERNIGHT_WORDS = ["昨夜", "昨晚", "隔夜"]

# 估計花費（美元／百萬 token）。只拿來印在紀錄裡與月度守門，帳單以 Console 為準。
PRICES = {
    "claude-opus-5-5": {"input": 4.00, "output": 20.00, "cache_write": 5.00, "cache_read": 0.20},
}
SEARCH_PRICE = 0.01               # 每次網頁搜尋 $10／1,000 次
MONTHLY_BUDGET_USD = 18.0         # 使用者給這個功能的額度是每月 15–20 美元


# --------------------------------------------------------- 美股交易日 --

# 紐約證交所休市日。只寫到 2027 年底；剩不到 60 天時建置會提醒補下一年
# （排完之後只能退回「週一到週五都開盤」，假日那天的晨報會把前一天說成昨夜）。
NYSE_HOLIDAYS = {
    date(2026, 1, 1), date(2026, 1, 19), date(2026, 2, 16), date(2026, 4, 3),
    date(2026, 5, 25), date(2026, 6, 19), date(2026, 7, 3), date(2026, 9, 7),
    date(2026, 11, 26), date(2026, 12, 25),
    date(2027, 1, 1), date(2027, 1, 18), date(2027, 2, 15), date(2027, 3, 26),
    date(2027, 5, 31), date(2027, 6, 18), date(2027, 7, 5), date(2027, 9, 6),
    date(2027, 11, 25), date(2027, 12, 24),
}
NYSE_CALENDAR_END = date(2027, 12, 31)


def us_trading_day(day: date) -> bool:
    return day.weekday() < 5 and day not in NYSE_HOLIDAYS


def session(issue_date: date) -> dict:
    """這一期的「昨夜」是哪一個美股交易日。

    台北早上 7 點是美東前一天傍晚，收盤已經結束。前一天（美東）有開盤，那就是昨夜；
    沒有（台北的週日、週一，或美國假日的隔天），最近一次收盤是更早的那個交易日，
    這一期不能寫「昨夜美股」。
    """
    day = issue_date - timedelta(days=1)
    while not us_trading_day(day):
        day -= timedelta(days=1)
    overnight = day == issue_date - timedelta(days=1)
    heading = ("昨夜美國市場" if overnight
               else f"最近一個交易日的美國市場（{day.month}/{day.day} 週{WEEKDAYS[day.weekday()]}）")
    return {"us_date": day.isoformat(), "overnight": overnight, "heading": heading,
            "calendar_known": issue_date <= NYSE_CALENDAR_END}


def session_note(issue_date: date) -> str:
    """給模型的那一行：今天是哪天、昨夜有沒有美股。它也是素材的一部分（日期數字從這裡來）。"""
    s = session(issue_date)
    us = date.fromisoformat(s["us_date"])
    head = (f"出刊日：{issue_date.isoformat()}（週{WEEKDAYS[issue_date.weekday()]}，台北）；"
            f"昨天是 {(issue_date - timedelta(days=1)).isoformat()}，"
            f"明天是 {(issue_date + timedelta(days=1)).isoformat()}。")
    if s["overnight"]:
        return head + (f"\n最近一個美股交易日：{us.isoformat()}（週{WEEKDAYS[us.weekday()]}，美東），"
                       "就是昨夜。")
    return head + (f"\n昨夜（美東 {(issue_date - timedelta(days=1)).isoformat()}）美股休市。"
                   f"最近一次收盤是 {us.isoformat()}（週{WEEKDAYS[us.weekday()]}，美東）——"
                   "這一期不能寫「昨夜」「昨晚」「隔夜」美股，要寫那一天的日期。")


# ------------------------------------------------------------ 數字檢查 --

# 千分位逗號只認「後面剛好三位」，其餘逗號是標點
NUMBER_RE = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?")
# 文章裡的數字：緊貼在英文字母後面的（M1B、Q3、S&P500 寫成一個字時）是名字的一部分
ARTICLE_NUMBER_RE = re.compile(r"(?<![A-Za-z\d.,])(?:\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)")
# 名字裡的數字，不是數據
NAME_RE = re.compile(r"S&P\s*500|標普\s*500|(?:Nasdaq|那斯達克)\s*100|(?:Russell|羅素)\s*2000"
                     r"|道瓊\s*30|\d+\s*年期|\d+\s*天期")
SECTION_NUMBER_RE = re.compile(r"(?m)^\d+\.\s")
CLOCK_RE = re.compile(r"(?<!\d)(\d{1,2}):(\d{2})(?!\d)")


def _decimal(text: str) -> Decimal | None:
    try:
        return Decimal(text.replace(",", ""))
    except InvalidOperation:
        return None


def material_numbers(material: str) -> set[Decimal]:
    """素材裡出現過的每一個數（取絕對值）。時刻另外補上 12 小時制的寫法：
    素材寫「20:30」，文章寫「晚上 8 點半」。"""
    # 段落編號（「4. 市場快照」）不是數據：不拿掉的話 1 到 8 永遠「對得上」
    material = SECTION_NUMBER_RE.sub("", material)
    found = {abs(v) for v in (_decimal(m) for m in NUMBER_RE.findall(material)) if v is not None}
    for hour, _minute in CLOCK_RE.findall(material):
        h = int(hour)
        if h > 12:
            found.add(Decimal(h - 12))
    return found


def article_numbers(text: str) -> list[str]:
    return ARTICLE_NUMBER_RE.findall(NAME_RE.sub(" ", text))


def number_found(raw: str, allowed: set[Decimal]) -> bool:
    """文章裡的一個數，素材裡有沒有。

    可以照常四捨五入（素材 6,712.35 → 文章 6,712；2.456 → 2.46），但小於 100 的整數
    要一模一樣：失業率 4.3% 寫成 4% 算四捨五入，讀起來卻是另一個數字。
    """
    value = _decimal(raw)
    if value is None:
        return True
    value = abs(value)
    if value in allowed:
        return True
    places = len(raw.split(".", 1)[1]) if "." in raw else 0
    if places == 0 and value < 100:
        return False
    quantum = Decimal(1).scaleb(-places)
    for candidate in allowed:
        for mode in (ROUND_HALF_UP, ROUND_HALF_EVEN):
            if candidate.quantize(quantum, rounding=mode) == value:
                return True
    return False


def unmatched_numbers(issue: dict, material: str) -> dict[str, list[str]]:
    """{欄目: [素材裡找不到的數字]}。全部對得上回空 dict。"""
    allowed = material_numbers(material)
    out: dict[str, list[str]] = {}
    for key in CHECKED_SECTIONS:
        text = "\n".join((issue.get("sections") or {}).get(key, {}).get("paragraphs") or [])
        missing = [n for n in article_numbers(text) if not number_found(n, allowed)]
        if missing:
            out[key] = list(dict.fromkeys(missing))
    return out


def count_numbers(issue: dict) -> int:
    return sum(len(article_numbers("\n".join((issue.get("sections") or {}).get(k, {})
                                             .get("paragraphs") or [])))
               for k in CHECKED_SECTIONS)


# ------------------------------------------------------------ 形狀與用語 --

def _paragraphs(raw) -> list[str]:
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    return [" ".join(p.split()) for p in raw if isinstance(p, str) and p.strip()]


def _clean_source(raw) -> dict | None:
    if not isinstance(raw, dict):
        return None
    url = str(raw.get("url") or "").strip()
    if not url.lower().startswith(("http://", "https://")):
        return None
    return {"title": " ".join(str(raw.get("title") or "").split()),
            "outlet": " ".join(str(raw.get("outlet") or "").split()),
            "url": url}


def normalise(raw: dict) -> dict:
    """把寫稿結果（或檔案內容）整理成固定形狀。不檢查對錯，只整理。"""
    raw = raw if isinstance(raw, dict) else {}
    stories = []
    for item in raw.get("stories") or []:
        if not isinstance(item, dict):
            continue
        stories.append({
            "headline": " ".join(str(item.get("headline") or "").split()),
            "paragraphs": _paragraphs(item.get("paragraphs")),
            "sources": [s for s in (_clean_source(x) for x in item.get("sources") or []) if s],
        })
    sections = {}
    raw_sections = raw.get("sections") or {}
    for key, default in SECTIONS:
        block = raw_sections.get(key) if isinstance(raw_sections, dict) else None
        if isinstance(block, list):
            block = {"paragraphs": block}
        block = block if isinstance(block, dict) else {}
        sections[key] = {"heading": str(block.get("heading") or default).strip(),
                         "paragraphs": _paragraphs(block.get("paragraphs"))}
    out = dict(raw)
    out.update({
        "date": str(raw.get("date") or ""),
        "written_at": str(raw.get("written_at") or ""),
        "title": " ".join(str(raw.get("title") or "").split()),
        "lede": " ".join(str(raw.get("lede") or "").split()),
        "stories": stories,
        "sections": sections,
    })
    return out


def body_length(issue: dict) -> int:
    """全文字數：導言、要聞內文、四個欄目（不含標題與來源），不算空白。"""
    parts = [issue.get("lede") or ""]
    for story in issue.get("stories") or []:
        parts += story.get("paragraphs") or []
    for block in (issue.get("sections") or {}).values():
        parts += block.get("paragraphs") or []
    return len(re.sub(r"\s", "", "".join(parts)))


def written_at(issue: dict) -> datetime | None:
    try:
        stamp = datetime.fromisoformat(str(issue.get("written_at") or ""))
    except ValueError:
        return None
    return stamp if stamp.tzinfo is not None else None


def problems(issue: dict, *, content: bool = True) -> list[str]:
    """不靠素材就能檢查的那幾關。回傳空 list 表示可以登。

    content=False 只查形狀與日期（建置讀檔時用）：用語、長度、休市這幾條是寫稿時的關卡，
    已經登過的一期不能因為之後規則變嚴就從網站上消失——跟深度專題同一個道理。
    """
    out: list[str] = []
    try:
        day = date.fromisoformat(issue.get("date") or "")
    except ValueError:
        return ["日期不是 YYYY-MM-DD"]
    stamp = written_at(issue)
    if stamp is None:
        out.append("寫稿時間不是帶時區的時間（要像 2026-10-15T06:52:00+08:00）")
    elif stamp.astimezone(clock.TAIPEI).date() != day:
        out.append(f"寫稿時間 {stamp.isoformat()} 不在出刊日 {day.isoformat()}（台北）")
    if not issue.get("title"):
        out.append("沒有標題")
    if not issue.get("lede"):
        out.append("沒有導言")

    stories = issue.get("stories") or []
    if not STORIES_MIN <= len(stories) <= STORIES_MAX:
        out.append(f"要聞 {len(stories)} 則，要 {STORIES_MIN}–{STORIES_MAX} 則")
    for i, story in enumerate(stories, 1):
        if not story.get("headline"):
            out.append(f"第 {i} 則要聞沒有標題")
        lo, hi = STORY_PARAGRAPHS
        if not lo <= len(story.get("paragraphs") or []) <= hi:
            out.append(f"第 {i} 則要聞 {len(story.get('paragraphs') or [])} 段，要 {lo}–{hi} 段")
        if not story.get("sources"):
            out.append(f"第 {i} 則要聞沒有來源")
        elif len(story["sources"]) > SOURCES_MAX:
            out.append(f"第 {i} 則要聞列了 {len(story['sources'])} 個來源，上限 {SOURCES_MAX}")
        elif any(not s.get("outlet") for s in story["sources"]):
            out.append(f"第 {i} 則要聞的來源沒寫媒體名稱")

    for key, name in SECTIONS:
        count = len(((issue.get("sections") or {}).get(key) or {}).get("paragraphs") or [])
        lo, hi = SECTION_PARAGRAPHS
        if not lo <= count <= hi:
            out.append(f"「{name}」{count} 段，要 {lo}–{hi} 段")

    if not content:
        return out

    length = body_length(issue)
    lo, hi = LENGTH_HARD
    if not lo <= length <= hi:
        out.append(f"全文 {length} 字，要在 {lo}–{hi} 之間（說明書寫 "
                   f"{LENGTH_TARGET[0]}–{LENGTH_TARGET[1]}）")

    everything = "\n".join([issue.get("title") or "", issue.get("lede") or ""]
                           + [s.get("headline") or "" for s in stories]
                           + [p for s in stories for p in s.get("paragraphs") or []]
                           + [p for b in (issue.get("sections") or {}).values()
                              for p in b.get("paragraphs") or []])
    for word in BANNED:
        if word in everything:
            out.append(f"出現「{word}」")
    fixed = "\n".join(p for b in (issue.get("sections") or {}).values()
                      for p in b.get("paragraphs") or [])
    for word in SECTION_BANNED:
        if word in fixed:
            out.append(f"固定欄目出現「{word}」")

    if not session(day)["overnight"]:
        markets = "\n".join([issue.get("title") or ""]
                            + [p for k in ("us", "markets")
                               for p in (issue.get("sections") or {}).get(k, {}).get("paragraphs") or []])
        for word in OVERNIGHT_WORDS:
            if word in markets:
                out.append(f"上一個美股交易日不是昨夜，卻寫了「{word}」")
    return out


def verify_sources(issue: dict, seen_urls: set[str]) -> tuple[dict, list[str]]:
    """只留下這一輪網頁搜尋真的回傳過的網址。模型自己想出來的網址不算來源。"""
    seen = {_url_key(u) for u in seen_urls}
    dropped = []
    for story in issue.get("stories") or []:
        kept = []
        for source in story.get("sources") or []:
            if _url_key(source["url"]) in seen:
                kept.append(source)
            else:
                dropped.append(source["url"])
        story["sources"] = kept
    return issue, dropped


def _url_key(url: str) -> str:
    url = url.strip().split("#", 1)[0]
    scheme, _, rest = url.partition("://")
    host, slash, path = rest.partition("/")
    return f"{scheme.lower()}://{host.lower()}{slash}{path}".rstrip("/")


# ------------------------------------------------------------ 讀寫 --

def path_for(day: date, directory: str | None = None) -> str:
    directory = directory or MORNING_DIR
    return os.path.join(directory, f"{day.isoformat()}.json")


def failed_path(day: date, directory: str | None = None) -> str:
    directory = directory or MORNING_DIR
    return os.path.join(directory, f"failed-{day.isoformat()}.json")


def load_all(directory: str | None = None) -> tuple[list[dict], dict[str, list[str]]]:
    """(可以登的各期，新的在前；{檔名: 不能登的原因})。"""
    directory = directory or MORNING_DIR
    issues, bad = [], {}
    if not os.path.isdir(directory):
        return issues, bad
    for name in sorted(os.listdir(directory)):
        match = FILENAME_RE.match(name)
        if not match:
            continue
        try:
            with open(os.path.join(directory, name), encoding="utf-8") as fh:
                issue = normalise(json.load(fh))
        except (OSError, ValueError) as exc:
            bad[name] = [f"讀不到：{exc}"]
            continue
        found = problems(issue, content=False)
        if issue["date"] != match.group(1):
            found.insert(0, f"檔名是 {match.group(1)}，內容寫 {issue['date']}")
        if found:
            bad[name] = found
            continue
        issue["day"] = date.fromisoformat(issue["date"])
        issue["path"] = f"/morning/{issue['date']}/"
        issues.append(issue)
    issues.sort(key=lambda i: i["day"], reverse=True)
    return issues, bad


def failure(day: date, directory: str | None = None) -> dict | None:
    """那一天沒出刊的紀錄（寫稿腳本留下的），沒有就回 None。"""
    directory = directory or MORNING_DIR
    try:
        with open(failed_path(day, directory), encoding="utf-8") as fh:
            record = json.load(fh)
    except (OSError, ValueError):
        return None
    return record if isinstance(record, dict) else None


def estimate_cost(usage: dict, model: str) -> float | None:
    price = PRICES.get(model)
    if not price:
        return None
    million = 1_000_000
    return round(
        (usage.get("input_tokens") or 0) * price["input"] / million
        + (usage.get("output_tokens") or 0) * price["output"] / million
        + (usage.get("cache_creation_input_tokens") or 0) * price["cache_write"] / million
        + (usage.get("cache_read_input_tokens") or 0) * price["cache_read"] / million
        + (usage.get("web_search_requests") or 0) * SEARCH_PRICE, 4)


def month_spend(year: int, month: int, directory: str | None = None) -> float:
    """這個月已經花掉的估計金額：出刊的與沒出刊的（寫了但沒過檢查也花了錢）都算。"""
    directory = directory or MORNING_DIR
    total = 0.0
    if not os.path.isdir(directory):
        return total
    for name in os.listdir(directory):
        match = FILENAME_RE.match(name) or FAILED_RE.match(name)
        if not match or not match.group(1).startswith(f"{year:04d}-{month:02d}"):
            continue
        try:
            with open(os.path.join(directory, name), encoding="utf-8") as fh:
                total += float(((json.load(fh) or {}).get("usage") or {}).get("cost_usd") or 0)
        except (OSError, ValueError, TypeError, AttributeError):
            continue
    return round(total, 4)


def weekday(day: date) -> str:
    return f"週{WEEKDAYS[day.weekday()]}"
