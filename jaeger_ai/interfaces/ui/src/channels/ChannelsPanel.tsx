/* Settings › Automations › Channels: the owner's phone channels (Telegram bot + iMessage self-chat).
 * Owner-only, like Hermes/OpenClaw DM pairing: Telegram is locked to one paired private chat, iMessage only
 * uses Matthew's own self-chat. Messages from the phone run in the home chat; scheduled results, approvals and
 * proactive notes are delivered back. Data: GET/PATCH /v1/channels/relay (+ /pair, /unpair, /test). */
import { useCallback, useEffect, useState } from "react";
import type { Agent } from "../api/types";
import type { JaegerSource } from "../api/source";
import { WidgetCard } from "../widgets/primitives/WidgetCard";

interface RelayChannel { enabled: boolean; live: boolean; error?: string | null }
interface RelaySnapshot {
  relay_running: boolean;
  telegram: RelayChannel & { token_present: boolean; token_env: string; paired: boolean; pairing_code?: string | null; bot_username?: string | null };
  imessage: RelayChannel & { send_to?: string | null; self_handles: string[] };
  deliver: { schedules?: boolean; approvals?: boolean; notifications?: boolean; fanout?: "first" | "all" };
  counters?: Record<string, number>;
}

async function call<T>(path: string, method = "GET", body?: unknown): Promise<T> {
  const response = await fetch(path, { method, credentials: "same-origin", headers: body ? { "Content-Type": "application/json" } : undefined, body: body ? JSON.stringify(body) : undefined });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error((data as { error?: string }).error || `HTTP ${response.status}`);
  return data as T;
}

const dot = (live: boolean) => <span aria-hidden className={`jg-chan-dot ${live ? "is-live" : ""}`} style={{ display: "inline-block", width: 8, height: 8, borderRadius: 4, marginRight: 6, background: live ? "#3fb950" : "#8b949e" }} />;

export function ChannelsPanel(_props: { source: JaegerSource; agents?: Agent[] }) {
  const [snap, setSnap] = useState<RelaySnapshot>();
  const [error, setError] = useState<string>();
  const [notice, setNotice] = useState<string>();
  const [busy, setBusy] = useState(false);
  const load = useCallback(() => { call<RelaySnapshot>("/v1/channels/relay").then(s => { setSnap(s); setError(undefined); }, e => setError(String(e))); }, []);
  useEffect(() => { load(); const t = setInterval(load, 5000); return () => clearInterval(t); }, [load]);
  const act = async (path: string, method: string, body?: unknown, done?: string) => {
    setBusy(true); setNotice(undefined);
    try { setSnap(await call<RelaySnapshot>(path, method, body)); if (done) setNotice(done); setError(undefined); }
    catch (e) { setError(String(e)); } finally { setBusy(false); }
  };
  if (!snap) return <section aria-label="Phone channels">{error ? <WidgetCard title="Phone channels" state="error" message={`Could not read channel status: ${error}`} /> : <WidgetCard title="Phone channels" state="loading" message="Reading channel status…" />}</section>;
  const tg = snap.telegram, im = snap.imessage, d = snap.deliver;
  return <section aria-label="Phone channels" className="jg-phone-channels">
    <p>Talk to Jaeger from your phone. Messages land in your home chat, so the history is the same everywhere. Only you can reach it: Telegram is locked to your paired chat, and iMessage only uses your own self-chat.</p>
    {!snap.relay_running && <p role="alert">The channels service isn't running. Start it with <code>scripts/install-jaeger-channels.sh</code>.</p>}
    {notice && <p role="status">{notice}</p>}{error && <p role="alert">{error}</p>}
    <WidgetCard title="Telegram" status={<>{dot(tg.live)}{tg.live ? `Live${tg.bot_username ? ` · @${tg.bot_username}` : ""}` : !tg.token_present ? "Needs a bot token" : !tg.paired ? "Waiting to pair" : "Offline"}</>}
      actions={<>{tg.token_present && !tg.paired && <button type="button" disabled={busy} onClick={() => void act("/v1/channels/relay/pair", "POST", {}, "Pairing code ready for one hour.")}>Get pairing code</button>}
        {tg.paired && <button type="button" disabled={busy} onClick={() => void act("/v1/channels/relay/unpair", "POST", {}, "Telegram unpaired.")}>Unpair</button>}</>}>
      {!tg.token_present && <ol><li>In Telegram, message <b>@BotFather</b>, send <code>/newbot</code>, and pick a name and a username ending in “bot”.</li><li>Add the token it gives you to <code>~/.jaeger/secrets.env</code> as <code>{tg.token_env}=…</code>.</li><li>Come back here and choose <b>Get pairing code</b>.</li></ol>}
      {tg.token_present && !tg.paired && tg.pairing_code && <p>Send <code>/pair {tg.pairing_code}</code> to {tg.bot_username ? <b>@{tg.bot_username}</b> : "your bot"} from your own Telegram account. Anyone else is ignored.</p>}
      {tg.error && <p role="alert">{tg.error}</p>}
    </WidgetCard>
    <WidgetCard title="iMessage" status={<>{dot(im.live && !im.error)}{im.error ? "Needs permission" : im.live ? `Live · ${im.send_to}` : "Off"}</>}>
      <p>Uses your self-chat with <b>{im.send_to || "your own handle"}</b>. Jaeger's replies start with “Jaeger:”. It never messages anyone else.</p>
      {im.error && <p role="alert">{im.error}. In System Settings › Privacy &amp; Security, turn on Full Disk Access for <code>python3.12</code> and allow it to control Messages.</p>}
    </WidgetCard>
    <WidgetCard title="Send to my phone">
      {(["schedules", "approvals", "notifications"] as const).map(key => <label key={key} style={{ display: "block" }}><input type="checkbox" checked={d[key] !== false} disabled={busy} onChange={e => void act("/v1/channels/relay", "PATCH", { deliver: { [key]: e.target.checked } })} /> {key === "schedules" ? "Scheduled job results" : key === "approvals" ? "Approval requests (reply “approve” or “deny”)" : "Jaeger's proactive messages"}</label>)}
      <label style={{ display: "block" }}><input type="checkbox" checked={d.fanout === "all"} disabled={busy} onChange={e => void act("/v1/channels/relay", "PATCH", { deliver: { fanout: e.target.checked ? "all" : "first" } })} /> Send to every live channel (otherwise Telegram first, then iMessage)</label>
      <button type="button" disabled={busy || !(tg.live || im.live)} onClick={() => void call("/v1/channels/relay/test", "POST", {}).then(() => setNotice("Test message queued."), e => setError(String(e)))}>Send a test message</button>
      {snap.counters && <small style={{ display: "block", marginTop: 8 }}>Received {snap.counters.inbound ?? 0} · replied {snap.counters.replies ?? 0} · delivered {snap.counters.delivered ?? 0} · failed {snap.counters.failed ?? 0}</small>}
    </WidgetCard>
  </section>;
}
