import {useEffect,useRef} from 'react';
import type {ChatSession} from '../chat/host';
import {activityState,type ClipState} from './avatar';
/** Observe the chat's existing state, without another stream or execution owner. */
export function useChatAvatar(session:ChatSession|null,running:boolean,error:string|undefined,onState?: (state:ClipState)=>void) {
 const prior=useRef<{session:string;pending:Set<string>}>({session:'',pending:new Set()});
 const completion=useRef<{id:string;expires:number}|null>(null);
 useEffect(()=>{
  if(!onState)return;
  if(!session){prior.current={session:'',pending:new Set()};completion.current=null;onState(error?'connecting':'idle');return;}
  if(prior.current.session!==session.id){prior.current={session:session.id,pending:new Set()};completion.current=null;}
  const finished=session.turns.find(t=>prior.current.pending.has(t.turnId)&&t.state==='complete');
  const pending=session.turns.filter(t=>t.state==='pending');
  prior.current.pending=new Set(pending.map(t=>t.turnId));
  const last=pending.at(-1)||session.turns.at(-1);
  const state=error?'connecting':activityState(last,running);
  // Completion can arrive before the stream handle is released. Keep it latched.
  if(finished)completion.current={id:finished.turnId,expires:Date.now()+4000};
  if(pending.length)completion.current=null;
  if(state!=='idle'){onState(state);return;}
  if(completion.current && completion.current.expires>Date.now()){onState('milestone_level_up');const timer=setTimeout(()=>{completion.current=null;onState('idle');},completion.current.expires-Date.now());return()=>clearTimeout(timer);}
  onState('idle');
 },[session,running,error,onState]);
}
