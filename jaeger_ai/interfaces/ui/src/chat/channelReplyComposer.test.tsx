import {act} from 'react';import {createRoot} from 'react-dom/client';import {it,expect,vi} from 'vitest';
import {MinimalChat} from './MinimalChat';import {messagesToTurns} from './webHost';import type {ChatHost} from './host';
const drafts=vi.hoisted(()=>new Map<string,{text:string;files:[]}>());
vi.mock('./drafts',()=>({readDraft:async(id:string)=>drafts.get(id)??{text:'',files:[]},writeDraft:async(id:string,value:{text:string;files:[]})=>{drafts.set(id,value);}}));
(globalThis as {IS_REACT_ACT_ENVIRONMENT?:boolean}).IS_REACT_ACT_ENVIRONMENT=true;
async function fixture(id:string,text:string,run:(el:HTMLDivElement,start:ReturnType<typeof vi.fn>)=>Promise<void>){
 drafts.set(id,{text,files:[]});const start=vi.fn();const turns=messagesToTurns([{id:42,role:'user',kind:'channel_message',content:'External incoming text',channel:{channel_id:'discord',provider_conversation_id:'discord:909',ingress_author_id:'101',external_message_id:'parent',authority:'incoming_data_only'}}]);
 const host={capabilities:{voice:false},startTurn:start,respondToConfirmation:vi.fn(),copy:vi.fn(),openExternal:vi.fn(),sessions:{list:vi.fn(),load:async()=>({id,title:'owned',turns})}} as unknown as ChatHost;
 const el=document.createElement('div');document.body.append(el);const root=createRoot(el);
 try{await act(async()=>root.render(<MinimalChat host={host} sessionId={id}/>));await run(el,start);}finally{await act(async()=>root.unmount());el.remove();drafts.delete(id);}
}
it('prepares a correlated external-reply draft from the actual saved DTO without starting execution',async()=>{
 await fixture('owned-reply-composer','',async(el,start)=>{const button=[...el.querySelectorAll('button')].find(b=>b.textContent==='Prepare bot reply')!;expect(button).toBeTruthy();await act(async()=>button.click());expect(start).not.toHaveBeenCalled();const draft=el.querySelector<HTMLTextAreaElement>('textarea[aria-label="Message"]')!.value;expect(draft).toContain('reply_to_message_id=42');expect(draft).toContain('recipient="909"');expect(draft).toContain('required approval');expect(drafts.get('owned-reply-composer')!.text).toBe(draft);});
});
it('keeps an existing unique composer draft and never auto-submits on ingress',async()=>{
 await fixture('owned-existing-reply','Unsent operator draft',async(el,start)=>{const button=[...el.querySelectorAll('button')].find(b=>b.textContent==='Prepare bot reply')!;expect(button.disabled).toBe(true);await act(async()=>button.click());expect(drafts.get('owned-existing-reply')!.text).toBe('Unsent operator draft');expect(start).not.toHaveBeenCalled();});
});
