/**
 * PWA Utilities — Service Worker registration, install prompt, notifications
 *
 * Features:
 * - Service worker registration
 * - Install prompt (Add to Home Screen)
 * - Push notification subscription
 * - Background sync
 * - Periodic background sync
 */

// ─────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────

interface BeforeInstallPromptEvent extends Event {
  prompt: () => Promise<void>
  userChoice: Promise<{ outcome: 'accepted' | 'dismissed' }>
}

// ─────────────────────────────────────────────────────────────
// Service Worker Registration
// ─────────────────────────────────────────────────────────────

let swRegistration: ServiceWorkerRegistration | null = null

export async function registerServiceWorker(): Promise<ServiceWorkerRegistration | null> {
  if (!('serviceWorker' in navigator)) {
    console.log('[PWA] Service workers not supported')
    return null
  }

  try {
    swRegistration = await navigator.serviceWorker.register('/sw.js', {
      scope: '/',
    })
    console.log('[PWA] Service worker registered:', swRegistration.scope)
    
    // Check for updates
    swRegistration.addEventListener('updatefound', () => {
      const newWorker = swRegistration!.installing
      console.log('[PWA] New service worker found')
      
      newWorker?.addEventListener('statechange', () => {
        if (newWorker.state === 'installed' && navigator.serviceWorker.controller) {
          // New version available
          console.log('[PWA] New version available')
          dispatchEvent(new CustomEvent('pwa-update-available'))
        }
      })
    })
    
    return swRegistration
  } catch (error) {
    console.error('[PWA] Service worker registration failed:', error)
    return null
  }
}

export function getServiceWorkerRegistration(): ServiceWorkerRegistration | null {
  return swRegistration
}

// ─────────────────────────────────────────────────────────────
// Install Prompt
// ─────────────────────────────────────────────────────────────

let deferredPrompt: BeforeInstallPromptEvent | null = null
let installPromptShown = false

export function setupInstallPrompt(): void {
  window.addEventListener('beforeinstallprompt', (e) => {
    console.log('[PWA] Install prompt available')
    e.preventDefault()
    deferredPrompt = e as BeforeInstallPromptEvent
    dispatchEvent(new CustomEvent('pwa-install-available'))
  })

  window.addEventListener('appinstalled', () => {
    console.log('[PWA] App installed')
    deferredPrompt = null
    installPromptShown = true
    dispatchEvent(new CustomEvent('pwa-installed'))
  })
}

export async function showInstallPrompt(): Promise<'accepted' | 'dismissed' | 'unavailable'> {
  if (!deferredPrompt) {
    return 'unavailable'
  }

  deferredPrompt.prompt()
  const { outcome } = await deferredPrompt.userChoice
  deferredPrompt = null
  installPromptShown = true
  
  return outcome
}

export function canInstall(): boolean {
  return deferredPrompt !== null
}

export function isInstalled(): boolean {
  // Check if running as PWA
  return window.matchMedia('(display-mode: standalone)').matches ||
         (window.navigator as any).standalone === true ||
         document.referrer.includes('android-app://')
}

// ─────────────────────────────────────────────────────────────
// Push Notifications
// ─────────────────────────────────────────────────────────────

export async function requestNotificationPermission(): Promise<NotificationPermission> {
  if (!('Notification' in window)) {
    console.log('[PWA] Notifications not supported')
    return 'denied'
  }

  const permission = await Notification.requestPermission()
  console.log('[PWA] Notification permission:', permission)
  return permission
}

export async function subscribeToPush(vapidPublicKey?: string): Promise<PushSubscription | null> {
  if (!swRegistration) {
    console.error('[PWA] No service worker registration')
    return null
  }

  try {
    // Check existing subscription
    let subscription = await swRegistration.pushManager.getSubscription()
    
    if (subscription) {
      console.log('[PWA] Already subscribed to push')
      return subscription
    }
    
    // Subscribe
    subscription = await swRegistration.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: vapidPublicKey ? urlBase64ToUint8Array(vapidPublicKey) : undefined,
    })
    
    console.log('[PWA] Push subscription created:', subscription.endpoint)
    
    // Send subscription to server
    // await fetch('/api/push/subscribe', {
    //   method: 'POST',
    //   headers: { 'Content-Type': 'application/json' },
    //   body: JSON.stringify(subscription),
    // })
    
    return subscription
  } catch (error) {
    console.error('[PWA] Push subscription failed:', error)
    return null
  }
}

export async function unsubscribeFromPush(): Promise<boolean> {
  if (!swRegistration) return false
  
  const subscription = await swRegistration.pushManager.getSubscription()
  if (subscription) {
    await subscription.unsubscribe()
    return true
  }
  return false
}

// ─────────────────────────────────────────────────────────────
// Background Sync
// ─────────────────────────────────────────────────────────────

export async function registerBackgroundSync(tag: string): Promise<void> {
  if (!swRegistration) {
    console.error('[PWA] No service worker registration')
    return
  }

  try {
    await (swRegistration as any).sync.register(tag)
    console.log('[PWA] Background sync registered:', tag)
  } catch (error) {
    console.error('[PWA] Background sync registration failed:', error)
  }
}

// ─────────────────────────────────────────────────────────────
// Periodic Background Sync
// ─────────────────────────────────────────────────────────────

export async function registerPeriodicSync(tag: string, minInterval: number = 24 * 60 * 60 * 1000): Promise<void> {
  if (!swRegistration) return
  if (!('periodicSync' in swRegistration)) {
    console.log('[PWA] Periodic sync not supported')
    return
  }

  try {
    await (swRegistration as any).periodicSync.register(tag, { minInterval })
    console.log('[PWA] Periodic sync registered:', tag)
  } catch (error) {
    console.error('[PWA] Periodic sync registration failed:', error)
  }
}

// ─────────────────────────────────────────────────────────────
// Offline Queue
// ─────────────────────────────────────────────────────────────

const DB_NAME = 'jaeger-offline'
const STORE_NAME = 'pending-messages'

async function openDB(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, 1)
    request.onerror = () => reject(request.error)
    request.onsuccess = () => resolve(request.result)
    request.onupgradeneeded = (event) => {
      const db = (event.target as IDBOpenDBRequest).result
      if (!db.objectStoreNames.contains(STORE_NAME)) {
        db.createObjectStore(STORE_NAME, { keyPath: 'id', autoIncrement: true })
      }
    }
  })
}

export async function queueMessageForSync(sessionId: string, text: string): Promise<void> {
  const db = await openDB()
  const tx = db.transaction(STORE_NAME, 'readwrite')
  const store = tx.objectStore(STORE_NAME)
  
  await new Promise<void>((resolve, reject) => {
    const request = store.add({
      sessionId,
      text,
      timestamp: Date.now(),
    })
    request.onsuccess = () => resolve()
    request.onerror = () => reject(request.error)
  })
  
  // Trigger background sync
  await registerBackgroundSync('sync-messages')
}

// ─────────────────────────────────────────────────────────────
// Online/Offline Status
// ─────────────────────────────────────────────────────────────

export function setupOnlineStatus(): void {
  window.addEventListener('online', () => {
    console.log('[PWA] Back online')
    dispatchEvent(new CustomEvent('pwa-online'))
  })

  window.addEventListener('offline', () => {
    console.log('[PWA] Gone offline')
    dispatchEvent(new CustomEvent('pwa-offline'))
  })
}

export function isOnline(): boolean {
  return navigator.onLine
}

// ─────────────────────────────────────────────────────────────
// Utilities
// ─────────────────────────────────────────────────────────────

function urlBase64ToUint8Array(base64String: string): Uint8Array {
  const padding = '='.repeat((4 - (base64String.length % 4)) % 4)
  const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/')
  const rawData = window.atob(base64)
  const outputArray = new Uint8Array(rawData.length)
  for (let i = 0; i < rawData.length; ++i) {
    outputArray[i] = rawData.charCodeAt(i)
  }
  return outputArray
}

// ─────────────────────────────────────────────────────────────
// Initialize PWA
// ─────────────────────────────────────────────────────────────

export async function initPWA(): Promise<void> {
  console.log('[PWA] Initializing...')
  
  await registerServiceWorker()
  setupInstallPrompt()
  setupOnlineStatus()
  
  // Register periodic sync for agent status (daily)
  await registerPeriodicSync('check-agent-status', 24 * 60 * 60 * 1000)
  
  console.log('[PWA] Initialized')
}

// Auto-initialize in browser
if (typeof window !== 'undefined') {
  initPWA()
}
