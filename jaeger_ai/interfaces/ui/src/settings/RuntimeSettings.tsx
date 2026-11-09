import { useEffect, useRef, useState } from "react";
import type { ModelInventory, ModelSettings, ModelChoiceSnapshot, ModelChoiceIntent, ModelChoiceReceipt } from "../api/source";
import { useExclusivePopup } from "../popups/coordinator";
import { Bot, Gauge, ChevronDown, Search, X } from "../components/Icons";

type RuntimeChoice = { id: string; model: string; provider: string; providerLabel: string; group: string; groupLabel: string; certified?: boolean; contextLength?: number | null };

/** Short human form of a context window: 1M / 262K / 128K. */
export const contextBadge = (value?: number | null) => {
  if (!value || value <= 0) return "";
  if (value >= 1_000_000) return `${(Math.round(value / 100_000) / 10).toString().replace(/\.0$/, "")}M`;
  if (value >= 1000) return `${Math.round(value / 1000)}K`;
  return value.toLocaleString("en-US");
};

const isCloudModel = (id: string, remoteHost?: string | null) => Boolean(remoteHost) || id.endsWith(":cloud") || id.endsWith("-cloud");
export function runtimeChoices(inventory?: ModelInventory): RuntimeChoice[] {
  return inventory?.providers.filter(provider => provider.reachable).flatMap(provider => provider.models
    .filter(model => model.available !== false && (!model.capabilities?.length || model.capabilities.includes("completion")))
    .map(model => {
      const ollama = provider.id === "ollama" || provider.id.startsWith("ollama-");
      const cloud = ollama && isCloudModel(model.id, model.remote_host);
      return {
        id: `@${provider.id}:${model.id}`,
        model: model.id,
        provider: provider.id,
        providerLabel: provider.display_name,
        group: ollama ? cloud ? "ollama-cloud" : "ollama-local" : provider.id,
        groupLabel: ollama ? cloud ? "Ollama Cloud" : "Ollama Local" : provider.display_name,
        certified: model.usable_for_react,
        contextLength: model.context_length,
      };
    })) ?? [];
}

/** Session choice only. Credentials, global routing and permissions stay Gateway-owned. */
export function RuntimeSettings({ settings, sessionId, disabled = false }: { settings?: ModelSettings; sessionId?: string; disabled?: boolean }) {
  const [open, setOpen] = useState(false), [attempt, setAttempt] = useState(0);
  const [query, setQuery] = useState("");
  const [providerGroup, setProviderGroup] = useState("all");
  const trigger = useRef<HTMLButtonElement>(null);
  const [inventory, setInventory] = useState<ModelInventory>();
  const [selected, setSelected] = useState(""), [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string>(), [notice, setNotice] = useState<string>();
  const [busy, setBusy] = useState(false), locked = useRef(false), generation=useRef(0), proposalRef=useRef<{owner:string;value:string}|undefined>(undefined);
  const [base,setBase]=useState<ModelChoiceSnapshot>(),[pending,setPending]=useState<ModelChoiceIntent>(),[confirmCancel,setConfirmCancel]=useState(false),[needsRefresh,setNeedsRefresh]=useState(false);
  const journal='jaeger.ui.model-choice.v1.'+sessionId,draftKey=journal+'.draft';
  const choice=(value:ModelChoiceSnapshot)=>value.model?value.provider?`@${value.provider}:${value.model}`:value.model:'';

  useExclusivePopup(open, () => { if (!locked.current) setOpen(false); }, trigger.current);
  useEffect(() => {
    if (!settings || !sessionId) return;
    let live = true;
    setInventory(undefined);
    void settings.inventory().then(models => { if (live) setInventory(models); }, () => { /* Keep an honest fallback until the picker can show the error. */ });
    void settings.read(sessionId).then(current => { if (live && current.session_id === sessionId) setBase(current); }, () => { /* the opened picker shows the actionable error */ });
    return () => { live = false; };
  }, [settings, sessionId]);
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
      const nextSelected=proposalRef.current?.owner===sessionId?proposalRef.current.value:proposal??choice(current);
      setSelected(nextSelected);
      const matching=runtimeChoices(models).find(model=>model.id===nextSelected);
      setProviderGroup(matching?.group??(runtimeChoices(models).some(model=>model.group==="ollama-cloud")?"ollama-cloud":"all"));
      setLoaded(true);
    }).catch(e => { if (live) setError(String((e as Error).message ?? e)); });
    return () => { live = false; generation.current++; };
  }, [open, settings, sessionId, attempt]);
  if (!settings || !sessionId) return null;
  const choices = runtimeChoices(inventory);
  const providerGroups = Array.from(new Map(choices.map(model => [model.group, model.groupLabel])).entries());
  const filteredChoices = choices.filter(model => (providerGroup === "all" || model.group === providerGroup) && (!query.trim() || `${model.model} ${model.providerLabel} ${model.groupLabel}`.toLowerCase().includes(query.trim().toLowerCase())));
  const currentChoice = base ? choice(base) : "";
  const currentLabel = currentChoice ? currentChoice.replace(/^@/, "").replace(":", " · ") : inventory?.active?.model || "Default model";
  const currentContext = currentChoice ? runtimeChoices(inventory).find(model => model.id === currentChoice)?.contextLength : undefined;
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
  const select = (value: string) => { proposalRef.current={owner:sessionId,value};setSelected(value);if(base?.atomic_model_operations)try{localStorage.setItem(draftKey,value);}catch{setError("Model proposal could not be saved on this device; draft retained in memory");} };
  return <div className="jg-runtime-picker"><button ref={trigger} type="button" className="jg-runtime-trigger" aria-label="Choose conversation model" title={`Configured model: ${currentLabel}. Provider execution is verified separately.`} aria-expanded={open} disabled={disabled} onClick={() => { setQuery(""); setOpen(value => !value); }}><Gauge size={20} /><span>{currentLabel}</span>{currentContext ? <span className="jg-runtime-context" title={`Context window: ${currentContext.toLocaleString("en-US")} tokens`}>{contextBadge(currentContext)}</span> : null}<ChevronDown size={14} /></button>
    {open && <section className="jg-runtime-menu" role="dialog" aria-label="Gateway models and settings" data-jg-popup>
      <header><strong>Model for this conversation</strong><button type="button" aria-label="Close model picker" onClick={() => setOpen(false)}><X size={16} /></button></header>
      {loaded && <div className="jg-runtime-tabs" role="tablist" aria-label="Model providers">
        <button type="button" role="tab" aria-selected={providerGroup === "all"} onClick={() => setProviderGroup("all")}><Bot size={15} />All</button>
        {providerGroups.map(([id,label]) => <button key={id} type="button" role="tab" aria-selected={providerGroup === id} onClick={() => setProviderGroup(id)}>{label}</button>)}
      </div>}
      <label className="jg-runtime-search"><Search size={15} /><input type="search" autoFocus value={query} onChange={e => setQuery(e.target.value)} placeholder="Search models…" aria-label="Search models" /></label>
      {error && <p className="jg-runtime-message is-error" role="alert">{error}</p>}{notice && <p className="jg-runtime-message" role="status">{notice}</p>}
      {!loaded && !error && !pending && !needsRefresh && <p className="jg-runtime-message" role="status">Loading Gateway models…</p>}
      {base && <p className="jg-runtime-message">Current saved choice: {choice(base)||"Gateway default"}{base.atomic_model_operations ? ` · revision ${base.model_choice_revision}` : ""}</p>}
      {loaded && <div className="jg-runtime-models" role="listbox" aria-label="Conversation model">
        <button type="button" role="option" aria-selected={selected === ""} onClick={() => select("")}><span><strong>Gateway default</strong>{inventory?.active?.model && <small>{inventory.active.provider} · {inventory.active.model}</small>}</span>{selected === "" && <span className="jg-runtime-check">✓</span>}</button>
        {selected && !choices.some(m => m.id === selected) && <button type="button" disabled><span><strong>{selected}</strong><small>Currently unavailable</small></span></button>}
        {filteredChoices.map(model => <button key={model.id} type="button" role="option" aria-selected={selected === model.id} onClick={() => select(model.id)}><span><strong>{model.model}</strong><small>{model.groupLabel}{model.certified ? " · Tool use verified" : " · Tool certification not verified"}</small></span>{selected === model.id && <span className="jg-runtime-check">✓</span>}</button>)}
        {!filteredChoices.length && <p className="jg-runtime-message">No available models match “{query}”.</p>}
      </div>}
      {pending&&<p className="jg-runtime-message" role="status">A model save needs its original receipt. It will not be resubmitted.</p>}
      {pending&&settings.operation&&<button className="jg-runtime-secondary" type="button" disabled={busy} onClick={()=>void check()}>Check original model save</button>}
      {pending&&settings.cancelPending&&!confirmCancel&&<button className="jg-runtime-secondary" type="button" disabled={busy} onClick={()=>setConfirmCancel(true)}>Review pending model cancellation</button>}
      {pending&&confirmCancel&&<div className="jg-runtime-confirm" role="group" aria-label="Confirm model save cancellation"><p>Cancel the pending command while preserving the committed choice and this proposal?</p><button type="button" disabled={busy} onClick={()=>void check(true)}>Confirm pending model cancellation</button><button type="button" disabled={busy} onClick={()=>setConfirmCancel(false)}>Keep pending model save</button></div>}
      <details className="jg-runtime-providers"><summary>Gateway provider status</summary><ul>{inventory?.providers.map(provider => <li key={provider.id}><strong>{provider.display_name}</strong> · {provider.availability==='unknown'?"Configuration unknown":provider.availability==='not_probed'?"Configured · health not probed":provider.reachable ? "Reachable" : provider.configured ? "Unreachable" : "Not configured"}{provider.reason ? ` · ${provider.reason}` : ""}</li>)}</ul></details>
      <footer><button type="button" disabled={busy} onClick={() => setAttempt(n => n + 1)}>Refresh models and settings</button><button className="jg-runtime-save" type="button" disabled={!loaded || busy || Boolean(pending) || Boolean(selected && !choices.some(m => m.id === selected))} onClick={() => void save()}>Save conversation model</button></footer>
    </section>}
  </div>;
}
