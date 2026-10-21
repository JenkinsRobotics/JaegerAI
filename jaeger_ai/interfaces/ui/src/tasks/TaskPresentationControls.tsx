import {useRef,useState} from 'react';
import type {Task,TaskPresentationAction,TaskPresentationIntent,TaskPresentationReceipt} from '../api/types';
import type {JaegerSource} from '../api/source';
const key=(id:string)=>'jaeger.ui.task-presentation.v1.'+encodeURIComponent(id);
export function TaskPresentationControls({task,controls,changed}:{task:Task;controls:NonNullable<JaegerSource['taskPresentation']>;changed:()=>void}){
 const [pending,setPending]=useState<TaskPresentationIntent|undefined>(()=>{try{const raw=localStorage.getItem(key(task.task_id));if(!raw)return;const value=JSON.parse(raw);if(typeof value.operation_id!=='string'||typeof value.action!=='string'||typeof value.expected_revision!=='number'||typeof value.expected_updated_at!=='number')throw Error();return value;}catch{return {operation_id:'invalid-preserved-intent',action:'pin',expected_revision:-1,expected_updated_at:-1};}});
 const [busy,setBusy]=useState(false),[error,setError]=useState<string>(),[notice,setNotice]=useState<string>();const lock=useRef(false);
 const settle=(receipt:TaskPresentationReceipt,intent:TaskPresentationIntent)=>{
  if(receipt.scope!=='task_presentation'||receipt.task_id!==task.task_id||receipt.operation_id!==intent.operation_id||receipt.action!==intent.action||typeof receipt.ok!=='boolean')throw Error('Foreign or incomplete task receipt; original intent retained');
  if(receipt.ok&&(!receipt.presentation||receipt.presentation.revision!==intent.expected_revision+1||typeof receipt.presentation.pinned!=='boolean'||typeof receipt.presentation.todo_done!=='boolean'||typeof receipt.presentation.unread!=='boolean'))throw Error('Incomplete task outcome; original intent retained');
  if(localStorage.getItem(key(task.task_id))!==JSON.stringify(intent))throw Error('Task intent changed in another window; original preserved');
  localStorage.removeItem(key(task.task_id));setPending(undefined);changed();
  if(!receipt.ok)throw Error(receipt.error??'Task changed; refresh and review');
  setNotice('Original presentation change recorded. Refreshing saved task; execution/result are unchanged.');
 };
 const run=async(action?:TaskPresentationAction)=>{
  if(lock.current)return;lock.current=true;setBusy(true);setError(undefined);setNotice(undefined);
  try{
   if(pending){if(action)return;const row=await controls.operation(task.task_id,pending.operation_id);if(!row.receipt)throw Error('Original outcome unknown; no resubmission');settle(row.receipt,pending);return;}
   if(!action||!task.presentation||typeof task.updated_at!=='number')return;
   if(localStorage.getItem(key(task.task_id)))throw Error('Another task intent is pending in this profile; reload to inspect it');
   const intent={operation_id:crypto.randomUUID(),action,expected_revision:task.presentation.revision,expected_updated_at:task.updated_at};
   localStorage.setItem(key(task.task_id),JSON.stringify(intent));setPending(intent);settle(await controls.change(task.task_id,intent),intent);
  }catch(e){setError(String(e));}finally{lock.current=false;setBusy(false);}
 };
 const p=task.presentation!;
 return <section aria-label={`Task presentation ${task.task_id}`}><p>{p.pinned?'Pinned · ':''}{p.unread?'Unread':'Read'} · To-do {p.todo_done?'done':'open'}. To-do completion is your checklist only; execution status, failure reason and approvals stay unchanged.</p>{error&&<p role="alert">{error}</p>}{notice&&<p role="status">{notice}</p>}{pending?<><p>Saved presentation intent needs reconciliation; nothing is repeated automatically.</p><button type="button" disabled={busy} onClick={()=>void run()}>Check original task change</button></>:<><button type="button" disabled={busy} onClick={()=>void run(p.pinned?'unpin':'pin')}>{p.pinned?'Unpin task':'Pin task'}</button><button type="button" disabled={busy} onClick={()=>void run(p.unread?'mark_read':'mark_unread')}>{p.unread?'Mark task as read':'Mark task as unread'}</button><button type="button" disabled={busy} onClick={()=>void run(p.todo_done?'todo_open':'todo_done')}>{p.todo_done?'Reopen to-do':'Mark to-do done'}</button></>}</section>;
}
