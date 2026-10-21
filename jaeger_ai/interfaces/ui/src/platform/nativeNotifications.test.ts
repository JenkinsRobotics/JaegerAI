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
it.each([true,false])('routes one-session summaries to that session and mixed summaries to inbox, same=%s',async(same)=>{
 const prior=Object.getOwnPropertyDescriptor(navigator,'locks');Object.defineProperty(navigator,'locks',{value:{request:async(_n:unknown,_o:unknown,fn:(lock:object)=>Promise<void>)=>fn({})},configurable:true});
 localStorage.removeItem(NATIVE_NOTIFICATION_CURSOR);localStorage.setItem(NATIVE_NOTIFICATION_KEY,JSON.stringify({enabled:true,quiet:false,start:'22:00',end:'08:00'}));
 let through=10;const read:Notifications['read']=async()=>({privacy:'metadata_only_no_message_preview',enabled:true,preferences:{revision:0,enabled:true,muted_agent_ids:[],read_through:0},observed_through:through,notifications:through===10?[]:[{event_id:11,session_id:'owned-beta-home',title:'Task updated',timestamp:1,unread:true},{event_id:12,session_id:same?'owned-beta-home':'owned-alpha-home',title:'Approval requested',timestamp:1,unread:true}]});
 const post=vi.fn(async(type:string,_payload?:unknown)=>type==='notifications.status'?{authorization:'authorized',permission_requested:false}:{accepted:true,permission_requested:false,notification_id:'owned-summary'});
 try{
  const consumer=new NativeNotificationConsumer(read,{post});await consumer.poll();through=12;await consumer.poll();
  const summary=post.mock.calls.find(row=>row[0]==='notify')![1] as {session_id?:string;body:string};
  expect(summary.session_id).toBe(same?'owned-beta-home':undefined);expect(summary.body).not.toContain('conversation content');
  await consumer.poll();expect(post.mock.calls.filter(row=>row[0]==='notify')).toHaveLength(1);
 }finally{localStorage.removeItem(NATIVE_NOTIFICATION_KEY);localStorage.removeItem(NATIVE_NOTIFICATION_CURSOR);if(prior)Object.defineProperty(navigator,'locks',prior);else Reflect.deleteProperty(navigator,'locks');}
});
it('badge-only preference uses authoritative retained presence without banners, cursor writes or permission requests',async()=>{
 const prior=Object.getOwnPropertyDescriptor(navigator,'locks');Object.defineProperty(navigator,'locks',{value:{request:async(_n:unknown,_o:unknown,fn:(lock:object)=>Promise<void>)=>fn({})},configurable:true});
 localStorage.removeItem(NATIVE_NOTIFICATION_CURSOR);localStorage.setItem(NATIVE_NOTIFICATION_KEY,JSON.stringify({enabled:false,badge:true,quiet:true,start:'00:00',end:'00:00'}));
 let presence:'present'|'unknown'|'absent'='present';const read:Notifications['read']=async()=>({preferences:{revision:0,enabled:true,muted_agent_ids:[],read_through:0},privacy:'metadata_only_no_message_preview',enabled:true,observed_through:1,notifications:[],retained_unread_presence:presence});
 const post=vi.fn(async(type:string,payload?:unknown)=>{if(type==='notifications.status')return{authorization:'denied',permission_requested:false,activity_badge_available:true};if(type==='notifications.badge')return{applied:true,state:(payload as {state:string}).state,scope:'menu_bar_retained_activity_presence'};throw Error('Badge must not request permission or submit a banner');});
 try{
  const consumer=new NativeNotificationConsumer(read,{post});await consumer.poll();presence='unknown';await consumer.poll();presence='absent';await consumer.poll();
  expect(post.mock.calls.filter(row=>row[0]==='notifications.badge').map(row=>row[1])).toEqual([{state:'present'},{state:'unknown'},{state:'absent'}]);expect(localStorage.getItem(NATIVE_NOTIFICATION_CURSOR)).toBeNull();
 }finally{localStorage.removeItem(NATIVE_NOTIFICATION_KEY);localStorage.removeItem(NATIVE_NOTIFICATION_CURSOR);if(prior)Object.defineProperty(navigator,'locks',prior);else Reflect.deleteProperty(navigator,'locks');}
});
