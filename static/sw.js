const CACHE_NAME = 'fersedo-v10';
const BASE_URL = 'http://192.168.0.20:5001';

// Само статични ресурси — кешираат при install
const STATIC_ASSETS = [
  '/static/manifest.json',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
  '/static/offline.html',
];

// Апликациски рути — network first, fallback на кеш
const APP_SHELL = [
  '/',
  '/nabavki',
  '/artikli',
  '/moj_zapisi',
  '/dashboard',
  '/plan_proizvodstvo',
  '/izvestaj',
  '/kalkulacija',
];

// ─────────────────────────────────────────────────────────────
// INSTALL — кешира само статични ресурси
// ─────────────────────────────────────────────────────────────
self.addEventListener('install', event => {
  console.log('[SW v10] Installing...');
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => {
      console.log('[SW v10] Caching static assets');
      return cache.addAll(STATIC_ASSETS);
    }).catch(err => {
      console.error('[SW v10] Cache addAll failed:', err);
    })
  );
  self.skipWaiting();
});

// ─────────────────────────────────────────────────────────────
// ACTIVATE — избриши стари кешови
// ─────────────────────────────────────────────────────────────
self.addEventListener('activate', event => {
  console.log('[SW v10] Activating...');
  event.waitUntil(
    caches.keys().then(keys => {
      return Promise.all(
        keys
          .filter(key => key !== CACHE_NAME)
          .map(key => {
            console.log('[SW v10] Deleting old cache:', key);
            return caches.delete(key);
          })
      );
    })
  );
  self.clients.claim();
});

// ─────────────────────────────────────────────────────────────
// FETCH
// ─────────────────────────────────────────────────────────────
self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);

  // 1. Само GET — сè друго пушти кон мрежата
  if (event.request.method !== 'GET') {
    return;
  }

  // 2. Надворешни домени — пушти кон мрежата (CDN, Google Fonts...)
  if (url.origin !== self.location.origin) {
    event.respondWith(
      fetch(event.request).catch(() => {
        return new Response('', { status: 408 });
      })
    );
    return;
  }

  // 3. Статични ресурси — Cache First
  if (
    url.pathname.startsWith('/static/') ||
    STATIC_ASSETS.includes(url.pathname)
  ) {
    event.respondWith(
      caches.match(event.request).then(cached => {
        if (cached) return cached;
        return fetch(event.request).then(networkResponse => {
          return caches.open(CACHE_NAME).then(cache => {
            cache.put(event.request, networkResponse.clone());
            return networkResponse;
          });
        }).catch(() => {
          return new Response('', { status: 404 });
        });
      })
    );
    return;
  }

  // 4. App Shell рути — Network First, fallback на кеш, па offline
  if (APP_SHELL.includes(url.pathname) || url.pathname === '/') {
    event.respondWith(
      fetch(event.request)
        .then(networkResponse => {
          // Само кешираj успешни одговори (не login redirect)
          if (networkResponse.ok) {
            return caches.open(CACHE_NAME).then(cache => {
              cache.put(event.request, networkResponse.clone());
              return networkResponse;
            });
          }
          return networkResponse;
        })
        .catch(() => {
          return caches.match(event.request).then(cached => {
            return cached || caches.match('/static/offline.html');
          });
        })
    );
    return;
  }

  // 5. Сè друго (API, динамички рути) — Network Only, без кеширање
  event.respondWith(
    fetch(event.request).catch(() => {
      // Ако е JSON барање врати JSON грешка
      if (event.request.headers.get('accept')?.includes('application/json')) {
        return new Response(
          JSON.stringify({ error: 'Нема интернет врска', offline: true }),
          { status: 503, headers: { 'Content-Type': 'application/json' } }
        );
      }
      // Инаку врати offline страница
      return caches.match('/static/offline.html');
    })
  );
});