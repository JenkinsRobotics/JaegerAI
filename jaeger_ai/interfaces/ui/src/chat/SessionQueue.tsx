import { useEffect, useRef, useState } from "react";
import type { QueuedRequest, SessionQueue as QueueControls } from "../api/source";
const prefix = (id: string) => `jaeger.ui.queue.v1.${encodeURIComponent(id)}`;
interface Intent { requestId: string; text: string }
/** Explicit text follow-ups; no second executor, blind retry or permanent removal. */
export function SessionQueue({ controls, sessionId, onAccepted }: { controls: QueueControls; sessionId: string; onAccepted: () => void }) {
  const [rows, setRows] = useState<QueuedRequest[]>(), [attempt, setAttempt] = useState(0);
  const [text, setText] = useState(""), [pending, setPending] = useState<Intent>();
  const [editing, setEditing] = useState<QueuedRequest>(), [editText, setEditText] = useState("");
  const [error, setError] = useState<string>(), [notice, setNotice] = useState<string>();
  const [busy, setBusy] = useState(false), lock = useRef(false);
  const [expanded, setExpanded] = useState(false);
  useEffect(() => {
    try {
      setText(localStorage.getItem(prefix(sessionId) + '.draft') ?? "");
      const raw = localStorage.getItem(prefix(sessionId) + '.intent');
      if (raw) { const saved = JSON.parse(raw); if (typeof saved.requestId !== 'string' || typeof saved.text !== 'string') throw Error('Saved queue identity invalid; original retained'); setPending(saved); }
    } catch (e) { lock.current = true; setError(`Queue recovery unavailable: ${String(e)}`); }
  }, [sessionId]);
  useEffect(() => {
    let live = true, reading = false;
    const load = async () => {
      if (reading) return; reading = true;
      try { const result = await controls.list(sessionId); if (result.session_id !== sessionId) throw Error('Queue conversation identity mismatch'); if (live) setRows(result.items); }
      catch (e) { if (live) setError(String((e as Error).message ?? e)); }
      finally { reading = false; }
    };
    void load(); const timer = setInterval(load, 3000);
    return () => { live = false; clearInterval(timer); };
  }, [controls, sessionId, attempt]);
  const accepted = (intent: Intent, status: string) => {
    setNotice(`Follow-up accepted: ${status}. Execution and tool approvals remain Gateway-owned.`);
    if ((localStorage.getItem(prefix(sessionId) + '.draft') ?? '') === intent.text) { localStorage.setItem(prefix(sessionId) + '.draft', ''); setText(current => current === intent.text ? '' : current); }
    localStorage.removeItem(prefix(sessionId) + '.intent'); setPending(undefined);
    setAttempt(n => n + 1); onAccepted();
  };
  const enqueue = async () => {
    if (lock.current || pending || !text.trim()) return;
    lock.current = true; setBusy(true); setError(undefined); setNotice(undefined);
    const intent = { requestId: crypto.randomUUID(), text };
    let admitted = false;
    try {
      localStorage.setItem(prefix(sessionId) + '.intent', JSON.stringify(intent)); setPending(intent);
      const receipt = await controls.enqueue(sessionId, intent.text, intent.requestId);
      if (receipt.session_id !== sessionId || receipt.request_id !== intent.requestId || !receipt.status) throw Error('Queue receipt identity unavailable');
      admitted = true;
      accepted(intent, receipt.status);
    } catch (e) { setError(`${admitted ? 'Follow-up accepted, but device recovery storage could not update' : 'Queue submission unconfirmed'}: ${String((e as Error).message ?? e)}. Check the saved request; no retry is automatic.`); }
    finally { lock.current = false; setBusy(false); }
  };
  const check = async () => {
    if (!pending || lock.current) return; lock.current = true; setBusy(true); setError(undefined);
    try { const row = await controls.status(sessionId, pending.requestId); if (row.request_id !== pending.requestId || row.session_id !== sessionId || !row.status) throw Error('No matching queue admission'); accepted(pending, row.status); }
    catch (e) { setError(`Saved queue outcome remains unconfirmed: ${String((e as Error).message ?? e)}. Nothing was resent.`); }
    finally { lock.current = false; setBusy(false); }
  };
  const update = async (row: QueuedRequest, patch: { text?: string; status?: 'paused' | 'queued' }) => {
    if (lock.current) return; lock.current = true; setBusy(true); setError(undefined);
    try { await controls.update(sessionId, row.request_id, { ...patch, expected_updated_at: row.updated_at }); setEditing(undefined); setAttempt(n => n + 1); onAccepted(); }
    catch (e) { setError(`Queue change not confirmed: ${String((e as Error).message ?? e)}. Refresh before changing it again.`); setAttempt(n => n + 1); }
    finally { lock.current = false; setBusy(false); }
  };
  const move = async (index: number, delta: number) => {
    if (!rows || lock.current) return; const order = rows.map(row => row.request_id); [order[index], order[index + delta]] = [order[index + delta], order[index]];
    lock.current = true; setBusy(true); setError(undefined);
    try { await controls.reorder(sessionId, order); setAttempt(n => n + 1); }
    catch (e) { setError(`Queue order not confirmed: ${String((e as Error).message ?? e)}`); setAttempt(n => n + 1); }
    finally { lock.current = false; setBusy(false); }
  };
  return <details className="jg-session-queue" open={expanded || Boolean(pending)} onToggle={e => setExpanded(e.currentTarget.open)}><summary>Follow-up queue{rows ? ` · ${rows.length}` : ''}</summary>
    {error && <p role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}
    {pending && <p role="alert">A queue submission needs reconciliation. <button type="button" disabled={busy} onClick={() => void check()}>Check saved queued request</button></p>}
    <form onSubmit={e => { e.preventDefault(); void enqueue(); }}><label>Queue a text follow-up <textarea aria-label="Queued follow-up text" value={text} disabled={busy || Boolean(pending)} onChange={e => { const next = e.target.value; setText(next); try { localStorage.setItem(prefix(sessionId) + '.draft', next); } catch (error) { setError(`Queue draft not saved: ${String(error)}`); } }} /></label><button disabled={busy || Boolean(pending) || !text.trim()}>Queue follow-up</button></form>
    <button type="button" disabled={busy} onClick={() => setAttempt(n => n + 1)}>Refresh queue</button>
    {rows?.map((row, index) => <article key={row.request_id}><p>{row.input_text}</p><span>{row.status}</span><button type="button" disabled={busy} onClick={() => void update(row, { status: row.status === 'paused' ? 'queued' : 'paused' })}>{row.status === 'paused' ? 'Resume queued request' : 'Pause queued request'}</button><button type="button" disabled={busy} onClick={() => { setEditing(row); setEditText(row.input_text); }}>Edit queued text</button><button type="button" disabled={busy || index === 0} onClick={() => void move(index, -1)}>Move earlier</button><button type="button" disabled={busy || index === rows.length - 1} onClick={() => void move(index, 1)}>Move later</button></article>)}
    {editing && <form onSubmit={e => { e.preventDefault(); void update(editing, { text: editText }); }}><textarea aria-label="Revised queued text" value={editText} disabled={busy} onChange={e => setEditText(e.target.value)} /><button disabled={busy || !editText.trim()}>Save queued text</button><button type="button" disabled={busy} onClick={() => setEditing(undefined)}>Close queue editor</button></form>}
  </details>;
}
