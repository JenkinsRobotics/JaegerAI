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
it('exports only a reviewed saved snapshot, preserves the draft and withholds mismatched content',async()=>{
 const {webcrypto,createHash}=await import('node:crypto');vi.stubGlobal('crypto',webcrypto);
 const digest=createHash('sha256').update('Saved content').digest('hex');
 const doc={id:'export-owned',title:'Saved name',content:'Saved content',revision:1,digest,archived:false,editable:true};
 const key='jaeger.ui.library.draft.v1.export-owned';localStorage.setItem(key,JSON.stringify({title:'Unsent title',content:'Keep this unsaved draft',revision:1}));
 let corrupt=false;const exportDocument=vi.fn(async()=>({format:'jaeger.document.snapshot',schema_version:1,access:'manual_local_export_no_recipient_grant',document:{...doc,content:corrupt?'Wrong content':doc.content}}));
 const controls={list:async()=>({collections:[],documents:[doc]}),read:async()=>doc,exportDocument}as unknown as LibraryControls;
 const create=vi.fn(()=> 'blob:owned-export'),revoke=vi.fn();vi.stubGlobal('URL',{createObjectURL:create,revokeObjectURL:revoke});const click=vi.spyOn(HTMLAnchorElement.prototype,'click').mockImplementation(()=>{});
 const el=document.createElement('div');document.body.append(el);const root=createRoot(el);
 try{
  await act(async()=>root.render(<LibraryPanel controls={controls}/>));await act(async()=>[...el.querySelectorAll('button')].find(b=>b.textContent?.startsWith('Saved name'))!.click());
  const button=[...el.querySelectorAll('button')].find(b=>b.textContent==='Export saved document')!;
  await act(async()=>button.click());await act(async()=>new Promise(r=>setTimeout(r,20)));
  expect(exportDocument).toHaveBeenCalledWith('export-owned',1,digest);expect(create).toHaveBeenCalledOnce();expect(click).toHaveBeenCalledOnce();expect(revoke).toHaveBeenCalledWith('blob:owned-export');
  expect(el.textContent).toContain('OS file delivery is unconfirmed');expect(localStorage.getItem(key)).toContain('Keep this unsaved draft');
  corrupt=true;await act(async()=>button.click());await act(async()=>new Promise(r=>setTimeout(r,20)));
  expect(el.textContent).toContain('Export digest mismatch');expect(create).toHaveBeenCalledOnce();expect(click).toHaveBeenCalledOnce();
 }finally{await act(async()=>root.unmount());el.remove();localStorage.removeItem(key);click.mockRestore();vi.unstubAllGlobals();}
});
it('keeps an expired or concurrently superseded write draft without claiming the newer revision as its own',async()=>{
 const key='jaeger.ui.library.draft.v1.concurrent-owned';localStorage.setItem(key,JSON.stringify({title:'My draft',content:'Preserve my local edit',revision:1}));
 const initial={id:'concurrent-owned',title:'Original',content:'Original',revision:1,digest:'first',archived:false,editable:true};let stage=0;
 const controls={list:async()=>({collections:[],documents:[initial]}),read:async()=>stage===2?{...initial,title:'Other winner',content:'Other value',revision:3,digest:'third'}:initial,
 mutate:vi.fn(async(_action,_id,body)=>stage++===0?{ok:false,operation_id:body.operation_id,error:'Write window expired before commit; changes rolled back'}:{ok:true,operation_id:body.operation_id,document:{id:initial.id,revision:2,digest:'second',archived:false}})}as unknown as LibraryControls;
 const el=document.createElement('div');document.body.append(el);const root=createRoot(el);
 try{
  await act(async()=>root.render(<LibraryPanel controls={controls}/>));await act(async()=>[...el.querySelectorAll('button')].find(b=>b.textContent?.startsWith('Original'))!.click());
  const save=[...el.querySelectorAll('button')].find(b=>b.textContent==='Save document')!;
  await act(async()=>save.click());expect(el.textContent).toContain('Write window expired');expect(el.textContent).not.toContain('Document action saved');expect(localStorage.getItem(key)).toContain('Preserve my local edit');
  await act(async()=>save.click());expect(el.textContent).toContain('Document action saved at revision 2');expect(el.textContent).toContain('Document advanced to revision 3');expect(el.querySelector<HTMLTextAreaElement>('[aria-label="Document content"]')!.value).toBe('Preserve my local edit');expect(JSON.parse(localStorage.getItem(key)!).revision).toBe(1);
 }finally{await act(async()=>root.unmount());el.remove();localStorage.removeItem(key);localStorage.removeItem('jaeger.ui.library.operation.v1');}
});
