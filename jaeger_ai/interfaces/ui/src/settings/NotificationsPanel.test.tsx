import {act} from 'react';
import {createRoot} from 'react-dom/client';
import {expect,it,vi} from 'vitest';
import {NotificationsPanel} from './NotificationsPanel';
import type {Notifications} from '../api/source';
(globalThis as {IS_REACT_ACT_ENVIRONMENT?:boolean}).IS_REACT_ACT_ENVIRONMENT=true;
it('advances the disclosed displayed-and-earlier watermark and retains rejected preference drafts',async()=>{
 const key='jaeger.ui.notifications.draft.v1';localStorage.removeItem(key);
 const preferences={revision:3,enabled:true,muted_agent_ids:[],read_through:0};
 const read=vi.fn(async()=>({preferences,notifications:[{event_id:12,session_id:'owned-home',title:'Approval requested',timestamp:1,unread:true}],privacy:'metadata_only_no_message_preview',enabled:true}));
 const markRead=vi.fn(async(through:number)=>({preferences:{...preferences,read_through:through}}));
 const save=vi.fn(async()=>{throw Error('Preferences changed');}),host=document.createElement('div');document.body.append(host);const root=createRoot(host);
 try{
  await act(async()=>root.render(<NotificationsPanel controls={{read,markRead,save} as Notifications} agents={[]} onOpen={()=>{}}/>));
  await act(async()=>[...host.querySelectorAll('button')].find(b=>b.textContent==='Mark displayed and earlier notifications read')!.click());
  expect(markRead).toHaveBeenCalledExactlyOnceWith(12);
  await act(async()=>[...host.querySelectorAll('button')].find(b=>b.textContent==='Save notification preferences')!.click());
  expect(save).toHaveBeenCalledExactlyOnceWith({expected_revision:3,enabled:true,muted_agent_ids:[]});
  expect(host.textContent).toContain('Preferences changed');expect(localStorage.getItem(key)).not.toBeNull();
  expect(host.textContent).not.toContain('Saved notification preferences.');
 }finally{await act(async()=>root.unmount());host.remove();localStorage.removeItem(key);}
});
it('loads older metadata without duplicates and requests a real backend category',async()=>{
 const key='jaeger.ui.notifications.draft.v1';localStorage.removeItem(key);
 const preferences={revision:0,enabled:true,muted_agent_ids:[],read_through:0};const row={event_id:40,session_id:'owned-home',title:'Approval requested',timestamp:1,unread:true};
 const base={preferences,privacy:'metadata_only_no_message_preview',enabled:true,categories:[{id:'all',label:'All activity'},{id:'approvals',label:'Approvals'}]};
 const read=vi.fn().mockResolvedValueOnce({...base,notifications:[row],next_before:40}).mockResolvedValueOnce({...base,notifications:[{...row,event_id:20}],next_before:null}).mockResolvedValue({...base,notifications:[row],next_before:null});
 const host=document.createElement('div');document.body.append(host);const root=createRoot(host);
 try{
  await act(async()=>root.render(<NotificationsPanel controls={{read,save:vi.fn(),markRead:vi.fn()}} agents={[]} onOpen={()=>{}}/>));
  await act(async()=>[...host.querySelectorAll('button')].find(b=>b.textContent==='Load earlier notifications')!.click());expect(read).toHaveBeenNthCalledWith(2,{category:'all',before:40});expect(host.querySelectorAll('article')).toHaveLength(2);
  const select=host.querySelector<HTMLSelectElement>('select[aria-label="Notification category"]')!;await act(async()=>{select.value='approvals';select.dispatchEvent(new Event('change',{bubbles:true}));});expect(read).toHaveBeenLastCalledWith({category:'approvals'});expect(host.querySelectorAll('article')).toHaveLength(1);
 }finally{await act(async()=>root.unmount());host.remove();localStorage.removeItem(key);}
});
