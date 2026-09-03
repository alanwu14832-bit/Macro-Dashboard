#!/usr/bin/env python3
"""每日財經推播的發送端——由 .github/workflows/notify.yml 每天跑一次。

內容直接重用 news 模組的聚合結果（多家獨立媒體同時報導的事件），
取焦點前三則組成一則通知。訂閱清單放在 Supabase 的 push_subs 表，
匿名端只能寫入自己的訂閱、不能讀清單；這支腳本用 service key 讀全部。

網站本體維持零依賴；Web Push 的 VAPID 簽章與 payload 加密（ES256、
ECDH、AES-GCM）不在標準庫能力範圍，所以這支「只在 CI 跑」的腳本
用 pywebpush——依賴止步於發送端，不進網站。

需要的環境變數：
    VAPID_PRIVATE_KEY      PEM 內容（GitHub secret）
    SUPABASE_SERVICE_KEY   Supabase service_role key（GitHub secret）
"""
from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from macro.compute import news  # noqa: E402  （path 調整要在前面）

SUPABASE_URL = "https://nwbfjoroqnhpymdtdbwu.supabase.co"  # 公開常數，同 layout.py
SITE = "https://macro-dashboard-aaalan1.vercel.app"
MAX_HEADLINES = 3

# 中文資本市場新聞源。三家輪流取，單一來源掛掉不影響其他家。
CH_FEEDS = [
    ("中央社財經", "https://feeds.feedburner.com/rsscna/finance"),
    ("鉅亨台股", "https://news.cnyes.com/rss/v1/news/category/tw_stock"),
    ("自由財經", "https://news.ltn.com.tw/rss/business.xml"),
]


def _clean_title(title: str) -> str:
    """去掉「[WEB][即時]」這類編輯標記，通知欄位寸土寸金。"""
    import re
    text = re.sub(r"^(\[[^\]]{1,8}\]|【[^】]{1,8}】)+\s*", "", title.strip())
    return text[:42] + ("…" if len(text) > 42 else "")


def _chinese_lines() -> list[str]:
    """近 24 小時的中文財經頭條，三家來源輪流取，同題只留一則。"""
    from datetime import datetime, timedelta, timezone
    from macro import http as macro_http
    from macro.compute.news import parse_feed

    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    per_source: list[list[dict]] = []
    for name, url in CH_FEEDS:
        try:
            body = macro_http.get(url, ttl=1800, namespace="news", timeout=15)
        except Exception:
            continue
        items = [i for i in parse_feed(body, name)
                 if i["published"] and i["published"] >= cutoff]
        items.sort(key=lambda i: i["published"], reverse=True)
        per_source.append(items)

    lines: list[str] = []
    seen: set[str] = set()
    rank = 0
    while len(lines) < MAX_HEADLINES and any(per_source):
        for items in per_source:            # 輪流取，來源觀點才有多樣性
            while items:
                item = items.pop(0)
                key = _clean_title(item["title"])[:15]
                if key in seen:
                    continue
                seen.add(key)
                lines.append("・" + _clean_title(item["title"]))
                break
            if len(lines) >= MAX_HEADLINES:
                break
        rank += 1
        if rank > 10:                       # 保險絲
            break
    return lines


def compose() -> dict | None:
    """中文資本市場新聞優先；全部抓不到才退回英文多源聚合。"""
    lines = _chinese_lines()
    if not lines:
        digest = news.compute(None)
        clusters = (digest or {}).get("clusters") or []
        lines = [f"・{c['headline']}" for c in clusters[:MAX_HEADLINES]]
    if not lines:
        return None
    return {
        "title": "今日財經焦點",
        "body": "\n".join(lines),
        "url": "/news/",
        "tag": "daily-news",
    }


def _rest(path: str, *, method: str = "GET", service_key: str) -> list | dict | None:
    request = urllib.request.Request(
        SUPABASE_URL + path, method=method,
        headers={"apikey": service_key, "Authorization": f"Bearer {service_key}"})
    with urllib.request.urlopen(request, timeout=30) as response:
        body = response.read()
    return json.loads(body) if body else None


# ---------------------------------------------- 數據更新推播（--data-update） --

# 指標 → 新聞關鍵字。配對到的頭條會附在推播裡當「市場在說什麼」。
NEWS_KEYWORDS = {
    "PAYEMS": ["非農", "就業報告", "nonfarm", "payroll"],
    "UNRATE": ["失業率", "unemployment"],
    "ICSA": ["初領", "失業金", "jobless claims"],
    "JTSJOL": ["JOLTS", "職缺"],
    "CPIAUCSL": ["CPI", "消費者物價", "通膨"],
    "PPIFIS": ["PPI", "生產者物價"],
    "PCEPILFE": ["PCE", "個人消費支出"],
    "GDPC1": ["GDP", "經濟成長率"],
    "RSAFS": ["零售銷售", "retail sales"],
    "INDPRO": ["工業生產", "industrial production"],
    "HOUST": ["新屋開工", "housing starts"],
    "DRTSCILM": ["放款標準", "SLOOS"],
}

# 市場反應的觀察標的：美股與債市對總經數據的第一反應。
FUTURES = [
    ("ES=F", "S&P 期貨"),
    ("NQ=F", "那斯達克期貨"),
    ("ZN=F", "10年債期貨"),
]


def _futures_reaction() -> str:
    """期貨即時漲跌。Yahoo 公開行情端點，抓不到就略過該檔。"""
    bits = []
    for symbol, label in FUTURES:
        try:
            request = urllib.request.Request(
                "https://query1.finance.yahoo.com/v8/finance/chart/"
                + urllib.parse.quote(symbol) + "?range=1d&interval=15m",
                headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(request, timeout=12) as response:
                meta = json.load(response)["chart"]["result"][0]["meta"]
            change = (meta["regularMarketPrice"] - meta["chartPreviousClose"]) \
                / meta["chartPreviousClose"] * 100
            bits.append(f"{label} {change:+.2f}%")
        except Exception:
            continue
    return "、".join(bits)


def _related_headline(new_ids: list[str]) -> str | None:
    """在中文財經頭條裡找跟剛公布指標相關的一則。"""
    from macro import http as macro_http
    from macro.compute.news import parse_feed

    keywords = [k for sid in new_ids for k in NEWS_KEYWORDS.get(sid, [])]
    if not keywords:
        return None
    lowered = [k.lower() for k in keywords]
    for _name, url in CH_FEEDS:
        try:
            body = macro_http.get(url, ttl=1800, namespace="news", timeout=15)
        except Exception:
            continue
        for item in parse_feed(body, _name):
            title = item["title"]
            if any(k in title.lower() for k in lowered):
                return _clean_title(title)
    return None


def compose_data_update() -> dict | None:
    """比對上一輪建置的 fresh 狀態，有新公布的指標才推。

    「新」的定義跟網站徽章同一套（FRED 兩天內更新），這裡再加一層
    跨建置去重：只有這一輪才出現的指標才算事件，同一次發布只推一次。
    """
    state_path = os.path.join(os.path.dirname(__file__), "..",
                              "data", "fresh_state.json")
    prev_path = os.environ.get("PREV_STATE", "")
    try:
        with open(state_path, encoding="utf-8") as fh:
            current = json.load(fh)
    except Exception:
        print("讀不到 fresh_state.json——先跑 build 才有狀態可比")
        return None
    previous = {}
    if prev_path and os.path.exists(prev_path):
        with open(prev_path, encoding="utf-8") as fh:
            previous = json.load(fh)

    new_ids = [sid for sid in current if sid not in previous]
    if not new_ids:
        print(f"fresh {len(current)} 項皆已推播過，本輪無新公布")
        return None

    names = "、".join(current[sid]["name"] for sid in new_ids)
    lines = []
    reaction = _futures_reaction()
    if reaction:
        lines.append("市場反應：" + reaction)
    headline = _related_headline(new_ids)
    if headline:
        lines.append("相關新聞：" + headline)
    lines.append("點開看讀數與判定變化")

    return {
        "title": f"數據更新：{names}",
        "body": "\n".join(lines),
        "url": "/",
        "tag": "data-update",   # 與每日新聞不同 tag，不互相覆蓋
    }


def main() -> int:
    private_key = os.environ.get("VAPID_PRIVATE_KEY", "").strip()
    service_key = os.environ.get("SUPABASE_SERVICE_KEY", "").strip()
    if not private_key or not service_key:
        print("缺 VAPID_PRIVATE_KEY 或 SUPABASE_SERVICE_KEY，無法發送")
        return 1

    if "--data-update" in sys.argv:
        payload = compose_data_update()
        if payload is None:
            return 0
    else:
        payload = compose()
        if payload is None:
            print("過去一天沒有多來源同報的焦點事件，今天不推")
            return 0

    subs = _rest("/rest/v1/push_subs?select=endpoint,p256dh,auth",
                 service_key=service_key) or []
    print(f"訂閱 {len(subs)} 台裝置；內容：{payload['body'][:80]}…")
    if not subs:
        return 0

    from pywebpush import webpush, WebPushException  # CI 才安裝

    # pywebpush 吃 PEM 檔路徑
    key_path = "/tmp/vapid_private.pem"
    with open(key_path, "w", encoding="utf-8") as fh:
        fh.write(private_key + ("\n" if not private_key.endswith("\n") else ""))

    def drop(endpoint: str) -> None:
        _rest("/rest/v1/push_subs?endpoint=eq."
              + urllib.parse.quote(endpoint, safe=""),
              method="DELETE", service_key=service_key)

    sent = gone = failed = 0
    for sub in subs:
        # 金鑰格式不對的訂閱（歷史測試資料、被截斷的列）直接清掉，
        # 否則 pywebpush 解碼時丟 binascii.Error 會拖垮整批發送。
        if len(sub.get("p256dh") or "") < 80 or len(sub.get("auth") or "") < 16:
            print(f"  － 金鑰格式不對，清除：{sub['endpoint'][:70]}")
            drop(sub["endpoint"])
            gone += 1
            continue
        info = {"endpoint": sub["endpoint"],
                "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]}}
        try:
            webpush(subscription_info=info,
                    data=json.dumps(payload, ensure_ascii=False),
                    vapid_private_key=key_path,
                    vapid_claims={"sub": "mailto:alanwu14832@gmail.com"},
                    ttl=12 * 3600)
            sent += 1
        except WebPushException as exc:
            status = getattr(exc.response, "status_code", None)
            if status in (404, 410):
                # 裝置已解除訂閱（換機、清資料、重裝 APP）——順手清掉
                print(f"  － 裝置已失效（{status}），清除：{sub['endpoint'][:70]}")
                drop(sub["endpoint"])
                gone += 1
            else:
                failed += 1
                print(f"  ✗ {status}: {str(exc)[:120]}")
        except Exception as exc:  # 單筆資料異常不該讓其他裝置收不到
            failed += 1
            print(f"  ✗ {sub['endpoint'][:60]}…: {type(exc).__name__} {str(exc)[:100]}")

    print(f"送出 {sent}，清除失效 {gone}，失敗 {failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
