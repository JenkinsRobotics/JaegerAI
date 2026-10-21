import {useEffect,useState} from 'react';
import type {MCPConfiguration,MCPConfigurationIntent,MCPConfigurationReceipt} from '../api/source';
const journal='jaeger.ui.mcp.configuration.v1';
function retained(){try{return localStorage.getItem(journal)||'';}catch{return '';}}
export function MCPSetup({controls}:{controls:MCPConfiguration}){
  const [snapshot,setSnapshot]=useState<Awaited<ReturnType<MCPConfiguration['read']>>>();
  const [name,setName]=useState(''),[transport,setTransport]=useState('http'),[target,setTarget]=useState(''),[args,setArgs]=useState('');
  const [review,setReview]=useState<MCPConfigurationIntent>(),[pending,setPending]=useState<string>(retained);
  const [result,setResult]=useState<MCPConfigurationReceipt>(),[error,setError]=useState(''),[busy,setBusy]=useState(false);
  async function refresh(){try{setSnapshot(await controls.read());setError('');}catch{setError('Local definitions unavailable. No connection attempted.');}}
  useEffect(()=>{void refresh();},[controls]);
  function accept(receipt:MCPConfigurationReceipt,id:string){
    if(receipt.operation_id!==id)throw Error('Original operation identity mismatch');
    setResult(receipt);
    if(receipt.outcome!=='unknown'){localStorage.removeItem(journal);setPending('');void refresh();}
  }
  async function inspect(){setBusy(true);try{accept(await controls.operation(pending),pending);}catch{setError('Original outcome unavailable. Retain pending intent; do not retry.');}finally{setBusy(false);}}
  async function save(){if(!review||pending)return;setBusy(true);setError('');
    try{localStorage.setItem(journal,review.operation_id);}catch{setError('Could not preserve the operation journal. Nothing was sent.');setBusy(false);return;}
    setPending(review.operation_id);const body=review;setReview(undefined);
    try{accept(await controls.change(body),body.operation_id);}catch{setError('Outcome unknown. Inspect the original operation; do not resubmit.');}finally{setBusy(false);}}
  function stage(){if(!snapshot)return;try{
    const definition=transport==='http'?{name,url:target}:{name,command:target,args:JSON.parse(args||'[]') as string[]};
    setReview({operation_id:crypto.randomUUID(),action:'stage',expected_revision:snapshot.config_revision,definition});setError('');
  }catch{setError('Arguments must be a JSON array of strings.');}}
  return <section aria-label="MCP setup and startup"><h3>MCP setup and startup</h3>
    <p>Local definitions only. New servers remain disabled. No credential access, connection or tool grants occur here. Startup changes apply at the next MCP initialization; current connections remain unchanged.</p>
    {error&&<p role="alert">{error}</p>}{result&&<p role="status">Configuration {result.outcome}. {result.error}</p>}
    {pending&&<p>Pending original operation. <button disabled={busy} onClick={()=>void inspect()}>Inspect original configuration result</button></p>}
    <button disabled={busy} onClick={()=>void refresh()}>Read local MCP definitions</button>
    {snapshot?.servers.map(row=><article key={row.name}><strong>{row.name}</strong><p>{row.transport} · {row.status} · startup {row.startup_enabled?'enabled':'disabled'}</p><button disabled={busy||!!pending} onClick={()=>setReview({action:'startup',operation_id:crypto.randomUUID(),expected_revision:snapshot.config_revision,name:row.name,enabled:!row.startup_enabled})}>Review {row.startup_enabled?'disable':'enable'} at next startup</button></article>)}
    <fieldset disabled={!snapshot||busy||!!pending}><legend>Add disabled MCP definition</legend>
      <label>Server name<input value={name} maxLength={64} onChange={e=>setName(e.target.value)}/></label>
      <label>Transport<select value={transport} onChange={e=>setTransport(e.target.value)}><option value="http">HTTP</option><option value="stdio">Local command</option></select></label>
      <label>{transport==='http'?'Server URL':'Executable'}<input value={target} maxLength={4096} onChange={e=>setTarget(e.target.value)}/></label>
      {transport==='stdio'&&<label>Arguments (JSON array, no secrets)<textarea value={args} onChange={e=>setArgs(e.target.value)}/></label>}
      <button onClick={stage}>Review disabled definition</button>
    </fieldset>
    {review&&<div role="dialog" aria-label="Review MCP configuration"><p>{review.action==='stage'?'Save a new disabled definition. No connection will start.':`Set ${review.name} startup to ${review.enabled?'enabled: the configured command or remote server may run/connect on the next initialization':'disabled'}. Existing connection is unchanged.`}</p>
      {review.action==='stage'&&<pre>{JSON.stringify(review.definition,null,2)}</pre>}
      <button disabled={busy||!!pending} onClick={()=>void save()}>Confirm configuration</button><button onClick={()=>setReview(undefined)}>Cancel</button></div>}
  </section>;
}
