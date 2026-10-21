import { useRef, useState } from 'react';
import { useExclusivePopup } from '../popups/coordinator';
import type { Handoff,HandoffCommandReceipt } from '../api/types';
const key=(id:string)=>'jaeger.ui.handoff-reply.v1.'+encodeURIComponent(id);
interface Intent {task:string;requestId:string;draftBody?:string}
function recover(id:string){
 let draft='';
 try{draft=localStorage.getItem(key(id)+'.draft')??'';const raw=localStorage.getItem(key(id));let pending:Intent|undefined;if(raw){pending=JSON.parse(raw);if(!pending||typeof pending.task!=='string'||typeof pending.requestId!=='string')throw Error();}return {draft,pending,error:''};}
 catch{return {draft,pending:undefined,error:'Reply recovery storage unavailable or malformed; original retained. No request will be sent.'};}
}
/** New owner follow-up, preserved before submission; incoming data never executes itself. */
export function HandoffReplyDialog({ handoffId, send,command,lookup,onClose }: { handoffId: string; send: (id: string, task: string, requestId: string) => Promise<Handoff>; command?:(id:string,task:string,rid:string)=>Promise<HandoffCommandReceipt>;lookup?:(id:string,rid:string)=>Promise<HandoffCommandReceipt>;onClose: () => void }) {
  const [recovery]=useState(()=>recover(handoffId));const [text,setText]=useState(recovery.draft),[pending,setPending]=useState<Intent|undefined>(recovery.pending),[storageReady,setStorageReady]=useState(!recovery.error);
  const [busy,setBusy]=useState(false),[error,setError]=useState(recovery.error),[status,setStatus]=useState('');const lock=useRef(false);
  useExclusivePopup(true,()=>{if(!busy)onClose();});
  const settle=(receipt:HandoffCommandReceipt,intent:Intent)=>{
    if(receipt.scope!=='handoff_reply'||receipt.resource_id!==handoffId||receipt.request_id!==intent.requestId||!['saved','rejected','unknown'].includes(receipt.outcome))throw Error('Foreign reply receipt; original retained');
    if(receipt.outcome==='unknown')throw Error('Original follow-up admission unknown; no resubmission');
    if(!receipt.command||Object.keys(receipt.command).length!==2||receipt.command.task!==intent.task||receipt.command.request_id!==intent.requestId)throw Error('Original reply body mismatch; intent retained');
    const row=receipt.handoff;
    if(receipt.outcome==='saved'&&(!row||row.request_id!==intent.requestId||row.task!==intent.task||row.metadata?.reply_to_handoff_id!==handoffId||!row.id||typeof row.status!=='string'))throw Error('Reply correlation mismatch; original retained');
    if(localStorage.getItem(key(handoffId))!==JSON.stringify(intent))throw Error('Reply intent changed in another window; original retained');
    localStorage.removeItem(key(handoffId));setPending(undefined);
    if(receipt.outcome==='rejected')throw Error(receipt.error??'Follow-up rejected before admission; draft retained');
    if(intent.draftBody!==undefined&&localStorage.getItem(key(handoffId)+'.draft')===intent.draftBody){localStorage.removeItem(key(handoffId)+'.draft');setText('');}
    setStatus(row!.status==='pending_approval'?'Follow-up saved. Awaiting approval.':`Follow-up saved: ${row!.status}`);
  };
  const submit=async(check=false)=>{
    if(lock.current||status||!storageReady)return;lock.current=true;setBusy(true);setError('');
    try{
      if(pending){if(!check)return;if(!lookup)throw Error('Original receipt lookup unsupported; preserve intent and inspect the exchange');settle(await lookup(handoffId,pending.requestId),pending);return;}
      if(check||!text.trim())return;
      const intent={task:text.trim(),requestId:crypto.randomUUID(),draftBody:text};if(localStorage.getItem(key(handoffId)))throw Error('Another original reply is pending; reopen to inspect it');
      localStorage.setItem(key(handoffId),JSON.stringify(intent));setPending(intent);
      if(command){settle(await command(handoffId,intent.task,intent.requestId),intent);return;}
      const row=await send(handoffId,intent.task,intent.requestId);
      // Older sources retain safe uncertainty; only a correlated actual record settles.
      settle({scope:'handoff_reply',resource_id:handoffId,request_id:intent.requestId,outcome:'saved',command:{task:intent.task,request_id:intent.requestId},handoff:row},intent);
    }catch(e){setError(String((e as Error).message??e));}finally{lock.current=false;setBusy(false);}
  };
  return <div className="jg-amenu__scrim"><form className="jg-aprompt" role="dialog" aria-label="Follow up in this exchange" onSubmit={e=>{e.preventDefault();void submit();}}><h3>Follow up in this exchange</h3><p>Uses the same bots and conversation. A new approval is required before work starts. Device recovery storage keeps drafts and original requests; save failures are shown below. Closing never cancels admitted work.</p><textarea aria-label="Follow-up message" value={text} disabled={busy||Boolean(pending)||!!status} maxLength={20000} onChange={e=>{const value=e.target.value;setText(value);try{localStorage.setItem(key(handoffId)+'.draft',value);setError('');setStorageReady(true);}catch(err){setStorageReady(false);setError('Draft not saved: '+String(err));}}}/>{error&&<p role="alert">{error}</p>}{status&&<p role="status">{status}</p>}{pending&&<><p>Original follow-up retained. Check it; nothing is resubmitted.</p><button type="button" disabled={busy} onClick={()=>void submit(true)}>Check original follow-up</button></>}<div className="jg-aprompt__actions"><button type="button" disabled={busy} onClick={onClose}>Close</button><button type="submit" disabled={busy||Boolean(pending)||!!status||!text.trim()||!storageReady}>Request follow-up</button></div></form></div>;
}
