import{act}from'react';import{createRoot}from'react-dom/client';import{it,expect,vi}from'vitest';import{AutomationsPanel,simpleTiming}from'./AutomationsPanel';import type{ScheduleControls}from'../api/source';
(globalThis as {IS_REACT_ACT_ENVIRONMENT?:boolean}).IS_REACT_ACT_ENVIRONMENT=true;
it('shows daily and weekday cron rules as simple times without rewriting custom schedules',()=>{
 expect(simpleTiming('30 9 * * 1-5')).toEqual({minute:30,hour:9,days:'1-5'});
 expect(simpleTiming('0 17 * * *')).toEqual({minute:0,hour:17,days:'*'});
 expect(simpleTiming('0 9 * * 1,3,5')).toBeUndefined();
 expect(simpleTiming('60 24 * * *')).toBeUndefined();
});
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
 expect(el.textContent).toContain('America/New_York');expect(el.querySelector('time')?.dateTime).toBe('2026-11-01T14:00:00+00:00');
 await act(async()=>[...el.querySelectorAll('button')].find(b=>b.textContent==='Edit automation')!.click());
 expect((el.querySelector('[aria-label="Automation timezone"]')as HTMLInputElement).value).toBe('America/New_York');
 await act(async()=>el.querySelector('form')!.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})));
 expect(mutate).toHaveBeenCalledWith('update',expect.objectContaining({timezone:'America/New_York',expected_revision:4,job_id:'zone-fixture'}));
 await act(async()=>root.unmount());el.remove();localStorage.clear();
});
it('shows loading and read errors without discarding schedules already loaded',async()=>{
 let resolve!: (value:{jobs:unknown[];scheduler:string})=>void;
 const job={id:'owned',name:'owned',prompt:'Saved objective',cron:'0 9 * * *',enabled:true,state:'active'};
 const list=vi.fn().mockImplementationOnce(()=>new Promise(r=>{resolve=r;})).mockRejectedValueOnce(Error('offline'));
 const controls={list,operation:vi.fn(),mutate:vi.fn(),history:vi.fn()}as unknown as ScheduleControls;
 const el=document.createElement('div');document.body.append(el);const root=createRoot(el);
 try {
  await act(async()=>root.render(<AutomationsPanel controls={controls}/>));
  expect(el.querySelector('[role="status"][aria-label="Loading"]')).not.toBeNull();
  await act(async()=>resolve({jobs:[job],scheduler:'jaeger'}));
  expect(el.querySelector('[aria-label="Schedules"]')?.textContent).toContain('owned');
  await act(async()=>[...el.querySelectorAll('button')].find(b=>b.textContent==='Refresh automations')!.click());
  expect(el.textContent).toContain('offline');
  expect(el.querySelector('[aria-label="Schedules"]')?.textContent).toContain('owned');
 } finally {await act(async()=>root.unmount());el.remove();}
});
