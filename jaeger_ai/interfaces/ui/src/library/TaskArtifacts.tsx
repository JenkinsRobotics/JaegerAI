import {useEffect,useMemo,useState} from 'react';
import type {SessionFiles as Files,TaskArtifact,TaskArtifacts as Controls} from '../api/source';
import {SessionFiles} from '../chat/SessionFiles';

/** Existing owner manifest + verified file pane. No client path or file copy. */
export function TaskArtifacts({controls,taskId,sessionId}:{controls:Controls;taskId?:string;sessionId?:string}){
 const key='jaeger.ui.artifact-selection.v1.'+encodeURIComponent(taskId??(sessionId?'session:'+sessionId:'library'));
 const [catalog,setCatalog]=useState<{stamp:string;rows:TaskArtifact[]}>(),[error,setError]=useState<string>(),[attempt,setAttempt]=useState(0);
 const stamp=key+':'+attempt;const rows=catalog?.stamp===stamp?catalog.rows:undefined;
 const [selected,setSelected]=useState<string>();
 useEffect(()=>{let live=true;setCatalog(undefined);setError(undefined);setSelected(undefined);
  try{setSelected(localStorage.getItem(key)??undefined);}catch(e){setError('Saved artifact selection unavailable: '+String(e));}
  void controls.list(taskId,sessionId).then(v=>{if(live)setCatalog({stamp,rows:v.artifacts});},e=>{if(live)setError(String(e));});
  return()=>{live=false;};
 },[controls,taskId,sessionId,attempt,key,stamp]);
 const artifact=rows?.find(row=>row.attachment_id===selected);
 const files=useMemo<Files|undefined>(()=>artifact?{
  list:async sessionId=>{const current=await controls.list(artifact.task_id);const row=current.artifacts.find(r=>r.attachment_id===artifact.attachment_id);if(!row||row.session_id!==sessionId||row.sha256!==artifact.sha256)throw Error('Artifact reference unavailable or changed; original withheld');return {session_id:sessionId,files:[row],max_bytes:current.max_bytes};},
  read:(_session,id)=>controls.read(artifact.task_id,id),
  preview:(_session,id,page)=>controls.preview(artifact.task_id,id,page),
 }:undefined,[controls,artifact]);
 const choose=(id?:string)=>{setSelected(id);try{if(id)localStorage.setItem(key,id);else localStorage.removeItem(key);}catch(e){setError('Artifact selection was not saved: '+String(e));}};
 return <section aria-label="Verified task artifacts"><h3>Verified task artifacts</h3><p>Owner-verified references only. Files stay in their originating workspace; reopening checks current access and the saved digest. No document copy or model-context admission.</p>
  <button type="button" onClick={()=>setAttempt(n=>n+1)}>Refresh artifact references</button>
  {error&&<p role="alert">{error}</p>}{!rows&&!error&&<p role="status">Loading artifact references…</p>}{rows?.length===0&&<p>No owner-verified file receipts for this selection.</p>}
  {rows?.map(row=><article key={row.attachment_id}><button type="button" onClick={()=>choose(row.attachment_id)}>{row.name}</button><p>{row.task_title} · {row.sha256}</p>{!row.readable&&<p>{row.unavailable_reason}</p>}</article>)}
  {rows&&selected&&!artifact&&<p role="alert">Saved artifact reference {selected} is unavailable. Its content is withheld. <button onClick={()=>choose()}>Close missing reference</button></p>}
  {artifact&&files&&<SessionFiles key={selected+':'+attempt} files={files} sessionId={artifact.session_id} initialAttachmentId={artifact.attachment_id} onClose={()=>choose()}/>}
 </section>;
}
