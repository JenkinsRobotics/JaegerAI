import {readBase64} from '../chat/composer';
import {useEffect,useRef,useState} from 'react';
import type {JaegerSource,PluginPackages,InstalledPlugin,PackagePlan,PackageReview,PackageCommand,ControlResult} from '../api/source';
type Snapshot=Awaited<ReturnType<PluginPackages['list']>>;
type Review={request:PackageReview;plan:PackagePlan};
type Intent={command:PackageCommand;package:string};
export function PluginPackagesPanel(props:{source:JaegerSource;sessionId?:string;controls:PluginPackages;rows:InstalledPlugin[];changed:()=>void}){
 const [snapshot,setSnapshot]=useState<Snapshot>(),[error,setError]=useState<string>(),[attempt,setAttempt]=useState(0),[before,setBefore]=useState<string>();
 useEffect(()=>{let live=true;void props.controls.list(before).then(value=>{if(live)setSnapshot(old=>before&&old&&old.environment===value.environment?{...value,operations:[...old.operations,...value.operations.filter(row=>!old.operations.some(prior=>prior.operation_id===row.operation_id))]}:value);},e=>{if(live)setError(String(e));});return()=>{live=false;};},[props.controls,attempt,before]);
 return <section aria-label="Plugin package files"><h3>Package files and recovery</h3><button type="button" onClick={()=>{setBefore(undefined);setAttempt(n=>n+1);}}>Refresh package receipts</button><p>Local portable pure Python wheels only. Existing dependencies must already be satisfied. No indexes, downloads, builds, dependency changes or plugin activation. Core, shared namespaces and mixed script packages are protected. Package changes disable future startup. In-use packages cannot be changed until a separately coordinated restart retires their code; this panel never restarts a process.</p>{error&&<p role="alert">{error}</p>}{snapshot&&<PackageEditor key={snapshot.environment} {...props} snapshot={snapshot} refresh={()=>{setBefore(undefined);setAttempt(n=>n+1);props.changed();}}/>}{snapshot?.next_before&&<button type="button" onClick={()=>setBefore(snapshot.next_before!)}>Load older package receipts</button>}</section>;
}
function PackageEditor({source,sessionId,controls,rows,snapshot,refresh}:{source:JaegerSource;sessionId?:string;controls:PluginPackages;rows:InstalledPlugin[];snapshot:Snapshot;refresh:()=>void}){
 const key='jaeger.ui.plugin-package.v1.'+snapshot.environment,uploadKey=key+'.upload';
 const saved=<T,>(name:string):T|undefined=>{const raw=localStorage.getItem(name);return raw?JSON.parse(raw):undefined;};
 const [pending,setPending]=useState<Intent|undefined>(()=>{try{return saved<Intent>(key);}catch{return {command:{operation_id:'invalid-journal',action:'remove',package:'unknown',expected_fingerprint:'unknown',expected_policy_revision:-1},package:'unknown'};}});
 const [upload,setUpload]=useState<{session_id:string;upload_key:string}|undefined>(()=>{try{return saved(uploadKey);}catch{return {session_id:'unknown',upload_key:'invalid-journal'};}}),[review,setReview]=useState<Review>(),[file,setFile]=useState<File>(),[error,setError]=useState<string>(),[notice,setNotice]=useState<string>(),[busy,setBusy]=useState(false);
 const lock=useRef(false);
 const run=async(work:()=>Promise<void>)=>{if(lock.current)return;lock.current=true;setBusy(true);setError(undefined);try{await work();}catch(e){setError(String(e)+'. No automatic package retry or activation.');}finally{lock.current=false;setBusy(false);}};
 const preview=async(request:PackageReview)=>{const plan=await controls.preview(request);if(plan.activation_performed!==false)throw Error('Unexpected review contract');setReview({request,plan});};
 const finish=(receipt:ControlResult,intent:Intent)=>{
  if(receipt.operation_id!==intent.command.operation_id)throw Error('Package receipt identity mismatch');
  const result=receipt.result as {domain?:string;package?:string;activation_performed?:boolean;state?:string};
  if(receipt.ok&&(result?.domain!=='plugin_package'||result.package!==intent.package||result.activation_performed!==false))throw Error('Package receipt target mismatch');
  localStorage.removeItem(key);setPending(undefined);setReview(undefined);setNotice(receipt.ok?`Verified package files: ${result.state}. Future startup disabled. No plugin activation or hot unload.`:receipt.error??'Package operation rejected');refresh();
 };
 const check=()=>run(async()=>{if(!pending)return;const value=await controls.operation(pending.command.operation_id);if(!value.receipt){refresh();throw Error(value.pending?.error??'Original outcome unresolved; no replay');}finish(value.receipt,pending);});
 const checkRecorded=(operation:Snapshot['operations'][number])=>run(async()=>{
  const value=await controls.operation(operation.operation_id);if(!value.receipt)throw Error(value.pending?.error??'Original outcome remains unknown');
  if(value.receipt.operation_id!==operation.operation_id)throw Error('Recorded receipt identity mismatch');
  if(pending?.command.operation_id===operation.operation_id)finish(value.receipt,pending);
  else setNotice(value.receipt.ok?'Historical package state receipt acknowledged; current state may differ after later changes.':value.receipt.error??'Historical package rejection acknowledged');
 });
 const stage=()=>run(async()=>{
  if(pending||upload||!sessionId||!file||!source.uploadAttachment)return;
  if(!file.name.endsWith('.whl')||file.size>25*1024*1024)throw Error('Choose a local .whl up to25MB');
  if(localStorage.getItem(uploadKey))throw Error('An existing upload needs receipt inspection; reopen this panel');
  const intent={session_id:sessionId,upload_key:crypto.randomUUID()};localStorage.setItem(uploadKey,JSON.stringify(intent));setUpload(intent);
  const encoded=await readBase64(file);
  const uploaded=await source.uploadAttachment(sessionId,{name:file.name,mime:'application/octet-stream',data_base64:encoded},intent.upload_key);
  await preview({action:'install',session_id:sessionId,attachment_id:uploaded.attachment_id});localStorage.removeItem(uploadKey);setUpload(undefined);
 });
 const recoverUpload=()=>run(async()=>{if(!upload)return;await preview({action:'install',session_id:upload.session_id,upload_key:upload.upload_key});localStorage.removeItem(uploadKey);setUpload(undefined);});
 const compensating=!!pending&&review?.request.action==='restore'&&review.request.restore_from===pending.command.operation_id;
 const commit=()=>run(async()=>{
  if(!review||pending&&!compensating)return;const existing=localStorage.getItem(key);if(existing&&(!compensating||JSON.parse(existing).command.operation_id!==pending?.command.operation_id))throw Error('Existing package command changed; reopen for receipt reconciliation');
  const base={operation_id:crypto.randomUUID(),expected_fingerprint:review.plan.expected_fingerprint,expected_policy_revision:review.plan.policy_revision};
  let command:PackageCommand;
  if(review.request.action==='install'){
   if(!review.plan.sha256||!review.plan.attachment_id)throw Error('Reviewed wheel identity missing');
   command={...base,action:'install',session_id:review.request.session_id,attachment_id:review.plan.attachment_id,sha256:review.plan.sha256};
  }else if(review.request.action==='remove')command={...base,action:'remove',package:review.plan.package};
  else command={...base,action:'restore',restore_from:review.request.restore_from};
  if(compensating&&pending){const originalKey=key+'.unknown.'+pending.command.operation_id;const original=localStorage.getItem(originalKey);if(original&&original!==JSON.stringify(pending))throw Error('Original unknown journal differs; no command sent');localStorage.setItem(originalKey,JSON.stringify(pending));}
  const intent={command,package:review.plan.package};localStorage.setItem(key,JSON.stringify(intent));setPending(intent);finish(await controls.change(command),intent);
 });
 const packages=[...new Set(rows.filter(row=>row.distribution_state!=='removed').map(row=>row.package))];
 return <><p>Reviews use staged file bytes and package receipts; they never submit a chat turn. Metadata/digest is not verified publisher identity.</p>{error&&<p role="alert">{error}</p>}{notice&&<p role="status">{notice}</p>}{pending?<button type="button" disabled={busy} onClick={()=>void check()}>Check package operation</button>:<>
 {upload?<button type="button" disabled={busy} onClick={()=>void recoverUpload()}>Check uploaded wheel</button>:<><label>Local plugin wheel<input aria-label="Local plugin wheel" type="file" accept=".whl" disabled={busy} onChange={e=>setFile(e.target.files?.[0])}/></label><button type="button" disabled={busy||!file||!sessionId||!source.uploadAttachment} onClick={()=>void stage()}>Review local wheel</button>{!sessionId&&<p>Open an existing bot conversation to use its existing file-staging owner.</p>}</>}
 {packages.map(name=><button key={name} type="button" disabled={busy} onClick={()=>void run(()=>preview({action:'remove',package:name}))}>Review recoverable removal of {name}</button>)}
 </>}{review&&(!pending||compensating)&&<div role="group" aria-label="Review package change"><h4>{review.request.action==='install'&&review.plan.installed_version?'Update':review.request.action} · {review.plan.package}</h4><p>Installed: {review.plan.installed_version??'absent'} · requested: {review.plan.version??'removed'} · {review.plan.provenance}</p>{review.plan.sha256&&<code>{review.plan.sha256}</code>}<p>Startup will be disabled. Recovery artifacts retained. A restart is required to retire previously loaded code; nothing will restart here.</p><ul>{review.plan.entries.map(entry=><li key={entry.slot_id}>{entry.name} · {entry.value}</li>)}</ul><button type="button" disabled={busy} onClick={()=>void commit()}>Confirm package change</button><button type="button" disabled={busy} onClick={()=>setReview(undefined)}>Cancel package review</button></div>}
 <h4>Retained package operations</h4>{snapshot.operations.length===0&&<p>No package transactions recorded for this environment.</p>}{snapshot.operations.map(operation=><article key={operation.operation_id}><p>{operation.package} · {operation.action} · {operation.version??'removal'} · recorded phase: {operation.phase}</p><button type="button" disabled={busy} onClick={()=>void checkRecorded(operation)}>Check recorded package outcome</button>{operation.backup_available&&<button type="button" disabled={busy||!!pending&&pending.command.operation_id!==operation.operation_id} onClick={()=>void run(()=>preview({action:'restore',restore_from:operation.operation_id}))}>Review preserved revision of {operation.package}</button>}</article>)}</>;
}
