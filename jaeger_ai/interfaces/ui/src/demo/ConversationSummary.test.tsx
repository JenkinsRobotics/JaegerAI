import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, expect, it, vi } from 'vitest';
import { ConversationSummary } from './ConversationSummary';
import { MockSource } from '../api/mock';
(globalThis as {IS_REACT_ACT_ENVIRONMENT?: boolean}).IS_REACT_ACT_ENVIRONMENT = true;
let root: Root;
afterEach(async () => { await act(async () => root?.unmount()); document.body.innerHTML=''; vi.restoreAllMocks(); vi.unstubAllGlobals(); });
const flush=async(f=()=>{})=>act(async()=>{f();await new Promise(resolve=>setTimeout(resolve,0));});
it('projects only the selected session, real Git stats and stored attachments',async()=>{
 const source=new MockSource();Object.defineProperty(source,'kind',{value:'live'});
 Object.assign(source,{sessionFiles:{list:vi.fn().mockResolvedValue({session_id:'selected',files:[{attachment_id:'photo',name:'drawing.png',mime:'image/png'}]})}});
 vi.spyOn(source,'handoffs').mockResolvedValue([{id:'worker',session_id:'selected',status:'completed',to_agent_id:'builder'},{id:'other',session_id:'foreign',status:'running'}]);
 const fetch=vi.fn().mockResolvedValue({ok:true,json:async()=>({git:{is_git:true,files:[{additions:84,deletions:16},{ignored:true,additions:100,deletions:100}],truncated:true}})});vi.stubGlobal('fetch',fetch);
 const open=vi.fn(); const el=document.createElement('div');document.body.append(el);root=createRoot(el);
 await flush(()=>root.render(<ConversationSummary source={source} sessionId="selected" workspace="/work/JaegerAI" agents={[]} onOpen={open} onClose={()=>{}}/>));
 expect(el.textContent).toContain('JaegerAI');expect(el.textContent).toContain('+84');expect(el.textContent).toContain('−16');expect(el.textContent).toContain('1 done');expect(el.textContent).not.toContain('active');expect(el.textContent).toContain('drawing.png');
 expect(source.handoffs).toHaveBeenCalledWith({session_id:'selected'});expect(fetch.mock.calls[0][0]).toBe('/api/git/status?session_id=selected');
 await flush(()=>[...el.querySelectorAll('button')].find(b=>b.textContent?.startsWith('Changes'))!.click());expect(open).toHaveBeenCalledWith('changes');
});
it('rejects mismatched source identities and never invents completion or zero change counts on failure',async()=>{
 const source=new MockSource();Object.defineProperty(source,'kind',{value:'live'});
 Object.assign(source,{sessionFiles:{list:async()=>({session_id:'foreign',files:[{name:'secret.txt',mime:'text/plain'}]})}});
 vi.spyOn(source,'handoffs').mockRejectedValue(Error('offline'));vi.stubGlobal('fetch',vi.fn().mockRejectedValue(Error('offline')));
 const el=document.createElement('div');document.body.append(el);root=createRoot(el);
 await flush(()=>root.render(<ConversationSummary source={source} sessionId="selected" agents={[]} onOpen={()=>{}} onClose={()=>{}}/>));
 expect(el.textContent).not.toContain('secret.txt');expect(el.textContent).toContain('Sources unavailable');expect(el.textContent).toContain('Subagents unavailable');expect(el.textContent).toContain('Changes unavailable');expect(el.textContent).not.toContain('+0');expect(el.textContent).not.toContain('done');
});
