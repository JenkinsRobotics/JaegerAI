import {Dialog} from '@aether/ui';
import {useEffect,useRef,useState} from 'react';
import type {MCPResources as Controls,ResourceCatalog,ResourceSnapshot,ResourceReceipt} from '../api/source';
type Action='list'|'read'|'import';
interface Intent {operation_id:string;action:Action}
export function MCPResources({controls,server,onClose}:{controls:Controls;server:{id:string;name:string};onClose:()=>void}){
 const prefix='jaeger.ui.mcp-resource.operation.v1.'+server.id+'.';
 const [catalog,setCatalog]=useState<ResourceCatalog>(),[snapshot,setSnapshot]=useState<ResourceSnapshot>(),[pending,setPending]=useState<Intent>(),[busy,setBusy]=useState(false),[error,setError]=useState<string>(),[notice,setNotice]=useState<string>(),[confirmImport,setConfirmImport]=useState(false);
 const lock=useRef(false),live=useRef(true);
 const saved=()=>Object.keys(localStorage).filter(k=>k.startsWith(prefix)).map(k=>{const value=JSON.parse(localStorage.getItem(k)!);if(typeof value.operation_id!=='string'||!['list','read','import'].includes(value.action))throw Error('Invalid resource operation journal; original retained');return value as Intent;});
 useEffect(()=>{live.current=true;try{setPending(saved()[0]);}catch(e){setError(String(e));}return()=>{live.current=false;};},[prefix]);
 const finish=async(receipt:ResourceReceipt,intent:Intent)=>{
  if(receipt.operation_id!==intent.operation_id)throw Error('Resource receipt identity mismatch');
  if(!receipt.ok){localStorage.removeItem(prefix+intent.operation_id);if(live.current)setPending(saved()[0]);throw Error(receipt.error??'Resource action rejected');}
  if(intent.action==='list'){if(receipt.result?.catalog?.server_id!==server.id)throw Error('Catalog identity mismatch');if(live.current)setCatalog(receipt.result.catalog);}
  if(intent.action==='read'){
   const descriptor=receipt.result?.snapshot;if(!descriptor||descriptor.server_id!==server.id)throw Error('Snapshot identity missing');
   // Local cache GET only. A recovered receipt never refetches the provider.
   try{const value=await controls.snapshot(server.id,descriptor.id);if(value.id!==descriptor.id||value.server_id!==server.id||value.digest!==descriptor.digest)throw Error('Snapshot identity/digest mismatch');if(live.current)setSnapshot(value);}
   catch(e){if(live.current)setNotice(`Resource read acknowledged, but volatile preview is unavailable: ${String(e)}. No automatic provider read occurred.`);}
  }
  if(intent.action==='import'){if(!receipt.result?.document?.id)throw Error('Managed document receipt missing');if(live.current){setNotice(`Saved managed Library document ${receipt.result.document.id}, revision ${receipt.result.document.revision}. No bot context or grants changed.`);setConfirmImport(false);}}
  localStorage.removeItem(prefix+intent.operation_id);if(live.current)setPending(saved()[0]);
 };
 const run=async(action:Action,body:Record<string,unknown>)=>{if(lock.current||pending)return;lock.current=true;setBusy(true);setError(undefined);setNotice(undefined);const intent={operation_id:crypto.randomUUID(),action};let dispatched=false;
  try{const existing=saved()[0];if(existing){setPending(existing);throw Error('Existing resource action needs reconciliation');}localStorage.setItem(prefix+intent.operation_id,JSON.stringify(intent));setPending(intent);dispatched=true;const receipt=await controls.mutate(server.id,action,{operation_id:intent.operation_id,...body});await finish(receipt,intent);}
  catch(e){if(live.current)setError(`${String(e)}${dispatched?'. Check original resource action; no automatic retry.':'. Nothing submitted.'}`);}finally{lock.current=false;if(live.current)setBusy(false);}
 };
 const check=async()=>{if(!pending||lock.current)return;lock.current=true;setBusy(true);setError(undefined);try{const {receipt}=await controls.operation(pending.operation_id);if(!receipt)throw Error('Original outcome remains unknown');await finish(receipt,pending);}catch(e){if(live.current)setError(String(e));}finally{lock.current=false;if(live.current)setBusy(false);}};
 return <Dialog open title={`Resources · ${server.name}`} onClose={()=>{if(!busy)onClose();}} actions={<button type="button" disabled={busy} onClick={onClose}>Close resources</button>}>
  <p>Explicit reads contact this already connected server with its current access. Only listed opaque resource handles are accepted. No connection, credential, tool grant or bot context is created. Imported text is reference data; server declarations are not verified publisher identity.</p>
  {error&&<p role="alert">{error}</p>}{notice&&<p role="status">{notice}</p>}{pending?<button type="button" disabled={busy} onClick={()=>void check()}>Check resource operation</button>:<button type="button" disabled={busy} onClick={()=>void run('list',{page:null})}>Read resource catalog from server</button>}
  {catalog?.truncated&&<p>Server page exceeded the catalog limit; only a bounded subset is shown.</p>}
  {catalog?.resources.map(resource=><article className="jg-card" key={resource.id}><strong>{resource.title}</strong><p>{resource.description}</p><small>{resource.mime}</small><button type="button" disabled={busy||Boolean(pending)} onClick={()=>{setSnapshot(undefined);setConfirmImport(false);void run('read',{resource_id:resource.id});}}>Read {resource.title}</button></article>)}
  {catalog?.next_page&&<button type="button" disabled={busy||Boolean(pending)} onClick={()=>void run('list',{page:catalog.next_page})}>Read next resource page</button>}
  {snapshot&&<section aria-label="Resource preview"><h3>{snapshot.title}</h3><p>Staged text SHA256 {snapshot.digest}. {snapshot.redacted?'Credential-like content was redacted.':'No configured-secret/pattern redaction was applied.'} Preview is volatile; import explicitly to keep a managed copy.</p><pre style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere',maxHeight:'50vh',overflow:'auto'}}>{snapshot.text}</pre><button type="button" disabled={busy||Boolean(pending)} onClick={()=>setConfirmImport(true)}>Import reviewed text to Library</button></section>}
  {confirmImport&&snapshot&&<div role="group" aria-label="Confirm resource import"><p>Save this reviewed text as a new managed Library document? It is not automatically attached, executed or assigned to any bot.</p><button type="button" disabled={busy||Boolean(pending)} onClick={()=>void run('import',{snapshot_id:snapshot.id,expected_digest:snapshot.digest})}>Confirm resource import</button><button type="button" disabled={busy} onClick={()=>setConfirmImport(false)}>Cancel resource import</button></div>}
 </Dialog>;
}
