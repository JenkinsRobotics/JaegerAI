import { act } from "react";import { createRoot } from "react-dom/client";import { expect,it,vi } from "vitest";import {RuntimeSettings} from './RuntimeSettings';
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
it('shows real reachable choices, leaves rejected save unconfirmed and never changes credentials',async()=>{
 const el=document.createElement('div');document.body.append(el);const root=createRoot(el);
 const save=vi.fn(async()=>{throw Error('Unknown or unreachable model');});
 const settings={inventory:async()=>({providers:[{id:'owned',display_name:'Owned provider',reachable:true,configured:true,models:[{id:'model'}]},{id:'offline',display_name:'Offline',reachable:false,configured:true,models:[{id:'not-selectable'}]}]}),read:async()=>({session_id:'owned-home',model:null}),save};
 await act(async()=>root.render(<RuntimeSettings settings={settings} sessionId="owned-home"/>));await act(async()=>(el.querySelector('button')!).click());
 const select=document.querySelector<HTMLSelectElement>('[aria-label="Conversation model"]')!;expect([...select.options].map(o=>o.value)).toEqual(['','@owned:model']);
 await act(async()=>{select.value='@owned:model';select.dispatchEvent(new Event('change',{bubbles:true}));});
 await act(async()=>{[...document.querySelectorAll('button')].find(b=>b.textContent==='Save conversation model')!.click();});
 expect(save).toHaveBeenCalledExactlyOnceWith('owned-home','@owned:model');expect(document.body.textContent).toContain('Unknown or unreachable model');expect(document.body.textContent).not.toContain('Conversation model saved.');
 await act(async()=>root.unmount());el.remove();
});
it('distinguishes configured but unprobed providers and preserves the saved unavailable model on refresh',async()=>{
 const el=document.createElement('div');document.body.append(el);const root=createRoot(el);const save=vi.fn();
 const settings={inventory:async()=>({providers:[{id:'cloud-owned',display_name:'Owned cloud',reachable:false,configured:true,availability:'not_probed' as const,models:[]}]}),read:async()=>({session_id:'owned-home',model:'saved-model',provider:'cloud-owned'}),save};
 try{await act(async()=>root.render(<RuntimeSettings settings={settings} sessionId="owned-home"/>));await act(async()=>el.querySelector('button')!.click());
 expect(document.body.textContent).toContain('Configured · health not probed');
 const select=document.querySelector<HTMLSelectElement>('[aria-label="Conversation model"]')!;expect(select.value).toBe('@cloud-owned:saved-model');
 await act(async()=>[...document.querySelectorAll('button')].find(b=>b.textContent==='Refresh models and settings')!.click());
 expect(document.querySelector<HTMLSelectElement>('[aria-label="Conversation model"]')!.value).toBe('@cloud-owned:saved-model');expect(save).not.toHaveBeenCalled();
 }finally{await act(async()=>root.unmount());el.remove();}
});
