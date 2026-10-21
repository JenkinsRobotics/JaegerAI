import {act} from 'react';import {createRoot} from 'react-dom/client';import {it,expect,vi,afterEach} from 'vitest';import {SpecialistHandoff} from './SpecialistHandoff';import type {JaegerSource} from '../api/source';
(globalThis as {IS_REACT_ACT_ENVIRONMENT?:boolean}).IS_REACT_ACT_ENVIRONMENT=true;afterEach(()=>localStorage.clear());
const body={task:'owned earlier task',request_id:'owned-original',session_id:'origin-home',from_agent_id:'native:origin',require_approval:true as const,model:'@ollama:fixture',background:true as const};
it('recovers original accepted handoff without resubmission or clearing a newer draft',async()=>{
 localStorage.setItem('jaeger.ui.delegate.intent.v1',JSON.stringify({version:1,target:'native:target',body,draft_text:'owned earlier task'}));
 localStorage.setItem('jaeger.ui.delegate.draft.v1',JSON.stringify({origin:'native:origin',target:'native:target',model:'@ollama:fixture',text:'newer draft'}));
 const create=vi.fn(),original=vi.fn(async()=>({scope:'handoff_request',resource_id:'native:target',request_id:body.request_id,outcome:'saved',command:body,handoff:{id:'saved-handoff',request_id:body.request_id,task:body.task,session_id:body.session_id,from_agent_id:body.from_agent_id,to_agent_id:'native:target',status:'pending_approval',metadata:{requested_model:body.model}}}));
 const host=document.createElement('div');document.body.append(host);const root=createRoot(host);await act(async()=>root.render(<SpecialistHandoff source={{delegation:{create,original}} as unknown as JaegerSource} agents={[]}/>));
 await act(async()=>[...host.querySelectorAll('button')].find(b=>b.textContent==='Check original handoff')!.click());expect(original).toHaveBeenCalledWith('native:target',body.request_id);expect(create).not.toHaveBeenCalled();expect(localStorage.getItem('jaeger.ui.delegate.intent.v1')).toBeNull();expect(localStorage.getItem('jaeger.ui.delegate.draft.v1')).toContain('newer draft');expect(host.textContent).toContain('pending_approval');
 await act(async()=>root.unmount());host.remove();
});
it('settles a durable rejection and retains the editable draft, but never settles unknown',async()=>{
 const intent={version:1,target:'native:target',body};localStorage.setItem('jaeger.ui.delegate.intent.v1',JSON.stringify(intent));const original=vi.fn(async()=>({scope:'handoff_request',resource_id:'native:target',request_id:body.request_id,outcome:'unknown',handoff:null}));
 const host=document.createElement('div');document.body.append(host);const root=createRoot(host);await act(async()=>root.render(<SpecialistHandoff source={{delegation:{create:vi.fn(),original}} as unknown as JaegerSource} agents={[]}/>));
 await act(async()=>[...host.querySelectorAll('button')].find(b=>b.textContent==='Check original handoff')!.click());expect(localStorage.getItem('jaeger.ui.delegate.intent.v1')).not.toBeNull();expect(host.textContent).toContain('admission unknown');
 original.mockResolvedValueOnce({scope:'handoff_request',resource_id:'native:target',request_id:body.request_id,outcome:'rejected',command:body,handoff:null,error:'Model unavailable'} as never);
 await act(async()=>[...host.querySelectorAll('button')].find(b=>b.textContent==='Check original handoff')!.click());expect(localStorage.getItem('jaeger.ui.delegate.intent.v1')).toBeNull();expect(host.textContent).toContain('Model unavailable');await act(async()=>root.unmount());host.remove();
});
it('submits the selected existing origin and configured child model once, then consumes only that task draft',async()=>{
 const saved={origin:'native:origin',target:'native:target',model:'@ollama:fixture',text:'new owned task'};localStorage.setItem('jaeger.ui.delegate.draft.v1',JSON.stringify(saved));
 const create=vi.fn(async(target,b)=>({scope:'handoff_request',resource_id:target,request_id:b.request_id,outcome:'saved',command:b,handoff:{id:'saved',request_id:b.request_id,task:b.task,session_id:b.session_id,from_agent_id:b.from_agent_id,to_agent_id:target,status:'pending_approval',metadata:{requested_model:b.model}}}));
 const source={delegation:{create,original:vi.fn()},agentHome:async()=>({agent_id:saved.origin,session_id:'origin-home'})} as unknown as JaegerSource;
 const agents=[{id:saved.origin,name:'Origin'},{id:saved.target,name:'Target',delegation:{can_request:true,background:'durable' as const,per_request_model:true,tools:'existing'}}];
 const host=document.createElement('div');document.body.append(host);const root=createRoot(host);await act(async()=>root.render(<SpecialistHandoff source={source} agents={agents}/>));
 await act(async()=>host.querySelector('form')!.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})));
 expect(create).toHaveBeenCalledTimes(1);expect(create).toHaveBeenCalledWith(saved.target,expect.objectContaining({task:saved.text,model:saved.model,session_id:'origin-home',from_agent_id:saved.origin,require_approval:true,background:true}));
 expect(JSON.parse(localStorage.getItem('jaeger.ui.delegate.draft.v1')!).text).toBe('');expect(host.textContent).toContain('pending_approval');expect((host.querySelector('button[type="submit"]')??[...host.querySelectorAll('button')].find(b=>b.textContent==='Request handoff'))!.hasAttribute('disabled')).toBe(true);
 await act(async()=>root.unmount());host.remove();
});
it('does not settle a rejection belonging to different original command data',async()=>{
 const intent={version:1,target:'native:target',body};localStorage.setItem('jaeger.ui.delegate.intent.v1',JSON.stringify(intent));const original=vi.fn(async()=>({scope:'handoff_request',resource_id:intent.target,request_id:body.request_id,outcome:'rejected',command:{...body,task:'different task'},handoff:null,error:'rejected'}));const host=document.createElement('div');document.body.append(host);const root=createRoot(host);await act(async()=>root.render(<SpecialistHandoff source={{delegation:{create:vi.fn(),original}} as unknown as JaegerSource} agents={[]}/>));await act(async()=>[...host.querySelectorAll('button')].find(b=>b.textContent==='Check original handoff')!.click());expect(localStorage.getItem('jaeger.ui.delegate.intent.v1')).not.toBeNull();expect(host.textContent).toContain('command body mismatch');await act(async()=>root.unmount());host.remove();
});
