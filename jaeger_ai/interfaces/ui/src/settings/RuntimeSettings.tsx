import { useEffect, useRef, useState } from "react";
import { Dialog } from "@aether/ui";
import { createPortal } from "react-dom";
import type { ModelInventory, ModelSettings } from "../api/source";
import { useExclusivePopup } from "../popups/coordinator";

/** Session choice only. Credentials, global routing and permissions stay Gateway-owned. */
export function RuntimeSettings({ settings, sessionId, disabled = false }: { settings?: ModelSettings; sessionId?: string; disabled?: boolean }) {
  const [open, setOpen] = useState(false), [attempt, setAttempt] = useState(0);
  const [inventory, setInventory] = useState<ModelInventory>();
  const [selected, setSelected] = useState(""), [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string>(), [notice, setNotice] = useState<string>();
  const [busy, setBusy] = useState(false), locked = useRef(false);
  useExclusivePopup(open, () => { if (!locked.current) setOpen(false); });
  useEffect(() => {
    if (!open || !settings || !sessionId) return;
    let live = true; setLoaded(false); setError(undefined); setNotice(undefined);
    void Promise.all([settings.inventory(), settings.read(sessionId)]).then(([models, current]) => {
      if (!live) return;
      if (current.session_id !== sessionId) throw new Error("Conversation identity mismatch");
      setInventory(models); setSelected(current.model ? current.provider ? `@${current.provider}:${current.model}` : current.model : ""); setLoaded(true);
    }).catch(e => { if (live) setError(String((e as Error).message ?? e)); });
    return () => { live = false; };
  }, [open, settings, sessionId, attempt]);
  if (!settings || !sessionId) return null;
  const choices = inventory?.providers.filter(p => p.reachable).flatMap(p => p.models.filter(m => m.available !== false).map(m => ({ id: `@${p.id}:${m.id}`, label: `${p.display_name} · ${m.id}`, certified: m.usable_for_react }))) ?? [];
  const save = async () => {
    if (locked.current || !loaded) return;
    locked.current = true; setBusy(true); setError(undefined); setNotice(undefined);
    try {
      await settings.save(sessionId, selected || null);
      const current = await settings.read(sessionId);
      const actual = current.model ? current.provider ? `@${current.provider}:${current.model}` : current.model : "";
      if (current.session_id !== sessionId || actual !== selected) throw new Error("Saved choice could not be confirmed; refresh before changing it again");
      setNotice("Conversation model saved. Existing admitted work keeps its original model.");
    } catch (e) { setError(String((e as Error).message ?? e)); }
    finally { locked.current = false; setBusy(false); }
  };
  return <><button type="button" className="aui-button jg-runtime-trigger" disabled={disabled} onClick={() => setOpen(true)}>Gateway settings</button>
    {createPortal(<Dialog open={open} title="Gateway settings" onClose={() => { if (!busy) setOpen(false); }} actions={<button type="button" className="aui-button" disabled={busy} onClick={() => setOpen(false)}>Close</button>}>
      <p>Choose the model for this conversation. Global provider configuration, credentials and tool permissions are managed by the Gateway.</p>
      {error && <p role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}
      {!loaded && !error && <p role="status">Loading models and conversation settings…</p>}
      <button type="button" disabled={busy} onClick={() => setAttempt(n => n + 1)}>Refresh models and settings</button>
      {loaded && <><label>Conversation model <select aria-label="Conversation model" value={selected} disabled={busy} onChange={e => setSelected(e.target.value)}>
        <option value="">Gateway default{inventory?.active?.model ? ` · ${inventory.active.provider}/${inventory.active.model}` : ""}</option>
        {selected && !choices.some(m => m.id === selected) && <option value={selected} disabled>{selected} (currently unavailable)</option>}
        {choices.map(m => <option key={m.id} value={m.id}>{m.label}{m.certified ? "" : " (tool certification not verified)"}</option>)}
      </select></label><button type="button" disabled={busy || Boolean(selected && !choices.some(m => m.id === selected))} onClick={() => void save()}>Save conversation model</button></>}
      <ul>{inventory?.providers.map(provider => <li key={provider.id}><strong>{provider.display_name}</strong> · {provider.reachable ? "Reachable" : provider.configured ? "Unreachable" : "Not configured"}{provider.reason ? ` · ${provider.reason}` : ""}</li>)}</ul>
    </Dialog>, document.body)}
  </>;
}
