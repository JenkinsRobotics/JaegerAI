import { useCallback, useEffect, useState } from "react";
import { csrfHeader } from "../api/gateway";
import { disablePush, enablePush, permission, pushApi, pushSupport, thisDeviceId, type PushDevice } from "../platform/webPush";

type Prefs = {
  revision: number;
  categories: Record<string, { push?: boolean }>;
  preview: "full" | "title_only" | "hidden";
  quiet_hours: { enabled: boolean; start: string; end: string; tz: string; allow: string[] };
};

/** What to push, grouped the way people think about it (each maps to Gateway categories). */
const TOPICS: { label: string; hint: string; keys: string[] }[] = [
  { label: "Approvals that need you", hint: "Actions waiting for your OK", keys: ["approvals_urgent", "approvals_routine", "spend_send", "design_reviews"] },
  { label: "Replies while you're away", hint: "When a longer reply finishes and Jaeger isn't open", keys: ["replies_away"] },
  { label: "Jaeger speaking up", hint: "When Jaeger has something to say and you aren't at the Mac Studio", keys: ["proactive_away"] },
  { label: "Scheduled job results", hint: "Results from your scheduled jobs", keys: ["scheduled"] },
  { label: "Problems", hint: "A task or job failed or is blocked", keys: ["task_failed"] },
];

const ago = (ts?: number | null) => {
  if (!ts) return "never";
  const s = Math.max(0, Date.now() / 1000 - ts);
  return s < 60 ? "just now" : s < 3600 ? `${Math.round(s / 60)} min ago` : s < 86400 ? `${Math.round(s / 3600)} h ago` : new Date(ts * 1000).toLocaleDateString();
};

async function json<T>(path: string, method = "GET", body?: unknown): Promise<T> {
  const res = await fetch(path, { method, cache: "no-store", credentials: "same-origin",
    headers: { Accept: "application/json", ...(body === undefined ? {} : { "Content-Type": "application/json" }), ...csrfHeader(method) },
    body: body === undefined ? undefined : JSON.stringify(body) });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error((data as { error?: string }).error || `HTTP ${res.status}`);
  return data as T;
}

/** Settings › Notifications › Push: this device, what to send, quiet hours, and every subscribed device. */
export function PushDevicesPanel() {
  const support = pushSupport();
  const [devices, setDevices] = useState<PushDevice[]>(), [prefs, setPrefs] = useState<Prefs>();
  const [mine, setMine] = useState<string | null>(thisDeviceId()), [perm, setPerm] = useState(permission());
  const [busy, setBusy] = useState(false), [error, setError] = useState(""), [notice, setNotice] = useState("");

  const load = useCallback(async () => {
    try {
      const [list, n] = await Promise.all([pushApi.devices(), json<{ preferences: Prefs }>("/v1/notifications")]);
      setDevices(list); setPrefs(n.preferences); setError("");
      const id = thisDeviceId();
      if (id && !list.some((d) => d.id === id)) { try { localStorage.removeItem("jaeger.push.subscription_id"); } catch { /* ignore */ } setMine(null); }
    } catch (e) { setError(String((e as Error).message ?? e)); }
  }, []);
  useEffect(() => { void load(); }, [load]);

  const run = async (fn: () => Promise<string | void>) => {
    setBusy(true); setError(""); setNotice("");
    try { const msg = await fn(); if (msg) setNotice(msg); } catch (e) { setError(String((e as Error).message ?? e)); }
    finally { setBusy(false); setPerm(permission()); setMine(thisDeviceId()); void load(); }
  };
  const enable = () => run(async () => { const d = await enablePush(); setMine(d.id); return "Notifications are on for this device."; });
  const disable = () => run(async () => { await disablePush(); return "Notifications are off for this device."; });
  const test = () => run(async () => {
    const r = await pushApi.test(mine ?? undefined);
    return r.delivered ? `Test sent to ${r.delivered} device${r.delivered === 1 ? "" : "s"}.` : "The push service didn't accept the test. Try turning notifications off and on again.";
  });
  const remove = (d: PushDevice) => run(async () => {
    if (d.id === mine) await disablePush(); else await pushApi.remove(d.id);
    return `Removed ${d.device_label || "device"}.`;
  });
  const patch = (body: Partial<Prefs>) => run(async () => {
    if (!prefs) return;
    const out = await json<{ preferences: Prefs }>("/v1/notifications", "PATCH", { expected_revision: prefs.revision, ...body });
    setPrefs(out.preferences);
  });

  const on = !!mine && perm === "granted";
  const topicOn = (keys: string[]) => !!prefs && keys.some((k) => prefs.categories[k]?.push);
  const setTopic = (keys: string[], value: boolean) => patch({ categories: Object.fromEntries(keys.map((k) => [k, { push: value }])) } as Partial<Prefs>);

  let hint = "";
  if (!support.ok && support.reason === "ios_browser") hint = "To get notifications on iPhone or iPad, tap Share, then Add to Home Screen, and open Jaeger from your Home Screen.";
  else if (!support.ok && support.reason === "insecure") hint = "Notifications need a secure (https) address. Open Jaeger through its Tailscale https address.";
  else if (!support.ok) hint = "This browser doesn't support push notifications.";
  else if (perm === "denied") hint = support.ios ? "Notifications are blocked. Turn them on in iOS Settings › Notifications › Jaeger." : "Notifications are blocked for this site. Allow them in your browser's site settings.";

  return <section aria-label="Push notifications" className="jg-push">
    <h3>Push notifications</h3>
    <div className="jg-push__row">
      <div>
        <strong>This device</strong>
        <p className="jg-push__muted">{on ? "On. Jaeger can notify you here even when the app is closed." : "Get notified on this device when Jaeger needs you."}</p>
      </div>
      {on
        ? <button type="button" disabled={busy} onClick={() => void disable()}>Turn off</button>
        : <button type="button" className="jg-push__primary" disabled={busy || !support.ok || perm === "denied"} onClick={() => void enable()}>Enable notifications on this device</button>}
    </div>
    {hint && <p className="jg-push__hint" role="note">{hint}</p>}
    {error && <p role="alert" className="jg-push__error">{error}</p>}
    {notice && <p role="status" className="jg-push__muted">{notice}</p>}

    {prefs && <fieldset className="jg-push__group" disabled={busy}>
      <legend>Notify me about</legend>
      {TOPICS.map((t) => <label key={t.label} className="jg-push__check">
        <input type="checkbox" checked={topicOn(t.keys)} onChange={(e) => void setTopic(t.keys, e.target.checked)} />
        <span><span>{t.label}</span><small>{t.hint}</small></span>
      </label>)}
      <label className="jg-push__inline">Show previews
        <select value={prefs.preview} onChange={(e) => void patch({ preview: e.target.value as Prefs["preview"] })}>
          <option value="full">Always</option><option value="title_only">Title only</option><option value="hidden">Never</option>
        </select>
      </label>
      <label className="jg-push__inline">
        <input type="checkbox" checked={prefs.quiet_hours.enabled} onChange={(e) => void patch({ quiet_hours: { ...prefs.quiet_hours, enabled: e.target.checked } })} />
        Quiet hours
        <input type="time" aria-label="Quiet hours start" value={prefs.quiet_hours.start} disabled={!prefs.quiet_hours.enabled}
          onChange={(e) => e.target.value && void patch({ quiet_hours: { ...prefs.quiet_hours, start: e.target.value } })} />
        to
        <input type="time" aria-label="Quiet hours end" value={prefs.quiet_hours.end} disabled={!prefs.quiet_hours.enabled}
          onChange={(e) => e.target.value && void patch({ quiet_hours: { ...prefs.quiet_hours, end: e.target.value } })} />
      </label>
      <p className="jg-push__muted">During quiet hours, notifications wait for a morning summary. Critical approvals still come through. Routine approvals are grouped every 30 minutes.</p>
    </fieldset>}

    <div className="jg-push__devices">
      <div className="jg-push__row">
        <strong>Devices</strong>
        <button type="button" disabled={busy || !devices?.length} onClick={() => void test()}>Send test</button>
      </div>
      {!devices && !error && <p className="jg-push__muted">Loading…</p>}
      {devices && !devices.length && <p className="jg-push__muted">No devices yet. Enable notifications on your phone to add it.</p>}
      {devices && devices.length > 0 && <ul>
        {devices.map((d) => <li key={d.id} className="jg-push__device">
          <span>
            <span>{d.device_label || d.push_service || "Device"}{d.id === mine && <em className="jg-push__pill">This device</em>}</span>
            <small>Added {ago(d.created_at)} · Last notification {ago(d.last_sent_at)}{d.last_status && d.last_status !== 201 && d.last_status !== 200 ? ` · last result ${d.last_status}` : ""}</small>
          </span>
          <button type="button" disabled={busy} onClick={() => void remove(d)}>Remove</button>
        </li>)}
      </ul>}
    </div>
  </section>;
}
