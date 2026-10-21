import {act} from 'react';import{createRoot}from'react-dom/client';import{it,expect,vi}from'vitest';import{LibraryPanel}from'./LibraryPanel';import type{LibraryControls}from'../api/source';
(globalThis as {IS_REACT_ACT_ENVIRONMENT?:boolean}).IS_REACT_ACT_ENVIRONMENT=true;
it('preserves a stale draft, sends its original revision and recovers unknown without repeating mutation',async()=>{
 const key='jaeger.ui.library.draft.v1.owned';localStorage.setItem(key,JSON.stringify({title:'My draft',content:'Preserve this edit',revision:1}));
 const mutate=vi.fn(async()=>{throw Error('Document changed; reload before saving');});const operation=vi.fn(async()=>({receipt:null}));
 const controls={list:async()=>({documents:[{id:'owned',title:'Saved document',revision:2}],collections:[]}),read:async()=>({id:'owned',title:'Saved document',content:'Other saved edit',revision:2,editable:true,digest:'hash'}),versions:vi.fn(),search:vi.fn(),mutate,operation}as unknown as LibraryControls;
 const el=document.createElement('div');document.body.append(el);let root=createRoot(el);await act(async()=>root.render(<LibraryPanel controls={controls}/>));
 await act(async()=>{[...el.querySelectorAll('button')].find(b=>b.textContent?.startsWith('Saved document'))!.click();});
 expect(el.querySelector<HTMLTextAreaElement>('[aria-label="Document content"]')!.value).toBe('Preserve this edit');expect(el.textContent).toContain('Document changed elsewhere');
 await act(async()=>{[...el.querySelectorAll('button')].find(b=>b.textContent==='Save document')!.click();});
 expect(mutate).toHaveBeenCalledOnce();expect(mutate.mock.calls[0]).toEqual(['save','owned',expect.objectContaining({expected_revision:1,content:'Preserve this edit'})]);
 expect(localStorage.getItem(key)).toContain('Preserve this edit');expect(el.textContent).not.toContain('Document action saved at revision');
 await act(async()=>root.unmount());root=createRoot(el);await act(async()=>root.render(<LibraryPanel controls={controls}/>));
 await act(async()=>{[...el.querySelectorAll('button')].find(b=>b.textContent==='Check saved document action')!.click();});expect(operation).toHaveBeenCalledOnce();expect(mutate).toHaveBeenCalledOnce();expect(el.textContent).toContain('Document action remains unknown');
 await act(async()=>root.unmount());el.remove();localStorage.removeItem(key);localStorage.removeItem('jaeger.ui.library.operation.v1');
});
