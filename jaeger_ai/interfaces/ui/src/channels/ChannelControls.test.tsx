import {act} from 'react';
import {createRoot} from 'react-dom/client';
import {expect,it,vi} from 'vitest';
import {ChannelControls} from './ChannelControls';
import type {ChannelSnapshot} from '../api/source';
(globalThis as {IS_REACT_ACT_ENVIRONMENT?:boolean}).IS_REACT_ACT_ENVIRONMENT=true;
it('requires confirmation and recovers an uncertain channel command without reconnecting',async()=>{
 const key='jaeger.ui.channel.operation.v1.owned-fixture';localStorage.removeItem(key);
 const mutate=vi.fn(async()=>{throw Error('Lost response');});
 const operation=vi.fn(async(id:string)=>({receipt:{ok:true,operation_id:id,result:{state:'registered_not_probed'}}}));
 const channel={id:'owned-fixture',name:'Owned fixture',binding:{agent_id:'owned-bot',revision:1},actions:['connect']} as ChannelSnapshot['channels'][number];
 const host=document.createElement('div');document.body.append(host);const root=createRoot(host);
 try{
  await act(async()=>root.render(<ChannelControls controls={{mutate,operation}} channel={channel} agents={[]} refresh={()=>{}}/>));
  await act(async()=>[...host.querySelectorAll('button')].find(b=>b.textContent==='Connect configured transport')!.click());
  expect(mutate).not.toHaveBeenCalled();expect(host.textContent).toContain('no automatic bot execution/reply');
  await act(async()=>[...host.querySelectorAll('button')].find(b=>b.textContent==='Confirm connect')!.click());
  const saved=JSON.parse(localStorage.getItem(key)!);
  expect(mutate).toHaveBeenCalledExactlyOnceWith('owned-fixture','connect',saved.body);
  expect(host.textContent).not.toContain('Gateway confirmed channel control');
  await act(async()=>[...host.querySelectorAll('button')].find(b=>b.textContent==='Check channel operation')!.click());
  expect(operation).toHaveBeenCalledExactlyOnceWith(saved.body.operation_id);expect(mutate).toHaveBeenCalledTimes(1);
  expect(localStorage.getItem(key)).toBeNull();
 }finally{await act(async()=>root.unmount());host.remove();localStorage.removeItem(key);}
});
