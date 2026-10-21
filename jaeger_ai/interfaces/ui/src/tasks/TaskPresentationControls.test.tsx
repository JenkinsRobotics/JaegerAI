import {act} from 'react';import {createRoot} from 'react-dom/client';import {afterEach,it,expect,vi} from 'vitest';
import {TaskPresentationControls} from './TaskPresentationControls';import type {Task,TaskPresentationIntent,TaskPresentationReceipt} from '../api/types';
(globalThis as {IS_REACT_ACT_ENVIRONMENT?:boolean}).IS_REACT_ACT_ENVIRONMENT=true;
afterEach(()=>localStorage.clear());
const task:Task={task_id:'owned-task',state:'failed',updated_at:12,presentation:{revision:0,pinned:false,todo_done:false,read_updated_at:0,unread_override:false,unread:true}};
const receipt=(body:TaskPresentationIntent):TaskPresentationReceipt=>({ok:true,scope:'task_presentation',actor:'webui',task_id:task.task_id,operation_id:body.operation_id,action:body.action,http_status:200,presentation:{...task.presentation!,revision:1,pinned:true}});
it('retains lost-ACK intent and checks original receipt after remount without repeat',async()=>{
 let intent:TaskPresentationIntent;const change=vi.fn(async(_id,body)=>{intent=body;throw Error('lost ACK');});const operation=vi.fn(async()=>({receipt:receipt(intent!)}));const changed=vi.fn();
 const el=document.createElement('div');document.body.append(el);let root=createRoot(el);await act(async()=>root.render(<TaskPresentationControls task={task} controls={{change,operation}} changed={changed}/>));
 await act(async()=>[...el.querySelectorAll('button')].find(b=>b.textContent==='Pin task')!.click());expect(change).toHaveBeenCalledTimes(1);expect(el.textContent).toContain('needs reconciliation');
 await act(async()=>root.unmount());root=createRoot(el);await act(async()=>root.render(<TaskPresentationControls task={task} controls={{change,operation}} changed={changed}/>));
 await act(async()=>[...el.querySelectorAll('button')].find(b=>b.textContent==='Check original task change')!.click());expect(change).toHaveBeenCalledTimes(1);expect(operation).toHaveBeenCalledWith('owned-task',intent!.operation_id);expect(changed).toHaveBeenCalledTimes(1);expect(localStorage.getItem('jaeger.ui.task-presentation.v1.owned-task')).toBeNull();expect(el.textContent).toContain('execution/result are unchanged');
 await act(async()=>root.unmount());el.remove();
});
it('rejects a foreign or incomplete success without clearing original intent',async()=>{
 const changed=vi.fn();const change=vi.fn(async(_id,body)=>({...receipt(body),task_id:'foreign'}));const el=document.createElement('div');document.body.append(el);const root=createRoot(el);await act(async()=>root.render(<TaskPresentationControls task={task} controls={{change,operation:vi.fn()}} changed={changed}/>));await act(async()=>[...el.querySelectorAll('button')].find(b=>b.textContent==='Mark to-do done')!.click());expect(el.textContent).toContain('Foreign or incomplete');expect(changed).not.toHaveBeenCalled();expect(localStorage.getItem('jaeger.ui.task-presentation.v1.owned-task')).not.toBeNull();await act(async()=>root.unmount());el.remove();
});
