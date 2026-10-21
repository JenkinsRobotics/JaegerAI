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

it('restores a lost versioned save journal and checks its original receipt without resending',async()=>{
 localStorage.clear();let model:string|null=null,revision=0,command:{operation_id:string;model:string|null;expected_model_revision:number}|undefined;
 const saveVersioned=vi.fn(async(_id,body)=>{command=body;model='model';revision=1;throw Error('lost ACK');});
 const settings={inventory:async()=>({providers:[{id:'owned',display_name:'Owned',reachable:true,configured:true,models:[{id:'model'}]}]}),read:async()=>({session_id:'owned-modern',model,provider:model?'owned':null,model_choice_revision:revision,atomic_model_operations:true}),save:vi.fn(),saveVersioned,operation:vi.fn(async id=>({receipt:{ok:true,operation_id:id,domain:'model_choice',session_id:'owned-modern'}}))};
 const el=document.createElement('div');document.body.append(el);let root=createRoot(el);
 const click=(label:string)=>[...document.querySelectorAll('button')].find(b=>b.textContent===label)!.click();
 try{
  await act(async()=>root.render(<RuntimeSettings settings={settings} sessionId="owned-modern"/>));await act(async()=>el.querySelector('button')!.click());
  const select=document.querySelector<HTMLSelectElement>('[aria-label="Conversation model"]')!;
  await act(async()=>{select.value='@owned:model';select.dispatchEvent(new Event('change',{bubbles:true}));});
  await act(async()=>click('Save conversation model'));
  expect(saveVersioned).toHaveBeenCalledTimes(1);expect(command?.expected_model_revision).toBe(0);
  expect(document.body.textContent).toContain('lost ACK');
  await act(async()=>root.unmount());root=createRoot(el);
  await act(async()=>root.render(<RuntimeSettings settings={settings} sessionId="owned-modern"/>));await act(async()=>el.querySelector('button')!.click());
  expect(document.body.textContent).toContain('original receipt');expect(saveVersioned).toHaveBeenCalledTimes(1);
  await act(async()=>click('Check original model save'));
  expect(settings.operation).toHaveBeenCalledWith(command!.operation_id);expect(saveVersioned).toHaveBeenCalledTimes(1);
  expect(document.body.textContent).toContain('Original model save confirmed: @owned:model');expect(settings.save).not.toHaveBeenCalled();
  expect(localStorage.getItem('jaeger.ui.model-choice.v1.owned-modern')).toBeNull();
 }finally{await act(async()=>root.unmount());el.remove();localStorage.clear();}
});

it('retains a rejected model proposal and requires fresh read before a new explicit save',async()=>{
 localStorage.clear();let revision=1;
 const saveVersioned=vi.fn(async(_id,body)=>{revision=2;return {ok:false,operation_id:body.operation_id,domain:'model_choice',session_id:'owned-conflict',error:'Changed elsewhere'};});
 const settings={inventory:async()=>({providers:[{id:'owned',display_name:'Owned',reachable:true,configured:true,models:[{id:'model'}]}]}),read:async()=>({session_id:'owned-conflict',model:null,model_choice_revision:revision,atomic_model_operations:true}),save:vi.fn(),saveVersioned};
 const el=document.createElement('div');document.body.append(el);const root=createRoot(el);
 try{await act(async()=>root.render(<RuntimeSettings settings={settings} sessionId="owned-conflict"/>));await act(async()=>el.querySelector('button')!.click());const select=document.querySelector<HTMLSelectElement>('[aria-label="Conversation model"]')!;
 await act(async()=>{select.value='@owned:model';select.dispatchEvent(new Event('change',{bubbles:true}));});await act(async()=>[...document.querySelectorAll('button')].find(b=>b.textContent==='Save conversation model')!.click());
 expect(document.body.textContent).toContain('Changed elsewhere');expect(document.body.textContent).not.toContain('save confirmed');
 expect(localStorage.getItem('jaeger.ui.model-choice.v1.owned-conflict.draft')).toBe('@owned:model');expect(saveVersioned).toHaveBeenCalledTimes(1);
 await act(async()=>[...document.querySelectorAll('button')].find(b=>b.textContent==='Refresh models and settings')!.click());
 expect(document.querySelector<HTMLSelectElement>('[aria-label="Conversation model"]')!.value).toBe('@owned:model');expect(document.body.textContent).toContain('revision 2');expect(saveVersioned).toHaveBeenCalledTimes(1);
 }finally{await act(async()=>root.unmount());el.remove();localStorage.clear();}
});
it('never settles a foreign model receipt or replays the saved command',async()=>{
 localStorage.clear();const intent={operation_id:'owned-model-pending',expected_model_revision:0,model:'@owned:model'};
 const key='jaeger.ui.model-choice.v1.owned-scope';localStorage.setItem(key,JSON.stringify(intent));
 const settings={inventory:async()=>({providers:[]}),read:async()=>({session_id:'owned-scope',model:null,model_choice_revision:0,atomic_model_operations:true}),save:vi.fn(),saveVersioned:vi.fn(),operation:vi.fn(async()=>({receipt:{ok:true,operation_id:intent.operation_id,domain:'model_choice',session_id:'foreign'}}))};
 const el=document.createElement('div');document.body.append(el);const root=createRoot(el);
 try{await act(async()=>root.render(<RuntimeSettings settings={settings} sessionId="owned-scope"/>));await act(async()=>el.querySelector('button')!.click());await act(async()=>[...document.querySelectorAll('button')].find(b=>b.textContent==='Check original model save')!.click());expect(document.body.textContent).toContain('identity/scope mismatch');expect(localStorage.getItem(key)).toBe(JSON.stringify(intent));expect(settings.saveVersioned).not.toHaveBeenCalled();expect(document.body.textContent).not.toContain('save confirmed');}finally{await act(async()=>root.unmount());el.remove();localStorage.clear();}
});
it('requires explicit review to cancel an uncommitted pending choice without undoing a saved model',async()=>{
 localStorage.clear();const intent={operation_id:'owned-cancel-model',expected_model_revision:0,model:'@owned:new'};const key='jaeger.ui.model-choice.v1.owned-cancel';localStorage.setItem(key,JSON.stringify(intent));localStorage.setItem(key+'.draft',intent.model);
 const cancelPending=vi.fn(async()=>({ok:false,operation_id:intent.operation_id,domain:'model_choice',session_id:'owned-cancel',result:{cancelled:true}}));
 const settings={inventory:async()=>({providers:[]}),read:async()=>({session_id:'owned-cancel',model:'old',provider:'owned',model_choice_revision:0,atomic_model_operations:true}),save:vi.fn(),saveVersioned:vi.fn(),operation:vi.fn(async()=>({receipt:null})),cancelPending};
 const el=document.createElement('div');document.body.append(el);const root=createRoot(el);
 const click=(label:string)=>[...document.querySelectorAll('button')].find(b=>b.textContent===label)!.click();
 try{await act(async()=>root.render(<RuntimeSettings settings={settings} sessionId="owned-cancel"/>));await act(async()=>el.querySelector('button')!.click());await act(async()=>click('Review pending model cancellation'));expect(cancelPending).not.toHaveBeenCalled();await act(async()=>click('Confirm pending model cancellation'));expect(cancelPending).toHaveBeenCalledExactlyOnceWith('owned-cancel',intent);expect(document.body.textContent).toContain('cancelled before commit');expect(document.body.textContent).not.toContain('Loading models');expect(localStorage.getItem(key)).toBeNull();expect(localStorage.getItem(key+'.draft')).toBe(intent.model);expect(settings.saveVersioned).not.toHaveBeenCalled();}finally{await act(async()=>root.unmount());el.remove();localStorage.clear();}
});
