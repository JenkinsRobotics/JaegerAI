import {ChannelDeliveries} from './ChannelDeliveries';
import { ChannelControls } from './ChannelControls';
import type { Agent } from '../api/types';
import { useEffect, useState } from 'react';
import type { ChannelSnapshot, JaegerSource } from '../api/source';
import { WidgetCard } from '../widgets/primitives/WidgetCard';
export function ChannelsPanel({ source, agents=[] }: { source: JaegerSource; agents?:Agent[] }) {
  const [snapshot, setSnapshot] = useState<ChannelSnapshot>(), [attempt, setAttempt] = useState(0), [error, setError] = useState<string>();
  useEffect(()=>{let live=true;void source.channels?.().then(value=>{if(live){setSnapshot(value);setError(undefined);}},e=>{if(live)setError(String(e));});return()=>{live=false;};},[source,attempt]);
  return <section aria-label="Messaging channels"><p>Registrations in the current Gateway. Connection health and message delivery have not been checked. Other running processes are outside this view.</p>
    <button type="button" onClick={()=>setAttempt(n=>n+1)}>Refresh channel status</button>
    {error&&<WidgetCard title="Messaging channels status" state="error" message={`Could not read channels: ${error}. Previous status retained.`}/>}{!snapshot&&!error&&<WidgetCard title="Messaging channels status" state="loading" message="Reading channel status…"/>}
    {source.channelDeliveries&&<ChannelDeliveries read={source.channelDeliveries.bind(source)}/>}
    {snapshot&&snapshot.channels.length===0&&<WidgetCard title="Messaging channels status" state="empty" message="No channels registered in this Gateway."/>}
    {snapshot?.channels.map(channel=><WidgetCard title={channel.name} key={channel.id}><p>{channel.bridge_registered?'Bridge registered':channel.adapter_registered?'Adapter registered; bridge unobserved':'Not registered in this Gateway'}</p><small>Catalog: {channel.catalog_maturity} · Transport thread: {channel.thread_state}</small><p>Saved inbox bot: {channel.binding?.agent_id??'unassigned'} · Active Gateway inbox binding: {channel.active_binding?.agent_id??'not observed'} · {channel.active_handlers??0} active handlers</p>{source.channelControls&&<ChannelControls controls={source.channelControls} channel={channel} agents={agents} refresh={()=>setAttempt(n=>n+1)}/>}<p>Incoming content is data, not authority. Automatic model replies are not enabled by connecting.</p></WidgetCard>)}
  </section>;
}
