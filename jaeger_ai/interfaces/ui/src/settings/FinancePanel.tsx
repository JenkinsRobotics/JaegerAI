import {useEffect,useRef,useState} from 'react';
import {GatewayError} from '../api/gateway';
import type {FinanceAction,FinanceControls,FinanceReceipt} from '../api/source';
import {keysWithPrefix} from '../lib/storageKeys';
const PREFIX='jaeger.ui.finance.review.v1.';
interface Intent {operation_id:string;action_id:string;expected_revision:string;decision:'record_review'|'deny'}
const intents=():Intent[]=>keysWithPrefix(PREFIX).map(k=>{const v=JSON.parse(localStorage.getItem(k)!);if(!v.operation_id||!v.action_id||!v.expected_revision||!['record_review','deny'].includes(v.decision))throw Error('Saved finance review invalid; original retained');return v;});
/** Local review metadata only. There is no charge/card/link/payment action. */
export function FinancePanel({controls}:{controls:FinanceControls}){
 const [snapshot,setSnapshot]=useState<Awaited<ReturnType<typeof controls.status>>>(),[pending,setPending]=useState<Intent[]>([]),[selected,setSelected]=useState<{row:FinanceAction;decision:Intent['decision']}>();
 const [error,setError]=useState<string>(),[notice,setNotice]=useState<string>(),[busy,setBusy]=useState(false),[attempt,setAttempt]=useState(0);const lock=useRef(false);
 useEffect(()=>{try{setPending(intents());}catch(e){lock.current=true;setError(String(e));}},[]);
 useEffect(()=>{let live=true;setSnapshot(undefined);void controls.status().then(v=>{if(live)setSnapshot(v);},e=>{if(live)setError('Financial metadata unavailable: '+String(e));});return()=>{live=false;};},[controls,attempt]);
 const finish=(intent:Intent,receipt:FinanceReceipt)=>{
  if(receipt.operation_id!==intent.operation_id||receipt.action_id!==intent.action_id||receipt.decision!==intent.decision||receipt.reviewed_revision!==intent.expected_revision||receipt.execution_performed!==false||receipt.review_only!==true)throw Error('Finance review receipt mismatch; inspect original operation');
  localStorage.removeItem(PREFIX+intent.operation_id);setPending(intents());setAttempt(n=>n+1);
  if(!receipt.ok)throw Error(receipt.error??`Review not applied: ${receipt.status}`);
  setNotice(`${receipt.status==='approved'?'Local review recorded':'Local review denied'}. No payment or financial action executed.`);
 };
 const submit=async()=>{
  if(!selected||lock.current||pending.length)return;lock.current=true;setBusy(true);setError(undefined);setNotice(undefined);
  let intent:Intent|undefined;
  try{if(intents().length)throw Error('Another review needs reconciliation');intent={operation_id:crypto.randomUUID(),action_id:selected.row.id,expected_revision:selected.row.revision,decision:selected.decision};localStorage.setItem(PREFIX+intent.operation_id,JSON.stringify(intent));setPending(intents());setSelected(undefined);const {action_id,...body}=intent;finish(intent,await controls.decide(action_id,body));}
  catch(e){const body=e instanceof GatewayError&&e.body&&typeof e.body==='object'?e.body as Record<string,unknown>:undefined;
   if(intent&&body?.operation_id===intent.operation_id&&body?.execution_performed===false&&body?.review_only===true){try{finish(intent,body as unknown as FinanceReceipt);}catch(error){setError(String(error));}}
   else if(intent&&e instanceof GatewayError&&[400,401,403,423].includes(e.status)&&!body?.execution_unknown){localStorage.removeItem(PREFIX+intent.operation_id);setPending(intents());setError('Review rejected; nothing executed. '+String(e));}
   else setError(String(e)+(intent?'. Check the original operation; no automatic retry.':'. Nothing submitted.'));
  }finally{lock.current=false;setBusy(false);}
 };
 const check=async(intent:Intent)=>{if(lock.current)return;lock.current=true;setBusy(true);try{const result=await controls.operation(intent.operation_id);if(!result.receipt)throw Error('Review receipt unavailable; outcome remains unknown. Nothing was resubmitted');finish(intent,result.receipt);}catch(e){setError(String(e));}finally{lock.current=false;setBusy(false);}};
 return <section aria-label="Financial policy and local reviews"><p>Financial policy is read-only. Payments, money movement, card creation and account linking are unavailable here. Recording a local review never executes the proposed change or creates a spending grant.</p>
 {error&&<p role="alert">{error}</p>}{notice&&<p role="status">{notice}</p>}
 <button disabled={busy} onClick={()=>setAttempt(n=>n+1)}>Refresh financial status</button>
 {pending.map(p=><p key={p.operation_id}>Original review {p.operation_id} needs reconciliation. <button disabled={busy} onClick={()=>void check(p)}>Check original finance review</button></p>)}
 {snapshot&&<><p>Local store: {snapshot.state}. Provider: {snapshot.policy.provider}. Money movement: {snapshot.policy.money_movement}. Unknown operations: {snapshot.policy.unknown_operations}.</p><p>Budget analysis is not an enforced card spending limit. Settlement is not observed by this panel. No credentials or encryption keys are read or created.</p>
 {snapshot.state==='not_initialized'&&<p>No existing local finance store. This panel does not initialize storage or connect accounts.</p>}
 <details><summary>Existing operation policy</summary>{snapshot.policy.operations.map(op=><p key={op.id}>{op.id} · {op.tier}</p>)}</details>
 {snapshot.actions.map(row=><article key={row.id}><h3>{row.operation}</h3><p>{row.id} · {row.status} · {row.policy_tier}</p>
 {row.declared_scope&&<p>Declared scope (not spending authority): {row.declared_scope.amount} {row.declared_scope.currency} · {row.declared_scope.merchant}</p>}
 {row.proposed_change&&<pre style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere'}}>{JSON.stringify(row.proposed_change,null,2)}</pre>}
 {row.status==='execution_unknown'&&<p role="alert">Original financial outcome is unresolved. This panel cannot settle it or retry a payment.</p>}
 {row.can_record_review&&<button disabled={busy||!!pending.length} onClick={()=>setSelected({row,decision:'record_review'})}>Record local review…</button>}
 {row.can_deny&&<button disabled={busy||!!pending.length} onClick={()=>setSelected({row,decision:'deny'})}>Deny local request…</button>}
 {!row.can_record_review&&row.status==='pending'&&<p>This request has no supported complete local review scope, or is blocked by policy. No approval action is available.</p>}
 </article>)}</>}
 {selected&&<section role="alertdialog" aria-label="Confirm local financial review"><p>{selected.decision==='deny'?'Deny this saved request?':'Record review of these exact saved local changes? This will not apply them or authorize spending.'}</p><p>{selected.row.id} · revision {selected.row.revision}</p>{selected.row.proposed_change&&<pre>{JSON.stringify(selected.row.proposed_change,null,2)}</pre>}<button onClick={()=>setSelected(undefined)}>Cancel</button><button disabled={busy} onClick={()=>void submit()}>Confirm local review decision</button></section>}
 </section>;
}
