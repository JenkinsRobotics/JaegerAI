import type {Agent,SessionDetail} from '../api/types';
export type NotificationNavigation={target:'notifications'}|{target:'conversation';session_id:string};
export function notificationNavigation(value:unknown):NotificationNavigation|null{
 if(!value||typeof value!=='object')return null;const row=value as Record<string,unknown>;
 if(Object.keys(row).length===1&&row.target==='notifications')return {target:'notifications'};
 if(Object.keys(row).length===2&&row.target==='conversation'&&typeof row.session_id==='string'&&/^[A-Za-z0-9_.:-]{1,256}$/.test(row.session_id))return {target:'conversation',session_id:row.session_id};
 return null;
}
/** Native route data never establishes access or the selected bot. */
export async function notificationConversation(read:(id:string)=>Promise<SessionDetail>,agents:Agent[],id:string){
 if(!notificationNavigation({target:'conversation',session_id:id}))throw Error('Invalid notification conversation identity');
 const session=await read(id);
 if(session.session_id!==id||!session.agent_id||!agents.some(a=>a.id===session.agent_id))throw Error('Notification conversation is unavailable or has no exposed bot identity');
 return {type:'agent' as const,agentId:session.agent_id,sessionId:session.session_id};
}

export function localConversationLink(id:string){
 if(!notificationNavigation({target:'conversation',session_id:id})||id==='.'||id==='..')throw Error('This conversation identity has no supported local deep link');
 return 'jaeger://conversation/'+encodeURIComponent(id);
}
