import{useEffect,useState}from'react';
import type{JaegerSource,UpdatePlan}from'../api/source';
import{nativeBridge}from'../platform/native';
const CHANNEL='jaeger.ui.update-review-channel.v1';
/** A real read-only installer plan. Never calls the vendored WebUI self-updater. */
export function UpdatePlanPanel({source}:{source:JaegerSource}){
 const [channel,setChannel]=useState<'stable'|'latest'>(()=>{try{return localStorage.getItem(CHANNEL)==='latest'?'latest':'stable';}catch{return'stable';}});
 const [result,setResult]=useState<{channel:string;plan:UpdatePlan}>(),[error,setError]=useState<string>(),[attempt,setAttempt]=useState(0);
 const [native,setNative]=useState<{version?:string;build?:string;dev_build?:boolean}>();
 useEffect(()=>{let live=true;setError(undefined);void source.updatePlan?.(channel).then(plan=>{if(!live)return;if(plan.component!=='jaeger-update-plan'||plan.channel!==channel)throw Error('Update plan identity mismatch');setResult({channel,plan});}).catch(e=>{if(live){setResult(undefined);setError(String(e));}});return()=>{live=false;};},[source,channel,attempt]);
 useEffect(()=>{let live=true;const bridge=nativeBridge();if(bridge)void bridge.post('app.info').then(value=>{if(live&&value&&typeof value==='object'){const row=value as Record<string,unknown>;const label=(v:unknown)=>typeof v==='string'&&/^[0-9A-Za-z+._-]{1,100}$/.test(v)?v:undefined;setNative({version:label(row.version),build:label(row.build),dev_build:row.dev_build===true});}},()=>{});return()=>{live=false;};},[]);
 const plan=result?.channel===channel?result.plan:undefined;
 return <section aria-label="Update and recovery plan"><h3>Update and recovery</h3>
  {native&&<p>Native bundle reports version {native.version||'unknown'}, build {native.build||'unknown'}{native.dev_build?' (development build)':''}. This is not a signature verification.</p>}
  <label>Reviewed command channel<select aria-label="Reviewed update channel" value={channel} onChange={e=>{const value=e.target.value==='latest'?'latest':'stable';setChannel(value);try{localStorage.setItem(CHANNEL,value);}catch(err){setError('Review preference not saved: '+String(err));}}}><option value="stable">Stable release</option><option value="latest">Latest development branch</option></select></label><p>Device review preference only; it selects the existing CLI plan below. It does not enable background updates or change installed code.</p>
  <button type="button" onClick={()=>{setResult(undefined);setAttempt(n=>n+1);}}>Refresh local update plan</button>
  {error&&<p role="alert">{error}</p>}{!plan&&!error&&<p role="status">Reading local installer state…</p>}
  {plan&&<><p>Gateway reports package {plan.reported_package_version} · {plan.install_method}. Remote release: {plan.release_state}; signature: {plan.signature_state}.</p><p>Checkout revision {plan.source_checkout_revision??'unknown'} · local changes {plan.source_checkout_dirty===null?'unknown':plan.source_checkout_dirty?'present':'none observed'}. {plan.identity_scope.replaceAll('_',' ')}.</p><p>Active instance schema {plan.active_instance_schema??'unknown'} / installed {plan.installed_schema}: {plan.migration_state.replaceAll('_',' ')}.</p><p>Restart policy: {plan.restart_policy.replaceAll('_',' ')}. {plan.work.active_requests} active requests; {plan.work.unknown_requests} unknown; {plan.work.nonterminal_tasks} nonterminal background tasks.</p>{plan.restart_blockers.length>0&&<ul>{plan.restart_blockers.map(reason=><li key={reason}>{reason.replaceAll('_',' ')}</li>)}</ul>}
  <details><summary>Existing operator commands (not executed here)</summary><p>Read-only local check: <code>{plan.check_command.join(' ')}</code></p><p>Update requires separate operator review: <code>{plan.manual_update_command.join(' ')}</code></p><p>Product-backup rollback {plan.rollback.available?'is present':'is not present'}; applicability still requires review. <code>{plan.rollback.command.join(' ')}</code></p></details>{plan.limits.map(limit=><p key={limit}>{limit}</p>)}</>}
 </section>;
}
