import {useEffect,useRef,useState} from 'react';
import type {SemanticClaimControls,SemanticClaimDetail,ControlResult} from '../api/source';
type Action='correct'|'forget'|'restore';
type Intent={operation_id:string;expected_revision:string;action:Action;text?:string};
export function SemanticClaimEditor({id,controls,close,changed}:{id:string;controls:SemanticClaimControls;close:()=>void;changed:()=>void}){
 const key='jaeger.ui.semantic-claim.v1.'+id,draftKey=key+'.draft';
 const [row,setRow]=useState<SemanticClaimDetail>(),[text,setText]=useState(()=>localStorage.getItem(draftKey)??''),[error,setError]=useState<string>(),[notice,setNotice]=useState<string>(),[confirm,setConfirm]=useState<Action>(),[busy,setBusy]=useState(false),[refresh,setRefresh]=useState(0);
 const [pending,setPending]=useState<Intent|undefined>(()=>{try{const raw=localStorage.getItem(key);return raw?JSON.parse(raw):undefined;}catch{return {operation_id:'invalid-journal',expected_revision:'',action:'forget'};}});
 const lock=useRef(false);
 useEffect(()=>{let live=true;void controls.detail(id).then(value=>{if(live){setRow(value);setError(undefined);}},e=>{if(live)setError(String(e));});return()=>{live=false;};},[controls,id,refresh]);
 const finish=(receipt:ControlResult,intent:Intent)=>{
  if(receipt.operation_id!==intent.operation_id)throw Error('Claim receipt identity mismatch');
  const result=receipt.result as {domain?:string;claim_id?:string;action?:string;replacement_claim_id?:string};
  if(receipt.ok&&(result?.domain!=='semantic_claim'||result.claim_id!==id||result.action!==intent.action))throw Error('Claim receipt target mismatch');
  localStorage.removeItem(key);setPending(undefined);setConfirm(undefined);
  setNotice(receipt.ok?`Saved ${intent.action}${result?.replacement_claim_id?' · replacement '+result.replacement_claim_id:''}. Existing conversations and running context unchanged.`:receipt.error??'Claim change rejected; draft retained');
  setRefresh(n=>n+1);changed();
 };
 const run=async(check=false)=>{if(lock.current)return;lock.current=true;setBusy(true);setError(undefined);try{
  if(check){if(!pending)return;const {receipt}=await controls.operation(pending.operation_id);if(!receipt)throw Error('Outcome unresolved; no replay');finish(receipt,pending);}
  else{if(!confirm||!row||pending)return;if(localStorage.getItem(key))throw Error('An existing command needs receipt reconciliation; close and reopen');
   const intent:Intent={operation_id:crypto.randomUUID(),expected_revision:row.revision,action:confirm,...(confirm==='correct'?{text}: {})};
   localStorage.setItem(key,JSON.stringify(intent));setPending(intent);
   finish(await controls.mutate(id,intent.action,{operation_id:intent.operation_id,expected_revision:intent.expected_revision,...(intent.action==='correct'?{text:intent.text}: {})}),intent);
  }
 }catch(e){setError(`${String(e)}. Draft and command preserved; check original receipt, never resubmit an uncertain change.`);}finally{lock.current=false;setBusy(false);}};
 return <div role="dialog" aria-label="Semantic claim details" aria-modal="true" className="jg-card"><h3>Semantic claim details</h3><button type="button" onClick={close}>Close claim</button><p>Forget expires future semantic retrieval only. Original evidence, conversation history and already running context remain. Restore cannot extend original validity. Corrections create a new told claim; they do not inherit verified provenance.</p>{error&&<p role="alert">{error}</p>}{notice&&<p role="status">{notice}</p>}{row&&<><strong>{row.subject} · {row.predicate}</strong><pre style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere'}}>{row.value}</pre><p>{row.provenance} · source {row.source_id} · confidence {row.confidence} · {row.active?'Active':'Historical'}</p><small>{row.claim_id} · revision {row.revision}</small>{row.replaces_claim_id&&<p>Corrects {row.replaces_claim_id}</p>}{row.changes.map((entry,index)=><p key={index}>{entry.action} · {entry.actor} · {new Date(entry.changed_at*1000).toLocaleString()}{entry.replacement_claim_id?' · replacement '+entry.replacement_claim_id:''}</p>)}<label>Correction draft<textarea aria-label="Claim correction draft" maxLength={16000} value={text} onChange={e=>{localStorage.setItem(draftKey,e.target.value);setText(e.target.value);}}/></label><button type="button" disabled={!!row.truncated||busy||!!pending} onClick={()=>{localStorage.setItem(draftKey,row.value);setText(row.value);}}>Copy saved value to draft</button>{row.truncated&&<p>Saved value exceeds editing limit; bounded preview is never used as a correction automatically.</p>}{!row.actions.length&&<p>No editable action available: inactive, protected, nonresident or caller scope restricted.</p>}{!pending&&row.actions.map(action=><button type="button" disabled={busy||action==='correct'&&!text.trim()} key={action} onClick={()=>setConfirm(action)}>{action==='correct'?'Review correction':action==='forget'?'Recoverable forget':'Review restore'}</button>)}</>}{pending&&<button type="button" disabled={busy} onClick={()=>void run(true)}>Check claim operation</button>}{confirm&&!pending&&<div role="group" aria-label="Confirm semantic claim change"><p>Confirm {confirm} against the displayed saved revision. Independent correction draft is retained.</p><button type="button" disabled={busy} onClick={()=>void run()}>Confirm claim change</button><button type="button" onClick={()=>setConfirm(undefined)}>Cancel claim change</button></div>}<button type="button" disabled={busy} onClick={()=>setRefresh(n=>n+1)}>Read current claim</button></div>;
}
