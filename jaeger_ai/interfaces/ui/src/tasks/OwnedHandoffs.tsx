import {useEffect,useRef,useState} from 'react';
import {GatewayError} from '../api/gateway';
import type {JaegerSource} from '../api/source';
import type {HandoffStopReceipt,HandoffStopRow} from '../api/types';
const KEY='jaeger.ui.handoff-stop.v1.';
interface Intent {id:string;request_id:string;operation_id:string}
function retained():Intent[]{return Object.keys(localStorage).filter(k=>k.startsWith(KEY)).map(k=>{const v=JSON.parse(localStorage.getItem(k)!);if(!v||typeof v.id!=='string'||typeof v.request_id!=='string'||typeof v.operation_id!=='string'||k!==KEY+v.operation_id)throw Error('Invalid saved Stop identity; original retained');return v;});}
/** Stop only existing owned work; never claims an ACK proves effect cleanup. */
export function OwnedHandoffs({source}:{source:JaegerSource}){
 const [rows,setRows]=useState<HandoffStopRow[]>([]),[pending,setPending]=useState<Intent[]>([]),[error,setError]=useState(''),[notice,setNotice]=useState(''),[busy,setBusy]=useState(false),[ready,setReady]=useState(false),[generation,setGeneration]=useState(0);const lock=useRef(false);
 useEffect(()=>{try{setPending(retained());setReady(true);}catch(e){setError(String(e));}},[]);
 useEffect(()=>{let live=true,reading=false;const load=async()=>{if(reading||!source.handoffStops)return;reading=true;try{const value=await source.handoffStops.list();if(value.limit!==100||!Array.isArray(value.handoffs))throw Error('Invalid handoff listing');if(live)setRows(value.handoffs);}catch(e){if(live)setError(String(e));}finally{reading=false;}};void load();const timer=setInterval(load,15000);return()=>{live=false;clearInterval(timer);};},[source,generation]);
 const settle=(intent:Intent,r:HandoffStopReceipt)=>{
  if(r.handoff_id!==intent.id||r.request_id!==intent.request_id||r.operation_id!==intent.operation_id||r.current?.handoff_id!==intent.id||!['accepted','unknown'].includes(r.outcome)||!Array.isArray(r.unconfirmed_task_ids)||typeof r.current.cancellation_confirmed!=='boolean')throw Error('Stop receipt identity mismatch; original retained');
  if(r.outcome==='unknown')throw Error(r.error??'Original Stop remains unknown; no replay');
  if(localStorage.getItem(KEY+intent.operation_id)!==JSON.stringify(intent))throw Error('Stop journal changed; original retained');
  localStorage.removeItem(KEY+intent.operation_id);setPending(retained());
  setNotice(r.current.cancellation_confirmed?'Cancellation confirmed for this request scope.':`Stop requested; effect cleanup remains unconfirmed${r.unconfirmed_task_ids.length?': '+r.unconfirmed_task_ids.join(', '):'. Check retained work status.'}`);setGeneration(n=>n+1);
 };
 const act=async(row?:HandoffStopRow,intent?:Intent)=>{
  if(lock.current||!ready||!source.handoffStops)return;lock.current=true;setBusy(true);setError('');setNotice('');
  try{
   if(intent){settle(intent,await source.handoffStops.original(intent.id,intent.operation_id));return;}
   if(!row)return;
   if(retained().some(p=>p.id===row.handoff_id))throw Error('Check the original Stop before sending another');
   const next={id:row.handoff_id,request_id:row.request_id,operation_id:crypto.randomUUID()};localStorage.setItem(KEY+next.operation_id,JSON.stringify(next));setPending(retained());
   try{settle(next,await source.handoffStops.stop(next.id,{operation_id:next.operation_id,request_id:next.request_id}));}
   catch(e){if(e instanceof GatewayError&&[400,401,403,404,405,423].includes(e.status)&&localStorage.getItem(KEY+next.operation_id)===JSON.stringify(next)){localStorage.removeItem(KEY+next.operation_id);setPending(retained());throw Error(`Stop rejected before execution: ${e.message}. No cancellation confirmed.`);}throw e;}
  }catch(e){setError(String(e));}finally{lock.current=false;setBusy(false);}
 };
 if(!source.handoffStops)return null;
 return <section aria-label="Owned specialist work"><h3>Specialist work</h3><p>Latest 100 retained handoffs. Stops signal only qualified owned request scopes. Acknowledgement does not prove tool effects ended; historical unqualified links remain unconfirmed.</p>{error&&<p role="alert">{error}</p>}{notice&&<p role="status">{notice}</p>}{pending.map(p=><p key={p.operation_id}>Original Stop · {p.id} <button disabled={busy||!ready} onClick={()=>void act(undefined,p)}>Check original Stop</button></p>)}<button disabled={busy} onClick={()=>setGeneration(n=>n+1)}>Refresh specialist work</button><ul>{rows.map(row=><li key={row.handoff_id}><strong>{row.task}</strong><p>{row.from_agent_id} → {row.to_agent_id} · {row.current.child_status??row.current.handoff_status??row.current.outcome}</p><code>{row.handoff_id}</code>{row.current.reason&&<p>{row.current.reason}</p>}{row.current.outcome!=='terminal'&&<button disabled={busy||!ready||pending.some(p=>p.id===row.handoff_id)} onClick={()=>void act(row)}>Stop specialist work</button>}</li>)}</ul></section>;
}
