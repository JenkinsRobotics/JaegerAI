import{act}from'react';import{createRoot}from'react-dom/client';import{it,expect,vi}from'vitest';import{AutomationsPanel}from'./AutomationsPanel';import type{ScheduleControls}from'../api/source';
(globalThis as {IS_REACT_ACT_ENVIRONMENT?:boolean}).IS_REACT_ACT_ENVIRONMENT=true;
it('recovers only a saved receipt and never replays an uncertain automation',async()=>{
 localStorage.setItem('jaeger.ui.schedule-operation.v1',JSON.stringify({version:1,operationId:'owned-unknown',action:'run'}));const mutate=vi.fn();const operation=vi.fn(async()=>({receipt:null}));
 const controls={list:async()=>({jobs:[],scheduler:'jaeger'}),operation,mutate,history:vi.fn()}as unknown as ScheduleControls;
 const el=document.createElement('div');document.body.append(el);const root=createRoot(el);await act(async()=>root.render(<AutomationsPanel controls={controls}/>));
 const buttons=[...el.querySelectorAll('button')];expect(buttons.find(b=>b.textContent==='New automation')!.disabled).toBe(true);
 await act(async()=>buttons.find(b=>b.textContent==='Check saved operation')!.click());expect(operation).toHaveBeenCalledExactlyOnceWith('owned-unknown');expect(mutate).not.toHaveBeenCalled();expect(el.textContent).toContain('Operation remains unknown');expect(localStorage.getItem('jaeger.ui.schedule-operation.v1')).toContain('owned-unknown');
 await act(async()=>root.unmount());el.remove();localStorage.removeItem('jaeger.ui.schedule-operation.v1');
});
