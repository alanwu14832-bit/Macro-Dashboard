#!/usr/bin/env python3
"""每日晨報的寫稿端——只在 GitHub Actions 跑（.github/workflows/morning.yml）。

    python3 tools/morning_brief.py --check     # 今天該不該寫（寫進 GITHUB_OUTPUT 的 due）
    python3 tools/morning_brief.py --dry-run   # 印出素材與提示詞的大小，不呼叫 API、不寫檔
    python3 tools/morning_brief.py             # 寫今天這一期 → data/morning/YYYY-MM-DD.json

流程：先跑過 build.py（快取是新的），這支用 tools/daily_digest.py 的輸出當素材——
那是數字的唯一來源——呼叫 Claude API 寫稿。新聞那一半用 API 的網頁搜尋找實際來源，
其餘四個固定欄目只准用素材裡的數字。寫完過 macro/morning.py 的機械檢查（形狀、長度、
用語、休市、數字對得上素材、來源網址真的是搜尋回傳的），沒過就把問題清單交回給模型
改一次；還是沒過就不出刊。

網站本體零依賴；這支腳本用官方的 anthropic SDK（workflow 裡 pip install，版本釘死），
跟 send_push.py 用 pywebpush 同一個理由：依賴止步於雲端的發送端，不進網站。
SDK 處理重試（429、5xx、連線錯誤）、型別化的錯誤與回應物件，自己用標準庫重寫那些
等於維護一份會漂移的 HTTP 客戶端。

沒寫成的時候（API 失敗、檢查沒過、達到花費上限）寫一份 data/morning/failed-日期.json
記下原因與花了多少，晨報頁照登上一期並標明日期；原因印在 Actions 的紀錄裡（::error::）。
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import re
import sys
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

from macro import clock, morning  # noqa: E402

MODEL = "claude-opus-5-5"
EFFORT = "medium"
MAX_TOKENS = 16000
MAX_SEARCHES = 4              # 一次寫稿最多搜尋幾次（每次 $0.01，搜尋結果另計 token）
MAX_CONTINUATIONS = 3         # 伺服器端搜尋迴圈被暫停（pause_turn）時最多接續幾次
REPAIR_ROUNDS = 1             # 檢查沒過時，把問題交回給模型改幾次
WINDOW = (6, 14)              # 排程只在台北 06:00–14:00 之間寫；手動觸發不受限
EXPECTED_COST = 0.8           # 一期大約花多少（月度守門用，第一次實跑後要依紀錄調整）
TIMEOUT = 900                 # 秒。伺服器端搜尋迴圈可能要好幾分鐘

SUBMIT_TOOL = {
    "name": "submit_brief",
    "description": "交出今天的晨報。全部欄位一次交齊；交出後程式會做機械檢查。",
    "strict": True,
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["title", "lede", "stories", "us", "markets", "watch", "verdict"],
        "properties": {
            "title": {"type": "string", "description": "這一期的標題，20 字以內"},
            "lede": {"type": "string", "description": "導言一段，60–120 字"},
            "stories": {
                "type": "array",
                "description": "今日要聞 3–5 則",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["headline", "paragraphs", "sources"],
                    "properties": {
                        "headline": {"type": "string"},
                        "paragraphs": {"type": "array", "items": {"type": "string"}},
                        "sources": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "required": ["title", "outlet", "url"],
                                "properties": {
                                    "title": {"type": "string"},
                                    "outlet": {"type": "string"},
                                    "url": {"type": "string"},
                                },
                            },
                        },
                    },
                },
            },
            "us": {"type": "array", "items": {"type": "string"}, "description": "美國市場那一欄，1–3 段"},
            "markets": {"type": "array", "items": {"type": "string"}, "description": "台股美股，1–3 段"},
            "watch": {"type": "array", "items": {"type": "string"}, "description": "今天要看什麼，1–3 段"},
            "verdict": {"type": "array", "items": {"type": "string"}, "description": "本站判定，1–3 段"},
        },
    },
}

SYSTEM = """你是財經網站 At the Margin 的晨報編輯。每天早上寫一篇給台灣讀者的晨報，篇幅與寫法參考天下雜誌的晨間新聞：先用幾則要聞把來龍去脈講清楚，再用固定欄目交代市場與今天的行程。讀者是網站作者本人，懂總經，早上用手機讀。

## 結構（用 submit_brief 一次交出）
- title：這一期的標題，20 字以內，點出今天最重要的一件事。
- lede：導言一段，60–120 字，說今天這份晨報的重點。
- stories：今日要聞 3–5 則，挑過去一天跟市場最有關的國際與台灣財經新聞。每則：
  - headline：一句話標題。
  - paragraphs：2–3 段。第一段寫發生了什麼（誰、何時、做了什麼）；後面寫來源怎麼說它跟市場的關係。
  - sources：1–3 個來源，每個寫 outlet（媒體名稱，例如 路透、彭博、中央社、CNBC、經濟日報）、title（原文標題）、url。
- us：美國市場那一欄，1–3 段：主要指數、殖利率、美元、商品在最近一個交易日怎麼走。
- markets：台股美股，1–3 段：台股與台積電等權值股、美股權值股與類股。
- watch：今天要看什麼，1–3 段：今天與這幾天要公布的數據、會議，以及公布前的模型預估或期貨定價。
- verdict：本站判定，1–3 段：本站固定規則算出的判定跟上一份存檔比有沒有變——情境格位、訊號增減、關鍵讀數的變動。
全文（不含標題與來源）1,000–1,500 字。繁體中文，台灣用語。

## 新聞一定要有出處
- 每一則要聞都先用 web_search 找到報導再寫；sources 的 url 必須是這次 web_search 實際回傳的網址，原樣抄寫。沒搜到的就不要寫那一則。程式會比對網址，對不上的來源會被刪掉，沒有來源的要聞會讓整期不出刊。
- 用自己的話摘要，不要照抄原文，引號內的直接引述最多一句。
- 來源的說法要歸給來源：「路透報導……」「彭博引述知情人士……」。不要把報導者的推測寫成事實。
- 只寫過去一天左右的新聞。搜尋最多 4 次，之後就用手上的寫。

## 四個固定欄目的數字（程式會逐一比對，對不上就不出刊）
- us、markets、watch、verdict 裡的每一個阿拉伯數字，都要原樣出現在使用者給的素材裡。可以照常四捨五入（6,712.35 寫成 6,712），但不能換算單位、不能自己加減乘除、不能自己算漲跌幅或差距。素材裡沒有的數字就不要寫，改用文字描述或乾脆不提。
- 這四欄的數據一律用阿拉伯數字，不要改寫成中文數字。
- 漲跌照素材的正負號寫成「漲」「跌」，不要寫反。殖利率的變動寫「上升／下降」，不寫漲跌。
- 新聞（stories）裡的數字來自報導，不受這條限制，但必須是報導裡真的有的。

## 不能寫的東西
- 不下自己的判斷、不預測、不給操作建議。不寫「建議」「逢低」「加碼」「減碼」這類字。
- 不寫「優於預期」「不如預期」「符合預期」「高於預期」「低於預期」，也不寫「市場預期」「市場共識」——本站沒有共識預期的資料。數據公布後只寫它是多少、比前一期高或低。
- 公布前的預期只有兩種，照素材第 8 段的名字寫並寫明來源：「模型預估（克里夫蘭聯準銀行 Inflation Nowcasting）」「模型預估（亞特蘭大聯準銀行 GDPNow）」，以及「期貨定價」（聯邦基金利率期貨）。它們都不是共識，但稿子裡不要寫「這不是共識」這類說明（頁面上已經寫了，而且「共識」兩個字會被程式擋下）。非農、失業率、零售銷售這類沒有公開預期來源的，什麼預期都不寫。
- 本站判定一欄只轉述素材第 1、2 段（規則算出的結果與跟上一份存檔的比對），不要替聯準會說話，不要寫「聯準會會怎麼做」。素材說「與上一份相同」就寫沒有變。
- 台灣：景氣燈號是國發會的，不是本站的判定；本站沒有替台灣訂情境規則，不要替台灣下結論。
- 素材第 4 段標「停更的報價」「不要引用」的，不要引用。
- 讀者看不到素材：不要寫「根據摘要」「素材顯示」這種話。

## 日期
素材第一行寫了出刊日與最近一個美股交易日。最近一個交易日不是昨夜（週末、美國假日）時，不能寫「昨夜」「昨晚」「隔夜」美股，要寫那一天的日期。

寫完後呼叫 submit_brief 一次。不要在工具以外輸出其他文字。"""


# ---------------------------------------------------------------- 素材 --

def digest_text() -> str:
    """跑 tools/daily_digest.py，把它印出來的東西收成一段文字。它自己強制離線。"""
    import daily_digest
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        daily_digest.main()
    return buffer.getvalue()


def trim_digest(text: str) -> str:
    """新聞那一段只留「今日焦點」：其餘是上百則標題清單，寫晨報用不到，
    卻佔掉素材的一大半（每天都要付這些 token 的錢）。要聞由模型自己搜尋。"""
    out, skipping = [], False
    for line in text.split("\n"):
        if line.startswith("-- 與總經相關") or line.startswith("-- 依分類"):
            skipping = True
            continue
        if skipping and (line.startswith("=") or line.startswith("-- ")):
            skipping = False
        if not skipping:
            out.append(line)
    return "\n".join(out)


def material_for(day: date, digest: str) -> str:
    return morning.session_note(day) + "\n\n" + trim_digest(digest)


# ---------------------------------------------------------------- API --

class Failed(Exception):
    """沒寫成。message 是給人看的原因。"""


def _usage_add(total: dict, usage) -> None:
    if usage is None:
        return
    for key in ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"):
        total[key] = total.get(key, 0) + (getattr(usage, key, 0) or 0)
    server = getattr(usage, "server_tool_use", None)
    total["web_search_requests"] = (total.get("web_search_requests", 0)
                                    + (getattr(server, "web_search_requests", 0) or 0))


def _walk(node, found: set[str]) -> None:
    """搜尋結果裡的網址。只看工具回傳的區塊，模型自己寫的字不算。"""
    if isinstance(node, dict):
        if node.get("type") == "web_search_result" and node.get("url"):
            found.add(node["url"])
        for value in node.values():
            _walk(value, found)
    elif isinstance(node, list):
        for value in node:
            _walk(value, found)


def search_urls(content: list) -> set[str]:
    found: set[str] = set()
    for block in content:
        data = block.to_dict() if hasattr(block, "to_dict") else block
        if str((data or {}).get("type", "")).endswith("tool_result"):
            _walk(data, found)
    return found


def explain_api_error(exc) -> str:
    """把 SDK 的錯誤翻成一句原因。花費上限要講清楚是哪一種，處理方式不同。"""
    import anthropic
    body = json.dumps(getattr(exc, "body", None) or {}, ensure_ascii=False)
    status = getattr(exc, "status_code", None)
    if isinstance(exc, anthropic.AuthenticationError):
        return "ANTHROPIC_API_KEY 無效（401）"
    if isinstance(exc, anthropic.PermissionDeniedError):
        return f"金鑰沒有權限（403）：{body[:200]}"
    if isinstance(exc, anthropic.RateLimitError) or status == 429:
        if "spend_limit" in body:
            return "達到用量等級的花費上限（429 enforced_spend_limit_reached），要到 Console 調整"
        return f"被限流（429），SDK 重試後仍失敗：{body[:200]}"
    if isinstance(exc, anthropic.BadRequestError):
        if re.search(r"spend|limit|credit|billing", body, re.I):
            return f"達到自設的每月花費上限（400）：{body[:200]}"
        return f"請求被拒（400）：{body[:300]}"
    if isinstance(exc, anthropic.APIStatusError):
        return f"API 錯誤（{status}）：{body[:200]}"
    if isinstance(exc, anthropic.APIConnectionError):
        return f"連不上 API：{exc}"
    return f"{type(exc).__name__}: {exc}"


def call(client, messages: list, usage: dict, urls: set[str]):
    """送一次請求；伺服器端搜尋迴圈被暫停就原樣接續。回傳最後一則回應。"""
    try:
        from anthropic import APIError
    except ImportError:          # 測試用假的客戶端，不裝 SDK
        APIError = ()
    for _ in range(MAX_CONTINUATIONS + 1):
        try:
            response = client.beta.messages.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                system=SYSTEM,
                messages=messages,
                tools=[{"type": "web_search_20260209", "name": "web_search", "max_uses": MAX_SEARCHES},
                       SUBMIT_TOOL],
                output_config={"effort": EFFORT},
                cache_control={"type": "ephemeral"},
                # 安全分類器誤判時，由伺服器改用建議的備援模型重跑，而不是整期開天窗
                betas=["server-side-fallback-2026-07-01"],
                extra_body={"fallbacks": "default"},
                timeout=TIMEOUT,
            )
        except APIError as exc:
            raise Failed(explain_api_error(exc)) from exc
        usage["requests"] = usage.get("requests", 0) + 1
        _usage_add(usage, response.usage)
        urls |= search_urls(response.content)
        if response.stop_reason != "pause_turn":
            return response
        messages.append({"role": "assistant", "content": response.content})
    raise Failed(f"搜尋迴圈接續 {MAX_CONTINUATIONS} 次仍沒有交稿")


def submitted(response):
    """回應裡交出來的那份稿（submit_brief 的輸入）。沒有就丟 Failed。"""
    if response.stop_reason == "refusal":
        details = getattr(response, "stop_details", None)
        raise Failed(f"模型拒絕寫稿（refusal，{getattr(details, 'category', None)}）")
    if response.stop_reason == "max_tokens":
        raise Failed(f"寫到 max_tokens（{MAX_TOKENS}）還沒寫完")
    block = next((b for b in response.content
                  if b.type == "tool_use" and b.name == "submit_brief"), None)
    if block is None:
        raise Failed(f"模型沒有呼叫 submit_brief（stop_reason={response.stop_reason}）")
    return block


def to_issue(day: date, payload: dict, written) -> dict:
    s = morning.session(day)
    raw = {
        "date": day.isoformat(),
        "written_at": written.isoformat(timespec="seconds"),
        "model": MODEL,
        "title": payload.get("title"),
        "lede": payload.get("lede"),
        "stories": payload.get("stories"),
        "sections": {
            "us": {"heading": s["heading"], "paragraphs": payload.get("us")},
            "markets": {"paragraphs": payload.get("markets")},
            "watch": {"paragraphs": payload.get("watch")},
            "verdict": {"paragraphs": payload.get("verdict")},
        },
        "session": {"us_date": s["us_date"], "overnight": s["overnight"]},
    }
    return morning.normalise(raw)


def check(issue: dict, material: str, urls: set[str]) -> tuple[dict, list[str], list[str]]:
    """(去掉假來源後的稿, 問題清單, 被刪掉的來源網址)。"""
    issue, dropped = morning.verify_sources(issue, urls)
    found = morning.problems(issue)
    for key, numbers in morning.unmatched_numbers(issue, material).items():
        name = dict(morning.SECTIONS).get(key, key)
        found.append(f"「{name}」裡的 {'、'.join(numbers)} 在素材裡找不到")
    if dropped:
        found.append(f"這些來源網址不是這次搜尋回傳的，已刪除：{'、'.join(dropped[:6])}")
    return issue, found, dropped


def write_issue(client, day: date, material: str) -> tuple[dict, dict]:
    """寫一期。回傳 (稿, 用量)；沒寫成丟 Failed（用量掛在例外的 usage 上）。"""
    usage: dict = {}
    urls: set[str] = set()
    messages: list = [{"role": "user", "content": (
        "以下是今天的素材。數字只能從這裡來；新聞請自己搜尋。\n\n<素材>\n"
        + material + "\n</素材>")}]
    try:
        for attempt in range(REPAIR_ROUNDS + 1):
            response = call(client, messages, usage, urls)
            block = submitted(response)
            issue = to_issue(day, dict(block.input or {}), clock.now())
            issue, found, _dropped = check(issue, material, urls)
            if not found:
                usage["attempts"] = attempt + 1
                issue["checks"] = {"numbers": morning.count_numbers(issue),
                                   "sources": sum(len(s["sources"]) for s in issue["stories"]),
                                   "searches": usage.get("web_search_requests", 0)}
                return issue, usage
            print(f"   ⚠ 第 {attempt + 1} 稿沒過檢查：", flush=True)
            for line in found:
                print(f"     · {line}", flush=True)
            if attempt == REPAIR_ROUNDS:
                raise Failed("檢查沒過：" + "；".join(found[:6]))
            # 照工具的規矩把問題交回去：同一段對話、append-only，思考區塊原樣保留
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": [{
                "type": "tool_result", "tool_use_id": block.id, "is_error": True,
                "content": ("程式檢查沒過，請修正下面每一點後再呼叫 submit_brief 一次。"
                            "不要再搜尋；找不到出處的數字就刪掉或改用文字描述。\n- "
                            + "\n- ".join(found))}]})
    except Failed as exc:
        exc.usage = usage
        raise
    raise Failed("沒有交稿")


# ---------------------------------------------------------------- 雜項 --

def output(**values) -> None:
    """寫進 GITHUB_OUTPUT，給 workflow 後面的步驟讀。本機執行時只印出來。"""
    target = os.environ.get("GITHUB_OUTPUT")
    lines = "".join(f"{k}={v}\n" for k, v in values.items())
    if target:
        with open(target, "a", encoding="utf-8") as fh:
            fh.write(lines)
    else:
        print(lines, end="")


def due(day: date, *, scheduled: bool, hour: int) -> tuple[bool, str]:
    """今天該不該寫。同一期只寫一次；花過錢卻沒寫成的那天，排程不再重試（手動可以）。"""
    if os.path.exists(morning.path_for(day)):
        return False, f"{day} 這一期已經出刊"
    if scheduled and not WINDOW[0] <= hour < WINDOW[1]:
        return False, f"台北 {hour} 點不在排程的出刊時段（{WINDOW[0]}–{WINDOW[1]} 點）"
    record = morning.failure(day)
    if scheduled and record and float(((record.get("usage") or {}).get("cost_usd")) or 0) > 0:
        return False, f"{day} 已經寫過一次沒成（{record.get('reason')}），排程不再花錢重試；要重寫請手動觸發"
    return True, "今天還沒出刊"


def record_failure(day: date, reason: str, usage: dict) -> None:
    usage = dict(usage or {})
    usage["cost_usd"] = morning.estimate_cost(usage, MODEL) or 0
    os.makedirs(morning.MORNING_DIR, exist_ok=True)
    with open(morning.failed_path(day), "w", encoding="utf-8") as fh:
        json.dump({"date": day.isoformat(), "at": clock.now().isoformat(timespec="seconds"),
                   "reason": reason, "usage": usage}, fh, ensure_ascii=False, indent=1)


def report_usage(usage: dict) -> None:
    cost = morning.estimate_cost(usage, MODEL)
    print(f"   用量：請求 {usage.get('requests', 0)} 次、輸入 {usage.get('input_tokens', 0):,}、"
          f"快取寫入 {usage.get('cache_creation_input_tokens', 0):,}、"
          f"快取讀取 {usage.get('cache_read_input_tokens', 0):,}、"
          f"輸出 {usage.get('output_tokens', 0):,} tokens；搜尋 {usage.get('web_search_requests', 0)} 次"
          + (f"；估計 ${cost:.3f}（{MODEL} 牌價，帳單以 Console 為準）" if cost is not None else ""),
          flush=True)


def fail(day: date, reason: str, usage: dict | None = None) -> int:
    print(f"   ✗ 晨報沒有出刊：{reason}", flush=True)
    if os.environ.get("GITHUB_ACTIONS"):
        print(f"::error title=晨報沒有出刊::{reason}", flush=True)
    if usage:
        report_usage(usage)
    record_failure(day, reason, usage or {})
    output(published="false")
    return 0          # 失敗紀錄還要提交；workflow 最後一步依 published 決定要不要標紅


def main() -> int:
    parser = argparse.ArgumentParser(description="寫每日晨報")
    parser.add_argument("--check", action="store_true", help="只判斷今天該不該寫")
    parser.add_argument("--dry-run", action="store_true", help="印出素材，不呼叫 API")
    parser.add_argument("--date", help="出刊日（預設台北的今天）")
    args = parser.parse_args()

    now = clock.now()
    day = date.fromisoformat(args.date) if args.date else now.date()
    scheduled = os.environ.get("GITHUB_EVENT_NAME") == "schedule"

    if args.check:
        ok, why = due(day, scheduled=scheduled, hour=now.hour)
        print(f"晨報 {day}：{why}")
        output(due="true" if ok else "false", date=day.isoformat())
        return 0

    print(f"== 晨報 {day}（{morning.weekday(day)}）==", flush=True)
    if not morning.session(day)["calendar_known"]:
        print(f"   ⚠ 美股休市日只排到 {morning.NYSE_CALENDAR_END}，請補進 macro/morning.py", flush=True)
    try:
        digest = digest_text()
    except Exception as exc:  # 素材壞了就不寫：沒有素材的數字檢查等於沒有檢查
        return fail(day, f"素材（daily_digest）跑不起來：{type(exc).__name__}: {exc}")
    if "序列 0 檔" in digest or len(digest) < 3000:
        return fail(day, f"素材不完整（{len(digest)} 字），先確認 build.py 有跑成功")
    material = material_for(day, digest)
    print(f"   素材 {len(material):,} 字（原始摘要 {len(digest):,} 字）", flush=True)

    if args.dry_run:
        print(material[:1200])
        print(f"…\n   系統提示 {len(SYSTEM):,} 字；dry run 不呼叫 API", flush=True)
        return 0

    spent = morning.month_spend(day.year, day.month)
    if spent + EXPECTED_COST > morning.MONTHLY_BUDGET_USD:
        return fail(day, f"這個月已估計花掉 ${spent:.2f}，再寫一期會超過本站自訂的每月 "
                         f"${morning.MONTHLY_BUDGET_USD:.0f}（macro/morning.py 的 MONTHLY_BUDGET_USD）")
    if not os.environ.get("ANTHROPIC_API_KEY", "").strip():
        return fail(day, "沒有 ANTHROPIC_API_KEY——到 repo 的 Settings → Secrets and variables → "
                         "Actions 新增")

    import anthropic
    client = anthropic.Anthropic(max_retries=3)
    try:
        issue, usage = write_issue(client, day, material)
    except Failed as exc:
        return fail(day, str(exc), getattr(exc, "usage", None))

    usage["cost_usd"] = morning.estimate_cost(usage, MODEL)
    issue["usage"] = usage
    os.makedirs(morning.MORNING_DIR, exist_ok=True)
    with open(morning.path_for(day), "w", encoding="utf-8") as fh:
        json.dump(issue, fh, ensure_ascii=False, indent=1)
    if os.path.exists(morning.failed_path(day)):
        os.remove(morning.failed_path(day))     # 手動重寫成功：同一天的失敗紀錄作廢
    print(f"   ✓ {issue['title']}（{morning.body_length(issue)} 字，要聞 {len(issue['stories'])} 則，"
          f"數字 {issue['checks']['numbers']} 個全部對得上素材）", flush=True)
    report_usage(usage)
    print(f"   本月估計累計 ${spent + (usage['cost_usd'] or 0):.2f}"
          f"（守門 ${morning.MONTHLY_BUDGET_USD:.0f}）", flush=True)
    output(published="true", date=day.isoformat())
    return 0


if __name__ == "__main__":
    sys.exit(main())
