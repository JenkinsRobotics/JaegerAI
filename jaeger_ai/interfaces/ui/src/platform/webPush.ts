/**
 * Web Push for the browser / iOS Home Screen app (standard Push API + VAPID).
 *
 * - `registerServiceWorker()` runs at startup (push-only worker, see public/sw.js).
 * - `enablePush()` must run from a user tap: it asks for notification permission,
 *   subscribes with the Gateway's VAPID key and registers the device.
 * - `startPresence()` tells the Gateway when this window is in use, so "reply ready"
 *   pushes only go out while the owner is away (ChatGPT-style).
 */
import { csrfHeader } from "../api/gateway";

const SUB_KEY = "jaeger.push.subscription_id";
const CLIENT_KEY = "jaeger.push.client_id";

export type PushSupport =
  | { ok: true; ios: boolean; standalone: boolean }
  | { ok: false; reason: "insecure" | "ios_browser" | "unsupported"; ios: boolean; standalone: boolean };

export type PushDevice = {
  id: string; device_label?: string; platform?: string; standalone?: boolean; created_at?: number;
  last_sent_at?: number | null; last_status?: number | string | null; push_service?: string | null; origin?: string | null;
};

export function isIOS(): boolean {
  const ua = navigator.userAgent || "";
  return /iPad|iPhone|iPod/.test(ua) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
}

export function isStandalone(): boolean {
  return window.matchMedia?.("(display-mode: standalone)").matches === true || (navigator as unknown as { standalone?: boolean }).standalone === true;
}

export function pushSupport(): PushSupport {
  const ios = isIOS(), standalone = isStandalone();
  if (!window.isSecureContext) return { ok: false, reason: "insecure", ios, standalone };
  const apis = "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
  if (ios && !standalone) return { ok: false, reason: "ios_browser", ios, standalone };
  if (!apis) return { ok: false, reason: "unsupported", ios, standalone };
  return { ok: true, ios, standalone };
}

export function permission(): NotificationPermission | "unsupported" {
  return "Notification" in window ? Notification.permission : "unsupported";
}

export function thisDeviceId(): string | null {
  try { return localStorage.getItem(SUB_KEY); } catch { return null; }
}

async function api<T>(path: string, method = "GET", body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method, cache: "no-store", credentials: "same-origin",
    headers: { Accept: "application/json", ...(body === undefined ? {} : { "Content-Type": "application/json" }), ...csrfHeader(method) },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error((data as { error?: string }).error || `HTTP ${res.status}`);
  return data as T;
}

function urlB64ToUint8Array(b64: string): Uint8Array {
  const pad = "=".repeat((4 - (b64.length % 4)) % 4);
  const raw = atob((b64 + pad).replace(/-/g, "+").replace(/_/g, "/"));
  return Uint8Array.from(raw, (c) => c.charCodeAt(0));
}

function deviceLabel(): string {
  const ua = navigator.userAgent;
  const device = /iPhone/.test(ua) ? "iPhone" : /iPad/.test(ua) || (isIOS() && !/iPhone/.test(ua)) ? "iPad"
    : /Android/.test(ua) ? "Android" : /Macintosh|Mac OS X/.test(ua) ? "Mac" : /Windows/.test(ua) ? "Windows" : /Linux/.test(ua) ? "Linux" : "Device";
  const browser = isStandalone() ? "Home Screen app" : /Edg\//.test(ua) ? "Edge" : /Chrome\//.test(ua) ? "Chrome"
    : /Firefox\//.test(ua) ? "Firefox" : /Safari\//.test(ua) ? "Safari" : "Browser";
  return `${device} · ${browser}`;
}

export async function registerServiceWorker(): Promise<ServiceWorkerRegistration | null> {
  if (!("serviceWorker" in navigator) || !window.isSecureContext) return null;
  try { return await navigator.serviceWorker.register("/sw.js", { scope: "/" }); } catch { return null; }
}

async function registration(): Promise<ServiceWorkerRegistration> {
  const reg = (await navigator.serviceWorker.getRegistration("/")) ?? (await registerServiceWorker());
  if (!reg) throw new Error("Service worker could not be registered");
  return navigator.serviceWorker.ready.then(() => reg);
}

async function saveSubscription(sub: PushSubscription): Promise<PushDevice> {
  const json = sub.toJSON();
  const out = await api<{ subscription: PushDevice }>("/v1/push/subscriptions", "POST", {
    endpoint: json.endpoint, keys: json.keys, device_label: deviceLabel(),
    platform: isIOS() ? "ios" : navigator.platform || "web", standalone: isStandalone(), origin: location.origin,
  });
  try { localStorage.setItem(SUB_KEY, out.subscription.id); } catch { /* private mode */ }
  return out.subscription;
}

/** Must be called from a user gesture (iOS only prompts after a tap). */
export async function enablePush(): Promise<PushDevice> {
  const support = pushSupport();
  if (!support.ok) throw new Error("Notifications aren't available here");
  const granted = await Notification.requestPermission();
  if (granted !== "granted") throw new Error(granted === "denied" ? "Notifications are blocked for this site" : "Permission was not granted");
  const reg = await registration();
  const { public_key } = await api<{ public_key: string }>("/v1/push/vapid-public-key");
  let sub = await reg.pushManager.getSubscription();
  const key = urlB64ToUint8Array(public_key);
  if (sub && sub.options.applicationServerKey) {
    const current = new Uint8Array(sub.options.applicationServerKey);
    if (current.length !== key.length || current.some((b, i) => b !== key[i])) { await sub.unsubscribe(); sub = null; }
  }
  sub = sub ?? await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: key as unknown as BufferSource });
  return saveSubscription(sub);
}

/** Turn off push on this device only. */
export async function disablePush(): Promise<void> {
  const id = thisDeviceId();
  try {
    const reg = await navigator.serviceWorker.getRegistration("/");
    const sub = await reg?.pushManager.getSubscription();
    await sub?.unsubscribe();
  } finally {
    if (id) await api(`/v1/push/subscriptions/${encodeURIComponent(id)}`, "DELETE").catch(() => undefined);
    try { localStorage.removeItem(SUB_KEY); } catch { /* ignore */ }
  }
}

/** On app open: keep an existing subscription registered (idempotent upsert). */
export async function syncPush(): Promise<void> {
  if (!pushSupport().ok || permission() !== "granted") return;
  const reg = await navigator.serviceWorker.getRegistration("/");
  const sub = await reg?.pushManager.getSubscription();
  if (sub && thisDeviceId()) await saveSubscription(sub).catch(() => undefined);
}

export const pushApi = {
  devices: () => api<{ subscriptions: PushDevice[] }>("/v1/push/subscriptions").then((r) => r.subscriptions),
  remove: (id: string) => api(`/v1/push/subscriptions/${encodeURIComponent(id)}`, "DELETE"),
  test: (subscription_id?: string) => api<{ delivered: number; dropped: number; results: { id: string; status: number | string }[] }>(
    "/v1/push/test", "POST", subscription_id ? { subscription_id } : {}),
};

function clientId(): string {
  try {
    let id = sessionStorage.getItem(CLIENT_KEY);
    if (!id) { id = crypto.randomUUID?.() ?? String(Math.random()).slice(2); sessionStorage.setItem(CLIENT_KEY, id); }
    return id;
  } catch { return "anon"; }
}

/** Heartbeat "this window is in use" so long replies only push while the owner is away. */
export function startPresence(): () => void {
  let lastInput = Date.now(), timer = 0, stopped = false;
  const id = clientId();
  const inUse = () => document.visibilityState === "visible" && document.hasFocus() && Date.now() - lastInput < 120_000;
  const send = (visible: boolean) => {
    if (stopped) return;
    const body = JSON.stringify({ client_id: id, visible });
    void fetch("/v1/push/presence", { method: "POST", keepalive: true, credentials: "same-origin",
      headers: { "Content-Type": "application/json", ...csrfHeader("POST") }, body }).catch(() => undefined);
  };
  const tick = () => send(inUse());
  const input = () => { const was = Date.now() - lastInput >= 120_000; lastInput = Date.now(); if (was) tick(); };
  const vis = () => send(inUse());
  ["pointerdown", "keydown", "touchstart", "wheel"].forEach((e) => window.addEventListener(e, input, { passive: true }));
  document.addEventListener("visibilitychange", vis);
  window.addEventListener("focus", vis); window.addEventListener("blur", vis);
  window.addEventListener("pagehide", () => send(false));
  tick(); timer = window.setInterval(tick, 25_000);
  return () => { stopped = true; clearInterval(timer); document.removeEventListener("visibilitychange", vis); };
}

/** Deep link a push opened: `/?session=<id>&src=push`. */
export function pushTarget(url: string): { session_id?: string } | null {
  try {
    const u = new URL(url, location.origin);
    if (u.searchParams.get("src") !== "push") return null;
    const session = u.searchParams.get("session");
    return session ? { session_id: session } : {};
  } catch { return null; }
}
