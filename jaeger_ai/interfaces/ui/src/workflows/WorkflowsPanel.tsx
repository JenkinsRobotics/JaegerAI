import { WorkflowRuns } from "./WorkflowRuns";
import { GatewayError } from "../api/gateway";
import { useEffect, useRef, useState } from 'react';
import type { JaegerSource, WorkflowAction, WorkflowDocument, WorkflowReceipt, WorkflowDefinition } from '../api/source';
import type { Agent } from '../api/types';
interface Draft { raw: string; revision?: number }
interface Intent { operationId: string; action: WorkflowAction; id: string; draft: Draft }
const draftKey = (id: string) => `jaeger.ui.workflow.draft.v1.${encodeURIComponent(id)}`;
const OP = 'jaeger.ui.workflow.operation.v1';
const journalKey = (id: string) => OP + '.pending.' + id;
const savedIntents = (): Intent[] => {
  const raw = [localStorage.getItem(OP), ...Object.keys(localStorage).filter(key=>key.startsWith(OP+'.pending.')).map(key=>localStorage.getItem(key))];
  const found = new Map<string,Intent>();
  for(const record of raw){if(!record)continue;const value=JSON.parse(record);if(!value.operationId||!value.action||!value.id||typeof value.draft?.raw!=='string')throw Error('Invalid workflow operation record; original retained');found.set(value.operationId,value);}
  return [...found.values()];
};
const settleIntent = (intent: Intent): Intent | undefined => {
  localStorage.removeItem(journalKey(intent.operationId));
  const pointer=JSON.parse(localStorage.getItem(OP)??'null');
  if(pointer?.operationId===intent.operationId)localStorage.removeItem(OP);
  return savedIntents()[0];
};
const backups = () => { try { return Object.keys(localStorage).filter(key=>key.startsWith(draftKey('new')+'.backup.')).reverse().slice(0,10); } catch { return []; } };
export function WorkflowsPanel({ source, agents }: { source: JaegerSource; agents: Agent[] }) {
  const controls = source.workflows!;
  const [catalog, setCatalog] = useState<Awaited<ReturnType<typeof controls.list>>>(), [attempt, setAttempt] = useState(0);
  const [selected, setSelected] = useState<string>(), [current, setCurrent] = useState<WorkflowDocument>(), [draft, setDraft] = useState<Draft>({raw:''});
  const [pending, setPending] = useState<Intent>(), [busy, setBusy] = useState(false), [error, setError] = useState<string>(), [notice, setNotice] = useState<string>();
  const [catalogError, setCatalogError] = useState<string>();
  const [origin, setOrigin] = useState(''), [confirm, setConfirm] = useState(false), [imported, setImported] = useState('');
  const lock = useRef(false), volatile = useRef(false), generation = useRef(0);
  useEffect(() => { try { const saved=savedIntents()[0];if(saved)setPending(saved); setImported(localStorage.getItem('jaeger.ui.workflow.import.v1') ?? ''); } catch (e) { lock.current = true; setError(`Workflow recovery unavailable: ${String(e)}`); } return () => { generation.current++; }; }, []);
  useEffect(() => { let live = true; void controls.list().then(value => { if (live) { setCatalog(value); setCatalogError(undefined); } }, e=>{if(live)setCatalogError(String(e));});return()=>{live=false;}; }, [controls, attempt]);
  const open = async (id: string) => {
    if (busy || volatile.current) { if (volatile.current) setError('Current draft is not saved; keep it open or copy its text before navigating'); return; }
    const owner = ++generation.current; setSelected(id); setCurrent(undefined); setDraft({raw:''}); setError(undefined); setNotice(undefined); setConfirm(false);
    try {
      const raw = localStorage.getItem(draftKey(id)), saved: Draft | undefined = raw ? JSON.parse(raw) : undefined;
      if (saved && typeof saved.raw !== 'string') throw Error('Saved definition invalid; original retained');
      if (id === 'new') { setDraft(saved ?? { raw: JSON.stringify({ format: catalog?.format, name:'', description:'', steps:[{title:'',instruction:''}] },null,2) }); return; }
      const value = await controls.read(id); if (owner !== generation.current) return;
      setCurrent(value); setDraft(saved ?? {raw:JSON.stringify(value.definition,null,2),revision:value.revision});
      if (saved && saved.revision !== value.revision) setError('Workflow changed elsewhere. Your draft is preserved; review the saved version before editing.');
    } catch(e) { if(owner===generation.current)setError(String(e)); }
  };
  const update = (raw: string) => { const value={...draft,raw};setDraft(value);try{localStorage.setItem(draftKey(selected!),JSON.stringify(value));volatile.current=false;}catch(e){volatile.current=true;setError(`Definition draft not saved: ${String(e)}. Keep this editor open.`);} };
  const finish = (intent: Intent, receipt: WorkflowReceipt) => {
    if (receipt.operation_id !== intent.operationId) throw Error('Workflow receipt identity mismatch');
    if (!receipt.ok) { setPending(settleIntent(intent));throw Error(receipt.error ?? 'Workflow action rejected'); }
    if (!receipt.workflow?.id || typeof receipt.workflow.revision !== 'number' || intent.action !== 'create' && receipt.workflow.id !== intent.id) throw Error('Workflow receipt has no matching saved definition');
    if(intent.action==='propose'&&(!receipt.task?.task_id||receipt.task.authorized!==false))throw Error('No verified unapproved task proposal receipt');
    const value=receipt.workflow;
    if(intent.action!=='propose'){
      const raw=localStorage.getItem(draftKey(intent.id)),latest:Draft|undefined=raw?JSON.parse(raw):undefined;
      const next=latest && latest.raw!==intent.draft.raw ? latest : intent.action==='archive'||intent.action==='restore' ? {...intent.draft,revision:value.revision} : {raw:JSON.stringify(value.definition,null,2),revision:value.revision};
      localStorage.setItem(draftKey(value.id),JSON.stringify(next));
      if(intent.action==='create' && (!latest || latest.raw===intent.draft.raw))localStorage.removeItem(draftKey('new'));
      setSelected(value.id);setCurrent(value);setDraft(next);
    }
    setPending(settleIntent(intent));setAttempt(n=>n+1);
    setNotice(intent.action==='propose' ? `Proposal ${receipt.task?.task_id ?? 'receipt saved'}. See Tasks for its current approval and execution status.` : `Workflow saved at revision ${value.revision}.`);
  };
  const mutate = async (action: WorkflowAction) => {
    if(lock.current||pending||!selected||selected!=='new'&&current?.id!==selected)return;lock.current=true;setBusy(true);setError(undefined);setConfirm(false);
    const intent:Intent={operationId:crypto.randomUUID(),action,id:selected,draft};
    let submitted=false;
    try{
      const definition=action==='create'||action==='save'?JSON.parse(draft.raw):undefined;
      const expected_revision=action==='propose'?current?.revision:draft.revision;
      if(action!=='create'&&(!Number.isInteger(expected_revision)||expected_revision!<1))throw Error('Saved revision unavailable; read the current definition and review your draft');
      localStorage.setItem(draftKey(selected),JSON.stringify(draft));volatile.current=false;
      let session_id:string|undefined;
      if(action==='propose'){if(!origin||!source.agentHome)throw Error('Choose an existing originating bot');const home=await source.agentHome(origin);if(home.agent_id!==origin||!home.session_id)throw Error('Origin identity mismatch');session_id=home.session_id;}
      const prior=savedIntents()[0];if(prior){setPending(prior);throw Error('Another saved workflow action needs reconciliation before a new action');}
      // Each command retains its own journal entry even if two tabs race on
      // the convenience pointer. A response can settle only its own identity.
      localStorage.setItem(journalKey(intent.operationId),JSON.stringify(intent));
      try{localStorage.setItem(OP,JSON.stringify(intent));}catch(error){localStorage.removeItem(journalKey(intent.operationId));throw error;}
      setPending(intent);submitted=true;
      const receipt=await controls.mutate(action,selected,{operation_id:intent.operationId,...(action==='create'?{}:{expected_revision}),...(action==='create'||action==='save'?{definition}:{}),...(session_id?{session_id}:{})});finish(intent,receipt);
    }catch(e){
      const body=e instanceof GatewayError && e.body && typeof e.body==='object' ? e.body as Record<string,unknown> : undefined;
      const rejected=e instanceof GatewayError && !body?.execution_unknown && ([400,401,403,404,405,423].includes(e.status) || body?.ok===false && body.operation_id===intent.operationId);
      if(rejected){try{setPending(settleIntent(intent));}catch{/* Preserve journal if recovery storage is unavailable. */}setError(`Workflow action rejected: ${String((e as Error).message??e)}. Original draft retained.`);}
      else setError(`${String((e as Error).message??e)}.${submitted?' Check saved workflow action; no automatic retry.':' Nothing submitted; original source remains in the editor.'}`);
    }finally{lock.current=false;setBusy(false);}
  };
  const check = async()=>{if(!pending||lock.current)return;lock.current=true;setBusy(true);try{const value=await controls.operation(pending.operationId);if(!value.receipt)throw Error('Workflow outcome remains unknown; nothing was resubmitted');finish(pending,value.receipt);}catch(e){setError(String(e));}finally{lock.current=false;setBusy(false);}};
  const reviewImport=()=>{if(busy||pending||volatile.current)return;try{const previous=localStorage.getItem(draftKey('new'));if(previous)localStorage.setItem(draftKey('new')+'.backup.'+crypto.randomUUID(),previous);localStorage.setItem(draftKey('new'),JSON.stringify({raw:imported}));void open('new');}catch(e){setError(String(e));}};
  const definition = (() => { try { const value=JSON.parse(draft.raw); return value && typeof value.name==='string' && typeof value.description==='string' && Array.isArray(value.steps) && value.steps.every((step: {title?: unknown;instruction?: unknown})=>step&&typeof step.title==='string'&&typeof step.instruction==='string') ? value as WorkflowDefinition : undefined; } catch { return undefined; } })();
  const editable = !busy && !pending && !current?.archived && (selected==='new'||current?.id===selected);
  const setDefinition = (value: WorkflowDefinition) => update(JSON.stringify(value,null,2));
  return <section aria-label="Workflows"><p>Versioned instruction workflows. Imported JSON is data; no URL is fetched or step executed while editing. Run proposals use existing Tasks and approvals.</p>
    {catalogError&&<p role="alert">Could not load workflows: {catalogError}. Previous list retained.</p>}
    {error&&<p role="alert">{error}</p>}{notice&&<p role="status">{notice}</p>}{pending&&<p role="alert">A workflow action needs reconciliation. <button disabled={busy} onClick={()=>void check()}>Check saved workflow action</button></p>}
    <button type="button" disabled={busy||Boolean(pending)||!catalog} onClick={()=>void open('new')}>New workflow</button><button type="button" disabled={busy} onClick={()=>setAttempt(n=>n+1)}>Refresh workflows</button>
    <label>Paste workflow JSON<textarea aria-label="Import workflow JSON" value={imported} disabled={busy||Boolean(pending)} onChange={e=>{setImported(e.target.value);try{localStorage.setItem('jaeger.ui.workflow.import.v1',e.target.value);}catch(error){setError(String(error));}}}/></label><button type="button" disabled={busy||Boolean(pending)||!imported.trim()} onClick={reviewImport}>Review imported definition</button>
    <ul>{catalog?.workflows.map(row=><li key={row.id}><button type="button" disabled={busy} onClick={()=>void open(row.id)}>{row.title} · revision {row.revision}{row.archived?' · Archived':''}</button></li>)}</ul>
    {selected&&<>
      {definition&&<div className="jg-form"><label className="jg-form__field">Workflow name<input aria-label="Workflow name" value={definition.name} disabled={!editable} onChange={e=>setDefinition({...definition,name:e.target.value})}/></label><label className="jg-form__field">Description<textarea aria-label="Workflow description" value={definition.description} disabled={!editable} onChange={e=>setDefinition({...definition,description:e.target.value})}/></label>
      {definition.steps.map((step,index)=><section key={index} className="jg-card"><label>Step {index+1} title<input aria-label={`Workflow step ${index+1} title`} value={step.title} disabled={!editable} onChange={e=>setDefinition({...definition,steps:definition.steps.map((s,i)=>i===index?{...s,title:e.target.value}:s)})}/></label><label>Instruction<textarea aria-label={`Workflow step ${index+1} instruction`} value={step.instruction} disabled={!editable} onChange={e=>setDefinition({...definition,steps:definition.steps.map((s,i)=>i===index?{...s,instruction:e.target.value}:s)})}/></label><button type="button" disabled={!editable||definition.steps.length<=1} onClick={()=>setDefinition({...definition,steps:definition.steps.filter((_,i)=>i!==index)})}>Remove instruction step</button></section>)}
      <button type="button" disabled={!editable||!catalog||definition.steps.length>=catalog.limits.steps} onClick={()=>setDefinition({...definition,steps:[...definition.steps,{title:'',instruction:''}]})}>Add instruction step</button></div>}
      <details><summary>Imported definition source</summary><label>Workflow definition JSON<textarea aria-label="Workflow definition JSON" rows={14} style={{width:'100%',boxSizing:'border-box'}} value={draft.raw} disabled={!editable} onChange={e=>update(e.target.value)}/></label></details>
      {!current?.archived&&<button type="button" disabled={busy||Boolean(pending)||!draft.raw.trim()||selected!=='new'&&current?.id!==selected} onClick={()=>void mutate(selected==='new'?'create':'save')}>Save workflow</button>}
      {current&&<WorkflowRuns source={source} workflowId={current.id} refresh={attempt}/>}
      {current&&<><details><summary>Current saved definition</summary><pre>{JSON.stringify(current.definition,null,2)}</pre></details><button type="button" disabled={busy||Boolean(pending)} onClick={()=>void mutate(current.archived?'restore':'archive')}>{current.archived?'Restore workflow':'Archive workflow'}</button>
      {!current.archived&&source.agentHome&&<><label>Return results to<select aria-label="Workflow originating bot" value={origin} disabled={busy||Boolean(pending)} onChange={e=>setOrigin(e.target.value)}><option value="">Choose bot</option>{agents.filter(a=>!a.hidden&&!a.deleted).map(a=><option key={a.id} value={a.id}>{a.display_name??a.name}</option>)}</select></label><button type="button" disabled={busy||Boolean(pending)||!origin} onClick={()=>setConfirm(true)}>Propose saved workflow run…</button></>}</>}
    </>}
    {backups().map(key=><button key={key} type="button" disabled={busy||Boolean(pending)} onClick={()=>{if(volatile.current){setError('Current draft is not saved; preserve it before recovering another draft');return;}try{const saved=JSON.parse(localStorage.getItem(key)!);if(typeof saved.raw!=='string')throw Error('Backup is invalid; retained');const previous=localStorage.getItem(draftKey('new'));if(previous)localStorage.setItem(draftKey('new')+'.backup.'+crypto.randomUUID(),previous);localStorage.setItem(draftKey('new'),JSON.stringify(saved));void open('new');}catch(e){setError(String(e));}}}>Recover previous new-workflow draft</button>)}
    {confirm&&<section role="alertdialog" aria-label="Propose workflow run"><p>Create a task proposal from saved revision {current?.revision}? Unsaved edits are excluded. Existing task approval is still required.</p><button type="button" onClick={()=>setConfirm(false)}>Cancel</button><button type="button" disabled={busy} onClick={()=>void mutate('propose')}>Create workflow proposal</button></section>}
  </section>;
}
