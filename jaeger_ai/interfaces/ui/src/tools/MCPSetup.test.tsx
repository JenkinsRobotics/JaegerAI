import {act} from 'react';
import {createRoot} from 'react-dom/client';
import {expect,it,vi} from 'vitest';
import {MCPSetup} from './MCPSetup';
import type {MCPConfiguration} from '../api/source';
(globalThis as {IS_REACT_ACT_ENVIRONMENT?:boolean}).IS_REACT_ACT_ENVIRONMENT=true;
it('reviews future startup separately and recovers lost ACK without replay',async()=>{
 localStorage.clear();
 const controls:MCPConfiguration={read:vi.fn(async()=>({config_revision:'reviewed',servers:[{name:'owned',transport:'stdio',status:'not_probed' as const,startup_enabled:false}]})),change:vi.fn(async()=>{throw Error('lost ACK');}),operation:vi.fn(async id=>({operation_id:id,outcome:'saved' as const,config_revision:'saved-revision',connection_attempted:false as const}))};
 const host=document.createElement('div');document.body.append(host);const root=createRoot(host);
 const click=async(text:string)=>act(async()=>[...host.querySelectorAll('button')].find(b=>b.textContent===text)!.click());
 try{
  await act(async()=>root.render(<MCPSetup controls={controls}/>));
  await click('Review enable at next startup');expect(controls.change).not.toHaveBeenCalled();
  expect(host.textContent).toContain('may run/connect on the next initialization');
  await click('Confirm configuration');const id=localStorage.getItem('jaeger.ui.mcp.configuration.v1')!;
  expect(controls.change).toHaveBeenCalledExactlyOnceWith({operation_id:id,action:'startup',expected_revision:'reviewed',name:'owned',enabled:true});
  await act(async()=>root.render(<MCPSetup key="reopen" controls={controls}/>));
  await click('Inspect original configuration result');expect(controls.operation).toHaveBeenCalledExactlyOnceWith(id);
  expect(controls.change).toHaveBeenCalledTimes(1);expect(localStorage.getItem('jaeger.ui.mcp.configuration.v1')).toBeNull();
  expect(host.textContent).toContain('Configuration saved');
 }finally{await act(async()=>root.unmount());host.remove();localStorage.clear();}
});
it('does not dispatch when the durable command journal cannot be written',async()=>{
 localStorage.clear();
 const controls:MCPConfiguration={read:vi.fn(async()=>({config_revision:'r',servers:[{name:'owned',startup_enabled:false,transport:'stdio',status:'not_probed' as const}]})),change:vi.fn(),operation:vi.fn()};
 const host=document.createElement('div');document.body.append(host);const root=createRoot(host);
 const click=async(text:string)=>act(async()=>[...host.querySelectorAll('button')].find(b=>b.textContent===text)!.click());
 try{
  await act(async()=>root.render(<MCPSetup controls={controls}/>));await click('Review enable at next startup');
  vi.spyOn(Storage.prototype,'setItem').mockImplementation(()=>{throw Error('unavailable');});
  await click('Confirm configuration');expect(controls.change).not.toHaveBeenCalled();expect(host.textContent).toContain('Nothing was sent');
 }finally{vi.restoreAllMocks();await act(async()=>root.unmount());host.remove();localStorage.clear();}
});
