import {DiagnosticCapturePanel} from "./DiagnosticCapturePanel";
import { useEffect, useState } from 'react';
import type { GatewayDiagnostics, JaegerSource } from '../api/source';
export function DiagnosticsPanel({ source }: { source: JaegerSource }) {
  const [snapshot, setSnapshot] = useState<GatewayDiagnostics>(), [attempt, setAttempt] = useState(0), [error, setError] = useState<string>();
  const [checking, setChecking] = useState<string>(), [receipt, setReceipt] = useState<string>();
  useEffect(() => { let live = true; void source.diagnostics?.().then(value => { if (live) { setSnapshot(value); setError(undefined); } }, e => { if (live) setError(String(e)); }); return () => { live = false; }; }, [source, attempt]);
  const check = async (session: string, request: string) => {
    if (checking || !source.requestStatus) return; setChecking(request); setReceipt(undefined);
    try { const current = await source.requestStatus(session, request); if (current.request_id !== request || current.session_id !== session) throw Error('Request identity mismatch'); setReceipt(`Saved request ${request}: ${current.status}. Nothing was resubmitted.`); }
    catch (e) { setReceipt(`Could not read saved request ${request}: ${String(e)}. Nothing was resubmitted.`); }
    finally { setChecking(undefined); }
  };
  return <><section aria-label="Gateway diagnostics"><p>Read-only durable state. Unknown execution is preserved; checking never retries work.</p><button type="button" onClick={() => setAttempt(n=>n+1)}>Refresh diagnostics</button>
    {error && <p role="alert">Could not read diagnostics: {error}. Last snapshot retained.</p>}{!snapshot && !error && <p role="status">Reading Gateway diagnostics…</p>}
    {snapshot && <><p>Gateway process {snapshot.process_id} · observed {new Date(snapshot.observed_at*1000).toLocaleString()}</p><details><summary>Backend source fingerprint</summary><code>{snapshot.server_module_sha256}</code><p>{snapshot.fingerprint_scope}. This does not identify every loaded module or this UI build.</p></details><p>{snapshot.sessions} persisted conversations</p>
      {(['requests','approvals','handoffs'] as const).map(group=><section key={group}><h3>{group}</h3><dl>{Object.entries(snapshot[group]).map(([state,count])=><div key={state}><dt>{state.replaceAll('_',' ')}</dt><dd>{count}</dd></div>)}</dl>{!Object.keys(snapshot[group]).length && <p>No records.</p>}</section>)}
      <h3>Unknown requests</h3><p>Showing up to {snapshot.unknown_list_limit}; total {snapshot.requests.execution_unknown ?? 0}.</p>{snapshot.unknown_requests.map(row=><article className="jg-card" key={row.request_id}><p>{row.request_id}</p><small>Conversation {row.session_id}</small>{source.requestStatus && <button type="button" disabled={Boolean(checking)} onClick={() => void check(row.session_id,row.request_id)}>Check saved request status</button>}</article>)}</>}
    {receipt && <p role="status">{receipt}</p>}
  </section>{source.diagnosticCapture&&<DiagnosticCapturePanel controls={source.diagnosticCapture}/>}</>;
}
