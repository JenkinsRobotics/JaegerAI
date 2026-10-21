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
it('shows authoritative timezone and next run and submits the editor original revision',async()=>{
 localStorage.clear();const job={id:'zone-fixture',name:'zone-fixture',prompt:'Saved objective',cron:'0 9 * * *',enabled:true,state:'active',timezone:'America/New_York',timezone_policy:'America/New_York',config_revision:4,next_fire_at:'2026-11-01T14:00:00+00:00'};
 const mutate=vi.fn(async(_action,body)=>({ok:true,operation_id:body.operation_id}));
 const controls={list:async()=>({jobs:[job],scheduler:'jaeger'}),operation:vi.fn(),mutate,history:vi.fn()}as unknown as ScheduleControls;
 const el=document.createElement('div');document.body.append(el);const root=createRoot(el);await act(async()=>root.render(<AutomationsPanel controls={controls}/>));
 expect(el.textContent).toContain('America/New_York');expect(el.textContent).toContain('2026-11-01T14:00:00+00:00');
 await act(async()=>[...el.querySelectorAll('button')].find(b=>b.textContent==='Edit automation')!.click());
 expect((el.querySelector('[aria-label="Automation timezone"]')as HTMLInputElement).value).toBe('America/New_York');
 await act(async()=>el.querySelector('form')!.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})));
 expect(mutate).toHaveBeenCalledWith('update',expect.objectContaining({timezone:'America/New_York',expected_revision:4,job_id:'zone-fixture'}));
 await act(async()=>root.unmount());el.remove();localStorage.clear();
});
