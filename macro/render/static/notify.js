/* 每日財經推播的訂閱開關。
 *
 * 流程：topbar 的「通知」鈕 → 瀏覽器權限 → PushManager 訂閱（VAPID 公鑰）
 * → 訂閱資訊存進 Supabase push_subs 表。發送端是 GitHub Actions 每天跑
 * tools/send_push.py，用 service key 讀出全部訂閱、逐一推送。
 *
 * 支援判定就是功能開關：iOS 只有「加入主畫面」的 PWA 才有 Notification，
 * Safari 分頁裡按鈕自動隱藏；window.__SB 沒設定（本機預覽）也隱藏。
 */
(() => {
  "use strict";
  const VAPID_PUBLIC = "BO4csrgxJA1DK1Ac2U3J-O69iWjo639R1bmWFIhJ8fHHpWyyRzJZ5ujYrJWHIbYN0XBbb4RI38rFendHT3p1lq0";
  const btn = document.getElementById("push-toggle");
  const SB = window.__SB;
  if (!btn || !SB || !SB.url || !("serviceWorker" in navigator)
      || !("PushManager" in window) || !("Notification" in window)) return;
  btn.hidden = false;

  const b64ToU8 = (s) => {
    const pad = "=".repeat((4 - (s.length % 4)) % 4);
    const raw = atob((s + pad).replace(/-/g, "+").replace(/_/g, "/"));
    return Uint8Array.from(raw, (c) => c.charCodeAt(0));
  };

  const headers = {
    apikey: SB.key, Authorization: "Bearer " + SB.key,
    "Content-Type": "application/json",
  };

  function paint(sub) {
    btn.classList.toggle("on", !!sub);
    btn.setAttribute("aria-pressed", sub ? "true" : "false");
    btn.title = sub ? "每日財經推播已開啟，點擊關閉" : "開啟每日財經推播（台北 08:05）";
  }

  async function save(sub) {
    const json = sub.toJSON();
    // 純 insert，不用 upsert：這張表沒有 select policy（誰都讀不到訂閱
    // 清單），而 upsert 的衝突合併需要回讀既有列，會被 RLS 擋下。
    // 同一個 endpoint 的金鑰不會變——409（已訂閱過）直接視為成功。
    const res = await fetch(SB.url + "/rest/v1/push_subs", {
      method: "POST",
      headers: { ...headers, Prefer: "return=minimal" },
      body: JSON.stringify({
        endpoint: sub.endpoint,
        p256dh: json.keys.p256dh,
        auth: json.keys.auth,
      }),
    });
    if (!res.ok && res.status !== 409) {
      throw new Error("subscribe store failed " + res.status);
    }
  }

  function remove(sub) {
    return fetch(SB.url + "/rest/v1/push_subs?endpoint=eq."
                 + encodeURIComponent(sub.endpoint),
                 { method: "DELETE", headers });
  }

  btn.addEventListener("click", async () => {
    btn.disabled = true;
    let step = "初始化";
    try {
      const reg = await navigator.serviceWorker.ready;
      let sub = await reg.pushManager.getSubscription();
      if (sub) {
        step = "取消訂閱";
        await remove(sub).catch(() => {});
        await sub.unsubscribe();
        paint(null);
        return;
      }
      step = "通知權限";
      if (await Notification.requestPermission() !== "granted") {
        alert("通知權限未開啟。到 設定 → 通知 → 總經儀表板 開啟後再試。");
        return;
      }
      step = "建立訂閱";
      sub = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: b64ToU8(VAPID_PUBLIC),
      });
      step = "寫入資料庫";
      try {
        await save(sub);
      } catch (err) {
        await sub.unsubscribe();   // 存不進去就別留孤兒訂閱
        throw err;
      }
      paint(sub);
    } catch (err) {
      // 手機上沒有開發者工具，失敗一定要說得出原因
      alert("訂閱失敗（" + step + "）：" + (err && err.message ? err.message : err));
    } finally {
      btn.disabled = false;
    }
  });

  navigator.serviceWorker.ready
    .then((reg) => reg.pushManager.getSubscription())
    .then(paint)
    .catch(() => {});
})();
