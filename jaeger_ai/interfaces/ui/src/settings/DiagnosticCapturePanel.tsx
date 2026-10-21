import {useEffect,useState,useRef} from 'react';
import {DIAGNOSTIC_CAPTURE_KEY,enableDiagnosticReporting,type DiagnosticCaptureControls,type DiagnosticCaptureSnapshot} from '../api/diagnosticCapture';
type Intent={kind:'start';operation_id:string;duration_seconds:number;boot_id:string}|{kind:'stop';capture_id:string;boot_id:string};
const KEY='jaeger.ui.diagnostics.intent.v1';
export function DiagnosticCapturePanel({controls}:{controls:DiagnosticCaptureControls}){
 const [snapshot,setSnapshot]=useState<DiagnosticCaptureSnapshot>(),[error,setError]=useState<string>(),[notice,setNotice]=useState<string>(),[review,setReview]=useState(false),[busy,setBusy]=useState(false),[report,setReport]=useState<string>();
 const lock=useRef(false);
 const [pending,setPending]=useState<Intent|undefined>(()=>{try{const raw=localStorage.getItem(KEY);return raw?JSON.parse(raw):undefined;}catch{return {kind:'start',operation_id:'invalid-journal',duration_seconds:0,boot_id:'unknown'};}});
 useEffect(()=>{let live=true;void controls.read().then(value=>{if(live)setSnapshot(value);},e=>{if(live)setError(String(e));});return()=>{live=false;};},[controls]);
 const settle=(value:DiagnosticCaptureSnapshot,intent:Intent)=>{
  setSnapshot(value);
  if(value.boot_id!==intent.boot_id)throw Error('Gateway process changed; earlier capture outcome unknown. No capture was restarted.');
  const capture=value.capture;
  if(intent.kind==='start'&&capture?.operation_id!==intent.operation_id.replaceAll('-','')||intent.kind==='stop'&&(capture?.id!==intent.capture_id||capture.state==='active'))throw Error('Original capture status not confirmed; preserve intent and read current status');
  if(localStorage.getItem(KEY)!==JSON.stringify(intent))throw Error('Diagnostic intent changed in another window; original retained');
  if(intent.kind==='start')enableDiagnosticReporting(value);else localStorage.removeItem(DIAGNOSTIC_CAPTURE_KEY);
  localStorage.removeItem(KEY);setPending(undefined);setReview(false);
  setNotice(intent.kind==='start'&&capture?.state==='active'?'Bounded reporting enabled for this browser profile. Fixed categories and opaque IDs only.':'Capture is not active. No model, tool or conversation was changed.');
 };
 const run=async(action:'read'|'start'|'stop')=>{
  if(lock.current)return;lock.current=true;setBusy(true);setError(undefined);
  try{
   if(action==='read'){const current=await controls.read();setSnapshot(current);if(pending)settle(current,pending);return;}
   if(!snapshot||pending)return;
   const intent:Intent=action==='start'?{kind:'start',operation_id:crypto.randomUUID(),duration_seconds:Math.min(60,snapshot.max_seconds),boot_id:snapshot.boot_id}:{kind:'stop',capture_id:snapshot.capture!.id,boot_id:snapshot.boot_id};
   if(localStorage.getItem(KEY))throw Error('Another diagnostic intent is pending; preserve it and read current status');
   localStorage.setItem(KEY,JSON.stringify(intent));setPending(intent);
   if(intent.kind==='stop')localStorage.removeItem(DIAGNOSTIC_CAPTURE_KEY);
   const result=intent.kind==='start'?await controls.start({operation_id:intent.operation_id,duration_seconds:intent.duration_seconds}):await controls.stop(intent.capture_id);
   settle(result,intent);
  }catch(e){setError(String(e));}finally{lock.current=false;setBusy(false);}
 };
 const preserve=()=>{if(!pending)return;try{const original=localStorage.getItem(KEY);if(!original||original!==JSON.stringify(pending))throw Error('Original intent changed in another window; preserve both');localStorage.setItem(KEY+'.previous.'+(pending.kind==='start'?pending.operation_id:pending.capture_id),original);localStorage.removeItem(KEY);localStorage.removeItem(DIAGNOSTIC_CAPTURE_KEY);setPending(undefined);setNotice('Prior intent preserved on this device. No capture started; review a new capture separately.');}catch(e){setError(String(e));}};
 const preview=async()=>{if(lock.current)return;lock.current=true;setBusy(true);try{const value=await controls.export();setReport(JSON.stringify(value,null,2));setNotice('Sanitized report prepared locally for review; nothing uploaded.');}catch(e){setError(String(e));}finally{lock.current=false;setBusy(false);}};
 const download=()=>{if(!report)return;try{const url=URL.createObjectURL(new Blob([report],{type:'application/json'})),link=document.createElement('a');link.href=url;link.download='jaeger-diagnostics.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);setNotice('Download requested; delivery depends on the browser/native host. No upload.');}catch(e){setError(String(e));}};
 return <section aria-label="Bounded transport diagnostics"><h3>Optional transport counters</h3><p>Off until explicitly enabled. Captures only fixed parser/transport/subscriber failure categories and opaque source references, never prompts, frames, headers, attachments or exception text. Reports are best effort, not a traffic recording or execution receipt. No external upload.</p><p>Most recent capture is in Gateway memory only; expiry stops collection and a Gateway restart loses counters without restarting capture. Export before replacing a previous capture.</p>{error&&<p role="alert">{error}</p>}{notice&&<p role="status">{notice}</p>}{snapshot&&<><p>Last observed state: {snapshot.capture?.state??'off'} · {snapshot.capture?.occurrences??0} received occurrences · {snapshot.capture?.unique_receipts??0} retained unique receipts · {snapshot.capture?.overflow_occurrences??0} overflow occurrences · limit {snapshot.max_events}{snapshot.capture?` · window ends ${new Date(snapshot.capture.expires_at*1000).toLocaleString()}`:""}</p>{snapshot.capture?.saturated&&<p>Counter limit reached; later reports are not retained.</p>}<button type="button" disabled={busy} onClick={()=>void run('read')}>Read current capture status</button>{!pending&&snapshot.capture?.state!=='active'&&<button type="button" disabled={busy} onClick={()=>setReview(true)}>Review 60-second diagnostic capture</button>}{!pending&&snapshot.capture?.state==='active'&&<button type="button" disabled={busy} onClick={()=>void run('stop')}>Stop diagnostic capture</button>}{review&&!pending&&<div role="group" aria-label="Confirm diagnostic capture"><p>Enable bounded failure counters for tabs in this browser profile for at most60 seconds. Previous in-memory diagnostic counters are replaced; conversations/history are untouched.</p><button type="button" disabled={busy} onClick={()=>void run('start')}>Enable bounded diagnostics</button><button type="button" onClick={()=>setReview(false)}>Cancel diagnostic review</button></div>}{pending&&<><p>Original capture intent retained. Read status; do not resubmit it.</p><button type="button" disabled={busy} onClick={preserve}>Preserve prior diagnostic intent separately</button></>}<button type="button" disabled={busy} onClick={()=>void preview()}>Prepare sanitized diagnostic export</button></>}{report&&<><pre style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere'}}>{report}</pre><button type="button" onClick={download}>Download reviewed diagnostic report</button></>}</section>;
}
