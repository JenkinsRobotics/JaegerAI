/* One device consumer of the existing notification feed. No permission request, model work or new service. */
import type {Notifications} from '../api/source';import type {JaegerNativeBridge} from './native';
export const NATIVE_NOTIFICATION_KEY='jaeger.ui.native-notifications.v1';
export const NATIVE_NOTIFICATION_CURSOR='jaeger.ui.native-notifications.cursor.v1';
export const NATIVE_NOTIFICATION_CHANGED='jaeger:native-notification-preferences';
export interface NativeNotificationPreferences {enabled:boolean;badge?:boolean;quiet:boolean;start:string;end:string;revision?:number}
const defaults:NativeNotificationPreferences={enabled:false,badge:false,quiet:false,start:'22:00',end:'08:00',revision:0};
function valid(value:NativeNotificationPreferences){return (value.badge===undefined||typeof value.badge==='boolean')&&typeof value.enabled==='boolean'&&typeof value.quiet==='boolean'&&[value.start,value.end].every(s=>typeof s==='string'&&/^([01]\d|2[0-3]):[0-5]\d$/.test(s))&&(value.revision===undefined||Number.isSafeInteger(value.revision)&&value.revision>=0);}
export function nativeNotificationPreferences():NativeNotificationPreferences{
 const raw=localStorage.getItem(NATIVE_NOTIFICATION_KEY);if(!raw)return {...defaults};const value=JSON.parse(raw);
 if(!valid(value))throw Error('Invalid native notification preferences; original retained');
 return value;
}
export function saveNativeNotificationPreferences(value:NativeNotificationPreferences){
 const old=nativeNotificationPreferences();if(!valid(value))throw Error('Invalid quiet hours; original preferences preserved');
 const saved={...value,revision:(old.revision??0)+1};
 // Enabling starts with a fresh observed baseline; no backlog is submitted.
 if(!old.enabled&&value.enabled)localStorage.removeItem(NATIVE_NOTIFICATION_CURSOR);
 localStorage.setItem(NATIVE_NOTIFICATION_KEY,JSON.stringify(saved));window.dispatchEvent(new Event(NATIVE_NOTIFICATION_CHANGED));return saved;
}
export function quietNow(prefs:NativeNotificationPreferences,date:Date){
 if(!prefs.quiet)return false;const minute=(s:string)=>Number(s.slice(0,2))*60+Number(s.slice(3));const start=minute(prefs.start),end=minute(prefs.end),now=date.getHours()*60+date.getMinutes();
 return start===end|| (start<end?now>=start&&now<end:now>=start||now<end);
}
export class NativeNotificationConsumer{
 private busy=false;private active=true;
 dispose(){this.active=false;}
 constructor(private read:Notifications['read'],private bridge:JaegerNativeBridge,private report:(message:string)=>void=()=>{}){}
 async poll(now=new Date()){
  try{const prefs=nativeNotificationPreferences();if(!prefs.enabled&&!prefs.badge)return;}catch(e){this.report(String(e));return;}
  if(typeof navigator==='undefined'||!navigator.locks){this.report('Exclusive native notification coordination unavailable; automatic notifications inactive.');return;}
  try{await navigator.locks.request('jaeger.native-notifications.v1',{ifAvailable:true},async lock=>{if(lock&&this.active)await this.consume(now);});}catch(e){this.report(`Exclusive notification coordination failed: ${String(e)}; automatic delivery inactive.`);}
 }
 private async consume(now:Date){
  if(this.busy)return;this.busy=true;
  try{
   const prefs=nativeNotificationPreferences();if(!this.active||!prefs.enabled&&!prefs.badge)return;
   const feed=await this.read();if(!this.active)return;const through=feed.observed_through;
   if(typeof through!=='number'||!Number.isSafeInteger(through)||through<0)throw Error('This Gateway lacks the observed notification cursor; native relay inactive');
   let badgeStatus:{authorization?:string;permission_requested?:boolean;activity_badge_available?:boolean}|undefined;
   if(prefs.badge){
    const current=nativeNotificationPreferences();if(!this.active||(current.revision??0)!==(prefs.revision??0))return;
    try{
     badgeStatus=await this.bridge.post('notifications.status') as typeof badgeStatus;
     const latest=nativeNotificationPreferences();if(!this.active||!latest.badge||(latest.revision??0)!==(prefs.revision??0))return;
     if(badgeStatus?.activity_badge_available!==true)this.report('This shell has no supported menu-bar activity badge; no Dock or permission change attempted.');
     else{
      const state=!feed.preferences.enabled?'absent':feed.retained_unread_presence??'unknown';
      if(!['present','absent','unknown'].includes(state))throw Error('Unknown retained-activity presence contract');
      const receipt=await this.bridge.post('notifications.badge',{state}) as {applied?:boolean;state?:string;scope?:string};
      if(receipt?.applied!==true||receipt.state!==state||receipt.scope!=='menu_bar_retained_activity_presence')throw Error('Native badge application not acknowledged');
     }
    }catch(e){this.report('Activity badge state unconfirmed: '+String(e));}
   }
   if(!prefs.enabled)return; // badge preference never enables banner submission/cursor admission
   const raw=localStorage.getItem(NATIVE_NOTIFICATION_CURSOR);const previous=raw?JSON.parse(raw):undefined;
   if(previous&&(!Number.isSafeInteger(previous.through)||previous.through<0))throw Error('Native notification cursor invalid; original retained');
   const write=(state:string,notificationId?:string)=>localStorage.setItem(NATIVE_NOTIFICATION_CURSOR,JSON.stringify({through,state,notificationId}));
   if(!previous){write('baseline');return;}
   if(through<previous.through)throw Error('Notification history cursor moved backwards; relay paused without replay');
   if(!feed.preferences.enabled||quietNow(prefs,now)){write('suppressed');return;}
   const incoming=feed.notifications.filter(n=>n.unread&&n.event_id>previous.through&&n.event_id<=through);
   if(!incoming.length){write('observed');return;}
   const status=badgeStatus??await this.bridge.post('notifications.status') as {authorization?:string;permission_requested?:boolean};
   if(status?.permission_requested!==false||!['authorized','provisional'].includes(status.authorization??'')){write('not_authorized');this.report('Native permission unavailable; no permission requested or backlog queued.');return;}
   const current=nativeNotificationPreferences();if(!this.active||!current.enabled||(current.revision??0)!==(prefs.revision??0))return;
   // Claim the cursor before native IPC. Lost/unknown replies are never retried after reload.
   write('submission_unknown');
   const sessions=[...new Set(incoming.map(n=>n.session_id))];
   const sessionId=sessions.length===1&&/^[A-Za-z0-9_.:-]{1,256}$/.test(sessions[0])?sessions[0]:undefined;
   const receipt=await this.bridge.post('notify',{...(sessionId?{session_id:sessionId}:{}),title:incoming.length===1?incoming[0].title:'Jaeger activity updates',body:`${incoming.length} new activity notification${incoming.length===1?'':'s'}. Open Jaeger to review.`}) as {accepted?:boolean;permission_requested?:boolean;notification_id?:string};
   if(receipt?.accepted!==true||receipt.permission_requested!==false)throw Error('Native submission not acknowledged; no automatic retry');
   write('accepted',receipt.notification_id);this.report('macOS accepted an activity notification request; visible delivery unverified.');
  }catch(e){this.report(`${String(e)}. No automatic notification replay.`);}finally{this.busy=false;}
 }
}
