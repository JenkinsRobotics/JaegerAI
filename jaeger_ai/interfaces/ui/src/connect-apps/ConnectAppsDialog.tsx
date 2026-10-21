/** Gateway registry and read-only probes; installation requires a separate explicit decision. */
import { useEffect, useRef, useState } from "react";
import { Dialog } from "@aether/ui";
import type { ConnectedApp, ConnectAppsListing, JaegerSource } from "../api/source";

export function ConnectAppsDialog({ open, onClose, source }: { open: boolean; onClose: () => void; source: JaegerSource }) {
  const [listing, setListing] = useState<ConnectAppsListing>();
  const [error, setError] = useState<string>(), [actionError, setActionError] = useState<string>();
  const [query, setQuery] = useState(""), [category, setCategory] = useState("");
  const [attempt, setAttempt] = useState(0), [confirm, setConfirm] = useState<ConnectedApp>();
  const [busy, setBusy] = useState<string>(), locked = useRef(false);
  const [unknown, setUnknown] = useState<string[]>([]);
  useEffect(() => {
    if (!open || !source.connectApps) return;
    let live = true, reading = false;
    const load = async () => {
      if (reading) return; reading = true;
      try { const value = await source.connectApps!.list(); if (live) { setListing(value); setError(undefined); } }
      catch (e) { if (live) setError(String((e as Error).message ?? e)); }
      finally { reading = false; }
    };
    void load(); const timer = setInterval(load, 15_000);
    return () => { live = false; clearInterval(timer); };
  }, [open, source, attempt]);
  const refresh = async (app: ConnectedApp) => {
    if (locked.current || !source.connectApps) return;
    locked.current = true; setBusy(app.id); setActionError(undefined);
    try {
      const result = await source.connectApps.state(app.id);
      if (result.id !== app.id) throw new Error("App identity mismatch");
      setListing(current => current && { ...current, apps: current.apps.map(a => a.id === app.id ? { ...a, state: result.state } : a) });
      if (["installed", "error"].includes(result.state.value)) setUnknown(ids => ids.filter(id => id !== app.id));
    } catch (e) { setActionError(String((e as Error).message ?? e)); }
    finally { locked.current = false; setBusy(undefined); }
  };
  const install = async () => {
    const app = confirm; if (!app || locked.current || !source.connectApps) return;
    locked.current = true; setBusy(app.id); setConfirm(undefined); setActionError(undefined);
    try {
      const receipt = await source.connectApps.install(app.id);
      // Acknowledgement is admission, not proof of installation. Read the probe again.
      if (receipt.state) setListing(current => current && { ...current, apps: current.apps.map(a => a.id === app.id ? { ...a, state: receipt.state! } : a) });
      setAttempt(n => n + 1);
    } catch (e) { setUnknown(ids => [...new Set([...ids, app.id])]); setActionError(`Installation outcome unconfirmed: ${String((e as Error).message ?? e)}. Check status; no automatic retry.`); }
    finally { locked.current = false; setBusy(undefined); }
  };
  return <Dialog open={open} title="Connect apps" onClose={onClose} actions={<button type="button" className="aui-button" onClick={onClose}>Close</button>}>
    {!source.connectApps && <p>App connections are not available from this host.</p>}
    {source.connectApps && <><label>Find app <input aria-label="Find app" value={query} onChange={e => setQuery(e.target.value)} /></label>
      <label>Category <select aria-label="App category" value={category} onChange={e => setCategory(e.target.value)}><option value="">All categories</option>{listing?.categories.map(c => <option key={c.id} value={c.id}>{c.label}</option>)}</select></label>
      {error && <p role="alert">Couldn't load app connections: {error} <button type="button" onClick={() => setAttempt(n => n + 1)}>Retry</button></p>}
      {actionError && <p role="alert">{actionError}</p>}
      {!listing && !error && <p role="status">Checking app connections…</p>}
      <ul className="jg-apps">{listing?.apps.filter(app => (!category || category === app.category) && `${app.name} ${app.description ?? ""}`.toLowerCase().includes(query.toLowerCase())).map(app => <li key={app.id} className="jg-apps__row">
        <span className="jg-agent-row__text"><span className="jg-agent-row__name">{app.name}</span><span className="jg-agent-row__preview">{app.description}</span><span>{app.state.value.replaceAll("_", " ")}{app.state.version ? ` · ${app.state.version}` : ""}{app.state.detail ? ` · ${app.state.detail.replaceAll("_", " ")}` : ""}</span></span>
        {app.status === "available" && <button type="button" className="aui-button" disabled={Boolean(busy)} onClick={() => void refresh(app)}>Check status</button>}
        {app.status === "available" && app.actions.includes("install") && app.state.value !== "installed" && <button type="button" className="aui-button" disabled={Boolean(busy) || app.state.value === "installing" || unknown.includes(app.id)} onClick={() => setConfirm(app)}>Install…</button>}
      </li>)}</ul>
      {confirm && <section role="alertdialog" aria-label={`Install ${confirm.name}`}><p>Install the Gateway's configured {confirm.name} integration? The Gateway checks caller permission and the local package before installation.</p><button type="button" onClick={() => setConfirm(undefined)}>Cancel</button><button type="button" disabled={Boolean(busy)} onClick={() => void install()}>Confirm installation</button></section>}
    </>}
  </Dialog>;
}
