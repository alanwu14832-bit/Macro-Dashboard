"""今日要聞整理（data/brief.json）。

網站本身沒有模型，只會做關鍵字聚合；「整理過的 headline」由排程任務
（Claude Code 的 macro-dashboard-daily-build）讀完 /news/ 後寫進這個檔，
再由建置渲染到總覽。檔案不在或太舊時，總覽退回原始標題並明講「未整理」。

格式：
{
  "date": "2026-09-07",
  "generated_at": "2026-09-07T16:50:00+08:00",
  "sections": [
    {"key": "macro", "title": "總經數據與事件",
     "items": [{"headline": "一句話標題", "detail": "為什麼重要（可省略）",
                "source": "Reuters／4 家", "link": "https://…（可省略）"}]},
    ...
  ],
  "synthesis": "與本期判斷的交集：…",
  "article": {"us": ["數據那一段", "新聞那一段"], "tw": ["…", "…"],
              "written_at": "（可省略）導讀寫的時間跟 generated_at 不同時才需要"}
}

article 是頭版頭條底下的「今日導讀」：美國版與台灣版各一篇，各兩段。它由排程任務
（一個語言模型）寫，不是機構的數字，也不是本站規則的判定，所以版面上自己有一枚印
（摘），而且永遠帶著寫的時間。這裡只管三件事，全部是機械檢查，不判斷內容對不對：

  形狀  每版最多兩段、每段是一串字；空的、型別不對的不要
  長度  一版超過 STORY_HARD 個字就不上版（寧可這一塊不出現，也不讓頭版被撐開）
  新鮮  寫了超過 STORY_MAX_AGE_HOURS 小時的不登——文章裡的「今天」已經不是今天

不合格的那一版會被丟掉並留下原因（article_problems），建置時印出來；其餘照常。
舊格式（沒有 article）的 brief.json 完全不受影響。
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta

from . import clock, paths

BRIEF_FILE = os.path.join(paths.DATA_DIR, "brief.json")
MAX_AGE_DAYS = 2
SECTION_ORDER = ["macro", "company", "geo", "taiwan"]
SECTION_TITLES = {"macro": "總經數據與事件", "company": "公司新聞",
                  "geo": "地緣政治", "taiwan": "台灣"}

# 今日導讀
STORY_EDITIONS = {"us": "美國版", "tw": "台灣版"}
STORY_PARAGRAPHS = 2
STORY_TARGET = 280            # 排程說明書上寫的長度（兩段合計）
STORY_HARD = 360              # 超過就不上版
STORY_MAX_AGE_HOURS = 24


def _clean_story(raw) -> tuple[list[str], str]:
    """一版的導讀 -> (段落, 問題)。問題是空字串表示可以用。"""
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return [], "不是一串段落"
    paragraphs = [" ".join(str(p).split()) for p in raw if isinstance(p, str) and p.strip()]
    if not paragraphs:
        return [], "沒有內容"
    if len(paragraphs) > STORY_PARAGRAPHS:
        return [], f"有 {len(paragraphs)} 段，上限是 {STORY_PARAGRAPHS} 段"
    length = sum(len(p) for p in paragraphs)
    if length > STORY_HARD:
        return [], f"{length} 個字，超過上限 {STORY_HARD}（說明書要求 {STORY_TARGET} 以內）"
    return paragraphs, ""


def _clean_article(raw) -> tuple[dict, list[str]]:
    article, problems = {}, []
    if raw is None:
        return article, problems
    if not isinstance(raw, dict):
        return article, ["導讀（article）的格式不對：要是 {\"us\": [...], \"tw\": [...]}"]
    for key, label in STORY_EDITIONS.items():
        if key not in raw:
            continue
        paragraphs, problem = _clean_story(raw[key])
        if problem:
            problems.append(f"{label}導讀沒有上版：{problem}")
        else:
            article[key] = paragraphs
    if article and str(raw.get("written_at") or "").strip():
        article["written_at"] = str(raw["written_at"]).strip()
    return article, problems


def _clean_item(raw) -> dict | None:
    if not isinstance(raw, dict):
        return None
    headline = str(raw.get("headline") or "").strip()
    if not headline:
        return None
    link = str(raw.get("link") or "").strip()
    if not link.lower().startswith(("http://", "https://")):
        link = ""
    return {"headline": headline,
            "detail": str(raw.get("detail") or "").strip(),
            "source": str(raw.get("source") or "").strip(),
            "link": link}


def normalise(raw: dict) -> dict | None:
    """把檔案內容整理成固定形狀；沒有任何有效條目就回 None。"""
    if not isinstance(raw, dict):
        return None
    try:
        when = date.fromisoformat(str(raw.get("date")))
    except (TypeError, ValueError):
        return None
    by_key = {}
    for sec in raw.get("sections") or []:
        if not isinstance(sec, dict):
            continue
        key = str(sec.get("key") or "").strip()
        items = [i for i in (_clean_item(x) for x in sec.get("items") or []) if i]
        if key in SECTION_TITLES:
            by_key[key] = {"key": key, "title": SECTION_TITLES[key], "items": items}
    sections = [by_key[k] for k in SECTION_ORDER if k in by_key]
    if not any(s["items"] for s in sections):
        return None
    article, problems = _clean_article(raw.get("article"))
    return {"date": when, "generated_at": str(raw.get("generated_at") or ""),
            "sections": sections,
            "synthesis": str(raw.get("synthesis") or "").strip(),
            "article": article, "article_problems": problems}


def written_at(brief: dict | None) -> datetime | None:
    """要聞與導讀是什麼時候寫的。沒有帶時區的時間就當作不知道——
    不知道什麼時候寫的文章不能登，因為沒辦法告訴讀者它有多舊。"""
    brief = brief or {}
    # 導讀有自己的時間就用它（要聞沒重寫、只補導讀的時候兩者不同）
    raw = (brief.get("article") or {}).get("written_at") or brief.get("generated_at") or ""
    try:
        stamp = datetime.fromisoformat(str(raw))
    except ValueError:
        return None
    return stamp if stamp.tzinfo is not None else None


def story(brief: dict | None, edition: str, now: datetime | None = None) -> dict | None:
    """這一版現在可以登的導讀：{"paragraphs": [...], "written": datetime}，沒有就回 None。"""
    paragraphs = ((brief or {}).get("article") or {}).get(edition)
    written = written_at(brief)
    if not paragraphs or written is None:
        return None
    age = (now or clock.now()) - written
    # 寫的時間在未來（時鐘或手誤）跟太舊一樣不可信
    if age < timedelta(minutes=-10) or age > timedelta(hours=STORY_MAX_AGE_HOURS):
        return None
    return {"paragraphs": paragraphs, "written": written}


def problems(brief: dict | None, now: datetime | None = None) -> list[str]:
    """建置時要印出來的話：哪一版的導讀沒有上版、為什麼。"""
    if not brief:
        return []
    out = list(brief.get("article_problems") or [])
    article = brief.get("article") or {}
    if article and written_at(brief) is None:
        out.append("導讀沒有上版：generated_at 不是帶時區的時間（要像 2026-10-10T08:52:00+08:00）")
    elif article and not any(story(brief, key, now) for key in STORY_EDITIONS):
        out.append(f"導讀沒有上版：寫了超過 {STORY_MAX_AGE_HOURS} 小時（{written_at(brief).isoformat()}）")
    return out


def load(today: date | None = None, path: str = BRIEF_FILE) -> dict | None:
    """讀取並檢查新鮮度：超過 MAX_AGE_DAYS 的整理不上總覽，寧可退回原始標題。"""
    today = today or clock.today()
    try:
        with open(path, encoding="utf-8") as fh:
            brief = normalise(json.load(fh))
    except Exception:
        return None
    if brief is None or (today - brief["date"]).days > MAX_AGE_DAYS:
        return None
    return brief
