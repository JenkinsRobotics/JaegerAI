import {useEffect,useRef} from 'react';
import {nativeBridge,onNativeEvent} from './native';
import {notificationNavigation,type NotificationNavigation} from './notificationNavigation';
/** Peek/ack prevents a click being lost before renderer/registry readiness. */
export function useNotificationNavigation(ready:boolean,open:(route:NotificationNavigation)=>void){
 const latest=useRef(open);latest.current=open;const handled=useRef(new Set<string>());
 useEffect(()=>{
  const bridge=nativeBridge();if(!ready||!bridge)return;let active=true,busy=false,again=false;
  const take=async()=>{if(busy){again=true;return;}busy=true;try{
   const receipt=await bridge.post('notifications.navigation') as {navigation?:{id?:unknown;destination?:unknown}};if(!active)return;
   if(receipt?.navigation==null)return;const pending=receipt.navigation,route=notificationNavigation(pending.destination);
   if(typeof pending.id!=='string'||! /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i.test(pending.id)||!route)throw Error('Invalid native notification destination; no navigation performed');
   if(!handled.current.has(pending.id)){if(handled.current.size>=128)handled.current.clear();handled.current.add(pending.id);latest.current(route);}
   // This acknowledges transient UI navigation only, never admission/approval.
   await bridge.post('notifications.navigationAck',{id:pending.id});
  }catch(e){if(active)window.dispatchEvent(new CustomEvent('jaeger:native-notification-status',{detail:'Notification navigation unavailable: '+String(e)}));}finally{busy=false;if(again&&active){again=false;void take();}}};
  const remove=onNativeEvent(detail=>{if(detail.type==='notification.open')void take();});void take();
  return()=>{active=false;remove();};
 },[ready]);
}
