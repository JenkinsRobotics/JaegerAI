import { useEffect, useState } from "react";
import type { JaegerSource, MemoryUpkeep, OwnerProfile } from "../api/source";

const when = (ts: number) => new Date(ts * 1000).toLocaleString();
const who = (origin: string) => origin === "owner" ? "You" : origin === "seed" ? "Imported" : "Jaeger";

/** What Jaeger knows about the owner (memory/USER.md) — readable and editable, with history. */
export function OwnerProfilePanel({ source }: { source: JaegerSource }) {
  const api = source.ownerProfile;
  const [data, setData] = useState<OwnerProfile>(), [draft, setDraft] = useState(""), [editing, setEditing] = useState(false);
  const [upkeep, setUpkeep] = useState<MemoryUpkeep>(), [error, setError] = useState(""), [notice, setNotice] = useState(""), [busy, setBusy] = useState(false), [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let live = true;
    void Promise.all([api?.get(), api?.upkeep()]).then(([p, u]) => { if (!live) return; if (p) { setData(p); if (!editing) setDraft(p.profile); } if (u) setUpkeep(u); setError(""); }, e => { if (live) setError(String((e as Error).message ?? e)); });
    return () => { live = false; };
  }, [api, attempt]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!api) return null;
  const save = async () => {
    setBusy(true); setNotice(""); setError("");
    try { const r = await api.save(draft); setNotice(r.changed ? "Saved. Jaeger uses this from the next message." : "No changes."); setEditing(false); setAttempt(n => n + 1); }
    catch (e) { setError(String((e as Error).message ?? e)); } finally { setBusy(false); }
  };
  const revert = async (previous: string) => {
    if (!window.confirm("Restore the profile as it was before this change? The current text is kept in history.")) return;
    setBusy(true); try { await api.revert(previous); setNotice("Restored."); setEditing(false); setAttempt(n => n + 1); } catch (e) { setError(String(e)); } finally { setBusy(false); }
  };
  const toggle = async (enabled: boolean) => { try { setUpkeep(await api.setUpkeep({ enabled })); } catch (e) { setError(String(e)); } };
  const setHour = async (hour: number) => { try { setUpkeep(await api.setUpkeep({ hour })); } catch (e) { setError(String(e)); } };
  const over = draft.length > (data?.limit ?? 3000);
  return <section aria-label="About you" className="owner-profile">
    <h3>About you</h3>
    <p>What Jaeger has learned about you from your chats. It reads this at the start of every conversation. Edit anything that's wrong; never put passwords or codes here.</p>
    {error && <p role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}
    {!data && !error && <p>Loading…</p>}
    {data && <>
      <textarea aria-label="Profile" value={draft} readOnly={!editing} onChange={e => setDraft(e.target.value)} rows={14}
        style={{ width: "100%", fontFamily: "ui-monospace, SFMono-Regular, monospace", fontSize: 12.5, opacity: editing ? 1 : .9 }} />
      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        {!editing && <button type="button" onClick={() => setEditing(true)}>Edit</button>}
        {editing && <><button type="button" disabled={busy || over} onClick={() => void save()}>Save</button><button type="button" disabled={busy} onClick={() => { setDraft(data.profile); setEditing(false); }}>Cancel</button></>}
        <span style={{ opacity: .7, color: over ? "var(--danger, #c33)" : undefined }}>{draft.length} / {data.limit} characters</span>
      </div>
      {data.changes.length > 0 && <details style={{ marginTop: 8 }}><summary>Recent changes ({data.changes.length})</summary>
        <ul style={{ listStyle: "none", padding: 0 }}>{data.changes.map((c, i) => <li key={i} style={{ display: "flex", gap: 8, alignItems: "baseline", flexWrap: "wrap", padding: "3px 0" }}>
          <span style={{ opacity: .7 }}>{when(c.ts)}</span><strong>{who(c.origin)}</strong><span>{c.summary}</span>
          {c.previous && <button type="button" disabled={busy} onClick={() => void revert(c.previous!)}>Undo</button>}
        </li>)}</ul></details>}
    </>}
    {upkeep && <div style={{ marginTop: 12 }}>
      <label style={{ display: "flex", gap: 8, alignItems: "center" }}><input type="checkbox" checked={upkeep.enabled} onChange={e => void toggle(e.target.checked)} />
        Nightly memory upkeep at <select value={upkeep.hour} disabled={!upkeep.enabled} onChange={e => void setHour(Number(e.target.value))}>{Array.from({ length: 24 }, (_, h) => <option key={h} value={h}>{new Date(2000, 0, 1, h).toLocaleTimeString([], { hour: "numeric" })}</option>)}</select></label>
      <p style={{ opacity: .75, margin: "4px 0" }}>Each night Jaeger reviews your messages from that day and updates this profile. It also does a short review every {upkeep.review_every_turns} messages in a chat.{upkeep.next_run ? ` Next run: ${new Date(upkeep.next_run).toLocaleString()}.` : ""}</p>
      {upkeep.runs.length > 0 && <details><summary>Upkeep history ({upkeep.runs.length})</summary><ul style={{ listStyle: "none", padding: 0 }}>{upkeep.runs.map((r, i) => <li key={i}><span style={{ opacity: .7 }}>{when(r.at)}</span> · {r.kind} · {r.status}{r.messages ? ` · ${r.messages} messages` : ""}{r.reply && r.reply !== "NO_REPLY" ? ` — ${r.reply}` : ""}{r.error ? ` — ${r.error}` : ""}</li>)}</ul></details>}
    </div>}
  </section>;
}
