/** Agent-mode safety in the chat: what a turn changed (with Undo) and the
 * chat's agent worktree (Apply to your checkout / Discard).
 *
 * Backed by the Gateway's per-turn checkpoints and session worktrees
 * (``core/gateway/agent_safety.py``) through the existing
 * ``/requests/{id}/changes`` and ``/changes/undo`` routes. */
import { useEffect, useState } from 'react';
import { getJson, sendJson } from '../unified/webui';
import { ChevronIcon, UndoIcon } from '../icons';
import './agentChanges.css';

type Changed = { path:string; status?:'added'|'modified'|'deleted'; added?:number; removed?:number };
type TurnChangeState = { files:Changed[]; canUndo?:boolean; undone?:boolean; undoBlocked?:string|null; safety?:'worktree'|'checkpoint'; worktree?:{branch:string;repo:string}|null; movedToTrash?:string|null; appliedTo?:string|null };
type Worktree = { active:boolean; repo?:string; repoName?:string; branch?:string; path?:string; files?:Changed[]; stat?:string; applied?:number; discarded?:boolean; movedTo?:string };

const enc=encodeURIComponent;
const mark=(s?:string)=>s==='added'?'A':s==='deleted'?'D':'M';
const plural=(n:number,w:string)=>`${n} ${w}${n===1?'':'s'}`;
export const AGENT_CHANGES_EVENT='jaeger:agent-changes';
const announce=()=>window.dispatchEvent(new Event(AGENT_CHANGES_EVENT));

function FileList({files}:{files:Changed[]}){
 return <ul className="jg-changes__files">{files.slice(0,50).map(f=><li key={f.path}><span className="jg-changes__mark" data-status={f.status||'modified'}>{mark(f.status)}</span><code>{f.path}</code></li>)}{files.length>50&&<li>…and {files.length-50} more</li>}</ul>;
}

/** Under a finished turn: "Changed N files · Undo". */
export function TurnChanges({sessionId,requestId,settled}:{sessionId:string;requestId:string;settled:boolean}){
 const [state,setState]=useState<TurnChangeState>(),[open,setOpen]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState(''),[tick,setTick]=useState(0);
 useEffect(()=>{const bump=()=>setTick(t=>t+1);window.addEventListener(AGENT_CHANGES_EVENT,bump);return()=>window.removeEventListener(AGENT_CHANGES_EVENT,bump);},[]);
 useEffect(()=>{
  if(!settled)return;const ctl=new AbortController();
  getJson<TurnChangeState>(`/v1/sessions/${enc(sessionId)}/requests/${enc(requestId)}/changes`,ctl.signal).then(d=>{if(!ctl.signal.aborted)setState(d);},()=>{});
  return()=>ctl.abort();
 },[sessionId,requestId,settled,tick]);
 if(!state?.files?.length)return null;
 const undo=async()=>{setBusy(true);setError('');try{setState(await sendJson<TurnChangeState>('POST',`/v1/sessions/${enc(sessionId)}/requests/${enc(requestId)}/changes/undo`,{}));announce();}catch(e){setError((e as Error).message);}finally{setBusy(false);}};
 const base=(p:string)=>p.split('/').filter(Boolean).pop()||p;
 const where=state.appliedTo?` · applied to ${base(state.appliedTo)}`:state.safety==='worktree'&&state.worktree?` in worktree ${state.worktree.branch}`:'';
 const undoTitle=state.canUndo?(state.appliedTo?`Revert these changes in ${state.appliedTo}`:'Put these files back the way they were before this turn'):state.undoBlocked||'Undo unavailable';
 return <div className="jg-changes" data-undone={state.undone||undefined}>
  <div className="jg-changes__row">
   <button type="button" className="jg-changes__toggle" aria-expanded={open} onClick={()=>setOpen(o=>!o)}><ChevronIcon className="jg-changes__chev"/>{state.undone?`Undid changes to ${plural(state.files.length,'file')}${state.appliedTo?` in ${base(state.appliedTo)}`:''}`:`Changed ${plural(state.files.length,'file')}${where}`}</button>
   {!state.undone&&<button type="button" className="jg-changes__undo" disabled={busy||!state.canUndo} title={undoTitle} onClick={()=>void undo()}><UndoIcon/>{busy?'Undoing…':state.appliedTo?'Undo in checkout':'Undo'}</button>}
  </div>
  {open&&<FileList files={state.files}/>}
  {state.undone&&state.movedToTrash&&<small className="jg-changes__note">New files were moved to {state.movedToTrash}</small>}
  {error&&<small className="jg-changes__error" role="alert">{error}</small>}
 </div>;
}

/** Above the composer while the chat's agent worktree has changes not yet applied. */
export function WorktreeBar({sessionId,refreshKey}:{sessionId:string;refreshKey:string}){
 const [wt,setWt]=useState<Worktree>(),[open,setOpen]=useState(false),[busy,setBusy]=useState(''),[confirm,setConfirm]=useState(false),[note,setNote]=useState(''),[error,setError]=useState(''),[tick,setTick]=useState(0);
 useEffect(()=>{const bump=()=>setTick(t=>t+1);window.addEventListener(AGENT_CHANGES_EVENT,bump);return()=>window.removeEventListener(AGENT_CHANGES_EVENT,bump);},[]);
 useEffect(()=>{const ctl=new AbortController();getJson<Worktree>(`/v1/sessions/${enc(sessionId)}/worktree`,ctl.signal).then(d=>{if(!ctl.signal.aborted)setWt(d);},()=>{});return()=>ctl.abort();},[sessionId,refreshKey,tick]);
 const act=async(action:'apply'|'discard')=>{setBusy(action);setError('');setConfirm(false);try{const d=await sendJson<Worktree>('POST',`/v1/sessions/${enc(sessionId)}/worktree/${action}`,{});setWt(d);setNote(action==='apply'?`Applied ${plural(d.applied||0,'file')} to ${d.repoName||'your checkout'} as uncommitted changes.`:`Discarded. Kept on branch ${d.branch}; folder moved to ${d.movedTo}.`);announce();}catch(e){setError((e as Error).message);}finally{setBusy('');}};
 const files=wt?.files||[];
 if(!wt?.active||!files.length)return note?<div className="jg-worktree jg-worktree--note" role="status">{note}<button type="button" aria-label="Dismiss" onClick={()=>setNote('')}>×</button></div>:null;
 return <div className="jg-worktree" role="region" aria-label="Agent worktree">
  <div className="jg-worktree__row">
   <button type="button" className="jg-changes__toggle" aria-expanded={open} onClick={()=>setOpen(o=>!o)}><ChevronIcon className="jg-changes__chev"/><span><strong>{plural(files.length,'file')} changed</strong> in a worktree, not yet in {wt.repoName}</span></button>
   <span className="jg-worktree__branch" title={wt.path}>{wt.branch}</span>
   <span className="jg-worktree__actions">
    {confirm?<><span>Discard these changes?</span><button type="button" onClick={()=>setConfirm(false)}>Keep</button><button type="button" className="jg-worktree__danger" disabled={Boolean(busy)} onClick={()=>void act('discard')}>Discard</button></>
     :<><button type="button" disabled={Boolean(busy)} onClick={()=>setConfirm(true)}>Discard</button><button type="button" className="jg-worktree__primary" disabled={Boolean(busy)} title={`Copy these changes into ${wt.repo} as uncommitted edits`} onClick={()=>void act('apply')}>{busy==='apply'?'Applying…':`Apply to ${wt.repoName}`}</button></>}
   </span>
  </div>
  {open&&<><FileList files={files}/>{wt.stat&&<small className="jg-changes__note">{wt.stat}</small>}</>}
  {error&&<small className="jg-changes__error" role="alert">{error}</small>}
 </div>;
}
