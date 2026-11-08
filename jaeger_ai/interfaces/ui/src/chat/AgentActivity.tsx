import type {ChatTurn} from './host';
import {Bot} from '../components/Icons';

/** Only recorded handoffs, never inferred agent execution or completion. */
export function agentActivity(turns:ChatTurn[]) {
 const turn=turns.filter(t=>t.state==='pending').at(-1) ?? turns.at(-1);
 const agents=new Map<string,{id:string;name:string;handoffId:string;status:string}>();
 for(const part of turn?.parts??[]) {
  if(part.kind!=='handoff')continue;
  const status=part.direction==='from'?'Replied':part.status==='delivered'?'Messaged':part.status==='pending_approval'?'Awaiting approval':['failed','execution_unknown'].includes(part.status??'')?'Delivery unconfirmed':['denied','rejected','cancelled'].includes(part.status??'')?'Not sent':'Message requested';
  for(const agent of part.agents??[{id:part.agentId,name:part.agentName}])
   agents.set(agent.id,{...agent,handoffId:part.handoffId,status});
 }
 return [...agents.values()];
}

export function AgentActivity({turns,onOpen}:{turns:ChatTurn[];onOpen?:(id:string)=>void}) {
 const agents=agentActivity(turns);
 if(!agents.length)return null;
 return <details className="jg-agent-activity">
  <summary><Bot size={18}/><span>{agents.length} {agents.length===1?'agent':'agents'}</span></summary>
  <ul aria-label="Agent activity">{agents.map(agent=><li key={agent.id}>
   {onOpen?<button type="button" onClick={()=>onOpen(agent.handoffId)}>{agent.name}</button>:<span>{agent.name}</span>}
   <small>{agent.status}</small>
  </li>)}</ul>
 </details>;
}
