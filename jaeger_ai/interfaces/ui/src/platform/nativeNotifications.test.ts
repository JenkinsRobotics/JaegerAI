import {it,expect,vi} from 'vitest';import {NativeNotificationConsumer,NATIVE_NOTIFICATION_KEY,NATIVE_NOTIFICATION_CURSOR,quietNow,saveNativeNotificationPreferences,nativeNotificationPreferences} from './nativeNotifications';import type {Notifications} from '../api/source';
it('claims before IPC and never replays a lost submission after consumer restart',async()=>{
 const prior=Object.getOwnPropertyDescriptor(navigator,'locks');Object.defineProperty(navigator,'locks',{value:{request:async(_name:unknown,_opts:unknown,fn:(lock:object)=>Promise<void>)=>fn({})},configurable:true});
 localStorage.removeItem(NATIVE_NOTIFICATION_CURSOR);localStorage.setItem(NATIVE_NOTIFICATION_KEY,JSON.stringify({enabled:true,quiet:false,start:'22:00',end:'08:00'}));
 const prefs={revision:0,enabled:true,muted_agent_ids:[],read_through:0};let through=10;
 const read=vi.fn(async()=>({preferences:prefs,notifications:[{event_id:through,session_id:'owned-home',title:'Approval requested',timestamp:1,unread:true}],privacy:'metadata_only_no_message_preview',enabled:true,observed_through:through}));
 const post=vi.fn(async(type:string)=>{if(type==='notifications.status')return {authorization:'authorized',permission_requested:false};expect(JSON.parse(localStorage.getItem(NATIVE_NOTIFICATION_CURSOR)!).through).toBe(11);throw Error('lost native IPC reply');});
 const messages:string[]=[];
 try{
  const first=new NativeNotificationConsumer(read as Notifications['read'],{post},m=>messages.push(m));await first.poll();expect(post).not.toHaveBeenCalled();
  through=11;await first.poll();expect(post).toHaveBeenCalledTimes(2);expect(messages.join()).toContain('No automatic notification replay');
  await new NativeNotificationConsumer(read as Notifications['read'],{post}).poll();expect(post).toHaveBeenCalledTimes(2);
 }finally{localStorage.removeItem(NATIVE_NOTIFICATION_KEY);localStorage.removeItem(NATIVE_NOTIFICATION_CURSOR);if(prior)Object.defineProperty(navigator,'locks',prior);else Reflect.deleteProperty(navigator,'locks');}
});
it('validates quiet hours before writes and handles overnight and full-day quiet',()=>{
 localStorage.removeItem(NATIVE_NOTIFICATION_KEY);
 try{
  saveNativeNotificationPreferences({enabled:false,quiet:true,start:'22:00',end:'08:00'});const saved=localStorage.getItem(NATIVE_NOTIFICATION_KEY);
  expect(()=>saveNativeNotificationPreferences({enabled:false,quiet:true,start:'99:00',end:'08:00'})).toThrow();expect(localStorage.getItem(NATIVE_NOTIFICATION_KEY)).toBe(saved);
  const prefs=nativeNotificationPreferences();expect(quietNow(prefs,new Date(2026,9,20,23))).toBe(true);expect(quietNow(prefs,new Date(2026,9,20,7))).toBe(true);expect(quietNow(prefs,new Date(2026,9,20,12))).toBe(false);expect(quietNow({...prefs,start:'08:00'},new Date(2026,9,20,12))).toBe(true);
 }finally{localStorage.removeItem(NATIVE_NOTIFICATION_KEY);}
});
