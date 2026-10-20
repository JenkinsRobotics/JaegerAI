import { useRef, useState } from 'react';
import { useExclusivePopup } from '../popups/coordinator';
import type { Handoff } from '../api/types';

/** A new approved follow-up in the existing exchange, never an incoming-message executor. */
export function HandoffReplyDialog({ handoffId, send, onClose }: { handoffId: string; send: (id: string, task: string, requestId: string) => Promise<Handoff>; onClose: () => void }) {
  const [text, setText] = useState(''); const [busy, setBusy] = useState(false); const [error, setError] = useState(''); const [status, setStatus] = useState('');
  const requestId = useRef(crypto.randomUUID());
  useExclusivePopup(true, () => { if (!busy) onClose(); });
  return <div className="jg-amenu__scrim"><form className="jg-aprompt" role="dialog" aria-label="Follow up in this exchange" onSubmit={async (e) => {
    e.preventDefault(); if (busy || !text.trim() || status) return;
    setBusy(true); setError('');
    try { const row = await send(handoffId, text.trim(), requestId.current); setStatus(row.status === 'pending_approval' ? 'Follow-up saved. Awaiting approval.' : `Follow-up saved: ${row.status ?? 'status unavailable'}`); }
    catch (err) { setError(String((err as Error).message ?? err)); }
    finally { setBusy(false); }
  }}><h3>Follow up in this exchange</h3><p>Uses the same bots and conversation. A new approval is required before work starts.</p>
    <textarea aria-label="Follow-up message" value={text} disabled={busy || !!status} maxLength={20000} onChange={(e) => setText(e.target.value)} />
    {error && <p role="alert">{error}</p>}{status && <p role="status">{status}</p>}
    <div className="jg-aprompt__actions"><button type="button" disabled={busy} onClick={onClose}>Close</button><button type="submit" disabled={busy || !!status || !text.trim()}>Request follow-up</button></div>
  </form></div>;
}
