import {it,expect,vi,afterEach} from 'vitest';import {webcrypto} from 'node:crypto';import {uploadChunks} from './chunkUpload';
vi.stubGlobal('crypto',webcrypto);afterEach(()=>localStorage.clear());
function fixture(){
 const bytes=new Uint8Array(270000).fill(65);let state:any;const chunks:number[]=[];let lose=true;
 const json=vi.fn(async(path:string,body?:any)=>{
  if(!body)return structuredClone(state);
  if(path.endsWith('/chunk')){chunks.push(body.offset);state.received_bytes=Math.min(state.size,body.offset+state.chunk_bytes);if(lose){lose=false;throw Error('ACK lost after retained chunk');}return structuredClone(state);}
  if(path.endsWith('/finish')){state.state='complete';state.attachment={attachment_id:'owned-attachment',name:state.name,mime:state.mime,size:state.size,sha256:state.sha256};return structuredClone(state);}
  state={...body,session_id:'owned',upload_id:'a'.repeat(32),state:'pending',received_bytes:0,chunk_bytes:262144,attachment:null};return structuredClone(state);
 });
 return {bytes,json:json as any,chunks,state:()=>state};
}
it('reads after lost chunk ACK, resumes only next bytes, and never stores bytes or posts a turn',async()=>{
 const f=fixture(),progress=vi.fn();const result=await uploadChunks(f.json,'owned',f.bytes,{name:'fixture.bin',mime:'application/octet-stream',data_base64:'PRIVATE-BYTES'} as any,'original-operation',{onProgress:progress});
 expect(result.attachment_id).toBe('owned-attachment');expect(f.chunks).toEqual([0,262144]);expect(progress).toHaveBeenLastCalledWith({received:270000,total:270000,state:'complete'});
 expect(JSON.stringify(localStorage)).not.toContain('PRIVATE-BYTES');expect(JSON.stringify(localStorage)).not.toContain('data_base64');
 const count=f.json.mock.calls.length;
 await uploadChunks(f.json,'owned',f.bytes,{name:'fixture.bin',mime:'application/octet-stream'},'different-turn-upload-key');
 expect(f.json.mock.calls.slice(count)).toHaveLength(1);expect(f.json.mock.calls[count][0]).toContain('?operation_id=original-operation');expect(f.chunks).toEqual([0,262144]);
 expect(f.json.mock.calls.some(([path]:[string])=>path.endsWith('/turns'))).toBe(false);
});
it('preserves incomplete journal on interruption and resumes through read without duplicate start/chunk',async()=>{
 const f=fixture(),controller=new AbortController();
 await expect(uploadChunks(f.json,'owned',f.bytes,{name:'fixture.bin',mime:'application/octet-stream'},'original-operation',{signal:controller.signal,onProgress:value=>{if(value.received===262144)controller.abort();}})).rejects.toThrow('Upload paused');
 expect(f.chunks).toEqual([0]);
 const count=f.json.mock.calls.length;
 await uploadChunks(f.json,'owned',f.bytes,{name:'fixture.bin',mime:'application/octet-stream'},'new-turn-key');
 expect(f.chunks).toEqual([0,262144]);expect(f.json.mock.calls[count][1]).toBeUndefined();expect(f.json.mock.calls.filter(([path,body]:[string,unknown])=>!path.includes('?')&&!path.endsWith('/chunk')&&!path.endsWith('/finish')&&body)).toHaveLength(1);
});
it('rejects foreign status without claiming attachment completion',async()=>{
 const f=fixture();const bad=vi.fn(async(path:string,body?:any)=>{const state=await f.json(path,body);return {...state,session_id:'foreign'};});
 await expect(uploadChunks(bad as any,'owned',f.bytes,{name:'fixture.bin',mime:'application/octet-stream'},'original-operation')).rejects.toThrow('identity/progress mismatch');expect(f.chunks).toEqual([]);expect(localStorage.length).toBe(1);
});

it('does not claim completion when finalization rejects and original status remains partial',async()=>{
 const f=fixture(),progress=vi.fn();const json=vi.fn(async(path:string,body?:any)=>{if(path.endsWith('/finish'))throw Object.assign(Error('finalization refused'),{status:409});return f.json(path,body);});
 await expect(uploadChunks(json as any,'owned',f.bytes,{name:'fixture.bin',mime:'application/octet-stream'},'original-operation',{onProgress:progress})).rejects.toThrow('finalization refused');
 expect(progress.mock.calls.some(([value])=>value.state==='complete')).toBe(false);expect(localStorage.length).toBe(1);expect(json.mock.calls.filter(([path])=>path.endsWith('/finish'))).toHaveLength(1);
});

it('does not recreate a previously acknowledged manifest that is no longer observable',async()=>{
 const f=fixture();await uploadChunks(f.json,'owned',f.bytes,{name:'fixture.bin',mime:'application/octet-stream'},'original-operation');
 const missing=vi.fn(async()=>{throw Object.assign(Error('Original manifest not retained'),{status:404});});
 await expect(uploadChunks(missing as any,'owned',f.bytes,{name:'fixture.bin',mime:'application/octet-stream'},'new-operation')).rejects.toThrow('Original manifest');
 expect(missing).toHaveBeenCalledTimes(1);expect(missing.mock.calls[0]).toHaveLength(3);expect((missing.mock.calls[0] as unknown[])[1]).toBeUndefined();expect(localStorage.length).toBe(1);
});
