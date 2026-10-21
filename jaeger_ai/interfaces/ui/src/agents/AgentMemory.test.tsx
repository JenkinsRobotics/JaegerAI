import {act} from 'react';
import {createRoot} from 'react-dom/client';
import {expect,it,vi} from 'vitest';
import {AgentMemory} from './AgentMemory';
import type {AgentMemorySnapshot} from '../api/source';
(globalThis as {IS_REACT_ACT_ENVIRONMENT?:boolean}).IS_REACT_ACT_ENVIRONMENT=true;
it('preserves an unknown notes save and reconciles only its receipt without replay',async()=>{
 const id='owned-memory',key='jaeger.ui.agent-memory.draft.v1.'+id,prefix='jaeger.ui.agent-memory.operation.v1.'+id+'.';
 localStorage.setItem(key,JSON.stringify({text:'Owned new draft',base:'old-revision'}));
 const row={agent_id:id,notes:'Old saved notes',revision:'old-revision',chars:15,max_chars:16000,prompt_chars:4000,editable:true,loaded_in_specialist_prompt:true,prompt_truncated:false,versions:[]} as AgentMemorySnapshot;
 const read=vi.fn(async()=>row),mutate=vi.fn(async()=>{throw Error('Lost notes response');});
 const operation=vi.fn(async(op:string)=>({receipt:{ok:true,operation_id:op,agent_id:id,revision:'new-revision'}}));
 const host=document.createElement('div');document.body.append(host);const root=createRoot(host);
 try{
  await act(async()=>root.render(<AgentMemory agentId={id} controls={{read,mutate,operation}} onClose={()=>{}}/>));
  await act(async()=>[...document.querySelectorAll('button')].find(b=>b.textContent==='Save specialist notes')!.click());
  const draft=JSON.parse(localStorage.getItem(key)!);expect(draft.pending).toBeTruthy();
  expect(JSON.parse(localStorage.getItem(prefix+draft.pending)!).text).toBe('Owned new draft');
  expect(mutate).toHaveBeenCalledExactlyOnceWith(id,{operation_id:draft.pending,expected_revision:'old-revision',action:'replace',text:'Owned new draft'});
  read.mockResolvedValueOnce({...row,notes:'Owned new draft\n',revision:'new-revision'});
  await act(async()=>[...document.querySelectorAll('button')].find(b=>b.textContent==='Check saved memory action')!.click());
  expect(operation).toHaveBeenCalledExactlyOnceWith(draft.pending);expect(mutate).toHaveBeenCalledTimes(1);
  expect(localStorage.getItem(prefix+draft.pending)).toBeNull();expect(JSON.parse(localStorage.getItem(key)!).base).toBe('new-revision');
 }finally{await act(async()=>root.unmount());host.remove();for(const k of Object.keys(localStorage))if(k===key||k.startsWith(prefix))localStorage.removeItem(k);}
});
it('confirms restore in app and preserves the independently unsaved draft',async()=>{
 const id='owned-restore',key='jaeger.ui.agent-memory.draft.v1.'+id,prefix='jaeger.ui.agent-memory.operation.v1.'+id+'.';
 localStorage.setItem(key,JSON.stringify({text:'Unsent unique memory draft',base:'current-revision'}));
 const row={agent_id:id,notes:'Current saved notes',revision:'current-revision',chars:19,max_chars:16000,prompt_chars:4000,editable:true,loaded_in_specialist_prompt:true,prompt_truncated:false,versions:[{revision:'older-revision',saved_at:1}]} as AgentMemorySnapshot;
 const read=vi.fn().mockResolvedValueOnce(row).mockResolvedValue({...row,notes:'Earlier saved notes',revision:'older-revision'});
 const mutate=vi.fn(async(_id:string,body:{operation_id:string})=>({ok:true,operation_id:body.operation_id,agent_id:id,revision:'older-revision'}));
 const host=document.createElement('div');document.body.append(host);const root=createRoot(host);
 try{
  await act(async()=>root.render(<AgentMemory agentId={id} controls={{read,mutate,operation:vi.fn()}} onClose={()=>{}}/>));
  await act(async()=>[...document.querySelectorAll('button')].find(b=>b.textContent==='Restore notes revision')!.click());
  expect(mutate).not.toHaveBeenCalled();
  await act(async()=>[...document.querySelectorAll('button')].find(b=>b.textContent==='Confirm notes restore')!.click());
  const saved=JSON.parse(localStorage.getItem(key)!);expect(saved.text).toBe('Unsent unique memory draft');expect(saved.base).toBe('current-revision');expect(saved.pending).toBeUndefined();
  expect(document.body.textContent).toContain('Existing draft retained separately');expect(document.body.textContent).toContain('Earlier saved notes');
 }finally{await act(async()=>root.unmount());host.remove();for(const k of Object.keys(localStorage))if(k===key||k.startsWith(prefix))localStorage.removeItem(k);}
});
