import type {UploadedAttachment} from './source';
export interface UploadProgress {received:number;total:number;state:'staging'|'complete'}
export interface UploadOptions {signal?:AbortSignal;onProgress?:(value:UploadProgress)=>void}
interface Descriptor {name:string;mime:string;size:number;sha256:string}
interface Intent extends Descriptor {version:1;session_id:string;operation_id:string;upload_id?:string}
interface State extends Descriptor {session_id:string;operation_id:string;upload_id:string;state:'pending'|'complete';received_bytes:number;chunk_bytes:number;attachment:UploadedAttachment|null}
type Json=<T>(path:string,body?:unknown,signal?:AbortSignal)=>Promise<T>;
const hex=(bytes:ArrayBuffer)=>[...new Uint8Array(bytes)].map(x=>x.toString(16).padStart(2,'0')).join('');
const digest=async(bytes:Uint8Array)=>hex(await crypto.subtle.digest('SHA-256',new Uint8Array(bytes).buffer));
const encode=(bytes:Uint8Array)=>{let binary='';for(let i=0;i<bytes.length;i+=0x8000)binary+=String.fromCharCode(...bytes.subarray(i,i+0x8000));return btoa(binary);};
const checkAbort=(signal?:AbortSignal)=>{if(signal?.aborted)throw new DOMException('Upload paused before dispatch; retained bytes are not deleted','AbortError');};
/** Only immutable byte staging resumes. This never admits or retries a model request. */
export async function uploadChunks(json:Json,sessionId:string,bytes:Uint8Array,body:{name:string;mime:string},operationId:string,options:UploadOptions={}):Promise<UploadedAttachment>{
 checkAbort(options.signal);
 const descriptor:Descriptor={name:body.name,mime:body.mime||'application/octet-stream',size:bytes.length,sha256:await digest(bytes)};
 checkAbort(options.signal);
 const key='jaeger.ui.upload.v1.'+await digest(new TextEncoder().encode(JSON.stringify([sessionId,descriptor])));
 const base=`/v1/sessions/${encodeURIComponent(sessionId)}/uploads`;
 let intent:Intent;let fresh=false;
 const saved=localStorage.getItem(key);
 if(saved){intent=JSON.parse(saved);if(intent.version!==1||intent.session_id!==sessionId||typeof intent.operation_id!=='string'||!intent.operation_id||Object.entries(descriptor).some(([k,v])=>intent[k as keyof Intent]!==v))throw Error('Original upload intent invalid; preserved without submission');}
 else{intent={version:1,session_id:sessionId,operation_id:operationId,...descriptor};localStorage.setItem(key,JSON.stringify(intent));fresh=true;}
 const progress=(value:UploadProgress)=>{try{options.onProgress?.(value);}catch{/* observation cannot change staging outcome */}};
 const validate=(state:State)=>{
  if(!state||state.session_id!==sessionId||state.operation_id!==intent.operation_id||!/^[a-f0-9]{32}$/.test(state.upload_id)||(intent.upload_id!==undefined&&intent.upload_id!==state.upload_id)||Object.entries(descriptor).some(([k,v])=>state[k as keyof State]!==v)||!['pending','complete'].includes(state.state)||!Number.isSafeInteger(state.received_bytes)||state.received_bytes<0||state.received_bytes>bytes.length||!Number.isSafeInteger(state.chunk_bytes)||state.chunk_bytes<1||state.chunk_bytes>1024*1024||(state.received_bytes!==bytes.length&&state.received_bytes%state.chunk_bytes!==0))throw Error('Upload identity/progress mismatch; original intent retained');
  if(!intent.upload_id){intent={...intent,upload_id:state.upload_id};localStorage.setItem(key,JSON.stringify(intent));}
  return state;
 };
 const read=async()=>validate(await json<State>(base+'?operation_id='+encodeURIComponent(intent.operation_id),undefined,options.signal));
 let state:State;
 if(fresh){try{state=validate(await json<State>(base,{operation_id:intent.operation_id,...descriptor},options.signal));}catch(error){checkAbort(options.signal);try{state=await read();}catch{throw error;}}}
 else {
  try{state=await read();}
  catch(error){
   // Explicit file staging invocation can safely recreate the same inert,
   // transactionally idempotent descriptor after a pre-commit process failure.
   // This is never a turn/tool/approval retry. Preserve all partial byte files.
   if((error as {status?:number}).status!==404||intent.upload_id)throw error;
   checkAbort(options.signal);state=validate(await json<State>(base,{operation_id:intent.operation_id,...descriptor},options.signal));
  }
 }
 while(state.state!=='complete'&&state.received_bytes<bytes.length){
  checkAbort(options.signal);progress({received:state.received_bytes,total:bytes.length,state:'staging'});
  checkAbort(options.signal);
  const offset=state.received_bytes,part=bytes.subarray(offset,offset+state.chunk_bytes);
  try{state=validate(await json<State>(base+'/chunk',{operation_id:intent.operation_id,upload_id:state.upload_id,offset,data_base64:encode(part)},options.signal));}
  catch(error){checkAbort(options.signal);const observed=await read();if(observed.received_bytes<offset+part.length)throw error;state=observed;}
  if(state.received_bytes<offset+part.length)throw Error('Chunk outcome unknown; retained original upload can be checked without replaying a turn');
 }
 checkAbort(options.signal);
 if(state.state!=='complete'){
  progress({received:state.received_bytes,total:bytes.length,state:'staging'});
  try{state=validate(await json<State>(base+'/finish',{operation_id:intent.operation_id,upload_id:state.upload_id},options.signal));}
  catch(error){checkAbort(options.signal);const observed=await read();if(observed.state!=='complete')throw error;state=observed;}
 }
 const attachment=state.attachment;
 if(state.state!=='complete'||!attachment||typeof attachment.attachment_id!=='string'||!attachment.attachment_id||attachment.sha256!==descriptor.sha256||attachment.size!==descriptor.size||attachment.mime!==descriptor.mime)throw Error('Final attachment not confirmed; original upload retained, no turn admitted');
 progress({received:bytes.length,total:bytes.length,state:'complete'});
 return attachment; // Keep descriptor-only recovery pointer; never stores file bytes or credentials.
}
