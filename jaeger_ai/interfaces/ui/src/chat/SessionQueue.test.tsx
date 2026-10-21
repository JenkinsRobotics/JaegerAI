import{act}from'react';import{createRoot}from'react-dom/client';import{it,expect,vi}from'vitest';import{SessionQueue}from'./SessionQueue';import type{SessionQueue as Controls}from'../api/source';
(globalThis as {IS_REACT_ACT_ENVIRONMENT?:boolean}).IS_REACT_ACT_ENVIRONMENT=true;
it('reconciles original queued identity without replay or clearing a newer device draft',async()=>{
 const key='jaeger.ui.queue.v1.owned';localStorage.setItem(key+'.intent',JSON.stringify({requestId:'owned-request',text:'Original follow-up'}));localStorage.setItem(key+'.draft','Newer independent draft');
 const enqueue=vi.fn(),status=vi.fn(async()=>({request_id:'owned-request',session_id:'owned',status:'queued'})),accepted=vi.fn();
 const controls={list:async()=>({session_id:'owned',items:[]}),enqueue,status,update:vi.fn(),reorder:vi.fn()}as unknown as Controls;
 const el=document.createElement('div');document.body.append(el);const root=createRoot(el);await act(async()=>root.render(<SessionQueue controls={controls} sessionId="owned" onAccepted={accepted}/>));
 const textarea=el.querySelector<HTMLTextAreaElement>('[aria-label="Queued follow-up text"]')!;expect(textarea.disabled).toBe(true);
 await act(async()=>{[...el.querySelectorAll('button')].find(b=>b.textContent==='Check saved queued request')!.click();});
 expect(status).toHaveBeenCalledExactlyOnceWith('owned','owned-request');expect(enqueue).not.toHaveBeenCalled();expect(accepted).toHaveBeenCalledOnce();expect(textarea.value).toBe('Newer independent draft');expect(localStorage.getItem(key+'.draft')).toBe('Newer independent draft');expect(localStorage.getItem(key+'.intent')).toBeNull();
 await act(async()=>root.unmount());el.remove();localStorage.removeItem(key+'.draft');
});
