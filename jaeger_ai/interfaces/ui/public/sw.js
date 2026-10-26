/**
 * Jaeger PWA Service Worker
 *
 * Features:
 * - Offline support (cache shell)
 * - Background sync (queue messages when offline)
 * - Push notifications (agent activity)
 * - Periodic background sync (check agent status)
 */

const CACHE_NAME = 'jaeger-v0.13.0'
const RUNTIME_CACHE = 'jaeger-runtime'

// Assets to cache immediately
const PRECACHE_URLS = [
  '/',
  '/?ui=apple',
  '/index.html',
  '/manifest.webmanifest',
  '/jaeger-icon.svg',
  '/jaeger-icon-180.png',
  '/jaeger-icon-512.png',
]

// Install: Cache shell assets
self.addEventListener('install', (event) => {
  console.log('[SW] Installing...')
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then((cache) => {
        console.log('[SW] Precaching shell')
        return cache.addAll(PRECACHE_URLS)
      })
      .then(() => self.skipWaiting())
  )
})

// Activate: Clean old caches
self.addEventListener('activate', (event) => {
  console.log('[SW] Activating...')
  event.waitUntil(
    caches.keys().then((cacheNames) => {
      return Promise.all(
        cacheNames
          .filter((name) => name !== CACHE_NAME && name !== RUNTIME_CACHE)
          .map((name) => {
            console.log('[SW] Deleting old cache:', name)
            return caches.delete(name)
          })
      )
    }).then(() => self.clients.claim())
  )
})

// Fetch: Network-first for API, cache-first for assets
self.addEventListener('fetch', (event) => {
  const { request } = event
  const url = new URL(request.url)

  // Skip non-GET requests
  if (request.method !== 'GET') return

  // Skip WebSocket
  if (url.protocol === 'ws:' || url.protocol === 'wss:') return

  // API requests: Network only (with fallback to cache)
  if (url.pathname.startsWith('/v1/') || url.pathname.startsWith('/api/')) {
    event.respondWith(
      fetch(request)
        .then((response) => {
          // Cache successful API responses
          if (response.ok) {
            const clone = response.clone()
            caches.open(RUNTIME_CACHE).then((cache) => {
              cache.put(request, clone)
            })
          }
          return response
        })
        .catch(() => {
          // Offline: return cached response if available
          return caches.match(request).then((cached) => {
            if (cached) return cached
            return new Response(JSON.stringify({ error: 'Offline' }), {
              status: 503,
              headers: { 'Content-Type': 'application/json' },
            })
          })
        })
    )
    return
  }

  // Static assets: Cache-first
  if (
    url.pathname.endsWith('.js') ||
    url.pathname.endsWith('.css') ||
    url.pathname.endsWith('.png') ||
    url.pathname.endsWith('.svg') ||
    url.pathname.endsWith('.woff2') ||
    url.pathname.endsWith('.webmanifest')
  ) {
    event.respondWith(
      caches.match(request).then((cached) => {
        if (cached) {
          // Return cached, but update in background
          fetch(request).then((response) => {
            if (response.ok) {
              caches.open(RUNTIME_CACHE).then((cache) => {
                cache.put(request, response)
              })
            }
          }).catch(() => {})
          return cached
        }
        return fetch(request).then((response) => {
          if (response.ok) {
            const clone = response.clone()
            caches.open(RUNTIME_CACHE).then((cache) => {
              cache.put(request, clone)
            })
          }
          return response
        })
      })
    )
    return
  }

  // HTML pages: Network-first with offline fallback
  if (request.headers.get('accept')?.includes('text/html')) {
    event.respondWith(
      fetch(request)
        .then((response) => {
          const clone = response.clone()
          caches.open(RUNTIME_CACHE).then((cache) => {
            cache.put(request, clone)
          })
          return response
        })
        .catch(() => {
          return caches.match(request).then((cached) => {
            if (cached) return cached
            // Fallback to cached shell
            return caches.match('/?ui=apple').then((shell) => {
              return shell || new Response('Offline', { status: 503 })
            })
          })
        })
    )
    return
  }

  // Default: Network only
  event.respondWith(fetch(request))
})

// Background Sync: Queue messages when offline
self.addEventListener('sync', (event) => {
  console.log('[SW] Background sync:', event.tag)
  if (event.tag === 'sync-messages') {
    event.waitUntil(syncMessages())
  }
})

async function syncMessages() {
  const db = await openDB()
  const messages = await db.getAll('pending-messages')
  
  for (const msg of messages) {
    try {
      const response = await fetch('/v1/sessions/' + msg.sessionId + '/turns', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: msg.text, source: 'pwa-offline' }),
      })
      if (response.ok) {
        await db.delete('pending-messages', msg.id)
        // Notify clients
        const clients = await self.clients.matchAll()
        clients.forEach((client) => {
          client.postMessage({ type: 'message-synced', id: msg.id })
        })
      }
    } catch (err) {
      console.error('[SW] Failed to sync message:', err)
    }
  }
}

// Push Notifications: Agent activity
self.addEventListener('push', (event) => {
  console.log('[SW] Push received:', event.data?.text())
  
  const data = event.data?.json() || {}
  const title = data.title || 'Jaeger'
  const options = {
    body: data.body || 'Your agent has an update',
    icon: '/jaeger-icon-180.png',
    badge: '/jaeger-icon-180.png',
    tag: data.tag || 'jaeger-notification',
    data: data.url || '/?ui=apple',
    actions: [
      { action: 'open', title: 'Open' },
      { action: 'dismiss', title: 'Dismiss' },
    ],
    requireInteraction: data.requireInteraction || false,
  }
  
  event.waitUntil(
    self.registration.showNotification(title, options)
  )
})

// Notification click
self.addEventListener('notificationclick', (event) => {
  console.log('[SW] Notification clicked:', event.action)
  event.notification.close()
  
  if (event.action === 'dismiss') return
  
  const url = event.notification.data || '/?ui=apple'
  
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true })
      .then((clients) => {
        // Focus existing window
        for (const client of clients) {
          if (client.url.includes(self.location.origin) && 'focus' in client) {
            client.navigate(url)
            return client.focus()
          }
        }
        // Open new window
        return self.clients.openWindow(url)
      })
  )
})

// Periodic Background Sync: Check agent status
self.addEventListener('periodicsync', (event) => {
  if (event.tag === 'check-agent-status') {
    event.waitUntil(checkAgentStatus())
  }
})

async function checkAgentStatus() {
  try {
    const response = await fetch('http://127.0.0.1:33418/health')
    const health = await response.json()
    
    // If agent is working, notify
    if (health.diagnostics?.owner_runtime?.execution_verified == false) {
      await self.registration.showNotification('Jaeger is working', {
        body: 'Your agent is processing a task',
        tag: 'agent-working',
        icon: '/jaeger-icon-180.png',
      })
    }
  } catch (err) {
    // Gateway unreachable — that's fine
  }
}

// Message from clients
self.addEventListener('message', (event) => {
  console.log('[SW] Message from client:', event.data)
  
  if (event.data?.type === 'SKIP_WAITING') {
    self.skipWaiting()
  }
  
  if (event.data?.type === 'CACHE_URLS') {
    event.waitUntil(
      caches.open(RUNTIME_CACHE).then((cache) => {
        return cache.addAll(event.data.urls)
      })
    )
  }
})

// IndexedDB helper for offline message queue
function openDB() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open('jaeger-offline', 1)
    request.onerror = () => reject(request.error)
    request.onsuccess = () => resolve(request.result)
    request.onupgradeneeded = (event) => {
      const db = event.target.result
      if (!db.objectStoreNames.contains('pending-messages')) {
        db.createObjectStore('pending-messages', { keyPath: 'id', autoIncrement: true })
      }
    }
  })
}

console.log('[SW] Jaeger Service Worker loaded')
