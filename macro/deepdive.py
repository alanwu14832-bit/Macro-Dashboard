"""每日資本市場深度專題（data/deep-dive/*.md）。

報告由另一個排程任務（deep-dive routine，規格在
`../deep-dive/PROMPT.md`）每天寫進 `../deep-dive/reports/`——那個目錄不在
這個 repo 裡。`sync()` 在本機建置時把它鏡像一份到 `data/deep-dive/` 並進
版控，因為雲端（GitHub Actions）建置只看得到 repo 裡的檔案：沒有這份副本，
網站上的深度專題就只有本機建置時才有內容。

鏡像是單向、只增不減的：來源端刪檔不會把網站上的報告拿掉。報告是已發表的
判斷紀錄，跟 data/archive/ 一樣，事後消失比留著更糟。

解析刻意寬鬆。報告的抬頭格式這半年換過三種寫法（`**類別**：C. …`、
`**類別 A｜…**`、`**類別 D（…）｜日期**`），所以每個欄位抓不到就留空、
由頁面自己降級，不要讓一篇報告因為抬頭寫法不同就整篇不上站。
"""
from __future__ import annotations

import os
import re
from datetime import date

from . import paths
from .render import markdown

DEEPDIVE_DIR = os.path.join(paths.DATA_DIR, "deep-dive")
TOPIC_LOG = "topic-log.md"

# 來源目錄：環境變數優先，其次是專案旁邊的 deep-dive/reports/。
SOURCE_DIR = os.environ.get("DEEP_DIVE_REPORTS") or os.path.join(
    os.path.dirname(paths.ROOT_DIR), "deep-dive", "reports")

FILENAME_RE = re.compile(
    r"^(deep-dive|weekly-review|FAILED)-(\d{4}-\d{2}-\d{2})-?(.*)\.md$")

CATEGORY_RE = re.compile(r"類別[^A-E]{0,4}([A-E])")
# 只認「本篇為 X 的補做」這句宣告。單純提到補做規則的排程說明不算。
BACKFILL_RE = re.compile(r"本篇為[^\n]{0,24}補做")
TARGET_RE = re.compile(
    r"(?:核心標的|核心資產|受影響標的|核心變數)[^:：\n]{0,4}[:：]\s*([^｜|\n]+)")

CATEGORIES = {
    "A": "產業結構",
    "B": "總經傳導",
    "C": "個股論點",
    "D": "跨市場比較",
    "E": "本週回顧",
}
CATEGORY_FULL = {
    "A": "A 產業結構性議題：供應鏈重組、競爭格局、技術世代轉換",
    "B": "B 總經傳導機制：某個總經變數如何傳導到哪些資產、誰受益誰受害",
    "C": "C 個股／個股群組論點：護城河、財務品質、估值、催化劑、風險",
    "D": "D 跨市場／跨資產比較：相對價值與資金流向",
    "E": "E 本週回顧：逐篇判定強化／中性／削弱／證偽，並檢討最錯的一篇",
}


def sync(source: str = SOURCE_DIR, target: str = DEEPDIVE_DIR) -> list[str]:
    """把來源目錄的報告鏡像到 data/deep-dive/，回傳這次真的有變動的檔名。

    連 topic-log.md 一起帶：報告抬頭的類別標註換過好幾種寫法，有幾篇根本
    沒寫，主題紀錄那張表是唯一每天都有類別的地方。
    """
    if not os.path.isdir(source):
        return []
    os.makedirs(target, exist_ok=True)
    changed = []
    names = sorted(os.listdir(source))
    log = os.path.join(os.path.dirname(source), TOPIC_LOG)
    if os.path.isfile(log):
        names.append(os.path.relpath(log, source))
    for name in names:
        if not FILENAME_RE.match(os.path.basename(name)) \
                and os.path.basename(name) != TOPIC_LOG:
            continue
        src = os.path.join(source, name)
        dst = os.path.join(target, os.path.basename(name))
        try:
            with open(src, "rb") as fh:
                payload = fh.read()
            if os.path.exists(dst):
                with open(dst, "rb") as fh:
                    if fh.read() == payload:
                        continue
            with open(dst, "wb") as fh:
                fh.write(payload)
            changed.append(os.path.basename(name))
        except OSError:
            continue
    return changed


def topic_log(directory: str = DEEPDIVE_DIR) -> dict[str, dict]:
    """主題紀錄那張表 → {日期: {類別, 狀態}}。沒有這個檔就回空的。"""
    path = os.path.join(directory, TOPIC_LOG)
    rows: dict[str, dict] = {}
    try:
        with open(path, encoding="utf-8") as fh:
            lines = fh.read().split("\n")
    except OSError:
        return rows
    for line in lines:
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 6 or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", cells[0]):
            continue
        rows[cells[0]] = {"category": cells[1] if cells[1] in CATEGORIES else "",
                          "status": cells[-1]}
    return rows


def _meta_lines(text: str) -> list[str]:
    """抬頭：H1 之後、第一個 H2 之前的粗體行，各種寫法都收。"""
    lines = []
    for raw in text.split("\n"):
        line = raw.strip()
        if line.startswith("## "):
            break
        if line.startswith("**") and line.endswith("**") or (
                line.startswith("**") and "：" in line):
            lines.append(markdown.plain(line))
    return lines


def parse(text: str, filename: str) -> dict | None:
    name = FILENAME_RE.match(filename)
    if not name:
        return None
    kind, when, topic = name.group(1), name.group(2), name.group(3)
    try:
        day = date.fromisoformat(when)
    except ValueError:
        return None

    head = "\n".join(text.split("\n")[:14])
    title = ""
    for raw in text.split("\n"):
        if raw.strip().startswith("# "):
            title = markdown.plain(raw.strip()[2:])
            break

    category = ""
    hit = CATEGORY_RE.search(head)
    if hit:
        category = hit.group(1)
    elif kind == "weekly-review":
        category = "E"

    targets = ""
    hit = TARGET_RE.search(head)
    if hit:
        targets = markdown.plain(hit.group(1)).strip("＊*　 ")

    # 摘要取「結論先行」那一段的第一段；沒有那一段（週回顧）就取第一段有內
    # 文的區塊——直接對全文抓第一段會抓到抬頭那幾行粗體。
    blocks = markdown.split_h2(text)
    summary = ""
    for heading, body in blocks:
        if "結論先行" in heading:
            summary = markdown.first_paragraph(body)
            break
    if not summary:
        for heading, body in blocks:
            if heading:
                summary = markdown.first_paragraph(body)
                if summary:
                    break

    slug = f"{when}-{topic}" if topic else f"{when}-{kind.lower()}"
    if kind == "weekly-review":
        title = title or f"本週回顧（{when}）"
    if kind == "FAILED":
        title = title or f"{when} 執行失敗"

    return {
        "kind": kind,
        "slug": slug,
        "path": f"/deep-dive/{slug}/",
        "date": day,
        "title": title or slug,
        "category": category,
        "category_label": CATEGORIES.get(category, ""),
        "targets": targets,
        "summary": summary,
        "meta": _meta_lines(text),
        "backfill": topic.endswith("backfill") or bool(BACKFILL_RE.search(head)),
        "failed": kind == "FAILED",
        "chars": len(re.sub(r"\s", "", text)),
        "markdown": text,
    }


def load_all(directory: str = DEEPDIVE_DIR) -> list[dict]:
    """全部報告，新的在前。讀不到或格式不符的檔案直接略過。"""
    if not os.path.isdir(directory):
        return []
    log = topic_log(directory)
    reports = []
    for name in sorted(os.listdir(directory)):
        if not FILENAME_RE.match(name):
            continue
        try:
            with open(os.path.join(directory, name), encoding="utf-8") as fh:
                parsed = parse(fh.read(), name)
        except OSError:
            continue
        if not parsed:
            continue
        # 主題紀錄優先於報告抬頭：抬頭偶爾會提到「原規劃類別 D」這種被改掉
        # 的排程說明，正則分不出哪個才是這篇實際的類別，那張表分得出來。
        logged = log.get(parsed["date"].isoformat(), {})
        parsed["category"] = logged.get("category") or parsed["category"]
        parsed["category_label"] = CATEGORIES.get(parsed["category"], "")
        parsed["status"] = logged.get("status", "")
        if parsed["status"] == "backfill":
            parsed["backfill"] = True
        reports.append(parsed)
    reports.sort(key=lambda r: (r["date"], r["slug"]), reverse=True)
    return reports
