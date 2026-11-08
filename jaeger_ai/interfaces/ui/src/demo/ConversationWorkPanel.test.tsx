import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, expect, it, vi } from 'vitest';
import { ConversationWorkPanel, type WorkView } from './ConversationWorkPanel';
import { MockSource } from '../api/mock';
import { useState } from 'react';
vi.mock('../chat/ChatPane',()=>({ChatPane:({sessionId}:{sessionId:string})=><div data-side-session={sessionId}/>}));
(globalThis as {IS_REACT_ACT_ENVIRONMENT?: boolean}).IS_REACT_ACT_ENVIRONMENT = true;
let root:Root;
afterEach(async()=>{await act(async()=>root?.unmount());document.body.innerHTML='';vi.restoreAllMocks();vi.unstubAllGlobals();});
const flush=async(f=()=>{})=>act(async()=>{f();await new Promise(resolve=>setTimeout(resolve,0));});
it('opens and closes working tabs, creates a side chat only on explicit start, and retains it when hidden',async()=>{
 const source=new MockSource();const create=vi.spyOn(source,'createSession').mockResolvedValue({session_id:'separate'});
 function Harness(){const [view,setView]=useState<WorkView>('tools');return <ConversationWorkPanel source={source} sessionId="main" agents={[]} recent={[]} view={view} open onView={setView} onClose={()=>{}} onConversation={()=>{}}/>;}
 const el=document.createElement('div');document.body.append(el);root=createRoot(el);await flush(()=>root.render(<Harness/>));
 await flush(()=>[...el.querySelectorAll('button')].find(b=>b.textContent==='Side chat')!.click());expect(create).not.toHaveBeenCalled();
 await flush(()=>[...el.querySelectorAll('button')].find(b=>b.textContent==='Start side chat')!.click());expect(create).toHaveBeenCalledTimes(1);expect(el.querySelector('[data-side-session]')).toHaveAttribute('data-side-session','separate');
 const chat=el.querySelector('[data-side-session]');await flush(()=>el.querySelector<HTMLButtonElement>('[role="tab"]')!.click());expect(el.querySelector('[data-side-session]')).toBe(chat);expect(el.querySelector<HTMLElement>('#work-view-sidechat')?.hidden).toBe(true);
 await flush(()=>el.querySelector<HTMLButtonElement>('[aria-label="Close Side chat tab"]')!.click());expect(el.querySelector('[data-side-session]')).toBeNull();
});
it('opening Terminal does not start a shell',async()=>{
 const source=new MockSource();Object.defineProperty(source,'kind',{value:'live'});const fetch=vi.fn().mockRejectedValue(Error('Session not found'));vi.stubGlobal('fetch',fetch);
 const el=document.createElement('div');document.body.append(el);root=createRoot(el);await flush(()=>root.render(<ConversationWorkPanel source={source} sessionId="selected" agents={[]} recent={[]} view="terminal" open onView={()=>{}} onClose={()=>{}} onConversation={()=>{}}/>));expect(fetch).not.toHaveBeenCalled();
 await flush(()=>[...el.querySelectorAll('button')].find(b=>b.textContent==='Connect terminal')!.click());expect(fetch.mock.calls[0][0]).toBe('/api/terminal/start');expect(JSON.parse(fetch.mock.calls[0][1].body)).toMatchObject({session_id:'selected'});expect(el.textContent).toContain('Session not found');
});
it('keeps verified outputs reachable and bound to the exact selected opaque conversation',async()=>{
 const source=new MockSource();const list=vi.fn().mockResolvedValue({artifacts:[]});Object.assign(source,{taskArtifacts:{list}});
 const el=document.createElement('div');document.body.append(el);root=createRoot(el);
 function Harness({sessionId}:{sessionId:string}){const [view,setView]=useState<WorkView>('tools');return <ConversationWorkPanel source={source} sessionId={sessionId} agents={[]} recent={[]} view={view} open onView={setView} onClose={()=>{}} onConversation={()=>{}}/>;}
 await flush(()=>root.render(<Harness sessionId="historic / α"/>));
 await flush(()=>[...el.querySelectorAll('button')].find(b=>b.textContent==='Outputs and artifacts')!.click());
 expect(list).toHaveBeenLastCalledWith(undefined,'historic / α');
 await flush(()=>root.render(<Harness sessionId="second / β"/>));
 expect(list).toHaveBeenLastCalledWith(undefined,'second / β');
 list.mockClear();await flush(()=>root.render(<Harness sessionId=""/>));
 expect(list).not.toHaveBeenCalled();expect(el.textContent).toContain('Choose a conversation to see its outputs.');
});
