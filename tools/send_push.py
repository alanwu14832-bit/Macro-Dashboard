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


def compose() -> dict | None:
    """從新聞聚合取焦點事件；沒有夠格的焦點就不推（寧缺勿濫）。"""
    digest = news.compute(None)
    clusters = (digest or {}).get("clusters") or []
    if not clusters:
        return None
    lines = [f"・{c['headline']}" for c in clusters[:MAX_HEADLINES]]
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


def main() -> int:
    private_key = os.environ.get("VAPID_PRIVATE_KEY", "").strip()
    service_key = os.environ.get("SUPABASE_SERVICE_KEY", "").strip()
    if not private_key or not service_key:
        print("缺 VAPID_PRIVATE_KEY 或 SUPABASE_SERVICE_KEY，無法發送")
        return 1

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
                # 裝置已解除訂閱（換機、清資料）——順手清掉
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
