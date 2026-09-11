"""Markdown → HTML，只涵蓋深度專題報告實際用得到的語法。

專案是純 stdlib，沒有 markdown 套件可用，也不需要一個完整實作：報告由
同一份規格（deep-dive/PROMPT.md §五、§七）產出，語法集合是固定的——標題、
粗體、斜體、行內程式碼、清單（含 checkbox）、引用、水平線、表格。

原則是**不吞內容**：遇到不認識的行就當普通段落輸出，寧可少一層排版，
也不要讓一段文字在頁面上消失。
"""
from __future__ import annotations

import re

from .html import esc

CODE_RE = re.compile(r"`([^`]+)`")
BOLD_RE = re.compile(r"\*\*(.+?)\*\*", re.S)
EM_RE = re.compile(r"(?<!\*)\*(\S[^*\n]*?)\*(?!\*)")
LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
RULE_RE = re.compile(r"^(-{3,}|\*{3,}|_{3,})$")
UL_RE = re.compile(r"^[-*+]\s+(.*)$")
OL_RE = re.compile(r"^\d+[.)]\s+(.*)$")
TASK_RE = re.compile(r"^\[([ xX])\]\s+(.*)$")
SEPARATOR_RE = re.compile(r"^\|?[\s:|-]*-[\s:|-]*\|?$")

# 右對齊的判準：整格看起來就是一個數字（可帶正負號、貨幣、單位）。
NUMERIC_RE = re.compile(
    r"^[+\-−–~約]?\$?\d[\d,.]*\s*"
    r"(?:%|x|X|倍|pp|bp|個百分點|億|萬|億元|萬元|美元|元)?$")

CJK = re.compile(r"[⺀-鿿豈-﫿＀-￯]")


def _join(lines: list[str]) -> str:
    """接續的段落行：中文之間不補空格，英文之間補。"""
    text = lines[0]
    for nxt in lines[1:]:
        glue = "" if (text and nxt and CJK.search(text[-1]) and CJK.search(nxt[0])) else " "
        text += glue + nxt
    return text


def inline(text: str) -> str:
    """行內語法。先跳脫，再套規則——順序反過來就會把 HTML 放進頁面。"""
    out = esc(text.strip())
    stash: list[str] = []

    def _keep(match: re.Match) -> str:
        stash.append(match.group(1))
        return f"\x00{len(stash) - 1}\x00"

    out = CODE_RE.sub(_keep, out)          # 程式碼裡的 * 不是強調
    out = LINK_RE.sub(
        r'<a href="\2" target="_blank" rel="noopener noreferrer">\1</a>', out)
    out = BOLD_RE.sub(r"<strong>\1</strong>", out)
    out = EM_RE.sub(r"<em>\1</em>", out)
    return re.sub(r"\x00(\d+)\x00",
                  lambda m: f"<code>{stash[int(m.group(1))]}</code>", out)


def plain(text: str) -> str:
    """去掉行內標記後的純文字（給標題、摘要、<title> 用）。"""
    out = CODE_RE.sub(r"\1", text.strip())
    out = LINK_RE.sub(r"\1", out)
    out = BOLD_RE.sub(r"\1", out)
    return EM_RE.sub(r"\1", out).strip()


def _cells(row: str) -> list[str]:
    row = row.strip()
    if row.startswith("|"):
        row = row[1:]
    if row.endswith("|"):
        row = row[:-1]
    return [c.strip() for c in row.split("|")]


def _table(rows: list[list[str]]) -> str:
    header, body = rows[0], rows[1:]
    width = len(header)
    body = [r + [""] * (width - len(r)) if len(r) < width else r[:width] for r in body]

    # 逐欄決定對齊：整欄多數是數字才右對齊，混著文字的欄位靠左比較好讀。
    numeric = []
    for col in range(width):
        values = [plain(r[col]) for r in body if plain(r[col]) not in ("", "—", "-")]
        hits = sum(1 for v in values if NUMERIC_RE.match(v))
        numeric.append(bool(values) and hits >= max(1, int(len(values) * 0.6)))

    head = "".join(f"<th>{inline(c)}</th>" for c in header)
    lines = []
    for row in body:
        cells = "".join(
            f'<td{" class=\"num\"" if numeric[i] else ""}>{inline(c)}</td>'
            for i, c in enumerate(row))
        lines.append(f"<tr>{cells}</tr>")
    return (f'<div class="table-wrap"><table><thead><tr>{head}</tr></thead>'
            f'<tbody>{"".join(lines)}</tbody></table></div>')


def _list_item(text: str) -> str:
    task = TASK_RE.match(text)
    if not task:
        return f"<li>{inline(text)}</li>"
    done = task.group(1).lower() == "x"
    mark = ("<span class=\"dd-check\" aria-hidden=\"true\">"
            + ("✓" if done else "○") + "</span>")
    label = "已通過：" if done else "未通過："
    return (f'<li class="dd-task">{mark}<span class="sr-only">{label}</span>'
            f'{inline(task.group(2))}</li>')


def to_html(text: str) -> str:
    lines = text.replace("\r\n", "\n").split("\n")
    out: list[str] = []
    i, total = 0, len(lines)

    while i < total:
        raw = lines[i]
        line = raw.strip()

        if not line:
            i += 1
            continue

        if line.startswith("```"):                                    # 程式碼區塊
            i += 1
            block = []
            while i < total and not lines[i].strip().startswith("```"):
                block.append(lines[i])
                i += 1
            i += 1
            out.append(f"<pre><code>{esc(chr(10).join(block))}</code></pre>")
            continue

        if RULE_RE.match(line):
            out.append("<hr>")
            i += 1
            continue

        heading = HEADING_RE.match(line)
        if heading:
            level = min(len(heading.group(1)), 6)
            out.append(f"<h{level}>{inline(heading.group(2))}</h{level}>")
            i += 1
            continue

        if line.startswith(">"):
            quote = []
            while i < total and lines[i].strip().startswith(">"):
                quote.append(lines[i].strip().lstrip(">").strip())
                i += 1
            out.append(f'<blockquote>{inline(_join([q for q in quote if q]))}</blockquote>')
            continue

        # 表格：這一行有管線，且下一行是分隔列
        if "|" in line and i + 1 < total and SEPARATOR_RE.match(lines[i + 1].strip()) \
                and "|" in lines[i + 1]:
            rows = [_cells(line)]
            i += 2
            while i < total and "|" in lines[i] and lines[i].strip():
                rows.append(_cells(lines[i]))
                i += 1
            out.append(_table(rows))
            continue

        if UL_RE.match(line) or OL_RE.match(line):
            ordered = bool(OL_RE.match(line))
            pattern = OL_RE if ordered else UL_RE
            items = []
            while i < total and pattern.match(lines[i].strip()):
                items.append(_list_item(pattern.match(lines[i].strip()).group(1)))
                i += 1
            tag = "ol" if ordered else "ul"
            cls = ' class="dd-tasks"' if "dd-task" in "".join(items) else ""
            out.append(f"<{tag}{cls}>{''.join(items)}</{tag}>")
            continue

        paragraph = []
        while i < total and lines[i].strip():
            nxt = lines[i].strip()
            if (HEADING_RE.match(nxt) or RULE_RE.match(nxt) or nxt.startswith(">")
                    or nxt.startswith("```") or UL_RE.match(nxt) or OL_RE.match(nxt)
                    or ("|" in nxt and i + 1 < total
                        and SEPARATOR_RE.match(lines[i + 1].strip()))):
                break
            paragraph.append(nxt)
            i += 1
        if paragraph:
            out.append(f"<p>{inline(_join(paragraph))}</p>")
        else:
            i += 1

    return "".join(out)


def split_h2(text: str) -> list[tuple[str, str]]:
    """以 H2 切段，回傳 [(標題, 該段 markdown)]。H2 之前的內容標題為空字串。"""
    blocks: list[tuple[str, list[str]]] = [("", [])]
    for line in text.replace("\r\n", "\n").split("\n"):
        heading = HEADING_RE.match(line.strip())
        if heading and len(heading.group(1)) == 2:
            blocks.append((plain(heading.group(2)), []))
        else:
            blocks[-1][1].append(line)
    return [(title, "\n".join(body).strip()) for title, body in blocks
            if title or "\n".join(body).strip()]


def first_paragraph(text: str) -> str:
    """第一段純文字——給索引頁的摘要用，不含標題、引用與表格。"""
    for line in text.replace("\r\n", "\n").split("\n"):
        line = line.strip()
        if (not line or line.startswith((">", "#", "|", "```"))
                or RULE_RE.match(line) or UL_RE.match(line) or OL_RE.match(line)):
            continue
        stripped = plain(line)
        if len(stripped) < 40 and stripped.endswith("："):   # 只是個小標，不是內文
            continue
        return stripped
    return ""
