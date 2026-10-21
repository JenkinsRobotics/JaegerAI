import { Dialog } from '@aether/ui';
import { useEffect, useRef, useState } from 'react';
import type { AgentKnowledgeControls, AgentKnowledgeSnapshot } from '../api/source';
export function AgentKnowledge({ agentId, controls, onClose, onSaved }: { agentId: string; controls: AgentKnowledgeControls; onClose: () => void; onSaved: () => void }) {
  const key = `jaeger.ui.agent-knowledge.v1.${encodeURIComponent(agentId)}`;
  const [row, setRow] = useState<AgentKnowledgeSnapshot>(), [selected, setSelected] = useState<string[]>([]), [base, setBase] = useState<number>(), [pending, setPending] = useState(false);
  const [busy, setBusy] = useState(false), [error, setError] = useState<string>(), [notice, setNotice] = useState<string>();
  const lock = useRef(false), volatile = useRef(false);
  useEffect(() => { let live = true; void controls.read(agentId).then(value => {
    if (!live) return; if (value.agent_id !== agentId) throw Error('Knowledge identity mismatch');
    const raw = localStorage.getItem(key), saved = raw ? JSON.parse(raw) : undefined;
    if (saved && (!Array.isArray(saved.ids) || !saved.ids.every((id: unknown) => typeof id === 'string') || !Number.isInteger(saved.revision))) throw Error('Saved knowledge selection invalid; original retained');
    setRow(value); setSelected(saved?.ids ?? value.documents.map(doc => doc.id)); setBase(saved?.revision ?? value.revision); setPending(saved?.pending === true);
    if (saved && saved.revision !== value.revision) setNotice('Selection began on an older configuration revision. Read current bindings before replacing a newer edit.');
  }).catch(e => { if (live) setError(String(e)); }); return () => { live = false; }; }, [agentId, controls, key]);
  const persist = (ids: string[], revision: number | undefined, uncertain: boolean) => { localStorage.setItem(key, JSON.stringify({ ids, revision, pending: uncertain })); volatile.current = false; };
  const toggle = (id: string) => {
    const next = selected.includes(id) ? selected.filter(value => value !== id) : [...selected, id]; setSelected(next);
    try { persist(next, base, false); } catch (e) { volatile.current = true; setError(`Selection not saved on this device: ${String(e)}. Keep this editor open.`); }
  };
  const save = async () => {
    if (!row?.editable || pending || lock.current || base === undefined) return;
    lock.current = true; setBusy(true); setError(undefined);
    try {
      persist(selected, base, true); setPending(true);
      const value = await controls.save(agentId, { expected_revision: base, document_ids: selected });
      if (value.agent_id !== agentId || value.revision !== base + 1 || JSON.stringify(value.documents.map(doc=>doc.id)) !== JSON.stringify(selected)) throw Error('Knowledge receipt identity/revision mismatch');
      setRow(value); setBase(value.revision); localStorage.removeItem(key); setPending(false); setNotice('Knowledge bindings saved at pinned document revisions. New turns load those revisions; no tools or permissions were granted.'); onSaved();
    } catch (e) { setError(`Knowledge save not confirmed: ${String((e as Error).message ?? e)}. Read current bindings; nothing is automatically retried.`); }
    finally { lock.current = false; setBusy(false); }
  };
  const check = async () => {
    if (lock.current) return; lock.current = true; setBusy(true);
    try { const value = await controls.read(agentId); if (value.agent_id !== agentId) throw Error('Knowledge identity mismatch'); const raw = localStorage.getItem(key), saved = raw ? JSON.parse(raw) : undefined; if (saved && (!Array.isArray(saved.ids) || !saved.ids.every((id: unknown) => typeof id === 'string') || !Number.isInteger(saved.revision))) throw Error('Saved selection is invalid and retained; recover it before saving'); const next = row ? selected : saved?.ids ?? value.documents.map(doc=>doc.id); persist(next, value.revision, false); setSelected(next); setRow(value); setBase(value.revision); setPending(false); setError(undefined); setNotice('Current bindings read without resubmitting. Your selection is preserved; compare saved revisions before saving again.'); }
    catch (e) { setError(String(e)); } finally { lock.current = false; setBusy(false); }
  };
  const close = () => { if (busy) return; if (volatile.current) { setError('Selection is not saved. Keep this editor open until it can be saved.'); return; } onClose(); };
  const catalog = row ? [...row.available, ...selected.filter(id=>!row.available.some(doc=>doc.id===id)).map(id=>({id,title:'Missing document',archived:true,revision:0,digest:''}))] : [];
  return <Dialog open title="Agent knowledge" onClose={close} actions={<><button type="button" disabled={busy} onClick={close}>Close</button><button type="button" disabled={busy || pending || !row?.editable || (!row?.limits || selected.length>row.limits.max_documents)} onClick={()=>void save()}>Save knowledge bindings</button></>}>
    <p>Choose managed Library documents{row?.limits ? ` (up to ${row.limits.max_documents}, ${row.limits.context_chars.toLocaleString()} characters total)` : ''}. Saving pins their current revisions for owner-authorized turns; external peers do not inherit document access. Indexed external files, credentials and access grants are not imported.</p>
    {error && <p role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}{!row && !error && <p role="status">Loading agent knowledge…</p>}
    {row && !row.editable && <p>This definition is protected or this caller cannot edit it.</p>}
    {catalog.map(doc=><label key={doc.id}><input type="checkbox" checked={selected.includes(doc.id)} disabled={busy || pending || !row?.editable || (doc.archived && !selected.includes(doc.id))} onChange={()=>toggle(doc.id)}/>{doc.title} · current revision {doc.revision}{doc.archived ? ' · archived/unavailable' : ''}</label>)}
    {row && <details><summary>Current saved knowledge bindings</summary>{row.documents.map(doc=><p key={doc.id}>{row.available.find(current=>current.id===doc.id)?.title ?? doc.id} · pinned revision {doc.revision}</p>)}{!row.documents.length && <p>No assigned documents.</p>}</details>}
    <button type="button" disabled={busy} onClick={()=>void check()}>Read current knowledge bindings</button>
  </Dialog>;
}
