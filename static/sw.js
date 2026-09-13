// SpoilerFree service worker — האפליקציה נפתחת מיד גם כשהשרת ב-Render ישן.
// /app: מוגש מהקאש מיד, ומתעדכן ברקע (הגרסה החדשה תופיע בפתיחה הבאה).
// נשמר רק הדף האמיתי (כותרת X-SF-App) — לעולם לא מסך הכניסה.
// /app?fresh=1: תמיד מהרשת (אחרי 401 — כדי להגיע למסך הכניסה בלי לולאה).
// נתוני API לא נשמרים כאן — הפרונט שומר אותם ב-localStorage.
const CACHE = 'sf-shell-v1';
const STATIC = ['/manifest.webmanifest', '/icons/icon-192.png',
                '/icons/icon-512.png', '/icons/apple-touch-icon.png'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(STATIC)).catch(() => {}));
  self.skipWaiting();
});

self.addEventListener('activate', e => {
  e.waitUntil((async () => {
    for (const k of await caches.keys()) if (k !== CACHE) await caches.delete(k);
    await self.clients.claim();
  })());
});

async function fetchAndStoreApp(request) {
  const resp = await fetch(request);
  if (resp.ok && resp.headers.get('X-SF-App') === '1') {
    const c = await caches.open(CACHE);
    await c.put('/app', resp.clone());
  }
  return resp;
}

self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET' || url.origin !== location.origin) return;

  // "/" (הכתובת הראשית) ו-"/app" (התקנות ישנות) — אותו דף, אותו קאש
  if (url.pathname === '/' || url.pathname === '/app') {
    if (url.searchParams.has('fresh')) {
      e.respondWith(fetchAndStoreApp(e.request));
      return;
    }
    e.respondWith((async () => {
      const cached = await caches.match('/app');
      const network = fetchAndStoreApp(e.request);
      if (cached) {
        e.waitUntil(network.catch(() => {}));
        return cached;
      }
      return network;
    })());
    return;
  }

  if (STATIC.includes(url.pathname)) {
    e.respondWith(caches.match(url.pathname).then(r => r || fetch(e.request)));
  }
});
