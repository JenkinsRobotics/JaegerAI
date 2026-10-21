import {displayDate} from "./devicePreferences";
import {useEffect,useRef,useState} from 'react';
import type {EpisodeContext,EpisodeControls,ControlResult} from '../api/source';
type Intent={operation_id:string;expected_revision:string;action:'annotate'|'forget'|'restore';text?:string};
export function EpisodeMemoryPanel({controls}:{controls:EpisodeControls}){
 const [query,setQuery]=useState(''),[before,setBefore]=useState<number>(),[refresh,setRefresh]=useState(0),[rows,setRows]=useState<EpisodeContext[]>([]),[next,setNext]=useState<number|null>(null),[error,setError]=useState<string>(),[selected,setSelected]=useState<string>();
 useEffect(()=>{let live=true;const timer=setTimeout(()=>{void controls.list(query,before).then(value=>{if(live){setRows(current=>before?[...current,...value.episodes.filter(row=>!current.some(old=>old.event_id===row.event_id))]:value.episodes);setNext(value.next_before);setError(undefined);}},e=>{if(live)setError(String(e));});},150);return()=>{live=false;clearTimeout(timer);};},[controls,query,before,refresh]);
 return <section aria-label="Episodic memory"><h3>Conversation episode memory</h3><p>Immutable records owned by the resident entity. Correction notes are recorded operator assertions, not rewritten history or verified facts. Recoverable forget excludes an episode from automatic cross-conversation recall; its original conversation, inline history and previously derived memories remain intact.</p><label>Search episode memory<input value={query} maxLength={200} onChange={e=>{setBefore(undefined);setQuery(e.target.value);}}/></label><button type="button" onClick={()=>{setBefore(undefined);setRefresh(n=>n+1);}}>Refresh episodes</button>{error&&<p role="alert">{error}. Earlier results retained.</p>}{rows.map(row=><article className="jg-card" key={row.event_id}><strong>{row.event_type} · {row.active?'Recall eligible':'Excluded from recall'}</strong><pre style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere'}}>{row.text}</pre>{row.truncated&&<p>Bounded preview; original bytes retained.</p>}<p>{row.actor} · {row.source} · {displayDate(new Date(row.timestamp*1000))}</p><small>{row.event_id} · conversation {row.session_id}</small>{row.annotation&&<p>Operator correction note: {row.annotation}</p>}<button type="button" onClick={()=>setSelected(row.event_id)}>Inspect episode context</button></article>)}{next&&<button type="button" onClick={()=>setBefore(next)}>Load older episodes</button>}{selected&&<EpisodeEditor key={selected} id={selected} controls={controls} close={()=>setSelected(undefined)} changed={()=>{setBefore(undefined);setRefresh(n=>n+1);}}/>}</section>;
}
function EpisodeEditor({id,controls,close,changed}:{id:string;controls:EpisodeControls;close:()=>void;changed:()=>void}){
 const key='jaeger.ui.episode-context.v1.'+id,draftKey=key+'.draft';
 const [row,setRow]=useState<EpisodeContext>(),[text,setText]=useState(()=>localStorage.getItem(draftKey)??''),[error,setError]=useState<string>(),[notice,setNotice]=useState<string>(),[confirm,setConfirm]=useState<Intent['action']>(),[busy,setBusy]=useState(false),[refresh,setRefresh]=useState(0);
 const [pending,setPending]=useState<Intent|undefined>(()=>{try{const raw=localStorage.getItem(key);return raw?JSON.parse(raw):undefined;}catch{return {operation_id:'invalid-journal',expected_revision:'',action:'forget'};}});
 const lock=useRef(false);
 useEffect(()=>{let live=true;void controls.detail(id).then(value=>{if(live){setRow(value);setError(undefined);}},e=>{if(live)setError(String(e));});return()=>{live=false;};},[controls,id,refresh]);
 const finish=(receipt:ControlResult,intent:Intent)=>{
  if(receipt.operation_id!==intent.operation_id)throw Error('Receipt does not match pending episode operation');
  if(receipt.execution_unknown)throw Error('Original outcome unknown; inspect without replay');
  if(localStorage.getItem(key)!==JSON.stringify(intent))throw Error('Pending journal changed in another window; original retained');
  localStorage.removeItem(key);setPending(undefined);setConfirm(undefined);setRefresh(n=>n+1);changed();
  if(!receipt.ok)throw Error(receipt.error??'Episode change rejected; draft preserved');
  setNotice('Episode context policy saved; original history preserved. Existing admitted work is unchanged.');
 };
 const run=async(check=false)=>{
  if(lock.current)return;lock.current=true;setBusy(true);setError(undefined);
  try{
   if(check&&pending){const value=await controls.operation(pending.operation_id);if(value.receipt)finish(value.receipt,pending);else setNotice('No durable receipt yet; pending command retained without replay.');return;}
   if(!row||!confirm||pending||!row.editable)return;
   if(localStorage.getItem(key))throw Error('Another pending operation exists; inspect it without overwriting');
   const intent:Intent={operation_id:crypto.randomUUID(),expected_revision:row.revision,action:confirm,...(confirm==='annotate'?{text}:{})};
   localStorage.setItem(key,JSON.stringify(intent));setPending(intent);
   const {action,...body}=intent;finish(await controls.mutate(id,action,body),intent);
  }catch(e){setError(String(e));}finally{lock.current=false;setBusy(false);}
 };
 return <div role="group" aria-label="Episode context inspector"><h4>Episode context inspector</h4>{error&&<p role="alert">{error}</p>}{notice&&<p role="status">{notice}</p>}{row&&<><p>Original {row.event_id} · {row.active?'Recall eligible':'Excluded from recall'}</p><pre style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere'}}>{row.text}</pre><p>Saved correction: {row.annotation||'None'}</p><label>Episode correction draft<textarea value={text} maxLength={8000} onChange={e=>{localStorage.setItem(draftKey,e.target.value);setText(e.target.value);}}/></label>{row.editable&&!pending&&<><button type="button" disabled={busy||!text.trim()} onClick={()=>setConfirm('annotate')}>Review correction note</button><button type="button" disabled={busy} onClick={()=>setConfirm(row.active?'forget':'restore')}>{row.active?'Review recoverable forget':'Review recall restore'}</button></>}{!row.editable&&<p>Existing resident owner admin scope required for changes. No runtime is started by inspection.</p>}</>}{confirm&&!pending&&<div role="group" aria-label="Confirm episode context change"><p>Confirm {confirm} against the displayed revision. This changes future cross-conversation context only; it does not erase history or derived memories, change permissions or restart in-flight work.</p><button type="button" disabled={busy} onClick={()=>void run()}>Confirm episode change</button><button type="button" onClick={()=>setConfirm(undefined)}>Cancel episode change</button></div>}{pending&&<button type="button" disabled={busy} onClick={()=>void run(true)}>Check original episode operation</button>}<button type="button" disabled={busy} onClick={()=>setRefresh(n=>n+1)}>Read current episode</button><button type="button" disabled={busy} onClick={close}>Close episode inspector</button></div>;
}
