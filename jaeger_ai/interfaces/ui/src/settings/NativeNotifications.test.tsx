import{NATIVE_NOTIFICATION_KEY}from'../platform/nativeNotifications';
import {act} from 'react';import {createRoot} from 'react-dom/client';import {expect,it,vi} from 'vitest';
import {NativeNotifications} from './NativeNotifications';
(globalThis as {IS_REACT_ACT_ENVIRONMENT?:boolean}).IS_REACT_ACT_ENVIRONMENT=true;
async function mount(post:NonNullable<Window['jaegerNative']>['post'],run:(host:HTMLDivElement)=>Promise<void>){const previous=window.jaegerNative;window.jaegerNative={post};const host=document.createElement('div');document.body.append(host);const root=createRoot(host);try{await act(async()=>root.render(<NativeNotifications/>));await run(host);}finally{await act(async()=>root.unmount());host.remove();window.jaegerNative=previous;}}
it('reads denied permission without requesting permission or sending a notification',async()=>{
 const post=vi.fn(async()=>({authorization:'denied',permission_requested:false}));
 await mount(post,async host=>{expect(post).toHaveBeenCalledExactlyOnceWith('notifications.status');expect((Array.from(host.querySelectorAll('button')).find(b=>b.textContent==='Send local notification check')! as HTMLButtonElement).disabled).toBe(true);});
});
it('reports only OS submission acceptance and never retries an uncertain submission',async()=>{
 const post=vi.fn().mockResolvedValueOnce({authorization:'authorized',permission_requested:false}).mockRejectedValueOnce(Error('lost submission reply'));
 await mount(post,async host=>{await act(async()=>[...host.querySelectorAll('button')].find(b=>b.textContent==='Send local notification check')!.click());expect(post).toHaveBeenCalledTimes(2);expect(host.textContent).toContain('submission may be unknown');expect(host.textContent).not.toContain('macOS accepted');});
});

it('persists the independent badge preference and explicitly clears it without banners or OS consent',async()=>{
 localStorage.removeItem(NATIVE_NOTIFICATION_KEY);
 const post=vi.fn(async(type:string,payload?:unknown)=>{if(type==='notifications.status')return{authorization:'denied',permission_requested:false,activity_badge_available:true};if(type==='notifications.badge'){expect(payload).toEqual({state:'off'});return{applied:true,state:'off'};}throw Error('Unexpected permission, service or banner command');});
 window.jaegerNative={post};const el=document.createElement('div');document.body.append(el);const root=createRoot(el);
 try{
  await act(async()=>root.render(<NativeNotifications/>));
  const checkbox=[...el.querySelectorAll('label')].find(row=>row.textContent?.includes('Show retained unread activity'))!.querySelector<HTMLInputElement>('input')!;
  expect(checkbox.disabled).toBe(false);await act(async()=>checkbox.click());
  expect(JSON.parse(localStorage.getItem(NATIVE_NOTIFICATION_KEY)!)).toMatchObject({enabled:false,badge:true});
  await act(async()=>checkbox.click());expect(JSON.parse(localStorage.getItem(NATIVE_NOTIFICATION_KEY)!)).toMatchObject({enabled:false,badge:false});
  expect(post.mock.calls.filter(row=>row[0]==='notifications.badge')).toHaveLength(1);expect(post.mock.calls.some(row=>row[0]==='notify')).toBe(false);
 }finally{await act(async()=>root.unmount());el.remove();delete window.jaegerNative;localStorage.removeItem(NATIVE_NOTIFICATION_KEY);}
});
