import {act} from 'react';import {createRoot} from 'react-dom/client';import {it,expect,vi} from 'vitest';
import {EpisodeMemoryPanel} from './EpisodeMemoryPanel';import type {EpisodeControls,EpisodeContext} from '../api/source';
const row:EpisodeContext={event_id:'evt-owned',event_type:'human.message',session_id:'owned-session',actor:'human:operator',source:'fixture',timestamp:1,text:'Owned original episode',annotation:'',active:true,revision:'a'.repeat(64),editable:true};
function click(element:HTMLElement,label:string){const b=[...element.querySelectorAll('button')].find(v=>v.textContent===label);expect(b).toBeTruthy();b!.click();}
async function wait(){await act(async()=>{await new Promise(r=>setTimeout(r,180));});}
it('requires explicit confirmation, resolves a lost receipt without replay and preserves correction draft',async()=>{
 localStorage.clear();let current={...row};let command:{operation_id:string;expected_revision:string}|undefined;
 const mutate=vi.fn(async(_id,_action,body)=>{command=body;throw Error('lost acknowledgment');});
 const controls:EpisodeControls={list:vi.fn(async()=>({available:true,editable:true,scope:'cross_conversation_automatic_context',episodes:[current],next_before:null})),detail:vi.fn(async()=>current),mutate,operation:vi.fn(async id=>{current={...current,active:false,revision:'b'.repeat(64)};return {receipt:{ok:true,operation_id:id,result:{original_preserved:true}}};})};
 const el=document.createElement('div');document.body.appendChild(el);let root=createRoot(el);
 try{
  await act(async()=>{root.render(<EpisodeMemoryPanel controls={controls}/>);});await wait();
  await act(async()=>click(el,'Inspect episode context'));
  const input=el.querySelector('textarea')!;
  await act(async()=>{const setter=Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')!.set!;setter.call(input,'Owned correction draft');input.dispatchEvent(new Event('input',{bubbles:true}));});
  await act(async()=>click(el,'Review recoverable forget'));expect(mutate).not.toHaveBeenCalled();
  await act(async()=>click(el,'Confirm episode change'));expect(mutate).toHaveBeenCalledTimes(1);
  expect(mutate.mock.calls[0][0]).toBe(row.event_id);expect(command?.expected_revision).toBe(row.revision);
  await act(async()=>root.unmount());root=createRoot(el);
  await act(async()=>root.render(<EpisodeMemoryPanel controls={controls}/>));await wait();
  await act(async()=>click(el,'Inspect episode context'));expect((el.querySelector('textarea') as HTMLTextAreaElement).value).toBe('Owned correction draft');
  await act(async()=>click(el,'Check original episode operation'));
  expect(mutate).toHaveBeenCalledTimes(1);expect(controls.operation).toHaveBeenCalledWith(command!.operation_id);
  expect(el.textContent).toContain('Original evt-owned · Excluded from recall');expect(el.textContent).toContain('Owned original episode');expect(el.textContent).toContain('Review recall restore');
 }finally{await act(async()=>root.unmount());el.remove();localStorage.clear();}
});
it('retains an unmatched/unknown receipt and exposes no mutation controls for a read-only owner',async()=>{
 localStorage.clear();const key='jaeger.ui.episode-context.v1.'+row.event_id;
 const intent={operation_id:'owned-pending',expected_revision:row.revision,action:'forget'};localStorage.setItem(key,JSON.stringify(intent));
 const controls:EpisodeControls={list:vi.fn(async()=>({available:true,editable:false,scope:'cross_conversation_automatic_context',episodes:[row],next_before:null})),detail:vi.fn(async()=>({...row,editable:false})),mutate:vi.fn(),operation:vi.fn(async()=>({receipt:{ok:true,operation_id:'wrong-id'}}))};
 const el=document.createElement('div');document.body.appendChild(el);const root=createRoot(el);
 try{await act(async()=>root.render(<EpisodeMemoryPanel controls={controls}/>));await wait();await act(async()=>click(el,'Inspect episode context'));await act(async()=>click(el,'Check original episode operation'));expect(localStorage.getItem(key)).toBe(JSON.stringify(intent));expect(el.textContent).toContain('Receipt does not match');expect(el.textContent).not.toContain('Review recoverable forget');expect(controls.mutate).not.toHaveBeenCalled();}finally{await act(async()=>root.unmount());el.remove();localStorage.clear();}
});
