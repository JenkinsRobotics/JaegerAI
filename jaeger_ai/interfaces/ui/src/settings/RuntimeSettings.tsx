import { useEffect, useRef, useState } from "react";
import { Dialog } from "@aether/ui";
import { createPortal } from "react-dom";
import type { ModelInventory, ModelSettings, ModelChoiceSnapshot, ModelChoiceIntent, ModelChoiceReceipt } from "../api/source";
import { useExclusivePopup } from "../popups/coordinator";

/** Session choice only. Credentials, global routing and permissions stay Gateway-owned. */
export function RuntimeSettings({ settings, sessionId, disabled = false }: { settings?: ModelSettings; sessionId?: string; disabled?: boolean }) {
  const [open, setOpen] = useState(false), [attempt, setAttempt] = useState(0);
  const [inventory, setInventory] = useState<ModelInventory>();
  const [selected, setSelected] = useState(""), [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string>(), [notice, setNotice] = useState<string>();
  const [busy, setBusy] = useState(false), locked = useRef(false), generation=useRef(0), proposalRef=useRef<{owner:string;value:string}|undefined>(undefined);
  const [base,setBase]=useState<ModelChoiceSnapshot>(),[pending,setPending]=useState<ModelChoiceIntent>(),[confirmCancel,setConfirmCancel]=useState(false),[needsRefresh,setNeedsRefresh]=useState(false);
  const journal='jaeger.ui.model-choice.v1.'+sessionId,draftKey=journal+'.draft';
  const choice=(value:ModelChoiceSnapshot)=>value.model?value.provider?`@${value.provider}:${value.model}`:value.model:'';

  useExclusivePopup(open, () => { if (!locked.current) setOpen(false); });
  useEffect(() => {
    if (!open || !settings || !sessionId) return;
    let live = true; generation.current++;setConfirmCancel(false);setNeedsRefresh(false);setLoaded(false);setBase(undefined); setError(undefined); setNotice(undefined);
    try { const raw=localStorage.getItem(journal);const value=raw?JSON.parse(raw):undefined;
      if(value&&(!value.operation_id||typeof value.operation_id!=='string'||!Number.isSafeInteger(value.expected_model_revision)||value.expected_model_revision<0||!(value.model===null||typeof value.model==='string')))throw Error('Invalid pending model command');
      if(raw&&!value)throw Error('Invalid pending model command');setPending(value); }
    catch {setPending({operation_id:'invalid-journal',expected_model_revision:-1,model:null});setError('Model journal unavailable or invalid; preserve it and inspect without replay');}
    void Promise.all([settings.inventory(), settings.read(sessionId)]).then(([models, current]) => {
      if (!live) return;
      if (current.session_id !== sessionId) throw new Error("Conversation identity mismatch");
      setInventory(models);setBase(current);
      let proposal:string|null=null;
      if(current.atomic_model_operations)try{proposal=localStorage.getItem(draftKey);}catch{setError('Model proposal storage unavailable; current settings retained');}
      setSelected(proposalRef.current?.owner===sessionId?proposalRef.current.value:proposal??choice(current));setLoaded(true);
    }).catch(e => { if (live) setError(String((e as Error).message ?? e)); });
    return () => { live = false; generation.current++; };
  }, [open, settings, sessionId, attempt]);
  if (!settings || !sessionId) return null;
  const choices = inventory?.providers.filter(p => p.reachable).flatMap(p => p.models.filter(m => m.available !== false).map(m => ({ id: `@${p.id}:${m.id}`, label: `${p.display_name} · ${m.id}`, certified: m.usable_for_react }))) ?? [];
  const finish=async(receipt:ModelChoiceReceipt,intent:ModelChoiceIntent,owner:number)=>{
    if(owner!==generation.current)return;
    if(receipt.operation_id!==intent.operation_id||receipt.domain!=='model_choice'||receipt.session_id!==sessionId||typeof receipt.ok!=='boolean')throw Error('Model receipt identity/scope mismatch; pending journal retained');
    if(receipt.execution_unknown)throw Error('Model operation outcome unknown; inspect without replay');
    if(localStorage.getItem(journal)!==JSON.stringify(intent))throw Error('Model journal changed in another window; original retained');
    localStorage.removeItem(journal);setPending(undefined);setConfirmCancel(false);
    if(!receipt.ok){setLoaded(false);setNeedsRefresh(true);if(receipt.result&&typeof receipt.result==='object'&&'cancelled' in receipt.result&&receipt.result.cancelled===true){setNotice('Pending model save cancelled before commit. Current model and proposal retained; refresh before a new save.');return;}throw Error((receipt.error??'Model choice rejected')+'. Proposal retained; refresh before reviewing a new save');}
    const current=await settings!.read(sessionId!);
    if(owner!==generation.current)return;
    if(current.session_id!==sessionId)throw Error('Current model response belongs to another conversation');
    setBase(current);setLoaded(true);setNeedsRefresh(false);
    if(choice(current)===(intent.model??'')){
      if(localStorage.getItem(draftKey)===(intent.model??''))localStorage.removeItem(draftKey);
      if(proposalRef.current?.owner===sessionId&&proposalRef.current.value===(intent.model??''))proposalRef.current=undefined;
      setNotice('Original model save confirmed: '+(intent.model??'Gateway default')+'. Existing admitted work keeps its original model.');
    }else setNotice('Original model save recorded; another model is current. Proposal retained for review.');
  };
  const save = async () => {
    if(locked.current||!loaded||pending||!settings||!sessionId)return;
    locked.current=true;setBusy(true);setError(undefined);setNotice(undefined);const owner=generation.current;
    try{
      if(base?.atomic_model_operations&&settings.saveVersioned&&Number.isSafeInteger(base.model_choice_revision)){
        if(localStorage.getItem(journal))throw Error('Another model operation is pending; inspect without overwriting');
        const intent:ModelChoiceIntent={operation_id:crypto.randomUUID(),model:selected||null,expected_model_revision:base.model_choice_revision!};
        localStorage.setItem(journal,JSON.stringify(intent));setPending(intent);
        await finish(await settings.saveVersioned(sessionId,intent),intent,owner);
      }else{
        await settings.save(sessionId,selected||null);const current=await settings.read(sessionId);
        if(owner!==generation.current)return;
        if(current.session_id!==sessionId||choice(current)!==selected)throw Error('Saved choice could not be confirmed; refresh before changing it again');
        setNotice('Conversation model saved. Existing admitted work keeps its original model.');
      }
    }catch(e){if(owner===generation.current){setError(String((e as Error).message??e));setLoaded(false);}}
    finally{locked.current=false;setBusy(false);}
  };
  const check=async(cancel=false)=>{
    if(!pending||!settings?.operation||locked.current)return;
    locked.current=true;setBusy(true);setError(undefined);const owner=generation.current;
    try{const result=cancel&&settings.cancelPending?{receipt:await settings.cancelPending(sessionId!,pending)}:await settings.operation(pending.operation_id);if(result.receipt)await finish(result.receipt,pending,owner);else if(owner===generation.current)setNotice('No durable model receipt yet; pending operation retained without replay.');}
    catch(e){if(owner===generation.current)setError(String((e as Error).message??e));}
    finally{locked.current=false;setBusy(false);}
  };
  return <><button type="button" className="aui-button jg-runtime-trigger" disabled={disabled} onClick={() => setOpen(true)}>Gateway settings</button>
    {createPortal(<Dialog open={open} title="Gateway settings" onClose={() => { if (!busy) setOpen(false); }} actions={<button type="button" className="aui-button" disabled={busy} onClick={() => setOpen(false)}>Close</button>}>
      <p>Choose the model for this conversation. Global provider configuration, credentials and tool permissions are managed by the Gateway.</p>
      {error && <p role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}
      {!loaded && !error && !pending && !needsRefresh && <p role="status">Loading models and conversation settings…</p>}
      <button type="button" disabled={busy} onClick={() => setAttempt(n => n + 1)}>Refresh models and settings</button>
      {base&&<p>Current saved choice: {choice(base)||'Gateway default'}{base.atomic_model_operations?` · revision ${base.model_choice_revision}`:' · server has no versioned model receipts'}</p>}
      {pending&&<p role="status">A model save needs its original receipt. Refreshing does not resubmit it.</p>}
      {pending&&settings.operation&&<button type="button" disabled={busy} onClick={()=>void check()}>Check original model save</button>}
      {pending&&settings.cancelPending&&!confirmCancel&&<button type="button" disabled={busy} onClick={()=>setConfirmCancel(true)}>Review pending model cancellation</button>}
      {pending&&confirmCancel&&<div role="group" aria-label="Confirm model save cancellation"><p>This preserves any already committed model choice. If the original command has no receipt, it records rejection atomically so a late handler cannot apply it. Your proposal is retained.</p><button type="button" disabled={busy} onClick={()=>void check(true)}>Confirm pending model cancellation</button><button type="button" disabled={busy} onClick={()=>setConfirmCancel(false)}>Keep pending model save</button></div>}
      {loaded && <><label>Conversation model <select aria-label="Conversation model" value={selected} disabled={busy} onChange={e => {proposalRef.current={owner:sessionId,value:e.target.value};setSelected(e.target.value);if(base?.atomic_model_operations)try{localStorage.setItem(draftKey,e.target.value);}catch{setError("Model proposal could not be saved on this device; draft retained in memory");}}}>
        <option value="">Gateway default{inventory?.active?.model ? ` · ${inventory.active.provider}/${inventory.active.model}` : ""}</option>
        {selected && !choices.some(m => m.id === selected) && <option value={selected} disabled>{selected} (currently unavailable)</option>}
        {choices.map(m => <option key={m.id} value={m.id}>{m.label}{m.certified ? "" : " (tool certification not verified)"}</option>)}
      </select></label><button type="button" disabled={busy || Boolean(pending) || Boolean(selected && !choices.some(m => m.id === selected))} onClick={() => void save()}>Save conversation model</button></>}
      <ul>{inventory?.providers.map(provider => <li key={provider.id}><strong>{provider.display_name}</strong> · {provider.availability==='unknown'?"Configuration unknown":provider.availability==='not_probed'?"Configured · health not probed":provider.reachable ? "Reachable" : provider.configured ? "Unreachable" : "Not configured"}{provider.reason ? ` · ${provider.reason}` : ""}</li>)}</ul>
    </Dialog>, document.body)}
  </>;
}
