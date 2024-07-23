const cacheName = 'la-marzocco-remote-cache-v1';
const assetsToCache = [
  '/',
  '/web/status',
  '/web/turn_on',
  '/web/turn_off',
  '/static/icons/icon_192x192.png',
  '/static/icons/icon_512x512.png',
  '/static/manifest_status.json',
  '/static/manifest_turn_on.json',
  '/static/manifest_turn_off.json',
  '/static/service-worker.js'
];

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(cacheName).then(cache => {
      return cache.addAll(assetsToCache);
    })
  );
});

self.addEventListener('fetch', event => {
  event.respondWith(
    caches.match(event.request).then(response => {
      return response || fetch(event.request);
    })
  );
});
