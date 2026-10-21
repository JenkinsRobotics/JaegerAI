import { Dialog } from '@aether/ui';
import { useEffect, useRef, useState } from 'react';
import type { SpecialistConfiguration as Configuration, SpecialistControls, SpecialistSettings } from '../api/source';
interface Pending { expected_revision: number; settings: SpecialistSettings }
const values = (row: SpecialistSettings): SpecialistSettings => ({ specialty: row.specialty, summary: row.summary, instructions: row.instructions });
/** Registry prompt settings only. Unknown saves reconcile by reading; no automatic retry. */
export function SpecialistConfiguration({ agentId, controls, onClose, onSaved }: { agentId: string; controls: SpecialistControls; onClose: () => void; onSaved: () => void }) {
  const key = `jaeger.ui.specialist-settings.v1.${encodeURIComponent(agentId)}`;
  const [row, setRow] = useState<Configuration>(), [draft, setDraft] = useState<SpecialistSettings>();
  const [baseRevision, setBaseRevision] = useState<number>();
  const storageBlocked = useRef(false);
  const [pending, setPending] = useState<Pending>(), [error, setError] = useState<string>(), [notice, setNotice] = useState<string>();
  const [busy, setBusy] = useState(false); const lock = useRef(false);
  useEffect(() => {
    let live = true;
    void controls.read(agentId).then(current => {
      if (!live) return;
      if (current.agent_id !== agentId) throw Error('Specialist configuration identity mismatch');
      const raw = localStorage.getItem(key);
      const saved = raw ? JSON.parse(raw) : undefined;
      if (saved && (!saved.draft || !['specialty', 'summary', 'instructions'].every(k => typeof saved.draft[k] === 'string'))) throw Error('Saved specialist draft invalid; original retained');
      setRow(current); setDraft(saved?.draft ?? values(current)); setPending(saved?.pending);
      setBaseRevision(saved?.baseRevision ?? saved?.pending?.expected_revision ?? current.revision);
      if (saved?.draft && (saved.baseRevision ?? saved.pending?.expected_revision ?? current.revision) !== current.revision) setNotice('This draft began on an older revision. Read current saved settings before replacing a newer edit.');
    }).catch(e => { if (live) setError(String(e)); });
    return () => { live = false; };
  }, [agentId, controls, key]);
  const edit = (patch: Partial<SpecialistSettings>) => {
    if (!draft) return; const next = { ...draft, ...patch }; setDraft(next);
    try { localStorage.setItem(key, JSON.stringify({ draft: next, pending, baseRevision })); storageBlocked.current = false; } catch (e) { storageBlocked.current = true; setError(`Draft not saved on this device: ${String(e)}`); }
  };
  const save = async () => {
    if (!row?.editable || !draft || pending || lock.current) return;
    lock.current = true; setBusy(true); setError(undefined); setNotice(undefined);
    const intent = { expected_revision: baseRevision ?? row.revision, settings: draft };
    try {
      localStorage.setItem(key, JSON.stringify({ draft, pending: intent, baseRevision: intent.expected_revision })); setPending(intent);
      const current = await controls.save(agentId, intent);
      if (current.agent_id !== agentId || current.revision !== intent.expected_revision + 1) throw Error('Save receipt identity/revision mismatch');
      setRow(current); setBaseRevision(current.revision); setDraft(values(current)); storageBlocked.current = false;
      localStorage.removeItem(key); setPending(undefined); setNotice('Specialist settings saved. Existing tools, approvals and conversations are unchanged.'); onSaved();
    } catch (e) { setError(`Save not confirmed: ${String((e as Error).message ?? e)}. Check current settings before changing them again.`); }
    finally { lock.current = false; setBusy(false); }
  };
  const check = async () => {
    if (lock.current) return; lock.current = true; setBusy(true); setError(undefined);
    try {
      const current = await controls.read(agentId);
      if (current.agent_id !== agentId) throw Error('Specialist configuration identity mismatch');
      // Preserve local text if another client won. Reading does not replay a save.
      const nextDraft = draft ?? values(current);
      localStorage.setItem(key, JSON.stringify({ draft: nextDraft, baseRevision: current.revision })); storageBlocked.current = false;
      setDraft(nextDraft); setBaseRevision(current.revision); setPending(undefined); setRow(current);
      setNotice(JSON.stringify(values(current)) === JSON.stringify(draft) ? `Current saved settings match this draft (revision ${current.revision}).` : `Current revision is ${current.revision}. Your draft is preserved; review it before saving against this revision.`); onSaved();
    } catch (e) { setError(`Could not reconcile settings: ${String(e)}. Nothing was resent.`); }
    finally { lock.current = false; setBusy(false); }
  };
  const close = () => { if (busy) return; if (storageBlocked.current) { setError('Draft is not saved on this device. Keep this editor open and save or copy your text before closing.'); return; } onClose(); };
  return <Dialog open title="Specialist configuration" onClose={close} actions={<><button type="button" disabled={busy} onClick={close}>Close</button><button type="button" disabled={busy || !row?.editable || !draft || Boolean(pending)} onClick={() => void save()}>Save specialist settings</button></>}>
    {!row && !error && <p role="status">Loading specialist configuration…</p>}
    {error && <p role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}
    {row && <><p>Revision {row.revision}{row.template ? ` · ${row.template.id} v${row.template.version}` : ''}. Prompt settings do not grant tools or bypass approvals.</p>{!row.editable && <p>This definition is protected or this caller cannot edit it.</p>}</>}
    {row && <details><summary>Current saved specialist settings</summary><p>{row.specialty}</p><p>{row.summary}</p><pre>{row.instructions}</pre></details>}
    {draft && <form className="jg-form" onSubmit={e => { e.preventDefault(); void save(); }}>{(['specialty', 'summary', 'instructions'] as const).map(field => <label className="jg-form__field" key={field}><span>{field}</span><textarea aria-label={`Specialist ${field}`} disabled={busy || !row?.editable || Boolean(pending)} maxLength={{specialty:200,summary:2000,instructions:12000}[field]} value={draft[field]} onChange={e => edit({ [field]: e.target.value })} /></label>)}</form>}
    <button type="button" disabled={busy} onClick={() => void check()}>{pending ? 'Check uncertain settings save' : 'Read current saved settings'}</button>
  </Dialog>;
}
