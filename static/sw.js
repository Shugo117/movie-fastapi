const CACHE_NAME = "movie-pwa-v1";
const CORE_ASSETS = [
  "/",
  "/static/manifest.webmanifest",
  "/static/sw.js",
  "/static/icons/icon-192.png",
  "/static/icons/icon-512.png"
];

// install: コアだけ先にキャッシュ
self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(CORE_ASSETS))
  );
  self.skipWaiting();
});

// activate: 古いキャッシュ掃除
self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.map((k) => (k === CACHE_NAME ? null : caches.delete(k))))
    )
  );
  self.clients.claim();
});

// fetch:
// - HTML(ナビゲーション)は「ネット優先→ダメならキャッシュ」
// - それ以外は「キャッシュ優先→なければネット」
self.addEventListener("fetch", (event) => {
  const req = event.request;

  // ブラウザの画面遷移（HTML）はネット優先にして壊れにくくする
  if (req.mode === "navigate") {
    event.respondWith(
      fetch(req).catch(() => caches.match("/"))
    );
    return;
  }

  event.respondWith(
    caches.match(req).then((cached) => cached || fetch(req))
  );
});
