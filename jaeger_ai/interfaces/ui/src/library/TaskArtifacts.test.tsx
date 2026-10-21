import {act} from 'react';import{createRoot}from'react-dom/client';import{it,expect,vi}from'vitest';import{TaskArtifacts}from'./TaskArtifacts';import type{TaskArtifacts as Controls}from'../api/source';
(globalThis as {IS_REACT_ACT_ENVIRONMENT?:boolean}).IS_REACT_ACT_ENVIRONMENT=true;
it('reopens the same verified reference, clears content on access failure and retains missing identity',async()=>{
 const {webcrypto}=await import('node:crypto');vi.stubGlobal('crypto',webcrypto);
 const digest=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode('Owned artifact'))),n=>n.toString(16).padStart(2,'0')).join('');
 const ref={task_id:'owned-task',task_title:'Owned task',session_id:'owned-session',attachment_id:'artifact-owned',name:'result.txt',mime:'text/plain',size:14,sha256:digest,readable:true};
 let available=true;const read=vi.fn(async()=>{if(!available)throw Error('Access unavailable');return{...ref,data_base64:btoa('Owned artifact')};});
 const controls={list:vi.fn(async()=>({artifacts:available?[ref]:[],max_bytes:100})),read,preview:vi.fn()}as Controls;
 const key='jaeger.ui.artifact-selection.v1.owned-task';localStorage.removeItem(key);
 const el=document.createElement('div');document.body.append(el);let root=createRoot(el);await act(async()=>root.render(<TaskArtifacts controls={controls} taskId="owned-task"/>));
 await act(async()=>[...el.querySelectorAll('button')].find(b=>b.textContent==='result.txt')!.click());
 // Async digest verification can finish on a later task.
 await act(async()=>new Promise(r=>setTimeout(r,20)));
 expect(el.textContent).toContain('Owned artifact');expect(read).toHaveBeenCalledWith('owned-task','artifact-owned');expect(localStorage.getItem(key)).toBe('artifact-owned');
 await act(async()=>root.unmount());root=createRoot(el);await act(async()=>root.render(<TaskArtifacts controls={controls} taskId="owned-task"/>));await act(async()=>new Promise(r=>setTimeout(r,20)));
 expect(el.textContent).toContain('Owned artifact');
 available=false;await act(async()=>[...el.querySelectorAll('button')].find(b=>b.textContent==='Refresh artifact references')!.click());
 expect(el.textContent).not.toContain('Owned artifact');expect(el.textContent).toContain('Saved artifact reference artifact-owned is unavailable');expect(localStorage.getItem(key)).toBe('artifact-owned');
 await act(async()=>root.unmount());el.remove();localStorage.removeItem(key);vi.unstubAllGlobals();
});
