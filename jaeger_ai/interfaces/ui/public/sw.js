/*
 * Jaeger service worker — Web Push only.
 *
 * Deliberately no fetch handler and no offline cache: the app shell always
 * comes from the server, so a deploy is never hidden behind a stale cache.
 * Activation also clears caches left by the old v0.13 PWA worker.
 *
 * Payload (core/gateway/push_routes.py build_payload):
 *   {v, type, title, body, url, tag, badge, silent, privacy, ...}
 */
self.addEventListener('install', () => { self.skipWaiting(); });

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    try { const keys = await caches.keys(); await Promise.all(keys.map((k) => caches.delete(k))); } catch (e) {}
    await self.clients.claim();
  })());
});

function readPayload(event) {
  if (!event.data) return {};
  try { return event.data.json() || {}; } catch (e) {
    try { return { body: event.data.text() }; } catch (_) { return {}; }
  }
}

self.addEventListener('push', (event) => {
  const data = readPayload(event);
  const title = data.title || 'Jaeger';
  const options = {
    body: data.body || '',
    icon: '/jaeger-icon-180.png',
    badge: '/jaeger-icon-180.png',
    tag: data.tag || data.type || 'jaeger',
    renotify: !data.silent,
    silent: !!data.silent,
    timestamp: Date.now(),
    data: { url: data.url || '/', type: data.type || '' },
  };
  event.waitUntil((async () => {
    // App icon badge (iOS 16.4+ Home Screen apps, Chromium): pending approvals.
    try {
      if (typeof data.badge === 'number' && self.navigator && 'setAppBadge' in self.navigator) {
        if (data.badge > 0) await self.navigator.setAppBadge(data.badge);
        else await self.navigator.clearAppBadge();
      }
    } catch (e) {}
    // iOS requires every push to show a notification, so always show one.
    await self.registration.showNotification(title, options);
    const wins = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
    wins.forEach((c) => c.postMessage({ type: 'jaeger:push', payload: data }));
  })());
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const url = new URL((event.notification.data && event.notification.data.url) || '/', self.location.origin).href;
  event.waitUntil((async () => {
    const wins = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
    const win = wins.find((c) => c.url.startsWith(self.location.origin));
    if (win) {
      try { await win.focus(); } catch (e) {}
      win.postMessage({ type: 'jaeger:push-open', url });
      return;
    }
    await self.clients.openWindow(url);
  })());
});

// The browser rotated the subscription: tell any open window to re-register it.
self.addEventListener('pushsubscriptionchange', (event) => {
  event.waitUntil((async () => {
    const wins = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
    wins.forEach((c) => c.postMessage({ type: 'jaeger:push-resubscribe' }));
  })());
});
