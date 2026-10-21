import { act } from 'react'; import { createRoot } from 'react-dom/client'; import { it, expect, vi } from 'vitest';
import { WorkflowsPanel } from './WorkflowsPanel'; import type { JaegerSource, WorkflowControls } from '../api/source';
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
it('reviews imported source and restores its unsent draft without creating a definition or task',async()=>{
 const raw='{"format":"owned-format","unsupported_grants":["terminal"]}';localStorage.setItem('jaeger.ui.workflow.import.v1',raw);
 const mutate=vi.fn();const workflows={list:async()=>({workflows:[],format:'owned-format',limits:{steps:20,bytes:64000}}),mutate}as unknown as WorkflowControls;
 const element=document.createElement('div');document.body.append(element);let root=createRoot(element);
 const render=()=> <WorkflowsPanel source={{workflows} as JaegerSource} agents={[]}/>;
 const button=(label:string)=>[...element.querySelectorAll('button')].find(b=>b.textContent===label)!;
 await act(async()=>root.render(render()));await act(async()=>button('Review imported definition').click());
 expect(element.querySelector<HTMLTextAreaElement>('[aria-label="Workflow definition JSON"]')?.value).toBe(raw);expect(mutate).not.toHaveBeenCalled();
 await act(async()=>root.unmount());root=createRoot(element);await act(async()=>root.render(render()));await act(async()=>button('New workflow').click());
 expect(element.querySelector<HTMLTextAreaElement>('[aria-label="Workflow definition JSON"]')?.value).toBe(raw);expect(mutate).not.toHaveBeenCalled();
 await act(async()=>root.unmount());element.remove();localStorage.removeItem('jaeger.ui.workflow.import.v1');localStorage.removeItem('jaeger.ui.workflow.draft.v1.new');
});
it('checks an unknown workflow proposal by original operation identity without replay',async()=>{
 const key='jaeger.ui.workflow.operation.v1';const pending={operationId:'owned-op',action:'propose',id:'owned-wf',draft:{raw:'original',revision:1}};localStorage.setItem(key,JSON.stringify(pending));
 const mutate=vi.fn(),operation=vi.fn(async()=>({receipt:null}));const workflows={list:async()=>({workflows:[],format:'owned-format',limits:{steps:20,bytes:64000}}),mutate,operation}as unknown as WorkflowControls;
 const element=document.createElement('div');document.body.append(element);const root=createRoot(element);await act(async()=>root.render(<WorkflowsPanel source={{workflows} as JaegerSource} agents={[]}/>));
 await act(async()=>[...element.querySelectorAll('button')].find(b=>b.textContent==='Check saved workflow action')!.click());
 expect(operation).toHaveBeenCalledExactlyOnceWith('owned-op');expect(mutate).not.toHaveBeenCalled();expect(localStorage.getItem(key)).toBe(JSON.stringify(pending));expect(element.textContent).toContain('outcome remains unknown');
 await act(async()=>root.unmount());element.remove();localStorage.removeItem(key);
});
it('edits a new workflow through ordinary fields and preserves an uncertain submitted definition',async()=>{
 const mutate=vi.fn(async()=>{throw Error('lost response');});const workflows={list:async()=>({workflows:[],format:'owned-format',limits:{steps:20,bytes:64000}}),mutate}as unknown as WorkflowControls;
 const element=document.createElement('div');document.body.append(element);const root=createRoot(element);await act(async()=>root.render(<WorkflowsPanel source={{workflows} as JaegerSource} agents={[]}/>));
 const button=(label:string)=>[...element.querySelectorAll('button')].find(b=>b.textContent===label)!;
 await act(async()=>button('New workflow').click());
 const fill=async(label:string,value:string)=>{const input=element.querySelector<HTMLInputElement|HTMLTextAreaElement>(`[aria-label="${label}"]`)!;await act(async()=>{Object.getOwnPropertyDescriptor(input instanceof HTMLInputElement?HTMLInputElement.prototype:HTMLTextAreaElement.prototype,'value')!.set!.call(input,value);input.dispatchEvent(new Event('input',{bubbles:true}));});};
 await fill('Workflow name','Owned workflow');await fill('Workflow step 1 title','Summarize');await fill('Workflow step 1 instruction','Summarize supplied fixture text.');
 await act(async()=>button('Save workflow').click());
 expect(mutate).toHaveBeenCalledExactlyOnceWith('create','new',expect.objectContaining({definition:{format:'owned-format',name:'Owned workflow',description:'',steps:[{title:'Summarize',instruction:'Summarize supplied fixture text.'}]}}));
 expect(element.textContent).toContain('Check saved workflow action');expect(element.textContent).not.toContain('Workflow saved at revision');
 expect(localStorage.getItem('jaeger.ui.workflow.draft.v1.new')).toContain('Summarize supplied fixture text.');
 await act(async()=>root.unmount());element.remove();const savedOperation=JSON.parse(localStorage.getItem('jaeger.ui.workflow.operation.v1')??'null');if(savedOperation)localStorage.removeItem('jaeger.ui.workflow.operation.v1.pending.'+savedOperation.operationId);localStorage.removeItem('jaeger.ui.workflow.operation.v1');localStorage.removeItem('jaeger.ui.workflow.draft.v1.new');
});
it('retains source but clears its action lock when Global Stop definitively rejects admission',async()=>{
 const {GatewayError}=await import('../api/gateway');const draft={raw:JSON.stringify({format:'owned-format',name:'Owned',description:'',steps:[{title:'Step',instruction:'Review supplied text'}]})};localStorage.setItem('jaeger.ui.workflow.draft.v1.new',JSON.stringify(draft));
 const mutate=vi.fn(async()=>{throw new GatewayError('global stop',423,{error:'global stop'});});const workflows={list:async()=>({workflows:[],format:'owned-format',limits:{steps:20,bytes:64000}}),mutate}as unknown as WorkflowControls;
 const element=document.createElement('div');document.body.append(element);const root=createRoot(element);await act(async()=>root.render(<WorkflowsPanel source={{workflows} as JaegerSource} agents={[]}/>));
 const button=(label:string)=>[...element.querySelectorAll('button')].find(b=>b.textContent===label)!;await act(async()=>button('New workflow').click());await act(async()=>button('Save workflow').click());
 expect(mutate).toHaveBeenCalledOnce();expect(localStorage.getItem('jaeger.ui.workflow.operation.v1')).toBeNull();expect(localStorage.getItem('jaeger.ui.workflow.draft.v1.new')).toBe(JSON.stringify(draft));expect(element.textContent).toContain('Workflow action rejected');
 await act(async()=>root.unmount());element.remove();localStorage.removeItem('jaeger.ui.workflow.draft.v1.new');
});
it('recovers every saved operation when two tabs race on the pending pointer',async()=>{
 const key='jaeger.ui.workflow.operation.v1';const first={operationId:'owned-first',action:'save',id:'owned-a',draft:{raw:'a',revision:1}},second={operationId:'owned-second',action:'save',id:'owned-b',draft:{raw:'b',revision:1}};
 localStorage.setItem(key,JSON.stringify(second));localStorage.setItem(key+'.pending.owned-first',JSON.stringify(first));localStorage.setItem(key+'.pending.owned-second',JSON.stringify(second));
 const mutate=vi.fn(),operation=vi.fn(async(id:string)=>id==='owned-second'?{receipt:{operation_id:id,ok:false,error:'Version conflict'}}:{receipt:null});
 const workflows={list:async()=>({workflows:[],format:'owned-format',limits:{steps:20,bytes:64000}}),mutate,operation}as unknown as WorkflowControls;
 const element=document.createElement('div');document.body.append(element);const root=createRoot(element);await act(async()=>root.render(<WorkflowsPanel source={{workflows} as JaegerSource} agents={[]}/>));
 const check=()=>[...element.querySelectorAll('button')].find(b=>b.textContent==='Check saved workflow action')!;
 await act(async()=>check().click());expect(localStorage.getItem(key+'.pending.owned-second')).toBeNull();expect(localStorage.getItem(key+'.pending.owned-first')).toBe(JSON.stringify(first));
 await act(async()=>check().click());expect(operation.mock.calls.map(call=>call[0])).toEqual(['owned-second','owned-first']);expect(mutate).not.toHaveBeenCalled();expect(localStorage.getItem(key+'.pending.owned-first')).toBe(JSON.stringify(first));
 await act(async()=>root.unmount());element.remove();localStorage.removeItem(key);localStorage.removeItem(key+'.pending.owned-first');
});
