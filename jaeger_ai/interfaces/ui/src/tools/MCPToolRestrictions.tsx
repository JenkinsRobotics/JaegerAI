import {useState} from 'react';
import type {MCPConfigurationIntent,MCPToolPolicy} from '../api/source';
/** Typed draft retains its original revision across inventory refreshes. */
export function MCPToolRestrictions({name,policy,revision,disabled,onReview}:{name:string;policy:MCPToolPolicy;revision:string;disabled:boolean;onReview:(intent:MCPConfigurationIntent)=>void}){
 const [draft,setDraft]=useState<{base:string;include:string;exclude:string;gated:boolean}>(),[error,setError]=useState('');
 function review(){if(!draft)return;try{
  const include=JSON.parse(draft.include),exclude=JSON.parse(draft.exclude);
  if(![include,exclude].every(v=>Array.isArray(v)&&v.length<=100&&v.every(s=>typeof s==='string'&&s.trim()===s&&s.length>0&&s.length<=200)))throw Error('Use bounded JSON arrays of tool names or glob patterns.');
  onReview({action:'policy',operation_id:crypto.randomUUID(),name,expected_revision:draft.base,policy:{include,exclude,gated:draft.gated}});setError('');
 }catch(e){setError(String(e));}}
 return <section aria-label={'Tool restrictions for '+name}>
  <p>Include {JSON.stringify(policy.include)} · Exclude {JSON.stringify(policy.exclude)} · {policy.gated?'Gated':'Not gated'}. Availability not probed.</p>
  <button disabled={disabled} onClick={()=>{if(draft)return;setDraft({base:revision,include:JSON.stringify(policy.include),exclude:JSON.stringify(policy.exclude),gated:policy.gated});}}>Edit next-startup tool restrictions for {name}</button>
  {draft&&<><p>Restriction-only edits. Keep existing exclusions and gating; include may narrow existing patterns. Max-tool limits, read-only declarations, credentials and grants are unchanged. Existing connections are unaffected.</p>
   {draft.base!==revision&&<p role="status">Configuration changed since this draft began. Draft retained; saving rejects until you explicitly discard it and review the current policy.</p>}
   <label>Include tool names or globs (JSON)<textarea aria-label={'Include tools for '+name} disabled={disabled} value={draft.include} onChange={e=>setDraft({...draft,include:e.target.value})}/></label>
   <label>Exclude tool names or globs (JSON)<textarea aria-label={'Exclude tools for '+name} disabled={disabled} value={draft.exclude} onChange={e=>setDraft({...draft,exclude:e.target.value})}/></label>
   <label><input type="checkbox" aria-label={'Gate tools for '+name} checked={draft.gated} disabled={disabled||policy.gated} onChange={e=>setDraft({...draft,gated:e.target.checked})}/>Require turn-scoped toolset visibility</label>
   <button disabled={disabled||draft.base!==revision} onClick={review}>Review tool restrictions for {name}</button><button disabled={disabled} onClick={()=>setDraft(undefined)}>Discard tool policy draft</button>
  </>}{error&&<p role="alert">{error}</p>}
 </section>;
}
