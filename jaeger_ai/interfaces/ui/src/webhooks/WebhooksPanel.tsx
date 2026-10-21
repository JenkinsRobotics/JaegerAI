import {useEffect, useRef, useState} from 'react';
import {GatewayError} from '../api/gateway';
import type {Agent} from '../api/types';
import type {JaegerSource, WebhookDefinition, WebhookDelivery, WebhookReceipt, WebhookSubscription} from '../api/source';

const DRAFT = 'jaeger.ui.webhook.draft.v1';
const OP = 'jaeger.ui.webhook.command.v1.';
interface Editor {id: string; revision: number; agentId: string; definition: WebhookDefinition}
interface Intent {id: string; operationId: string; editor: Editor; definition: WebhookDefinition}
const pendingCommands = (): Intent[] => Object.keys(localStorage).filter(k => k.startsWith(OP)).map(k => {
  const value = JSON.parse(localStorage.getItem(k)!);
  if (typeof value.operationId !== 'string' || typeof value.id !== 'string' || !value.editor || !value.definition) throw Error('Saved webhook command invalid; original retained');
  return value as Intent;
});
const savedDraftKeys = () => {try {return Object.keys(localStorage).filter(key => key.startsWith(DRAFT + '.saved.'));} catch {return [];}};
const empty = (): Editor => ({id: crypto.randomUUID(), revision: 0, agentId: '', definition: {name: '', provider: 'generic', events: [], senders: [], session_id: '', objective: '', enabled: false, archived: false}});

/** Setup definitions and receipts only. No test-send, listener or credential mutation. */
export function WebhooksPanel({source, agents}: {source: JaegerSource; agents: Agent[]}) {
  const controls = source.webhooks!;
  const [catalog, setCatalog] = useState<Awaited<ReturnType<typeof controls.list>>>();
  const [editor, setEditor] = useState<Editor>();
  const [pending, setPending] = useState<Intent[]>([]);
  const [history, setHistory] = useState<{id: string; rows: WebhookDelivery[]}>();
  const [attempt, setAttempt] = useState(0), [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>(), [notice, setNotice] = useState<string>();
  const [confirm, setConfirm] = useState<{row: WebhookSubscription; enabled: boolean; archived: boolean}>();
  const lock = useRef(false), volatile = useRef(false), historyGeneration = useRef(0);
  useEffect(() => {
    try {
      setPending(pendingCommands());
      const raw = localStorage.getItem(DRAFT);
      if (raw) {const draft = JSON.parse(raw); if (!draft.id || !draft.definition || !Number.isInteger(draft.revision)) throw Error('Saved webhook draft invalid; original retained'); setEditor(draft);}
    } catch (e) {lock.current = true; setError(String(e));}
    return () => {historyGeneration.current++;};
  }, []);
  useEffect(() => {let live = true; void controls.list().then(value => {if (live) setCatalog(value);}, e => {if (live) {setCatalog(undefined); setError(String(e));}}); return () => {live = false;};}, [controls, attempt]);
  const edit = (value: Editor) => {
    setEditor(value);
    try {localStorage.setItem(DRAFT + '.saved.' + value.id, JSON.stringify(value)); localStorage.setItem(DRAFT, JSON.stringify(value)); volatile.current = false;}
    catch (e) {volatile.current = true; setError('Draft not saved; preserve it before leaving: ' + String(e));}
  };
  const finish = (intent: Intent, receipt: WebhookReceipt) => {
    if (receipt.scope !== 'webhook.subscription' || receipt.operation_id !== intent.operationId) throw Error('Webhook receipt identity mismatch');
    if (receipt.ok && (!receipt.subscription || receipt.subscription.id !== intent.id)) throw Error('Saved subscription receipt mismatch');
    localStorage.removeItem(OP + intent.operationId); setPending(pendingCommands());
    if (!receipt.ok) throw Error(receipt.error ?? 'Subscription command rejected');
    // Do not replace a newer unsent draft or silently rebase it.
    const raw = localStorage.getItem(DRAFT);
    if (raw === JSON.stringify(intent.editor)) {
      localStorage.removeItem(DRAFT); localStorage.removeItem(DRAFT + '.saved.' + intent.id); setEditor(undefined);
    }
    setNotice(`Subscription saved at revision ${receipt.subscription!.revision}. No task was approved or external connection started.`);
    setAttempt(n => n + 1);
  };
  const save = async (value: Editor) => {
    if (lock.current || pending.length || volatile.current) return;
    lock.current = true; setBusy(true); setError(undefined); setNotice(undefined); setConfirm(undefined);
    let intent: Intent | undefined;
    try {
      const definition = {...value.definition};
      if (!value.agentId) throw Error('Choose an existing bot');
      const saved = catalog?.subscriptions.find(r => r.id === value.id);
      if (!saved || saved.agent_id !== value.agentId) {
        if (!source.agentHome) throw Error('Existing conversation binding unavailable');
        const home = await source.agentHome(value.agentId);
        if (home.agent_id !== value.agentId || !home.session_id) throw Error('Bot conversation identity mismatch');
        definition.session_id = home.session_id;
      }
      if (pendingCommands().length) throw Error('Another webhook command needs reconciliation');
      intent = {id: value.id, operationId: crypto.randomUUID(), editor: value, definition};
      localStorage.setItem(OP + intent.operationId, JSON.stringify(intent)); setPending(pendingCommands());
      finish(intent, await controls.save(value.id, {operation_id: intent.operationId, expected_revision: value.revision, definition}));
    } catch (e) {
      const body = e instanceof GatewayError && e.body && typeof e.body === 'object' ? e.body as Record<string, unknown> : undefined;
      const rejected = e instanceof GatewayError && !body?.execution_unknown && ([400,401,403,423].includes(e.status) || body?.ok === false && body.operation_id === intent?.operationId);
      if (rejected && intent) {localStorage.removeItem(OP + intent.operationId); setPending(pendingCommands());}
      setError(String(e) + (intent && !rejected ? '. Check the saved command; nothing is automatically repeated.' : '. Nothing was approved; original draft retained.'));
    } finally {lock.current = false; setBusy(false);}
  };
  const reconcile = async (intent: Intent) => {
    if (lock.current) return; lock.current = true; setBusy(true);
    try {const result = await controls.operation(intent.operationId); if (!result.receipt) throw Error('Webhook command remains unknown'); finish(intent, result.receipt);}
    catch (e) {setError(String(e));} finally {lock.current = false; setBusy(false);}
  };
  const openHistory = async (id: string) => {
    const generation = ++historyGeneration.current; setHistory(undefined);
    try {const result = await controls.history(id); if (result.subscription_id !== id) throw Error('Delivery history identity mismatch'); if (generation === historyGeneration.current) setHistory({id, rows: result.deliveries});}
    catch (e) {if (generation === historyGeneration.current) setError(String(e));}
  };
  const disabled = busy || pending.length > 0;
  const update = (patch: Partial<WebhookDefinition>) => editor && edit({...editor, definition: {...editor.definition, ...patch}});
  return <section className="jg-webhook-preferences" aria-label="Webhook subscriptions"><h3>Inbound webhook subscriptions</h3>
    <p>Events create paused Tasks for your approval. Incoming text never authorizes tools. Existing shared-secret transport is required; sender filters do not independently verify a remote publisher. This panel starts no listener and creates no credentials.</p>
    {catalog && <p>Listener: {catalog.listener} · Existing credential: {catalog.credential_status} · Admission: {catalog.admission}</p>}
    {error && <p role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}
    {pending.map(intent => <p key={intent.operationId}>Saved webhook command needs reconciliation. <button disabled={busy} onClick={() => void reconcile(intent)}>Check saved webhook command</button></p>)}
    <button disabled={disabled || volatile.current} onClick={() => edit(empty())}>New disabled subscription</button>
    <button disabled={busy} onClick={() => {setAttempt(n => n + 1); if (history) void openHistory(history.id);}}>Refresh webhook status</button>
    {catalog?.subscriptions.map(row => <article key={row.id}><strong>{row.name}</strong><p>{row.provider} · revision {row.revision} · {row.archived ? 'Archived' : row.enabled ? 'Proposals enabled' : 'Disabled'} · {row.agent_id}</p>
      <p>Local path: /hook/{row.id}</p>
      <button disabled={disabled || volatile.current} onClick={() => edit({id: row.id, revision: row.revision, agentId: row.agent_id, definition: {name: row.name, provider: row.provider, events: row.events, senders: row.senders, session_id: row.session_id, objective: row.objective, enabled: false, archived: row.archived}})}>Edit subscription</button>
      {!row.archived && <button disabled={disabled} onClick={() => setConfirm({row, enabled: !row.enabled, archived: false})}>{row.enabled ? 'Disable proposals' : 'Enable proposals…'}</button>}
      <button disabled={disabled} onClick={() => setConfirm({row, enabled: false, archived: !row.archived})}>{row.archived ? 'Restore disabled…' : 'Archive subscription…'}</button>
      <button disabled={busy} onClick={() => void openHistory(row.id)}>Delivery receipts</button>
    </article>)}
    {savedDraftKeys().map(key => <button key={key} disabled={disabled || volatile.current} onClick={() => {try {const saved = JSON.parse(localStorage.getItem(key)!); if (!saved.id || !saved.definition) throw Error('Invalid saved draft'); edit(saved);} catch (e) {setError(String(e));}}}>Recover subscription draft {key.slice((DRAFT + '.saved.').length)}</button>)}
    {editor && <form aria-label="Webhook subscription editor" onSubmit={e => {e.preventDefault(); void save(editor);}}>
      <label>Name<input aria-label="Webhook name" value={editor.definition.name} disabled={disabled} onChange={e => update({name: e.target.value})}/></label>
      <label>Provider<select aria-label="Webhook provider" value={editor.definition.provider} disabled={disabled} onChange={e => update({provider: e.target.value as 'generic' | 'github'})}><option value="generic">Generic</option><option value="github">GitHub</option></select></label>
      <label>Bot<select aria-label="Webhook bot" value={editor.agentId} disabled={disabled} onChange={e => edit({...editor, agentId: e.target.value})}><option value="">Choose bot</option>{agents.filter(a => !a.hidden && !a.deleted && !a.disabled).map(a => <option key={a.id} value={a.id}>{a.display_name ?? a.name}</option>)}</select></label>
      <label>Event types (one per line)<textarea aria-label="Webhook event filters" value={editor.definition.events.join('\n')} disabled={disabled} onChange={e => update({events: e.target.value.split('\n')})}/></label>
      <label>Sender IDs (one per line)<textarea aria-label="Webhook sender filters" value={editor.definition.senders.join('\n')} disabled={disabled} onChange={e => update({senders: e.target.value.split('\n')})}/></label>
      <label>Owner objective<textarea aria-label="Webhook objective" value={editor.definition.objective} disabled={disabled} onChange={e => update({objective: e.target.value})}/></label>
      <p>Saving leaves this subscription disabled. Review its filters before separately enabling proposals.</p>
      <button disabled={disabled || !editor.agentId || !editor.definition.name.trim() || !editor.definition.objective.trim()}>Save disabled subscription</button>
      <button type="button" disabled={volatile.current || busy} onClick={() => setEditor(undefined)}>Close editor (keep draft)</button>
    </form>}
    {confirm && <section role="alertdialog" aria-label="Confirm webhook state"><p>{confirm.enabled ? 'Enable approval-bound proposals from these exact existing filters?' : confirm.archived ? 'Archive and disable this subscription? Saved delivery and task history stay intact.' : 'Save disabled state? Restore never enables proposals.'}</p><p>{confirm.row.name} · events: {confirm.row.events.join(', ')} · senders: {confirm.row.senders.join(', ')}</p><button onClick={() => setConfirm(undefined)}>Cancel</button><button disabled={disabled} onClick={() => {const r = confirm.row; void save({id: r.id, revision: r.revision, agentId: r.agent_id, definition: {name: r.name, provider: r.provider, events: r.events, senders: r.senders, session_id: r.session_id, objective: r.objective, enabled: confirm.enabled, archived: confirm.archived}});}}>Confirm subscription state</button></section>}
    {history && <section aria-label="Webhook delivery receipts"><h4>Recent delivery receipts</h4><p>Gateway arrival order; remote event chronology is unknown. Event bodies and credentials are withheld here. Review and decide Tasks individually.</p>{history.rows.length === 0 && <p>No saved deliveries.</p>}{history.rows.map(row => <article key={row.delivery_id}><p>{row.delivery_id} · {row.status}{row.reason ? ' · ' + row.reason : ''}</p>{row.task_id && <p>Task {row.task_id} · {row.task_state} · Execution receipt: {row.request_status ?? 'No admitted execution'}</p>}{row.request_status === 'execution_unknown' && <p role="alert">Execution needs reconciliation; do not replay this event.</p>}</article>)}</section>}
  </section>;
}
