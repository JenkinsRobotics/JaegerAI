import {useEffect,useRef,useState} from 'react';
import type {TemplateCatalogControls,TemplateCatalogState,TemplateCatalogIntent,TemplateCatalogReceipt} from '../api/source';
/** Durable local catalog only. No publication, copied context or execution authority. */
export function TemplateCatalog({agentId,controls}:{agentId:string;controls:TemplateCatalogControls}){
 const key='jaeger.ui.template.catalog.v1.'+encodeURIComponent(agentId),identity=useRef(agentId);identity.current=agentId;
 const [row,setRow]=useState<TemplateCatalogState>(),[pending,setPending]=useState<string>(),[review,setReview]=useState<TemplateCatalogIntent>(),[busy,setBusy]=useState(false),[error,setError]=useState(''),[notice,setNotice]=useState('');const lock=useRef(false);
 useEffect(()=>{let active=true;setRow(undefined);setReview(undefined);setNotice('');setPending(undefined);
  try{setPending(localStorage.getItem(key)||undefined);}catch{setError('Catalog command journal unavailable; writes require durable storage.');}
  void controls.read(agentId).then(value=>{if(!active)return;if(value.agent_id!==agentId)throw Error('Catalog source mismatch');setRow(value);},()=>{if(active)setError('Local catalog unavailable. Existing versions retained.');}).catch(()=>{if(active)setError('Catalog source mismatch');});
  return()=>{active=false;};
 },[agentId,controls,key]);
 function accept(value:TemplateCatalogReceipt,id:string){
  if(identity.current!==agentId)return;
  if(value.operation_id!==id||value.result&&value.result.agent_id!==agentId)throw Error('Catalog receipt identity mismatch');
  if(value.outcome==='unknown'){setError('Original catalog result unresolved. Nothing is resent.');return;}
  if(value.outcome!=='saved'&&value.outcome!=='rejected'||value.outcome==='saved'&&!value.result)throw Error('Catalog receipt unsupported');
  localStorage.removeItem(key);setPending(undefined);setReview(undefined);
  if(value.result)setRow(value.result);
  setNotice(value.outcome==='saved'?'Local template catalog saved. Source prompt, permissions and history unchanged.':'Catalog change rejected. Read current catalog before reviewing another change.');setError(value.error||'');
 }
 async function confirm(){if(!review||pending||lock.current)return;lock.current=true;setBusy(true);setError('');const intent=review;
  try{localStorage.setItem(key,intent.operation_id);}catch{setError('Journal unavailable. Nothing was sent.');lock.current=false;setBusy(false);return;}
  setPending(intent.operation_id);setReview(undefined);
  try{accept(await controls.change(agentId,intent),intent.operation_id);}catch{if(identity.current===agentId)setError('Catalog save unconfirmed. Inspect original result; do not resubmit.');}finally{lock.current=false;if(identity.current===agentId)setBusy(false);}}
 async function inspect(){if(!pending||lock.current)return;lock.current=true;setBusy(true);try{accept(await controls.operation(pending),pending);}catch{setError('Original result unavailable. Nothing was resent.');}finally{lock.current=false;setBusy(false);}}
 async function refresh(){try{const value=await controls.read(agentId);if(identity.current!==agentId)return;if(value.agent_id!==agentId)throw Error();setRow(value);setError('');}catch{setError('Local catalog read failed; prior versions retained.');}}
 return <section aria-label="Saved local templates"><h3>Saved local template versions</h3><p>Owner-local prompt snapshots only. No public publication, history, tools, accounts or grants copied.</p>
  {error&&<p role="alert">{error}</p>}{notice&&<p role="status">{notice}</p>}
  {pending&&<button disabled={busy} onClick={()=>void inspect()}>Inspect original template result</button>}
  <button disabled={busy} onClick={()=>void refresh()}>Read saved template catalog</button>
  {row&&<><p>Catalog revision {row.catalog_revision} · {row.hidden?'Hidden from creation picker':'Available in creation picker'}</p><ul>{row.versions.map(v=><li key={v.version}>Version {v.version}</li>)}</ul>
   <button disabled={busy||!!pending} onClick={()=>setReview({operation_id:crypto.randomUUID(),action:'save',expected_revision:row.source_revision,expected_catalog_revision:row.catalog_revision})}>Review save current prompt as template</button>
   {!!row.versions.length&&<button disabled={busy||!!pending} onClick={()=>setReview({operation_id:crypto.randomUUID(),action:'visibility',hidden:!row.hidden,expected_catalog_revision:row.catalog_revision})}>{row.hidden?'Review restore template to picker':'Review hide template from picker'}</button>}
  </>}
  {review&&<div role="dialog" aria-label="Review local template catalog"><p>{review.action==='save'?'Save the current saved prompt as an immutable local version. Unsent prompt drafts are excluded.':review.hidden?'Hide all saved versions from new-agent selection. Retain every version and existing bot.':'Restore retained versions to new-agent selection.'}</p><button disabled={busy||!!pending} onClick={()=>void confirm()}>Confirm local template change</button><button onClick={()=>setReview(undefined)}>Cancel</button></div>}
 </section>;
}
