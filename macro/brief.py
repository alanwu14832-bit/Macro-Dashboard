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
  "synthesis": "與本期判斷的交集：…"
}
"""
from __future__ import annotations

import json
import os
from datetime import date

from . import paths

BRIEF_FILE = os.path.join(paths.DATA_DIR, "brief.json")
MAX_AGE_DAYS = 2
SECTION_ORDER = ["macro", "company", "geo", "taiwan"]
SECTION_TITLES = {"macro": "總經數據與事件", "company": "公司新聞",
                  "geo": "地緣政治", "taiwan": "台灣"}


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
    return {"date": when, "generated_at": str(raw.get("generated_at") or ""),
            "sections": sections,
            "synthesis": str(raw.get("synthesis") or "").strip()}


def load(today: date | None = None, path: str = BRIEF_FILE) -> dict | None:
    """讀取並檢查新鮮度：超過 MAX_AGE_DAYS 的整理不上總覽，寧可退回原始標題。"""
    today = today or date.today()
    try:
        with open(path, encoding="utf-8") as fh:
            brief = normalise(json.load(fh))
    except Exception:
        return None
    if brief is None or (today - brief["date"]).days > MAX_AGE_DAYS:
        return None
    return brief
