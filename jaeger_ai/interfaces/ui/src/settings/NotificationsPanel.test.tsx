import {act} from 'react';
import {createRoot} from 'react-dom/client';
import {expect,it,vi} from 'vitest';
import {NotificationsPanel} from './NotificationsPanel';
import type {Notifications} from '../api/source';
(globalThis as {IS_REACT_ACT_ENVIRONMENT?:boolean}).IS_REACT_ACT_ENVIRONMENT=true;
it('marks only displayed notifications read and retains rejected preference drafts',async()=>{
 const key='jaeger.ui.notifications.draft.v1';localStorage.removeItem(key);
 const preferences={revision:3,enabled:true,muted_agent_ids:[],read_through:0};
 const read=vi.fn(async()=>({preferences,notifications:[{event_id:12,session_id:'owned-home',title:'Approval requested',timestamp:1,unread:true}],privacy:'metadata_only_no_message_preview',enabled:true}));
 const markRead=vi.fn(async(through:number)=>({preferences:{...preferences,read_through:through}}));
 const save=vi.fn(async()=>{throw Error('Preferences changed');}),host=document.createElement('div');document.body.append(host);const root=createRoot(host);
 try{
  await act(async()=>root.render(<NotificationsPanel controls={{read,markRead,save} as Notifications} agents={[]} onOpen={()=>{}}/>));
  await act(async()=>[...host.querySelectorAll('button')].find(b=>b.textContent==='Mark displayed notifications read')!.click());
  expect(markRead).toHaveBeenCalledExactlyOnceWith(12);
  await act(async()=>[...host.querySelectorAll('button')].find(b=>b.textContent==='Save notification preferences')!.click());
  expect(save).toHaveBeenCalledExactlyOnceWith({expected_revision:3,enabled:true,muted_agent_ids:[]});
  expect(host.textContent).toContain('Preferences changed');expect(localStorage.getItem(key)).not.toBeNull();
  expect(host.textContent).not.toContain('Saved notification preferences.');
 }finally{await act(async()=>root.unmount());host.remove();localStorage.removeItem(key);}
});
