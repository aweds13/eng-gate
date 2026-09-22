/* timeflow service worker — 缓存应用壳，**断网也能打开**。
   范围（G 批 · T-G10 起说清楚）：缓存的是**静态壳**（页面 / 样式 / 离线引擎 / 图标）；
   数据写入仍然走网络（API）—— 连不上时由页面里的离线队列兜住（`src/web/offline.js`），
   队列要靠 `离线记` 页导出成同步包、再在电脑上导入（场景 ①，见 `复盘/手机离线记-T-G10.md`）。
   注意：**API 请求不进缓存**（数据必须新鲜；缓存一份旧账比不缓存更糟）。 */

const CACHE = "timeflow-v2";           // v1 → v2：壳里多了 `/offline.js`（改名才会重新预缓存）
const SHELL = ["/", "/app.css", "/offline.js", "/manifest.json"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)));
  self.skipWaiting();
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  // 只缓存同源静态资源；API 请求直接走网络（保证数据新鲜）
  if (url.origin === self.location.origin && !url.pathname.startsWith("/api/")) {
    e.respondWith(
      fetch(e.request)
        .then((res) => {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(e.request, copy));
          return res;
        })
        .catch(() => caches.match(e.request).then((r) => r || caches.match("/")))
    );
  }
});
