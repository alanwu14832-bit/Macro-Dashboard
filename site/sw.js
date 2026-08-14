/* PWA service worker——只做兩件事：
   1. 讓網站可安裝（Android 的安裝條件之一）
   2. 離線時退回上次看過的頁面
   策略是 network-first：有網路永遠拿最新建置，快取只是離線備援——
   本站一天重建兩次，cache-first 會讓人看到過期的判斷，比沒有快取更糟。
   報價（/api/）完全不碰：盤中數字快取毫無意義。 */
const CACHE = "macro-static-v1";

self.addEventListener("install", () => self.skipWaiting());

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(
        keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()));
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  const url = new URL(request.url);
  if (request.method !== "GET" || url.origin !== location.origin) return;
  if (url.pathname.startsWith("/api/")) return;

  event.respondWith(
    fetch(request)
      .then((response) => {
        if (response.ok) {
          const copy = response.clone();
          caches.open(CACHE).then((cache) => cache.put(request, copy));
        }
        return response;
      })
      .catch(() =>
        caches.match(request).then((hit) =>
          hit || caches.match("/", { ignoreSearch: true })))
  );
});
